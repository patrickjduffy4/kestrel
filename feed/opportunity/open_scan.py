import os
import sqlite3
import pandas as pd
import logging
from datetime import datetime
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestBarRequest

# --- Config ---
from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY,
    ROOT, DB_SIGNALS
)

# --- Logging ---
LOG_PATH = os.path.join(ROOT, "logs/open_scan.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.open_scan")

# --- Alpaca client ---
historical_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

# --- Settings ---
GAP_CONFIRMED_THRESHOLD = 0.01
BATCH_SIZE              = 50

def get_premarket_candidates():
    conn = sqlite3.connect(DB_SIGNALS)
    try:
        df = pd.read_sql("SELECT * FROM pre_market_gaps", conn)
        log.info(f"Loaded {len(df)} pre-market candidates")
        return df
    except Exception as e:
        log.error(f"Failed to load pre-market candidates: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def get_opening_bars(tickers):
    opening_bars = {}
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        try:
            request = StockLatestBarRequest(symbol_or_symbols=batch)
            result  = historical_client.get_stock_latest_bar(request)
            for ticker, bar in result.items():
                opening_bars[ticker] = {
                    'open':   bar.open,
                    'high':   bar.high,
                    'low':    bar.low,
                    'close':  bar.close,
                    'volume': bar.volume
                }
        except Exception as e:
            log.error(f"Bar fetch failed for batch: {e}")
    log.info(f"Retrieved opening bars for {len(opening_bars)} tickers")
    return opening_bars

def confirm_gaps(candidates_df, opening_bars):
    confirmed = []
    rejected  = 0
    adjusted  = 0

    for _, row in candidates_df.iterrows():
        ticker = row['ticker']

        if ticker not in opening_bars:
            rejected += 1
            continue

        bar             = opening_bars[ticker]
        real_open       = bar['open']
        yesterday_close = row['yesterday_close']

        if yesterday_close == 0:
            rejected += 1
            continue

        real_gap = (real_open - yesterday_close) / yesterday_close

        if abs(real_gap) < GAP_CONFIRMED_THRESHOLD:
            rejected += 1
            log.debug(f"  {ticker}: gap faded — estimated {row['gap_pct']:+.2f}% actual {real_gap*100:+.2f}%")
            continue

        estimated_direction = row['direction']
        real_direction      = 'up' if real_gap > 0 else 'down'
        direction_flipped   = estimated_direction != real_direction

        if direction_flipped:
            adjusted += 1
            log.info(f"  {ticker}: direction flipped — was {estimated_direction} now {real_direction}")

        gap_accuracy = abs(real_gap - row['gap']) / abs(row['gap']) if row['gap'] != 0 else 0

        confirmed.append({
            'ticker':            ticker,
            'yesterday_close':   round(yesterday_close, 4),
            'estimated_gap_pct': row['gap_pct'],
            'real_open':         round(real_open, 4),
            'real_gap':          round(real_gap, 4),
            'real_gap_pct':      round(real_gap * 100, 2),
            'direction':         real_direction,
            'direction_flipped': direction_flipped,
            'gap_accuracy':      round(1 - gap_accuracy, 4),
            'open_volume':       bar['volume'],
            'avg_volume':        row['avg_volume'],
            'volume_ratio':      round(bar['volume'] / row['avg_volume'], 2) if row['avg_volume'] > 0 else 0,
            'spread':            row['spread'],
            'relative_gap':      row['relative_gap'],
            'confirmed_at':      datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

    log.info(f"Confirmed: {len(confirmed)} | Rejected: {rejected} | Direction flipped: {adjusted}")
    return pd.DataFrame(confirmed)

def save_confirmed(confirmed_df):
    conn = sqlite3.connect(DB_SIGNALS)
    confirmed_df.to_sql('confirmed_gaps', conn, if_exists='replace', index=False)
    conn.close()
    log.info(f"Saved {len(confirmed_df)} confirmed gaps to signals.db")

def run():
    log.info("=== OPEN SCAN STARTING ===")
    log.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    candidates_df = get_premarket_candidates()
    if candidates_df.empty:
        log.info("No pre-market candidates to confirm")
        return

    tickers = candidates_df['ticker'].tolist()

    opening_bars = get_opening_bars(tickers)
    if not opening_bars:
        log.error("No opening bars retrieved")
        return

    confirmed_df = confirm_gaps(candidates_df, opening_bars)
    if confirmed_df.empty:
        log.info("No gaps confirmed at open")
        return

    save_confirmed(confirmed_df)

    up      = len(confirmed_df[confirmed_df['direction'] == 'up'])
    down    = len(confirmed_df[confirmed_df['direction'] == 'down'])
    flipped = len(confirmed_df[confirmed_df['direction_flipped'] == True])

    log.info(f"""
    =============================
    OPEN SCAN COMPLETE
    =============================
    Confirmed:         {len(confirmed_df)}
    Gap up:            {up}
    Gap down:          {down}
    Direction flipped: {flipped}
    =============================
    """)

    log.info("Top 10 confirmed gaps:")
    for _, row in confirmed_df.head(10).iterrows():
        log.info(
            f"  {row['ticker']:6} | "
            f"{row['direction']:4} | "
            f"real gap: {row['real_gap_pct']:+.2f}% | "
            f"vol ratio: {row['volume_ratio']:.1f}x | "
            f"accuracy: {row['gap_accuracy']*100:.0f}%"
        )

if __name__ == "__main__":
    run()