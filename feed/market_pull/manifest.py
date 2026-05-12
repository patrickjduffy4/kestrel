import os
import sqlite3
import pandas as pd
import logging

# --- Paths ---
from config import ROOT, DB_MARKET, RAW_DATA

# --- Logging ---
LOG_PATH = os.path.join(ROOT, "logs/manifest.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.manifest")

def classify_by_history(days):
    """Classify a stock based on days of price history."""
    if days >= 500:
        return 'FULL'
    elif days >= 200:
        return 'TRACK'
    else:
        return 'WATCH'

def build_from_raw():
    """
    Read every parquet file in data/raw/ and build
    a manifest entry for each stock.
    """
    log.info("Building manifest from raw data...")
    records = []

    files = [f for f in os.listdir(RAW_DATA) if f.endswith('.parquet')]
    total = len(files)
    log.info(f"Found {total} parquet files")

    for i, filename in enumerate(files, 1):
        ticker = filename.replace('.parquet', '')
        path = os.path.join(RAW_DATA, filename)

        try:
            df = pd.read_parquet(path)
            days = len(df)
            classification = classify_by_history(days)

            records.append({
                'ticker':         ticker,
                'classification': classification,
                'days_of_data':   days,
                'source':         'downloaded',
                'last_updated':   pd.Timestamp.today().strftime('%Y-%m-%d')
            })

        except Exception as e:
            log.error(f"  {ticker}: failed to read — {e}")

        if i % 500 == 0:
            log.info(f"  Progress: {i}/{total}")

    log.info(f"Built {len(records)} manifest entries from raw data")
    return pd.DataFrame(records)

def merge_scan_results(manifest_df):
    """
    Merge scan classifications for the 649 failed tickers.
    Scan results override default classification where they exist.
    """
    log.info("Merging scan results...")

    conn = sqlite3.connect(DB_MARKET)
    scan_df = pd.read_sql("SELECT ticker, classification FROM scan", conn)
    conn.close()

    # Only keep scan results that aren't already in manifest
    new_tickers = scan_df[~scan_df['ticker'].isin(manifest_df['ticker'])]

    if len(new_tickers) > 0:
        new_records = []
        for _, row in new_tickers.iterrows():
            new_records.append({
                'ticker':         row['ticker'],
                'classification': row['classification'],
                'days_of_data':   0,
                'source':         'scan',
                'last_updated':   pd.Timestamp.today().strftime('%Y-%m-%d')
            })
        new_df = pd.DataFrame(new_records)
        manifest_df = pd.concat([manifest_df, new_df], ignore_index=True)
        log.info(f"Added {len(new_records)} tickers from scan results")

    return manifest_df

def save_manifest(manifest_df):
    """Write manifest to market.db."""
    conn = sqlite3.connect(DB_MARKET)
    manifest_df.to_sql('manifest', conn, if_exists='replace', index=False)
    conn.close()
    log.info(f"Manifest saved to market.db — {len(manifest_df)} total tickers")

def run():
    # Build from downloaded files
    manifest_df = build_from_raw()

    # Merge scan results
    manifest_df = merge_scan_results(manifest_df)

    # Save
    save_manifest(manifest_df)

    # Summary
    counts = manifest_df['classification'].value_counts()
    log.info(f"""
    =============================
    KESTREL MANIFEST COMPLETE
    =============================
    Total tickers:  {len(manifest_df)}
    FULL:           {counts.get('FULL', 0)}
    TRACK:          {counts.get('TRACK', 0)}
    WATCH:          {counts.get('WATCH', 0)}
    GHOST:          {counts.get('GHOST', 0)}
    IGNORE:         {counts.get('IGNORE', 0)}
    =============================
    """)

if __name__ == "__main__":
    run()