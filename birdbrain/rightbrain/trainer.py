import sys
sys.path.insert(0, "D:/Kestrel")

import os
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
import sqlite3
import pandas as pd
import logging
from datetime import datetime
from config import ROOT, DB_SIGNALS, DB_PERF

LOG_PATH = os.path.join(ROOT, "logs/rightbrain.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.rightbrain.trainer")

# --- Settings ---
BATCH_SIZE    = 64
EPOCHS        = 50
LEARNING_RATE = 0.0005
TRAIN_SPLIT   = 0.80
MIN_SAMPLES   = 10

def load_live_samples():
    """
    Load live training samples from watchlist history and trade outcomes.
    Joins watchlist_history with trade outcomes to build labeled dataset.
    Returns X, y or None, None if insufficient data.
    """
    try:
        # Load watchlist history
        conn     = sqlite3.connect(DB_SIGNALS)
        history  = pd.read_sql(
            "SELECT * FROM watchlist_history ORDER BY snapshot_at DESC",
            conn
        )
        avoided  = pd.read_sql(
            "SELECT * FROM avoided_opportunities ORDER BY avoided_at DESC",
            conn
        )
        conn.close()

        # Load trade outcomes
        conn_perf = sqlite3.connect(DB_PERF)
        trades    = pd.read_sql(
            "SELECT ticker, date, pnl, pnl_pct, exit_reason, system_a_score FROM trades",
            conn_perf
        )
        conn_perf.close()

        if trades.empty:
            log.warning("No trade outcomes available yet — skipping live training")
            return None, None

        log.info(f"Found {len(trades)} trades, {len(history)} watchlist snapshots, {len(avoided)} avoided")

        X = []
        y = []

        # --- Positive samples: stocks that were traded ---
        for _, trade in trades.iterrows():
            ticker = trade['ticker']
            date   = trade['date']

            # Find matching watchlist snapshot
            snap = history[
                (history['ticker'] == ticker) &
                (history['snapshot_at'].str.startswith(date))
            ]

            if snap.empty:
                continue

            row = snap.iloc[0]

            # Build features
            features = build_live_features(row, ticker)
            if features is None:
                continue

            # Label based on P&L
            pnl_pct = float(trade['pnl_pct'])
            if pnl_pct >= 2.0:
                label = 1.0
            elif pnl_pct >= 0:
                label = 0.7
            elif pnl_pct >= -2.0:
                label = 0.3
            else:
                label = 0.0

            X.append(features)
            y.append(label)

        # --- Negative samples: stocks that were avoided ---
        for _, av in avoided.iterrows():
            ticker = av['ticker']
            date   = av.get('avoided_at', '')[:10]

            features = build_avoided_features(av, ticker)
            if features is None:
                continue

            # Avoided stocks labeled as 0.3 — slightly negative
            # rightbrain learns to be cautious about similar patterns
            X.append(features)
            y.append(0.3)

        if len(X) < MIN_SAMPLES:
            log.warning(f"Insufficient samples for live training: {len(X)} < {MIN_SAMPLES}")
            return None, None

        X = np.array(X, dtype=np.float32)
        y = np.array(y, dtype=np.float32)

        log.info(f"Live training data: {len(X)} samples")
        log.info(f"Label distribution: mean={y.mean():.3f}")

        return X, y

    except Exception as e:
        log.error(f"Failed to load live samples: {e}")
        return None, None

def build_live_features(row, ticker):
    """Build feature vector from watchlist history row."""
    try:
        from birdbrain.data_loader import build_rightbrain_features, load_market_context
        from feed.opportunity.catalyst import get_catalyst, assess_catalyst

        ctx      = load_market_context()
        catalyst = get_catalyst(ticker)
        assess   = assess_catalyst(catalyst, gap_direction='up')

        features = build_rightbrain_features(
            gap_pct            = float(row.get('gap_pct', 0) or 0) / 100,
            relative_gap       = float(row.get('relative_gap', 0) or 0),
            vol_trend          = float(row.get('volume_trend', 1) or 1),
            avg_vol            = float(row.get('avg_volume', 0) or 0),
            below_5d           = 0.5,
            below_20d          = 0.5,
            momentum_20        = 0.0,
            vol_trend_hist     = 1.0,
            price_vs_20ma      = 0.0,
            avg_daily_range    = 0.0,
            rsi                = 0.5,
            atr                = 0.5,
            gap_fill_rate      = 0.5,
            high_52w_dist      = 0.5,
            candle_type        = 0.5,
            consecutive_days   = 0.0,
            spy_momentum       = ctx.get('spy_momentum', 0.5),
            qqq_momentum       = ctx.get('qqq_momentum', 0.5),
            vix_norm           = ctx.get('vix_norm', 0.5),
            float_norm         = 0.5,
            short_ratio_norm   = 0.5,
            earnings_proximity = 0.5,
            catalyst_quality      = assess.get('catalyst_quality', 0.5),
            catalyst_alignment    = assess.get('catalyst_alignment', 0.5),
            catalyst_credibility  = assess.get('catalyst_credibility', 0.5)
        )
        return features
    except Exception as e:
        log.debug(f"Live feature build failed for {ticker}: {e}")
        return None

