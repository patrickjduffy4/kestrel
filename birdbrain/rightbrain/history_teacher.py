import sys
sys.path.insert(0, "D:/Kestrel")

import os
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
import logging
from datetime import datetime
from config import ROOT

LOG_PATH = os.path.join(ROOT, "logs/rightbrain.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.rightbrain.history_teacher")

TRAIN_SPLIT   = 0.80
BATCH_SIZE    = 256
EPOCHS        = 300
LEARNING_RATE = 0.001

def train(X, y, model):
    """
    Train rightbrain on historical gap data.
    X: numpy array (N, 12)
    y: numpy array (N,)
    model: RightBrain instance
    """
    log.info(f"Training rightbrain on {len(X):,} historical samples...")

    # Shuffle
    idx = np.random.permutation(len(X))
    X, y = X[idx], y[idx]

    # Train/val split
    split    = int(len(X) * TRAIN_SPLIT)
    X_train  = torch.FloatTensor(X[:split])
    y_train  = torch.FloatTensor(y[:split]).unsqueeze(1)
    X_val    = torch.FloatTensor(X[split:])
    y_val    = torch.FloatTensor(y[split:]).unsqueeze(1)

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
        # Training
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

        # Validation
        model.eval()
        with torch.no_grad():
            val_output = model(X_val)
            val_loss   = criterion(val_output, y_val).item()

            # Accuracy
            predicted = (val_output > 0.5).float()
            actual    = (y_val > 0.5).float()
            accuracy  = (predicted == actual).float().mean().item()

        scheduler.step(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state    = {k: v.clone() for k, v in model.state_dict().items()}

        if epoch % 10 == 0 or epoch == EPOCHS - 1:
            log.info(
                f"Epoch {epoch+1:3d}/{EPOCHS} | "
                f"Train loss: {train_loss:.4f} | "
                f"Val loss: {val_loss:.4f} | "
                f"Val accuracy: {accuracy*100:.1f}%"
            )

    # Load best weights
    if best_state:
        model.load_state_dict(best_state)
        log.info(f"Loaded best model — val loss: {best_val_loss:.4f}")

    # Update training history
    model.training_history['sessions']      += 1
    model.training_history['total_samples'] += len(X)
    model.training_history['last_trained']   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    model.training_history['last_accuracy']  = round(accuracy * 100, 1)

    return model, accuracy

def run():
    """Load historical data, train rightbrain, save model."""
    from birdbrain.data_loader import load_all_samples
    from birdbrain.rightbrain.model import get_model

    log.info("=== RIGHTBRAIN HISTORY TEACHER STARTING ===")

    # Load data
    X, y = load_all_samples(mode='rightbrain', max_tickers=None)
    if X is None:
        log.error("No training data available")
        return

    # Get model
    model = get_model()

    # Train
    model, accuracy = train(X, y, model)

    # Save
    model.save()

    log.info(f"=== LESSON COMPLETE — accuracy: {accuracy*100:.1f}% ===")

if __name__ == "__main__":
    run()