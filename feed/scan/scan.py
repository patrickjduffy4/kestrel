import requests
import yfinance as yf
import pandas as pd
import logging
import os
import time
import sqlite3


# --- Paths ---
ROOT = "D:/Kestrel"
RAW_DATA = os.path.join(ROOT, "data/raw")
DB_PATH = os.path.join(ROOT, "data/database/market.db")
LOG_PATH = os.path.join(ROOT, "logs/scan.log")
FAILED_TICKERS = os.path.join(ROOT, "logs/failed_tickers.txt")

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.scan")

# --- Classification thresholds ---
LAYER1_VOLUME       = 100000   # avg daily volume
LAYER1_DOLLAR_VOL   = 1000000  # avg daily dollar volume
LAYER1_MARKET_CAP   = 100000000 # $100M
LAYER1_HISTORY_DAYS = 200

def is_derivative(ticker):
    """Filter out warrants, units, rights."""
    suffixes = ['W', 'U', 'R', 'WS', 'WT']
    return any(ticker.endswith(s) for s in suffixes)

def layer1_check(ticker, info, history):
    """
    Fast quantitative screen.
    Returns True if obviously legitimate and trackable.
    """
    if is_derivative(ticker):
        return False, 'derivative'

    market_cap = info.get('marketCap', 0) or 0
    avg_volume = info.get('averageVolume', 0) or 0
    price = info.get('currentPrice', 0) or info.get('regularMarketPrice', 0) or 0
    dollar_volume = avg_volume * price
    history_days = len(history)

    if market_cap >= LAYER1_MARKET_CAP \
    and avg_volume >= LAYER1_VOLUME \
    and dollar_volume >= LAYER1_DOLLAR_VOL \
    and history_days >= LAYER1_HISTORY_DAYS:
        return True, 'layer1_pass'

    return False, 'layer1_fail'

def check_edgar(ticker):
    """Check SEC EDGAR for real filings using CIK lookup."""
    try:
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=&CIK={ticker}&type=10-K&dateb=&owner=include&count=10&output=atom"
        headers = {'User-Agent': 'Kestrel/1.0 contact@kestrel.com'}
        response = requests.get(url, timeout=5, headers=headers)
        if response.status_code == 200 and '<entry>' in response.text:
            count = response.text.count('<entry>')
            return count
        return 0
    except Exception:
        return 0

def layer2_check(ticker, info):
    """
    Intelligent legitimacy check for Layer1 failures.
    Uses EDGAR as primary signal, yfinance description as fallback.
    """
    # Primary — EDGAR
    filing_count = check_edgar(ticker)

    if filing_count > 10:
        edgar_result = 'strong'
    elif filing_count > 0:
        edgar_result = 'weak'
    else:
        edgar_result = 'none'

    # Fallback — yfinance description
    description = info.get('longBusinessSummary', '') or ''
    has_description = len(description) > 100

    # Classify
    if edgar_result == 'strong':
        return 'TRACK', filing_count, description
    elif edgar_result == 'weak' and has_description:
        return 'WATCH', filing_count, description
    elif edgar_result == 'weak':
        return 'GHOST', filing_count, description
    elif has_description:
        return 'GHOST', filing_count, description
    else:
        return 'IGNORE', filing_count, description

def assess_ticker(ticker):
    """Full assessment pipeline for one ticker."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        try:
            history = stock.history(period="max")
        except Exception:
            try:
                history = stock.history(period="5y")
            except Exception:
                history = pd.DataFrame()

        # Layer 1 — obvious yes
        passes, reason = layer1_check(ticker, info, history)
        if passes:
            return {
                'ticker': ticker,
                'classification': 'FULL',
                'reason': reason,
                'edgar_filings': None,
                'description': info.get('longBusinessSummary', '')[:100]
            }

        # Layer 2 — intelligent inspection
        classification, filing_count, description = layer2_check(ticker, info)
        return {
            'ticker': ticker,
            'classification': classification,
            'reason': reason,
            'edgar_filings': filing_count,
            'description': description[:100] if description else None
        }

    except Exception as e:
        log.error(f"  {ticker}: assessment failed — {e}")
        return {
            'ticker': ticker,
            'classification': 'IGNORE',
            'reason': f'error: {e}',
            'edgar_filings': 0,
            'description': None
        }

def load_failed_tickers():
    """Load the failed tickers from the downloader."""
    with open(FAILED_TICKERS, 'r') as f:
        tickers = [line.strip() for line in f if line.strip()]
    log.info(f"Loaded {len(tickers)} failed tickers")
    return tickers

def run():
    tickers = load_failed_tickers()
    total = len(tickers)
    results = []

    log.info(f"Starting scan on {total} tickers\n")

    for i, ticker in enumerate(tickers, 1):
        log.info(f"[{i}/{total}] Scanning {ticker}...")
        result = assess_ticker(ticker)
        results.append(result)
        log.info(f"  -> {result['classification']} | {result['reason']}")
        time.sleep(0.3)

        # Progress every 50
        if i % 50 == 0:
            counts = pd.DataFrame(results)['classification'].value_counts()
            log.info(f"\n  Progress {i}/{total}\n{counts}\n")

    # Save results to database
    df = pd.DataFrame(results)
    conn = sqlite3.connect(DB_PATH)
    df.to_sql('scan', conn, if_exists='replace', index=False)
    conn.close()
    log.info(f"Results saved to market.db")

    # Summary
    counts = df['classification'].value_counts()
    log.info(f"""
    =============================
    KESTREL SCAN COMPLETE
    =============================
    Total scanned:  {total}
    FULL:           {counts.get('FULL', 0)}
    TRACK:          {counts.get('TRACK', 0)}
    WATCH:          {counts.get('WATCH', 0)}
    GHOST:          {counts.get('GHOST', 0)}
    IGNORE:         {counts.get('IGNORE', 0)}
    =============================
    """)

if __name__ == "__main__":
    run()

    if os.path.exists(DB_PATH):
        log.info(f"market.db created successfully")
    else:
        log.error(f"market.db was NOT created at {DB_PATH}")