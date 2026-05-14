import sys
sys.path.insert(0, "D:/Kestrel")

import os
import re
import time
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from config import ROOT, FINNHUB_API_KEY, ALPHA_VANTAGE_KEY

LOG_PATH = os.path.join(ROOT, "logs/catalyst.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.catalyst")

# --- Cache ---
_cache = {}

# --- Settings ---
EDGAR_LOOKBACK_DAYS  = 3
REDDIT_LOOKBACK_DAYS = 1
REQUEST_TIMEOUT      = 5

def _get(url, params=None, timeout=REQUEST_TIMEOUT):
    """Safe GET request."""
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        if resp.status_code == 200:
            return resp
        return None
    except Exception:
        return None

# --- Source 1: SEC EDGAR ---

def check_edgar(ticker):
    """Check SEC EDGAR for recent 8-K filings."""
    result = {'has_8k': False, 'filing_type': None, 'filing_date': None}
    try:
        url  = "https://efts.sec.gov/LATEST/search-index?q=%22{}%22&dateRange=custom&startdt={}&enddt={}&forms=8-K".format(
            ticker,
            (datetime.now() - timedelta(days=EDGAR_LOOKBACK_DAYS)).strftime('%Y-%m-%d'),
            datetime.now().strftime('%Y-%m-%d')
        )
        resp = _get(url)
        if resp:
            data = resp.json()
            hits = data.get('hits', {}).get('hits', [])
            if hits:
                result['has_8k']      = True
                result['filing_type'] = '8-K'
                result['filing_date'] = hits[0].get('_source', {}).get('period_of_report', '')
    except Exception as e:
        log.debug(f"EDGAR check failed for {ticker}: {e}")
    return result

# --- Source 2: Finnhub ---

def check_finnhub(ticker):
    """Check Finnhub for earnings surprise and recent news."""
    result = {
        'earnings_surprise': 0.0,
        'has_earnings':      False,
        'news_count':        0,
        'sentiment':         0.5
    }
    try:
        resp = _get(
            "https://finnhub.io/api/v1/stock/earnings",
            params={"symbol": ticker, "token": FINNHUB_API_KEY}
        )
        if resp:
            data = resp.json()
            if data and len(data) > 0:
                latest   = data[0]
                actual   = latest.get('actual', None)
                estimate = latest.get('estimate', None)
                period   = latest.get('period', '')

                if actual is not None and estimate is not None and estimate != 0:
                    surprise = (actual - estimate) / abs(estimate)
                    result['earnings_surprise'] = float(surprise)
                    try:
                        earnings_date = datetime.strptime(period, '%Y-%m-%d')
                        days_ago = (datetime.now() - earnings_date).days
                        if days_ago <= 7:
                            result['has_earnings'] = True
                    except Exception:
                        pass

        from_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
        to_date   = datetime.now().strftime('%Y-%m-%d')
        resp = _get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": ticker,
                "from":   from_date,
                "to":     to_date,
                "token":  FINNHUB_API_KEY
            }
        )
        if resp:
            news = resp.json()
            result['news_count'] = len(news) if isinstance(news, list) else 0
            if isinstance(news, list) and news:
                positive_words = ['beat', 'surge', 'jump', 'rally', 'gain',
                                  'profit', 'record', 'upgrade', 'buy', 'strong']
                negative_words = ['miss', 'fall', 'drop', 'loss', 'cut',
                                  'downgrade', 'sell', 'weak', 'decline', 'warning']
                pos = 0
                neg = 0
                for article in news[:10]:
                    headline = article.get('headline', '').lower()
                    pos += sum(1 for w in positive_words if w in headline)
                    neg += sum(1 for w in negative_words if w in headline)
                total = pos + neg
                if total > 0:
                    result['sentiment'] = pos / total
                else:
                    result['sentiment'] = 0.5
    except Exception as e:
        log.debug(f"Finnhub check failed for {ticker}: {e}")
    return result

# --- Source 3: Alpha Vantage ---

