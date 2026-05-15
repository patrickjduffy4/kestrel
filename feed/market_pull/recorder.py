"""
Minute-bar recorder.

Pulls minute-resolution price/volume bars from Alpaca and stores them as
per-ticker parquet files under data/training/intraday/. This is the feed
leftbrain practices on — every minute of every trading day, ticker by ticker.

Sibling to price_download.py (which records daily bars).
"""
import sys
sys.path.insert(0, "D:/Kestrel")

import os
import time
import sqlite3
import pandas as pd
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY,
    ROOT, DB_MARKET, RAW_DATA, INTRADAY_DATA
)

# --- Logging ---
LOG_PATH = os.path.join(ROOT, "logs/recorder.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.recorder")

# --- Alpaca client ---
client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

# --- Settings ---
HISTORY_YEARS = 2     # how far back to pull on first run
TOP_N         = 500   # how many tickers to record by recent volume
CHUNK_DAYS    = 90    # request window per Alpaca call (keeps responses small)
PT            = ZoneInfo("America/Los_Angeles")
ET            = ZoneInfo("America/New_York")

os.makedirs(INTRADAY_DATA, exist_ok=True)

# --- Ticker selection ---

def get_full_tickers():
    """Tickers with enough daily history to be worth recording."""
    conn = sqlite3.connect(DB_MARKET)
    df   = pd.read_sql(
        "SELECT ticker FROM manifest WHERE classification = 'FULL'",
        conn
    )
    conn.close()
    return df['ticker'].tolist()

def get_recent_avg_volume(ticker, days=20):
    """Recent average daily volume from the daily parquet."""
    path = os.path.join(RAW_DATA, f"{ticker}.parquet")
    if not os.path.exists(path):
        return 0
    try:
        df = pd.read_parquet(path)
        vol_col = next((c for c in df.columns
                        if str((c[0] if isinstance(c, tuple) else c)).lower().startswith('v')), None)
        if vol_col is None or df.empty:
            return 0
        return float(df[vol_col].tail(days).mean())
    except Exception:
        return 0

def get_target_tickers(top_n=TOP_N):
    """The top N FULL tickers by recent volume — the universe we record."""
    log.info("Selecting top tickers by recent volume...")
    tickers = get_full_tickers()
    log.info(f"  {len(tickers)} FULL-history tickers in manifest")

    scored = [(t, get_recent_avg_volume(t)) for t in tickers]
    scored = [s for s in scored if s[1] > 0]
    scored.sort(key=lambda x: x[1], reverse=True)
    picked = [t for t, _ in scored[:top_n]]
    log.info(f"  Picked top {len(picked)} by 20-day avg volume")
    return picked

# --- Per-ticker recording ---

def last_recorded_minute(ticker):
    """Most recent minute already on disk for this ticker, or None."""
    path = os.path.join(INTRADAY_DATA, f"{ticker}.parquet")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_parquet(path)
        if df.empty:
            return None
        idx = df.index
        # Multi-index (symbol, timestamp) — drop symbol level if present
        if hasattr(idx, 'nlevels') and idx.nlevels > 1:
            idx = idx.get_level_values(-1)
        last = idx.max()
        return pd.Timestamp(last)
    except Exception:
        return None

def pull_window(ticker, start, end):
    """Pull a single window of minute bars for one ticker."""
    request = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end,
        adjustment='all'
    )
    bars = client.get_stock_bars(request)
    df = bars.df
    if df is None or df.empty:
        return None
    # Drop the symbol level so the index is just timestamp
    if hasattr(df.index, 'nlevels') and df.index.nlevels > 1:
        df = df.droplevel(0)
    return df

def save_ticker(ticker, df):
    """Merge new minute bars with whatever is already on disk."""
    if df is None or df.empty:
        return 0

    path = os.path.join(INTRADAY_DATA, f"{ticker}.parquet")
    if os.path.exists(path):
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df])
        df = df[~df.index.duplicated(keep='last')]
        df = df.sort_index()

    df.to_parquet(path)
    return len(df)

def record_ticker(ticker, start_default, end):
    """
    Record one ticker. Resumes from wherever we left off.
    Returns (bars_added, success).
    """
    last = last_recorded_minute(ticker)
    start = (last + timedelta(minutes=1)) if last is not None else start_default

    # Already current?
    if start >= end - timedelta(minutes=1):
        return 0, True

    total_added = 0
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS), end)
        try:
            df = pull_window(ticker, cursor, chunk_end)
            if df is not None and not df.empty:
                save_ticker(ticker, df)
                total_added += len(df)
        except Exception as e:
            log.warning(f"  {ticker}: chunk {cursor.date()}–{chunk_end.date()} failed — {e}")
            return total_added, False
        cursor = chunk_end
        # Light rate-limiting hygiene — Alpaca free tier is 200/min
        time.sleep(0.2)

    return total_added, True

# --- Main ---

def run(top_n=TOP_N, years=HISTORY_YEARS, tickers=None):
    """
    Record minute bars for the top N tickers (or a supplied list).
    Idempotent — re-running picks up where it left off.
    """
    log.info("=== RECORDER STARTING ===")
    log.info(f"Target: top {top_n} tickers, {years} years of minute history")

    if tickers is None:
        tickers = get_target_tickers(top_n=top_n)

    # Window: Alpaca requires end to be at least 15 minutes ago on free feed
    end   = datetime.now(ET) - timedelta(minutes=20)
    start = end - timedelta(days=365 * years)
    log.info(f"Window: {start.isoformat()} → {end.isoformat()}")

    success    = 0
    failed     = 0
    skipped    = 0
    total_bars = 0
    failed_list = []

    for i, ticker in enumerate(tickers, 1):
        try:
            added, ok = record_ticker(ticker, start, end)
            if added == 0 and ok:
                skipped += 1
            elif ok:
                success += 1
                total_bars += added
                log.info(f"  [{i}/{len(tickers)}] {ticker}: +{added:,} bars")
            else:
                failed += 1
                failed_list.append(ticker)
        except Exception as e:
            log.error(f"  [{i}/{len(tickers)}] {ticker}: {e}")
            failed += 1
            failed_list.append(ticker)

        if i % 25 == 0:
            log.info(
                f"Progress: {i}/{len(tickers)} | "
                f"Success: {success} | Skipped: {skipped} | "
                f"Failed: {failed} | Total bars: {total_bars:,}"
            )

    if failed_list:
        fail_path = os.path.join(ROOT, "logs/recorder_failed.txt")
        with open(fail_path, "w") as f:
            f.write("\n".join(failed_list))

    log.info(f"""
    =============================
    RECORDER COMPLETE
    =============================
    Tickers:        {len(tickers)}
    Recorded:       {success}
    Already current:{skipped}
    Failed:         {failed}
    Total bars:     {total_bars:,}
    =============================
    """)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Record minute bars from Alpaca.")
    ap.add_argument("--top",     type=int, default=TOP_N,         help="Top N tickers by volume (default 500)")
    ap.add_argument("--years",   type=int, default=HISTORY_YEARS, help="Years of history (default 2)")
    ap.add_argument("--tickers", type=str, default=None,
                    help="Comma-separated ticker list (overrides --top)")
    args = ap.parse_args()

    tickers = None
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    run(top_n=args.top, years=args.years, tickers=tickers)
