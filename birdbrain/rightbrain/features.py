import sys
sys.path.insert(0, "D:/Kestrel")

import os
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime
from config import ROOT, DB_SIGNALS, RAW_DATA

import logging
LOG_PATH = os.path.join(ROOT, "logs/rightbrain.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.rightbrain.features")

# Feature names — order matters for NN input
FEATURE_NAMES = [
    'gap_pct',
    'relative_gap',
    'spread',
    'volume_trend',
    'avg_volume_norm',
    'gap_accuracy',
    'below_5d',
    'below_20d',
    'momentum_20',
    'vol_trend_hist',
    'price_vs_20ma',
    'avg_daily_range'
]

def get_historical_features(ticker):
    """Pull price/volume features from local parquet."""
    try:
        path = os.path.join(RAW_DATA, f"{ticker}.parquet")
        if not os.path.exists(path):
            return None

        df = pd.read_parquet(path)
        if len(df) < 20:
            return None

        close_col = [c for c in df.columns if c[0] == 'Close'][0]
        vol_col   = [c for c in df.columns if c[0] == 'Volume'][0]

        closes  = df[close_col]
        volumes = df[vol_col]

        current   = float(closes.iloc[-1])
        avg_5     = float(closes.tail(5).mean())
        avg_20    = float(closes.tail(20).mean())
        vol_5     = float(volumes.tail(5).mean())
        vol_20    = float(volumes.tail(20).mean())

        momentum_20    = (current - float(closes.iloc[-20])) / float(closes.iloc[-20])
        vol_trend_hist = vol_5 / vol_20 if vol_20 > 0 else 1.0
        price_vs_20ma  = (current - avg_20) / avg_20
        avg_daily_range = float((df[[c for c in df.columns if c[0] == 'High'][0]].tail(20) -
                                  df[[c for c in df.columns if c[0] == 'Low'][0]].tail(20)).mean() / avg_20)

        return {
            'below_5d':        1.0 if current < avg_5 else 0.0,
            'below_20d':       1.0 if current < avg_20 else 0.0,
            'momentum_20':     float(np.clip(momentum_20, -1, 1)),
            'vol_trend_hist':  float(np.clip(vol_trend_hist, 0, 5)),
            'price_vs_20ma':   float(np.clip(price_vs_20ma, -1, 1)),
            'avg_daily_range': float(np.clip(avg_daily_range, 0, 0.2))
        }

    except Exception as e:
        log.debug(f"Historical features failed for {ticker}: {e}")
        return None

def build_feature_vector(row, hist_features):
    """
    Build normalized feature vector for one candidate.
    Returns numpy array of shape (12,) or None.
    """
    try:
        gap_pct      = float(row.get('gap_pct', 0) or 0)
        relative_gap = float(row.get('relative_gap', 0) or 0)
        spread       = float(row.get('spread', 0) or 0)
        volume_trend = float(row.get('volume_trend', 1) or 1)
        avg_volume   = float(row.get('avg_volume', 0) or 0)
        gap_accuracy = float(row.get('gap_accuracy', 0) or 0)

        # Normalize
        gap_pct_norm      = np.clip(gap_pct / 50, -1, 1)
        relative_gap_norm = np.clip(relative_gap / 10, 0, 1)
        spread_norm       = np.clip(1 - spread * 20, 0, 1)  # tighter = higher
        vol_trend_norm    = np.clip(volume_trend / 3, 0, 1)
        avg_vol_norm      = np.clip(avg_volume / 50_000_000, 0, 1)
        accuracy_norm     = np.clip(gap_accuracy, 0, 1)

        # Historical features
        below_5d        = hist_features.get('below_5d', 0.5) if hist_features else 0.5
        below_20d       = hist_features.get('below_20d', 0.5) if hist_features else 0.5
        momentum_20     = hist_features.get('momentum_20', 0) if hist_features else 0
        vol_trend_hist  = hist_features.get('vol_trend_hist', 1) / 5 if hist_features else 0.2
        price_vs_20ma   = hist_features.get('price_vs_20ma', 0) if hist_features else 0
        avg_daily_range = hist_features.get('avg_daily_range', 0) / 0.2 if hist_features else 0

        features = np.array([
            gap_pct_norm,
            relative_gap_norm,
            spread_norm,
            vol_trend_norm,
            avg_vol_norm,
            accuracy_norm,
            below_5d,
            below_20d,
            momentum_20,
            vol_trend_hist,
            price_vs_20ma,
            avg_daily_range
        ], dtype=np.float32)

        return features

    except Exception as e:
        log.debug(f"Feature vector failed: {e}")
        return None

def load_training_data(days_back=30):
    """
    Load historical scoring data with outcomes for training.
    Joins watchlist_history with trade outcomes.
    Returns X (features) and y (labels).
    """
    try:
        conn = sqlite3.connect(DB_SIGNALS)

        # Load watchlist history
        history = pd.read_sql(
            "SELECT * FROM watchlist_history ORDER BY snapshot_at DESC",
            conn
        )
        conn.close()

        if history.empty:
            log.warning("No watchlist history available for training")
            return None, None

        # Load trade outcomes
        from config import DB_PERF
        conn_perf = sqlite3.connect(DB_PERF)
        trades = pd.read_sql(
            "SELECT ticker, date, pnl_pct, outcome FROM trades",
            conn_perf
        )
        conn_perf.close()

        if trades.empty:
            log.warning("No trade outcomes available for training")
            return None, None

        # Build feature vectors and labels
        X = []
        y = []

        for _, row in history.iterrows():
            ticker = row['ticker']

            # Find matching trade outcome
            trade = trades[trades['ticker'] == ticker]
            if trade.empty:
                continue

            pnl_pct = float(trade.iloc[0]['pnl_pct'])

            # Label — was this a good pick?
            # 1 if profitable, 0 if not
            label = 1.0 if pnl_pct > 0 else 0.0

            # Build features
            hist = get_historical_features(ticker)
            features = build_feature_vector(row, hist)

            if features is not None:
                X.append(features)
                y.append(label)

        if not X:
            log.warning("No valid training samples built")
            return None, None

        X = np.array(X, dtype=np.float32)
        y = np.array(y, dtype=np.float32)

        log.info(f"Training data: {len(X)} samples, {X.shape[1]} features")
        log.info(f"Label distribution: {y.mean():.2f} positive rate")

        return X, y

    except Exception as e:
        log.error(f"Failed to load training data: {e}")
        return None, None

if __name__ == "__main__":
    log.info("Testing feature extraction...")

    conn = sqlite3.connect(DB_SIGNALS)
    try:
        df = pd.read_sql("SELECT * FROM confirmed_gaps LIMIT 3", conn)
        conn.close()

        for _, row in df.iterrows():
            ticker = row['ticker']
            hist   = get_historical_features(ticker)
            vec    = build_feature_vector(row, hist)
            if vec is not None:
                log.info(f"{ticker}: features shape {vec.shape} — {vec}")
            else:
                log.warning(f"{ticker}: feature extraction failed")
    except Exception as e:
        log.error(f"Test failed: {e}")