def build_avoided_features(row, ticker):
    """Build feature vector from avoided opportunity row."""
    try:
        from birdbrain.data_loader import build_rightbrain_features, load_market_context

        ctx = load_market_context()

        features = build_rightbrain_features(
            gap_pct            = float(row.get('gap_pct', 0) or 0) / 100,
            relative_gap       = 0.5,
            vol_trend          = 1.0,
            avg_vol            = 0.0,
            below_5d           = 0.5,
            below_20d          = 0.5,
            momentum_20        = 0.0,
            vol_trend_hist     = 1.0,
            price_vs_20ma      = 0.0,
            avg_daily_range    = 0.0,
            rsi                = 0.5,
            atr                = 0.5,
            gap_fill_rate      = 0.5,
            high_52w_dist      = 0.5,
            candle_type        = 0.5,
            consecutive_days   = 0.0,
            spy_momentum       = ctx.get('spy_momentum', 0.5),
            qqq_momentum       = ctx.get('qqq_momentum', 0.5),
            vix_norm           = ctx.get('vix_norm', 0.5),
            float_norm         = 0.5,
            short_ratio_norm   = 0.5,
            earnings_proximity = 0.5,
            catalyst_quality     = 0.5,
            catalyst_alignment   = 0.5,
            catalyst_credibility = 0.5
        )
        return features
    except Exception as e:
        log.debug(f"Avoided feature build failed for {ticker}: {e}")
        return None

def train(X, y, model):
    """Train rightbrain on live trade data."""
    log.info(f"Training on {len(X)} live samples...")

    idx = np.random.permutation(len(X))
    X, y = X[idx], y[idx]

    split   = int(len(X) * TRAIN_SPLIT)
    X_train = torch.FloatTensor(X[:split])
    y_train = torch.FloatTensor(y[:split]).unsqueeze(1)
    X_val   = torch.FloatTensor(X[split:])
    y_val   = torch.FloatTensor(y[split:]).unsqueeze(1)

    train_ds     = TensorDataset(X_train, y_train)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)

    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, patience=5, factor=0.5
    )

    best_val_loss = float('inf')
    best_state    = None
    accuracy      = 0.0

    for epoch in range(EPOCHS):
        model.train()
        train_loss = 0
        for X_batch, y_batch in train_loader:
            optimizer.zero_grad()
            output = model(X_batch)
            loss   = criterion(output, y_batch)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()

        train_loss /= len(train_loader)

        model.eval()
        with torch.no_grad():
            val_output = model(X_val)
            val_loss   = criterion(val_output, y_val).item()
            predicted  = (val_output > 0.5).float()
            actual     = (y_val > 0.5).float()
            accuracy   = (predicted == actual).float().mean().item()

        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state    = {k: v.clone() for k, v in model.state_dict().items()}

        if epoch % 10 == 0 or epoch == EPOCHS - 1:
            log.info(
                f"Epoch {epoch+1:3d}/{EPOCHS} | "
                f"Train: {train_loss:.4f} | "
                f"Val: {val_loss:.4f} | "
                f"Acc: {accuracy*100:.1f}%"
            )

    if best_state:
        model.load_state_dict(best_state)

    model.training_history['sessions']      += 1
    model.training_history['total_samples'] += len(X)
    model.training_history['last_trained']   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    model.training_history['last_accuracy']  = round(accuracy * 100, 1)

    return model, accuracy

def run():
    """
    Nightly training loop.
    Runs after market close, trains on today's outcomes.
    """
    from birdbrain.rightbrain.model import get_model

    log.info("=== RIGHTBRAIN NIGHTLY TRAINER STARTING ===")

    X, y = load_live_samples()
    if X is None:
        log.info("No live data yet — skipping nightly training")
        return

    model = get_model()
    model, accuracy = train(X, y, model)
    model.save()

    log.info(f"=== NIGHTLY TRAINING COMPLETE — accuracy: {accuracy*100:.1f}% ===")

if __name__ == "__main__":
    run()