import os
import sqlite3
import pandas as pd
import logging
from datetime import datetime
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

# --- Config ---
from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY,
    ROOT, DB_MARKET, RAW_DATA, DB_SIGNALS
)

# --- Logging ---
LOG_PATH = os.path.join(ROOT, "logs/pre_market_scan.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.pre_market_scan")

# --- Alpaca client ---
client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

# --- Settings ---
GAP_THRESHOLD  = 0.02    # 2% minimum gap
MIN_AVG_VOLUME = 500000  # minimum average daily volume
BATCH_SIZE     = 50      # quotes per Alpaca request
ATR_TOP_N      = 500     # pre-filter to top N volatile stocks

def get_stock_history(ticker):
    path = os.path.join(RAW_DATA, f"{ticker}.parquet")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_parquet(path)
        if df.empty or len(df) < 20:
            return None
        return df
    except Exception:
        return None

def get_close_col(df):
    cols = [c for c in df.columns if c[0] == 'Close']
    return cols[0] if cols else None

def get_volume_col(df):
    cols = [c for c in df.columns if c[0] == 'Volume']
    return cols[0] if cols else None

def validate_data_quality(df, yesterday_close):
    close_col = get_close_col(df)
    if close_col is None:
        return False
    recent = df[close_col].tail(20)
    mean   = recent.mean()
    std    = recent.std()
    if std == 0:
        return False
    z_score = abs(yesterday_close - mean) / std
    return z_score <= 3.0

def validate_liquidity(df):
    vol_col = get_volume_col(df)
    if vol_col is None:
        return 0
    return float(df[vol_col].tail(20).mean())

def validate_quote(quote):
    return (
        quote.bid_price is not None and
        quote.ask_price is not None and
        quote.bid_price > 0 and
        quote.ask_price > 0 and
        quote.ask_price >= quote.bid_price
    )

def get_volatile_tickers():
    conn = sqlite3.connect(DB_MARKET)
    df = pd.read_sql(
        "SELECT ticker FROM manifest WHERE classification IN ('FULL', 'TRACK')",
        conn
    )
    conn.close()

    tickers    = df['ticker'].tolist()
    volatility = []

    log.info(f"Calculating volatility for {len(tickers)} tickers...")

    for ticker in tickers:
        hist = get_stock_history(ticker)
        if hist is None:
            continue
        try:
            close_col = get_close_col(hist)
            if close_col is None:
                continue
            returns = hist[close_col].pct_change().dropna()
            vol     = float(returns.tail(20).std())
            avg_vol = validate_liquidity(hist)
            if avg_vol < MIN_AVG_VOLUME:
                continue
            volatility.append({'ticker': ticker, 'volatility': vol})
        except Exception:
            continue

    vol_df = pd.DataFrame(volatility).reset_index(drop=True)
    vol_df = vol_df.dropna(subset=['volatility'])
    vol_df = vol_df.sort_values('volatility', ascending=False)
    top_tickers = vol_df.head(ATR_TOP_N)['ticker'].tolist()

    log.info(f"Selected top {len(top_tickers)} liquid volatile tickers")
    return top_tickers

def get_premarket_quotes(tickers):
    quotes = {}
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=batch)
            result  = client.get_stock_latest_quote(request)
            for ticker, quote in result.items():
                if validate_quote(quote):
                    mid = (quote.bid_price + quote.ask_price) / 2
                    quotes[ticker] = {
                        'mid':    mid,
                        'bid':    quote.bid_price,
                        'ask':    quote.ask_price,
                        'spread': round((quote.ask_price - quote.bid_price) / mid, 4)
                    }
        except Exception as e:
            log.error(f"Quote batch failed: {e}")
    log.info(f"Retrieved valid quotes for {len(quotes)} tickers")
    return quotes

def assess_candidates(tickers, quotes):
    candidates = []

    for ticker in tickers:
        if ticker not in quotes:
            continue

        hist = get_stock_history(ticker)
        if hist is None:
            continue

        close_col = get_close_col(hist)
        if close_col is None:
            continue

        yesterday_close = float(hist[close_col].iloc[-1])
        if yesterday_close == 0:
            continue

        if not validate_data_quality(hist, yesterday_close):
            log.debug(f"  {ticker}: failed data quality check")
            continue

        avg_volume = validate_liquidity(hist)
        if avg_volume < MIN_AVG_VOLUME:
            continue

        premarket_price = quotes[ticker]['mid']
        gap = (premarket_price - yesterday_close) / yesterday_close

        if abs(gap) < GAP_THRESHOLD:
            continue

        spread = quotes[ticker]['spread']

        if spread > 0.05:
            continue

        returns  = hist[close_col].pct_change().dropna()
        avg_move = float(returns.tail(20).abs().mean())
        relative_gap = abs(gap) / avg_move if avg_move > 0 else 0

        candidates.append({
            'ticker':          ticker,
            'yesterday_close': round(yesterday_close, 4),
            'premarket_price': round(premarket_price, 4),
            'gap':             round(gap, 4),
            'gap_pct':         round(gap * 100, 2),
            'direction':       'up' if gap > 0 else 'down',
            'avg_volume':      int(avg_volume),
            'spread':          spread,
            'avg_daily_move':  round(avg_move * 100, 2),
            'relative_gap':    round(relative_gap, 2),
            'scan_time':       datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

    df = pd.DataFrame(candidates)
    if not df.empty:
        df = df.sort_values('relative_gap', ascending=False)
    return df

def save_candidates(gaps_df):
    conn = sqlite3.connect(DB_SIGNALS)
    gaps_df.to_sql('pre_market_gaps', conn, if_exists='replace', index=False)
    conn.close()
    log.info(f"Saved {len(gaps_df)} candidates to signals.db")

def run():
    log.info("=== PRE-MARKET SCAN STARTING ===")
    log.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"Gap threshold: {GAP_THRESHOLD * 100}%")
    log.info(f"Min avg volume: {MIN_AVG_VOLUME:,}")

    tickers      = get_volatile_tickers()
    quotes       = get_premarket_quotes(tickers)
    candidates_df = assess_candidates(tickers, quotes)

    if candidates_df.empty:
        log.info("No valid candidates found")
        return

    save_candidates(candidates_df)

    up   = len(candidates_df[candidates_df['direction'] == 'up'])
    down = len(candidates_df[candidates_df['direction'] == 'down'])

    log.info(f"""
    =============================
    PRE-MARKET SCAN COMPLETE
    =============================
    Candidates:   {len(candidates_df)}
    Gap up:       {up}
    Gap down:     {down}
    =============================
    """)

    log.info("Top 10 candidates by relative gap:")
    for _, row in candidates_df.head(10).iterrows():
        log.info(
            f"  {row['ticker']:6} | "
            f"{row['direction']:4} | "
            f"gap: {row['gap_pct']:+.2f}% | "
            f"rel: {row['relative_gap']:.1f}x | "
            f"vol: {row['avg_volume']:,.0f} | "
            f"spread: {row['spread']*100:.2f}%"
        )

if __name__ == "__main__":
    run()