def check_alpha_vantage(ticker):
    """Check Alpha Vantage for news sentiment score."""
    result = {'av_sentiment': 0.5, 'av_relevance': 0.0}
    if not ALPHA_VANTAGE_KEY:
        return result
    try:
        resp = _get(
            "https://www.alphavantage.co/query",
            params={
                "function": "NEWS_SENTIMENT",
                "tickers":  ticker,
                "limit":    10,
                "apikey":   ALPHA_VANTAGE_KEY
            }
        )
        if resp:
            data = resp.json()
            feed = data.get('feed', [])
            if feed:
                sentiments = []
                relevances = []
                for article in feed[:10]:
                    for ts in article.get('ticker_sentiment', []):
                        if ts.get('ticker') == ticker:
                            sentiments.append(float(ts.get('ticker_sentiment_score', 0)))
                            relevances.append(float(ts.get('relevance_score', 0)))
                if sentiments:
                    result['av_sentiment'] = float(
                        sum(s * r for s, r in zip(sentiments, relevances)) /
                        max(sum(relevances), 0.001)
                    )
                    result['av_relevance'] = float(sum(relevances) / len(relevances))
                    result['av_sentiment'] = (result['av_sentiment'] + 1) / 2
    except Exception as e:
        log.debug(f"Alpha Vantage check failed for {ticker}: {e}")
    return result

# --- Source 4: Reddit ---

def check_reddit(ticker):
    """Check Reddit for mention count in last 24h."""
    result = {'mention_count': 0, 'mention_score': 0.0}
    try:
        resp = _get(
            "https://www.reddit.com/search.json",
            params={
                "q":     f"${ticker}",
                "sort":  "new",
                "limit": 25,
                "t":     "day"
            }
        )
        if resp:
            data  = resp.json()
            posts = data.get('data', {}).get('children', [])
            count = len(posts)
            result['mention_count'] = count
            result['mention_score'] = float(min(count / 20, 1.0))
    except Exception as e:
        log.debug(f"Reddit check failed for {ticker}: {e}")
    return result

# --- Source 5: Yahoo Finance Headlines ---

def check_yahoo_news(ticker):
    """Scrape Yahoo Finance news headlines for ticker."""
    result = {'headline': '', 'has_catalyst': False, 'yahoo_sentiment': 0.5}
    try:
        resp = _get(
            f"https://finance.yahoo.com/quote/{ticker}/news",
            timeout=8
        )
        if resp:
            html      = resp.text
            pattern   = r'<h3[^>]*>([^<]+)</h3>'
            headlines = re.findall(pattern, html)[:5]
            if headlines:
                result['headline'] = headlines[0]
                catalyst_words = [
                    'earnings', 'beats', 'misses', 'revenue', 'guidance',
                    'fda', 'approval', 'merger', 'acquisition', 'buyout',
                    'partnership', 'contract', 'upgrade', 'downgrade',
                    'dividend', 'split', 'buyback', 'lawsuit', 'recall'
                ]
                combined = ' '.join(headlines).lower()
                result['has_catalyst'] = any(w in combined for w in catalyst_words)
                positive = ['beat', 'surge', 'soar', 'rally', 'gain', 'record', 'strong']
                negative = ['miss', 'fall', 'drop', 'cut', 'weak', 'loss', 'decline']
                pos = sum(1 for w in positive if w in combined)
                neg = sum(1 for w in negative if w in combined)
                if pos + neg > 0:
                    result['yahoo_sentiment'] = pos / (pos + neg)
    except Exception as e:
        log.debug(f"Yahoo news check failed for {ticker}: {e}")
    return result

# --- Aggregator ---

