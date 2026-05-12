import os
import sqlite3
import pandas as pd
import logging
from datetime import datetime, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# --- Config ---
from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY,
    ROOT, DB_MARKET, RAW_DATA
)

# --- Logging ---
LOG_PATH = os.path.join(ROOT, "logs/market_pull.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.market_pull")

# --- Alpaca client ---
client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

# --- Settings ---
HISTORY_YEARS = 10
BATCH_SIZE    = 50  # tickers per request

def get_tracked_tickers():
    """Pull FULL and TRACK tickers from manifest."""
    conn = sqlite3.connect(DB_MARKET)
    df = pd.read_sql(
        "SELECT ticker FROM manifest WHERE classification IN ('FULL', 'TRACK')",
        conn
    )
    conn.close()
    tickers = df['ticker'].tolist()
    log.info(f"Found {len(tickers)} tickers to update")
    return tickers

def already_current(ticker):
    """Check if we already have today's data."""
    path = os.path.join(RAW_DATA, f"{ticker}.parquet")
    if not os.path.exists(path):
        return False
    df = pd.read_parquet(path)
    if df.empty:
        return False
    last_date = df.index[-1]
    if hasattr(last_date, 'date'):
        last_date = last_date.date()
    return last_date >= datetime.today().date() - timedelta(days=3)

def download_batch(tickers, start_date, end_date):
    """Download a batch of tickers from Alpaca."""
    request = StockBarsRequest(
        symbol_or_symbols=tickers,
        timeframe=TimeFrame.Day,
        start=start_date,
        end=end_date,
        adjustment='all'
    )
    bars = client.get_stock_bars(request)
    return bars.df

def save_ticker(ticker, df):
    """Save a single ticker's data as parquet."""
    path = os.path.join(RAW_DATA, f"{ticker}.parquet")

    # If file exists, merge with existing data
    if os.path.exists(path):
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df])
        df = df[~df.index.duplicated(keep='last')]
        df = df.sort_index()

    df.to_parquet(path)

def run():
    tickers = get_tracked_tickers()
    total   = len(tickers)

    # Filter out already current
    tickers = [t for t in tickers if not already_current(t)]
    log.info(f"{total - len(tickers)} already current, downloading {len(tickers)}")

    end_date   = datetime.today()
    start_date = end_date - timedelta(days=365 * HISTORY_YEARS)

    success = 0
    failed  = 0
    failed_list = []

    # Process in batches
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        log.info(f"Batch {i//BATCH_SIZE + 1} — downloading {len(batch)} tickers...")

        try:
            df = download_batch(batch, start_date, end_date)

            for ticker in batch:
                try:
                    if ticker in df.index.get_level_values(0):
                        ticker_df = df.loc[ticker]
                        save_ticker(ticker, ticker_df)
                        success += 1
                    else:
                        log.warning(f"  {ticker}: no data returned")
                        failed += 1
                        failed_list.append(ticker)
                except Exception as e:
                    log.error(f"  {ticker}: save failed — {e}")
                    failed += 1
                    failed_list.append(ticker)

        except Exception as e:
            log.error(f"Batch failed — {e}")
            failed += len(batch)
            failed_list.extend(batch)

        # Progress
        if (i // BATCH_SIZE + 1) % 10 == 0:
            log.info(f"Progress: {i + BATCH_SIZE}/{len(tickers)} | Success: {success} | Failed: {failed}")

    # Save failed list
    if failed_list:
        fail_path = os.path.join(ROOT, "logs/market_pull_failed.txt")
        with open(fail_path, "w") as f:
            f.write("\n".join(failed_list))

    log.info(f"""
    =============================
    MARKET PULL COMPLETE
    =============================
    Total:      {len(tickers)}
    Success:    {success}
    Failed:     {failed}
    =============================
    """)

if __name__ == "__main__":
    run()