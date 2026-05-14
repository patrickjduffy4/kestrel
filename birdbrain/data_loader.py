import sys
sys.path.insert(0, "D:/Kestrel")

import os
import numpy as np
import pandas as pd
import logging
from datetime import datetime, timedelta
from config import ROOT, RAW_DATA

LOG_PATH = os.path.join(ROOT, "logs/rightbrain.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.birdbrain.data_loader")

# --- Settings ---
MIN_GAP_PCT    = 0.05
MIN_AVG_VOLUME = 500_000
LOOKBACK       = 20

# --- Market context cache ---
_market_context = None

def get_col(df, prefix):
    """Get column by prefix — handles both string and tuple column names."""
    for c in df.columns:
        name = c[0] if isinstance(c, tuple) else c
        if str(name).lower().startswith(prefix.lower()):
            return c
    return None

def load_ticker(path):
    """Load and validate a parquet file."""
    try:
        df = pd.read_parquet(path)
        if len(df) < LOOKBACK + 5:
            return None

        close_col = get_col(df, 'C')
        open_col  = get_col(df, 'O')
        high_col  = get_col(df, 'H')
        low_col   = get_col(df, 'L')
        vol_col   = get_col(df, 'V')

        if not all([close_col, open_col, high_col, low_col, vol_col]):
            return None

        return {
            'df':    df,
            'close': close_col,
            'open':  open_col,
            'high':  high_col,
            'low':   low_col,
            'vol':   vol_col
        }
    except Exception:
        return None

# --- Pass 1: Parquet-derived feature calculators ---

def calc_rsi(closes, period=14):
    """Calculate RSI from close prices."""
    try:
        deltas = np.diff(closes[-period-1:])
        gains  = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains) if len(gains) > 0 else 0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0
        if avg_loss == 0:
            return 1.0
        rs  = avg_gain / avg_loss
        rsi = 1 - (1 / (1 + rs))
        return float(np.clip(rsi, 0, 1))
    except Exception:
        return 0.5

def calc_atr(highs, lows, closes, period=14):
    """Calculate Average True Range normalized by price."""
    try:
        trs = []
        for j in range(1, min(period + 1, len(closes))):
            tr = max(
                highs[-j] - lows[-j],
                abs(highs[-j] - closes[-j-1]),
                abs(lows[-j] - closes[-j-1])
            )
            trs.append(tr)
        atr       = np.mean(trs) if trs else 0
        avg_price = np.mean(closes[-period:])
        return float(np.clip(atr / avg_price if avg_price > 0 else 0, 0, 0.1)) / 0.1
    except Exception:
        return 0.5

def calc_gap_fill_rate(opens, closes, gap_threshold=0.02, lookback=60):
    """What fraction of past gaps did this stock fill by end of day?"""
    try:
        fills = 0
        gaps  = 0
        start = max(1, len(closes) - lookback)
        for j in range(start, len(closes) - 1):
            prev = closes[j - 1]
            op   = opens[j]
            cl   = closes[j]
            if prev <= 0:
                continue
            gap = (op - prev) / prev
            if gap >= gap_threshold:
                gaps += 1
                if cl < prev:
                    fills += 1
        return float(fills / gaps) if gaps > 0 else 0.5
    except Exception:
        return 0.5

def calc_52w_high_distance(closes):
    """How far is current price from 52 week high? 0=at high, 1=far below."""
    try:
        lookback = min(252, len(closes))
        high_52w = np.max(closes[-lookback:])
        current  = closes[-1]
        if high_52w <= 0:
            return 0.5
        dist = (high_52w - current) / high_52w
        return float(np.clip(dist, 0, 1))
    except Exception:
        return 0.5

def calc_candle_type(open_price, close_price, high, low):
    """Previous day candle classification. 1.0=strong bullish, 0.0=strong bearish."""
    try:
        body   = close_price - open_price
        range_ = high - low
        if range_ == 0:
            return 0.5
        body_ratio = body / range_
        return float(np.clip((body_ratio + 1) / 2, 0, 1))
    except Exception:
        return 0.5

def calc_consecutive_days(closes, lookback=10):
    """Consecutive up/down days going into the gap. Normalized -1 to 1."""
    try:
        streak = 0
        for j in range(len(closes) - 1, max(len(closes) - lookback - 1, 0), -1):
            if closes[j] > closes[j-1]:
                if streak >= 0:
                    streak += 1
                else:
                    break
            else:
                if streak <= 0:
                    streak -= 1
                else:
                    break
        return float(np.clip(streak / lookback, -1, 1))
    except Exception:
        return 0.0