def get_catalyst(ticker, use_cache=True):
    """
    Run all catalyst checks for one ticker.
    Returns unified catalyst dict with score and type.
    Cached per session.
    """
    if use_cache and ticker in _cache:
        return _cache[ticker]

    log.debug(f"Checking catalyst for {ticker}...")

    edgar   = check_edgar(ticker)
    finnhub = check_finnhub(ticker)
    av      = check_alpha_vantage(ticker)
    reddit  = check_reddit(ticker)
    yahoo   = check_yahoo_news(ticker)

    # Determine catalyst type
    if finnhub['has_earnings']:
        catalyst_type = 'earnings'
    elif edgar['has_8k']:
        catalyst_type = 'filing'
    elif yahoo['has_catalyst']:
        catalyst_type = 'news'
    elif reddit['mention_count'] > 10:
        catalyst_type = 'social'
    else:
        catalyst_type = 'none'

    # Calculate catalyst score 0-1
    score = 0.0
    if finnhub['has_earnings']:
        score += min(abs(finnhub['earnings_surprise']) * 35, 35)
    if edgar['has_8k']:
        score += 20

    sentiments    = [finnhub['sentiment'], av['av_sentiment'], yahoo['yahoo_sentiment']]
    avg_sentiment = sum(sentiments) / len(sentiments)
    score += avg_sentiment * 20
    score += min(finnhub['news_count'] / 10, 1.0) * 10
    score += reddit['mention_score'] * 10
    score += av['av_relevance'] * 5

    catalyst_score = round(min(score / 100, 1.0), 3)

    result = {
        'ticker':            ticker,
        'catalyst_score':    catalyst_score,
        'catalyst_type':     catalyst_type,
        'earnings_surprise': round(finnhub['earnings_surprise'], 3),
        'has_earnings':      finnhub['has_earnings'],
        'has_8k':            edgar['has_8k'],
        'news_count':        finnhub['news_count'],
        'sentiment':         round(avg_sentiment, 3),
        'reddit_mentions':   reddit['mention_count'],
        'av_relevance':      round(av['av_relevance'], 3),
        'headline':          yahoo['headline'][:200] if yahoo['headline'] else '',
        'checked_at':        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    _cache[ticker] = result

    log.info(
        f"{ticker} | type: {catalyst_type} | "
        f"score: {catalyst_score:.3f} | "
        f"earnings: {finnhub['has_earnings']} | "
        f"8-K: {edgar['has_8k']} | "
        f"sentiment: {avg_sentiment:.2f} | "
        f"reddit: {reddit['mention_count']}"
    )

    return result

# --- Assessment ---

def assess_catalyst(result, gap_direction='up'):
    """
    Qualitatively assess catalyst quality, alignment, credibility.
    Returns three normalized scores 0-1.
    """
    credibility = 0.0
    if result['has_8k']:
        credibility += 0.35
    if result['has_earnings']:
        credibility += 0.35
    if result['av_relevance'] > 0.3:
        credibility += 0.20
    if result['news_count'] > 2:
        credibility += 0.10
    credibility = min(credibility, 1.0)

    sentiment = result['sentiment']
    if gap_direction == 'up':
        alignment = sentiment
    else:
        alignment = 1 - sentiment

    surprise = result['earnings_surprise']
    if gap_direction == 'up' and surprise > 0:
        alignment = min(alignment + 0.2, 1.0)
    elif gap_direction == 'up' and surprise < 0:
        alignment = max(alignment - 0.2, 0.0)

    quality = (
        credibility * 0.40 +
        alignment   * 0.35 +
        min(result['catalyst_score'], 1.0) * 0.25
    )

    return {
        'catalyst_quality':     round(quality, 3),
        'catalyst_alignment':   round(alignment, 3),
        'catalyst_credibility': round(credibility, 3)
    }

# --- Runner ---

def run(tickers):
    """Run catalyst check for a list of tickers."""
    log.info(f"=== CATALYST SCAN — {len(tickers)} tickers ===")
    results = {}
    for i, ticker in enumerate(tickers):
        results[ticker] = get_catalyst(ticker)
        if i % 5 == 0 and i > 0:
            time.sleep(1)
    log.info(f"Catalyst scan complete — {len(results)} tickers processed")
    return results

if __name__ == "__main__":
    import sqlite3
    import pandas as pd
    from config import DB_SIGNALS

    conn = sqlite3.connect(DB_SIGNALS)
    df   = pd.read_sql("SELECT DISTINCT ticker FROM confirmed_gaps", conn)
    conn.close()

    tickers = df['ticker'].tolist()
    if not tickers:
        tickers = ['QUBT', 'RXT', 'HIMS', 'PLUG']

    log.info(f"Testing catalyst scan on: {tickers}")
    results = run(tickers)

    print("\n=== CATALYST RESULTS ===")
    for ticker, r in results.items():
        print(f"\n{ticker}:")
        print(f"  Type:        {r['catalyst_type']}")
        print(f"  Score:       {r['catalyst_score']}")
        print(f"  Earnings:    {r['has_earnings']} (surprise: {r['earnings_surprise']})")
        print(f"  8-K:         {r['has_8k']}")
        print(f"  Sentiment:   {r['sentiment']}")
        print(f"  Reddit:      {r['reddit_mentions']} mentions")
        print(f"  Headline:    {r['headline'][:80]}")

        assessment = assess_catalyst(r, gap_direction='up')
        print(f"  Quality:     {assessment['catalyst_quality']}")
        print(f"  Alignment:   {assessment['catalyst_alignment']}")
        print(f"  Credibility: {assessment['catalyst_credibility']}")