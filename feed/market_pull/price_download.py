import yfinance as yf
import pandas as pd
import os
import time
import logging
from datetime import datetime, timedelta

# --- Paths ---
ROOT = "D:/Kestrel"
RAW_DATA = os.path.join(ROOT, "data/raw")
LOG_PATH = os.path.join(ROOT, "logs/downloader.log")

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.downloader")

# --- Date range ---
END_DATE   = datetime.today().strftime("%Y-%m-%d")
START_DATE = (datetime.today() - timedelta(days=365 * 10)).strftime("%Y-%m-%d")

def get_all_tickers():
    """Pull every ticker from NYSE, NASDAQ, and AMEX."""
    log.info("Fetching full US market ticker list...")

    url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt"
    try:
        tickers = pd.read_csv(url, header=None)[0].tolist()
        tickers = [t.strip().upper() for t in tickers if isinstance(t, str)]
        log.info(f"Found {len(tickers)} tickers")
        return tickers
    except Exception as e:
        log.error(f"Failed to fetch ticker list: {e}")
        return []

def already_downloaded(ticker):
    """Check if we already have this stock's data."""
    path = os.path.join(RAW_DATA, f"{ticker}.parquet")
    return os.path.exists(path)

def download_ticker(ticker):
    """Download 10 years of daily OHLCV data for one ticker."""
    try:
        df = yf.download(
            ticker,
            start=START_DATE,
            end=END_DATE,
            progress=False,
            auto_adjust=True
        )

        if df.empty or len(df) < 100:
            log.warning(f"  {ticker}: insufficient data ({len(df)} rows) — skipping")
            return False

        # Save as parquet
        path = os.path.join(RAW_DATA, f"{ticker}.parquet")
        df.to_parquet(path)
        return True

    except Exception as e:
        log.error(f"  {ticker}: failed — {e}")
        return False

def run():
    tickers = get_all_tickers()
    if not tickers:
        log.error("No tickers found. Exiting.")
        return

    total     = len(tickers)
    skipped   = 0
    success   = 0
    failed    = 0
    failed_list = []

    log.info(f"Starting download: {total} tickers | {START_DATE} to {END_DATE}\n")

    for i, ticker in enumerate(tickers, 1):
        if already_downloaded(ticker):
            skipped += 1
            if skipped % 100 == 0:
                log.info(f"  Skipped {skipped} already downloaded...")
            continue

        log.info(f"[{i}/{total}] Downloading {ticker}...")
        result = download_ticker(ticker)

        if result:
            success += 1
        else:
            failed += 1
            failed_list.append(ticker)

        # Be polite to Yahoo Finance — don't hammer it
        time.sleep(0.3)

        # Progress update every 100 stocks
        if i % 100 == 0:
            log.info(f"\n  Progress: {i}/{total} | Success: {success} | Failed: {failed} | Skipped: {skipped}\n")

    # Save failed tickers so we can retry later
    if failed_list:
        fail_path = os.path.join(ROOT, "logs/failed_tickers.txt")
        with open(fail_path, "w") as f:
            f.write("\n".join(failed_list))
        log.info(f"\nFailed tickers saved to {fail_path}")

    log.info(f"""
    =============================
    KESTREL DOWNLOAD COMPLETE
    =============================
    Total tickers:   {total}
    Downloaded:      {success}
    Skipped:         {skipped}
    Failed:          {failed}
    =============================
    """)

if __name__ == "__main__":
    run()