# --- Pass 2: Market context loader ---

def load_market_context():
    """
    Load market-wide context once per session.
    SPY/QQQ from local parquet, VIX from yfinance.
    """
    global _market_context
    if _market_context is not None:
        return _market_context

    ctx = {
        'spy_momentum': 0.5,
        'qqq_momentum': 0.5,
        'vix_norm':     0.5,
    }

    # SPY/QQQ momentum from local parquet
    for symbol, key in [('SPY', 'spy_momentum'), ('QQQ', 'qqq_momentum')]:
        path = os.path.join(RAW_DATA, f"{symbol}.parquet")
        if os.path.exists(path):
            try:
                df        = pd.read_parquet(path)
                close_col = get_col(df, 'C')
                if close_col is not None:
                    closes   = df[close_col].values
                    mom_5    = (closes[-1] - closes[-5]) / closes[-5] if closes[-5] > 0 else 0
                    ctx[key] = float(np.clip((mom_5 + 0.05) / 0.10, 0, 1))
                    log.info(f"{symbol} momentum loaded: {ctx[key]:.3f}")
                else:
                    log.debug(f"{symbol}: close column not found")
            except Exception as e:
                log.debug(f"{symbol} context failed: {e}")

    # VIX from yfinance
    try:
        import yfinance as yf
        vix      = yf.Ticker("^VIX")
        vix_hist = vix.history(period="5d")
        if not vix_hist.empty:
            vix_val      = float(vix_hist['Close'].iloc[-1])
            ctx['vix_norm'] = float(np.clip((vix_val - 10) / 50, 0, 1))
    except Exception:
        pass

    _market_context = ctx
    log.info(f"Market context loaded: {ctx}")
    return ctx

def load_ticker_fundamentals(ticker):
    """Load fundamental data for one ticker via yfinance."""
    defaults = {
        'float_norm':         0.5,
        'short_ratio_norm':   0.5,
        'earnings_proximity': 0.5,
        'sector_norm':        0.5,
    }
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info  = stock.info

        float_shares       = info.get('floatShares', 0) or 0
        float_norm         = float(np.clip(1 - float_shares / 1_000_000_000, 0, 1))

        short_ratio        = info.get('shortRatio', 0) or 0
        short_ratio_norm   = float(np.clip(short_ratio / 20, 0, 1))

        earnings_ts        = info.get('earningsTimestamp', None)
        if earnings_ts:
            earnings_date      = datetime.fromtimestamp(earnings_ts)
            days_to_earnings   = (earnings_date - datetime.now()).days
            earnings_proximity = float(np.clip(1 - abs(days_to_earnings) / 90, 0, 1))
        else:
            earnings_proximity = 0.5

        sector_map = {
            'Technology': 1.0, 'Healthcare': 0.8,
            'Consumer Cyclical': 0.7, 'Financial Services': 0.6,
            'Communication Services': 0.6, 'Industrials': 0.5,
            'Consumer Defensive': 0.4, 'Energy': 0.4,
            'Basic Materials': 0.3, 'Real Estate': 0.3,
            'Utilities': 0.2
        }
        sector      = info.get('sector', '')
        sector_norm = sector_map.get(sector, 0.5)

        return {
            'float_norm':         float_norm,
            'short_ratio_norm':   short_ratio_norm,
            'earnings_proximity': earnings_proximity,
            'sector_norm':        sector_norm,
        }
    except Exception:
        return defaults

def build_rightbrain_features(gap_pct, relative_gap, vol_trend,
                               avg_vol, below_5d, below_20d,
                               momentum_20, vol_trend_hist,
                               price_vs_20ma, avg_daily_range,
                               rsi, atr, gap_fill_rate,
                               high_52w_dist, candle_type,
                               consecutive_days, spy_momentum,
                               qqq_momentum, vix_norm,
                               float_norm, short_ratio_norm,
                               earnings_proximity,
                               catalyst_quality=0.5,
                               catalyst_alignment=0.5,
                               catalyst_credibility=0.5):
    """Build normalized 25-feature vector for rightbrain."""
    spread_norm   = 0.5
    accuracy_norm = 0.5

    return np.array([
        np.clip(gap_pct / 0.50, 0, 1),
        np.clip(relative_gap / 10, 0, 1),
        spread_norm,
        np.clip(vol_trend / 3, 0, 1),
        np.clip(avg_vol / 50_000_000, 0, 1),
        accuracy_norm,
        float(below_5d),
        float(below_20d),
        float(np.clip(momentum_20, -1, 1)),
        float(np.clip(vol_trend_hist / 5, 0, 1)),
        float(np.clip(price_vs_20ma, -1, 1)),
        float(np.clip(avg_daily_range, 0, 1)),
        rsi,
        atr,
        gap_fill_rate,
        high_52w_dist,
        candle_type,
        float(np.clip((consecutive_days + 1) / 2, 0, 1)),
        spy_momentum,
        qqq_momentum,
        vix_norm,
        earnings_proximity,
        float(catalyst_quality),
        float(catalyst_alignment),
        float(catalyst_credibility),
    ], dtype=np.float32)

