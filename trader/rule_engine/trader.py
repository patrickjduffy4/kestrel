import sys
sys.path.insert(0, "D:/Kestrel")

import os
import time
import logging
import asyncio
import sqlite3
import pandas as pd
from zoneinfo import ZoneInfo
from datetime import datetime, time as dtime, timedelta
from alpaca.data.live import StockDataStream
from alpaca.data.models import Bar

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ROOT, DB_SIGNALS
from trader.rule_engine.state import (
    refresh,
    get_positions,
    has_position,
    get_watchlist,
    update_watchlist,
    is_price_eligible,
    get_max_position_dollars
)
from trader.rule_engine.sizing import position_size
from trader.rule_engine.execution import place_buy, close_all_positions
from trader.rule_engine.positions import (
    init_position,
    process_position,
    end_of_day_close,
    get_all_position_states
)

# --- Logging ---
LOG_PATH = os.path.join(ROOT, "logs/trader.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.trader")

# --- Settings ---
MARKET_OPEN_PT  = dtime(6, 30)
MARKET_CLOSE_PT = dtime(12, 45)
WATCHLIST_POLL  = 300
MAX_POSITIONS   = 3
MIN_SCORE       = 0.40
PT              = ZoneInfo("America/Los_Angeles")

# --- Live price cache ---
_prices     = {}
_volumes    = {}
_vol_trends = {}

# --- WebSocket stream ---
stream = StockDataStream(ALPACA_API_KEY, ALPACA_SECRET_KEY)

# --- Market hours ---

def is_market_open():
    now = datetime.now(PT).time()
    return MARKET_OPEN_PT <= now <= MARKET_CLOSE_PT

def is_end_of_day():
    now = datetime.now(PT).time()
    return now >= MARKET_CLOSE_PT

def time_until_open():
    now     = datetime.now(PT)
    today   = now.date()
    open_dt = datetime.combine(today, MARKET_OPEN_PT, tzinfo=PT)

    if now >= open_dt or now.weekday() >= 5:
        days_ahead = 1
        while True:
            next_day = today + timedelta(days=days_ahead)
            if next_day.weekday() < 5:
                open_dt = datetime.combine(next_day, MARKET_OPEN_PT, tzinfo=PT)
                break
            days_ahead += 1

    return (open_dt - now).total_seconds(), open_dt

def wait_for_market():
    while True:
        if is_market_open():
            log.info("Market is open. Starting trader.")
            return

        seconds, open_dt = time_until_open()
        hours   = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)

        log.info(
            f"Market opens at 6:30am PT "
            f"({open_dt.strftime('%A %B %d')}), "
            f"which is in {hours}h {minutes}m. "
            f"Sleeping until then..."
        )

        sleep_time = min(seconds, 3600)
        time.sleep(sleep_time)

# --- Watchlist ---

def load_watchlist():
    """Load current watchlist from signals.db."""
    try:
        conn = sqlite3.connect(DB_SIGNALS)
        df   = pd.read_sql(
            "SELECT * FROM confirmed_gaps ORDER BY relative_gap DESC",
            conn
        )
        conn.close()

        watchlist = []
        for _, row in df.iterrows():
            ticker = row['ticker']
            score  = row.get('relative_gap', 0) / 10

            # Long only
            if row.get('direction') != 'up':
                continue

            # Price check
            price = _prices.get(ticker, 0)
            if price > 0 and not is_price_eligible(price):
                continue

            if score >= MIN_SCORE:
                watchlist.append({
                    'ticker':     ticker,
                    'score':      min(score, 1.0),
                    'gap_pct':    row.get('real_gap_pct', 0),
                    'avg_volume': row.get('avg_volume', 0)
                })

        watchlist.sort(key=lambda x: x['score'], reverse=True)
        return watchlist[:20]

    except Exception as e:
        log.error(f"Failed to load watchlist: {e}")
        return []

# --- Historical data helpers ---

def get_historical_volume_trend(ticker):
    """5d avg vs 20d avg volume from local parquet."""
    try:
        from config import RAW_DATA
        path = os.path.join(RAW_DATA, f"{ticker}.parquet")
        if not os.path.exists(path):
            return 1.0
        df      = pd.read_parquet(path)
        vol_col = [c for c in df.columns if c[0] == 'Volume'][0]
        avg_20  = float(df[vol_col].tail(20).mean())
        avg_5   = float(df[vol_col].tail(5).mean())
        return round(avg_5 / avg_20, 2) if avg_20 > 0 else 1.0
    except Exception:
        return 1.0

def get_historical_averages(ticker):
    """5d and 20d price averages from local parquet."""
    try:
        from config import RAW_DATA
        path = os.path.join(RAW_DATA, f"{ticker}.parquet")
        if not os.path.exists(path):
            return None, None
        df        = pd.read_parquet(path)
        close_col = [c for c in df.columns if c[0] == 'Close'][0]
        avg_5     = float(df[close_col].tail(5).mean())
        avg_20    = float(df[close_col].tail(20).mean())
        return avg_5, avg_20
    except Exception:
        return None, None

# --- Entry logic ---