def build_leftbrain_features(gap_pct, price_vs_5d, price_vs_20d,
                              vol_trend, avg_vol, momentum_20,
                              avg_daily_range, day_of_week,
                              relative_gap, vol_trend_hist,
                              rsi, atr, gap_fill_rate,
                              spy_momentum, qqq_momentum,
                              vix_norm, float_norm,
                              short_ratio_norm):
    """Build normalized 18-feature vector for leftbrain."""
    return np.array([
        np.clip(gap_pct / 0.50, 0, 1),
        float(np.clip(price_vs_5d, -1, 1)),
        float(np.clip(price_vs_20d, -1, 1)),
        np.clip(vol_trend / 3, 0, 1),
        np.clip(avg_vol / 50_000_000, 0, 1),
        float(np.clip(momentum_20, -1, 1)),
        float(np.clip(avg_daily_range, 0, 1)),
        day_of_week / 4.0,
        np.clip(relative_gap / 10, 0, 1),
        float(np.clip(vol_trend_hist / 5, 0, 1)),
        rsi,
        atr,
        gap_fill_rate,
        spy_momentum,
        qqq_momentum,
        vix_norm,
        float_norm,
        short_ratio_norm,
    ], dtype=np.float32)

def extract_samples(ticker, data, mode='rightbrain', fundamentals=None):
    """Extract training samples from one ticker's history."""
    samples = []

    df      = data['df']
    closes  = df[data['close']].values
    opens   = df[data['open']].values
    highs   = df[data['high']].values
    lows    = df[data['low']].values
    volumes = df[data['vol']].values

    try:
        dates = df.index
    except Exception:
        dates = range(len(df))

    ctx  = load_market_context()
    fund = fundamentals or {
        'float_norm': 0.5, 'short_ratio_norm': 0.5,
        'earnings_proximity': 0.5, 'sector_norm': 0.5
    }

    gap_fill_rate = calc_gap_fill_rate(opens, closes)

    for i in range(LOOKBACK + 1, len(df)):
        try:
            prev_close  = closes[i - 1]
            today_open  = opens[i]
            today_close = closes[i]
            today_high  = highs[i]
            today_low   = lows[i]

            if prev_close <= 0 or today_open <= 0:
                continue

            gap_pct = (today_open - prev_close) / prev_close

            if gap_pct < MIN_GAP_PCT:
                continue

            hist_closes  = closes[i - LOOKBACK:i]
            hist_volumes = volumes[i - LOOKBACK:i]
            hist_highs   = highs[i - LOOKBACK:i]
            hist_lows    = lows[i - LOOKBACK:i]

            avg_vol = float(np.mean(hist_volumes))
            if avg_vol < MIN_AVG_VOLUME:
                continue

            avg_5  = float(np.mean(hist_closes[-5:]))
            avg_20 = float(np.mean(hist_closes))
            vol_5  = float(np.mean(hist_volumes[-5:]))
            vol_20 = float(np.mean(hist_volumes))

            momentum_20    = (prev_close - hist_closes[0]) / hist_closes[0] if hist_closes[0] > 0 else 0
            vol_trend      = vol_5 / vol_20 if vol_20 > 0 else 1.0
            vol_trend_hist = vol_trend
            price_vs_20ma  = (today_open - avg_20) / avg_20 if avg_20 > 0 else 0
            price_vs_5d    = (today_open - avg_5) / avg_5 if avg_5 > 0 else 0

            hist_ranges     = hist_highs - hist_lows
            avg_daily_range = float(np.mean(hist_ranges) / avg_20) if avg_20 > 0 else 0

            daily_moves    = np.abs(np.diff(hist_closes) / hist_closes[:-1])
            avg_daily_move = float(np.mean(daily_moves)) if len(daily_moves) > 0 else 0.01
            relative_gap   = gap_pct / avg_daily_move if avg_daily_move > 0 else 0

            below_5d  = today_open < avg_5
            below_20d = today_open < avg_20

            try:
                day_of_week = pd.Timestamp(dates[i]).dayofweek
            except Exception:
                day_of_week = 2

            rsi              = calc_rsi(hist_closes)
            atr              = calc_atr(hist_highs, hist_lows, hist_closes)
            high_52w_dist    = calc_52w_high_distance(hist_closes)
            candle_type      = calc_candle_type(opens[i-1], closes[i-1], highs[i-1], lows[i-1])
            consecutive_days = calc_consecutive_days(hist_closes)

            spy_momentum       = ctx.get('spy_momentum', 0.5)
            qqq_momentum       = ctx.get('qqq_momentum', 0.5)
            vix_norm           = ctx.get('vix_norm', 0.5)
            float_norm         = fund.get('float_norm', 0.5)
            short_ratio_norm   = fund.get('short_ratio_norm', 0.5)
            earnings_proximity = fund.get('earnings_proximity', 0.5)

            if mode == 'rightbrain':
                features = build_rightbrain_features(
                    gap_pct, relative_gap, vol_trend,
                    avg_vol, below_5d, below_20d,
                    momentum_20, vol_trend_hist,
                    price_vs_20ma, avg_daily_range,
                    rsi, atr, gap_fill_rate,
                    high_52w_dist, candle_type,
                    consecutive_days, spy_momentum,
                    qqq_momentum, vix_norm,
                    float_norm, short_ratio_norm,
                    earnings_proximity
                )
                end_return = (today_close - today_open) / today_open
                if end_return >= 0.02:
                    label = 1.0
                elif end_return >= 0.0:
                    label = 0.6
                elif end_return >= -0.02:
                    label = 0.4
                else:
                    label = 0.0

            elif mode == 'leftbrain':
                features = build_leftbrain_features(
                    gap_pct, price_vs_5d, price_vs_20ma,
                    vol_trend, avg_vol, momentum_20,
                    avg_daily_range, day_of_week,
                    relative_gap, vol_trend_hist,
                    rsi, atr, gap_fill_rate,
                    spy_momentum, qqq_momentum,
                    vix_norm, float_norm, short_ratio_norm
                )
                end_return = (today_close - today_open) / today_open
                label = float(np.clip((end_return + 0.10) / 0.20, 0, 1))

            else:
                continue

            samples.append((features, label))

        except Exception:
            continue

    return samples

def load_all_samples(mode='rightbrain', max_tickers=None,
                     min_samples=10, use_fundamentals=False):
    """Load training samples from all tickers."""
    log.info(f"Loading historical samples — mode: {mode}")

    parquet_files = [f for f in os.listdir(RAW_DATA) if f.endswith('.parquet')]
    if max_tickers:
        parquet_files = parquet_files[:max_tickers]

    log.info(f"Processing {len(parquet_files)} tickers...")

    all_X         = []
    all_y         = []
    tickers_used  = 0
    total_samples = 0

    for i, fname in enumerate(parquet_files):
        ticker = fname.replace('.parquet', '')
        path   = os.path.join(RAW_DATA, fname)

        data = load_ticker(path)
        if data is None:
            continue

        fundamentals = None
        if use_fundamentals:
            fundamentals = load_ticker_fundamentals(ticker)

        samples = extract_samples(ticker, data, mode=mode,
                                  fundamentals=fundamentals)

        if len(samples) < min_samples:
            continue

        for features, label in samples:
            all_X.append(features)
            all_y.append(label)

        tickers_used  += 1
        total_samples += len(samples)

        if i % 500 == 0 and i > 0:
            log.info(f"  Processed {i}/{len(parquet_files)} tickers — {total_samples:,} samples so far")

    if not all_X:
        log.error("No samples extracted")
        return None, None

    X = np.array(all_X, dtype=np.float32)
    y = np.array(all_y, dtype=np.float32)

    log.info(f"Done — {tickers_used} tickers, {total_samples:,} samples")
    log.info(f"Feature shape: {X.shape}")
    log.info(f"Label distribution: mean={y.mean():.3f} std={y.std():.3f}")

    return X, y

if __name__ == "__main__":
    log.info("Testing data loader...")

    log.info("--- rightbrain mode (50 tickers, no fundamentals) ---")
    X, y = load_all_samples(mode='rightbrain', max_tickers=None)
    if X is not None:
        log.info(f"rightbrain: {X.shape[0]:,} samples, {X.shape[1]} features")
        log.info(f"Label mean: {y.mean():.3f}")

    log.info("--- leftbrain mode (50 tickers, no fundamentals) ---")
    X, y = load_all_samples(mode='leftbrain', max_tickers=None)
    if X is not None:
        log.info(f"leftbrain: {X.shape[0]:,} samples, {X.shape[1]} features")
        log.info(f"Label mean: {y.mean():.3f}")