def should_enter(ticker, current_price, score):
    """Mean reversion entry signal."""
    if has_position(ticker):
        return False, "already_in_position"

    positions = get_positions()
    if len(positions) >= MAX_POSITIONS:
        return False, "max_positions_reached"

    avg_5, avg_20 = get_historical_averages(ticker)
    if avg_5 is None or avg_20 is None:
        return False, "no_historical_data"

    if current_price >= avg_5:
        return False, f"price_above_5d_avg (${current_price:.2f} >= ${avg_5:.2f})"

    if current_price >= avg_20:
        return False, f"price_above_20d_avg (${current_price:.2f} >= ${avg_20:.2f})"

    vol_trend = _vol_trends.get(ticker, 1.0)
    if vol_trend < 0.8:
        return False, f"volume_not_confirming (trend: {vol_trend:.2f})"

    return True, "mean_reversion_entry"

# --- Trade logging ---

def log_trade(ticker, exit_price, reason):
    """Log completed trade to performance.db."""
    try:
        from config import DB_PERF
        conn = sqlite3.connect(DB_PERF)
        c    = conn.cursor()

        position = get_all_position_states().get(ticker)
        if not position:
            return

        entry_price = position['entry_price']
        shares      = position['shares']
        pnl         = (exit_price - entry_price) * shares
        pnl_pct     = ((exit_price - entry_price) / entry_price) * 100
        hold_time   = (datetime.now() - position['entered_at']).seconds / 60

        c.execute("""
            INSERT INTO trades (
                date, ticker, direction, entry_price, exit_price,
                shares, pnl, pnl_pct, hold_time_minutes,
                exit_reason, system_a_score, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime('%Y-%m-%d'),
            ticker,
            'long',
            entry_price,
            exit_price,
            shares,
            round(pnl, 2),
            round(pnl_pct, 2),
            round(hold_time, 1),
            reason,
            position['score'],
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ))

        conn.commit()
        conn.close()
        log.info(f"Trade logged: {ticker} P&L ${pnl:.2f} ({pnl_pct:+.2f}%)")

    except Exception as e:
        log.error(f"Failed to log trade: {e}")

# --- WebSocket handler ---

async def on_bar(bar: Bar):
    """Called on every price bar from WebSocket."""
    ticker = bar.symbol
    price  = float(bar.close)
    volume = float(bar.volume)

    _prices[ticker]  = price
    _volumes[ticker] = volume

    vol_trend = get_historical_volume_trend(ticker)
    _vol_trends[ticker] = vol_trend

    if is_end_of_day():
        end_of_day_close()
        return

    if not is_market_open():
        return

    # Manage existing positions
    if has_position(ticker):
        action, reason = process_position(ticker, price, vol_trend)
        if action == 'exit':
            log_trade(ticker, price, reason)
        return

    # Check for new entries
    watchlist  = get_watchlist()
    wl_tickers = [w['ticker'] for w in watchlist]

    if ticker not in wl_tickers:
        return

    wl_entry = next((w for w in watchlist if w['ticker'] == ticker), None)
    if not wl_entry:
        return

    score = wl_entry['score']
    enter, reason = should_enter(ticker, price, score)

    if enter:
        shares, dollars = position_size(price, score)
        if shares > 0:
            order = place_buy(ticker, shares)
            if order:
                init_position(ticker, price, shares, score)
                log.info(
                    f"ENTERED {ticker} | "
                    f"Price: ${price:.2f} | "
                    f"Shares: {shares} | "
                    f"Value: ${dollars:.2f} | "
                    f"Score: {score:.2f} | "
                    f"Reason: {reason}"
                )

# --- Watchlist poller ---

async def poll_watchlist():
    """Poll watchlist every 5 minutes, update WebSocket subscriptions."""
    current_subs = set()

    while True:
        await asyncio.sleep(WATCHLIST_POLL)

        watchlist   = load_watchlist()
        update_watchlist(watchlist)
        new_tickers = set(w['ticker'] for w in watchlist)

        to_add = new_tickers - current_subs
        if to_add:
            await stream.subscribe_bars(on_bar, *to_add)
            log.info(f"Subscribed to: {to_add}")

        to_remove = current_subs - new_tickers
        for ticker in to_remove:
            if not has_position(ticker):
                await stream.unsubscribe_bars(ticker)
                log.info(f"Unsubscribed: {ticker}")

        current_subs = new_tickers | set(get_positions().keys())
        log.info(f"Watchlist: {len(watchlist)} stocks | Streaming: {len(current_subs)}")

# --- Main ---

async def run():
    """Main trader loop."""
    log.info("=== KESTREL TRADER STARTING ===")
    wait_for_market()
    refresh()

    watchlist = load_watchlist()
    update_watchlist(watchlist)

    if not watchlist:
        log.warning("No watchlist candidates — waiting for opportunity agent")
    else:
        log.info(f"Initial watchlist: {[w['ticker'] for w in watchlist]}")

    tickers = [w['ticker'] for w in watchlist]
    if tickers:
        stream.subscribe_bars(on_bar, *tickers)

    await asyncio.gather(
        stream._run_forever(),
        poll_watchlist()
    )

if __name__ == "__main__":
    asyncio.run(run())