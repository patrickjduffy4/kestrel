import sys
sys.path.insert(0, "D:/Kestrel")

import os
import torch
import torch.nn as nn
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
log = logging.getLogger("kestrel.rightbrain.model")

MODEL_DIR = "/birdbrain/rightbrain/models"

class RightBrain(nn.Module):
    """
    rightbrain — neural network advisor.
    Learns to score gap candidates from rule-based advisor outcomes.

    Input:  12 normalized features
    Output: score 0-1 (higher = better candidate)
    """
    def __init__(self, input_size=12):
        super(RightBrain, self).__init__()

        self.network = nn.Sequential(
            nn.Linear(input_size, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid()
        )

        # Track training history
        self.training_history = {
            'sessions':    0,
            'total_samples': 0,
            'last_trained':  None,
            'last_accuracy': None
        }

    def forward(self, x):
        return self.network(x)

    def score(self, features):
        """
        Score a single candidate.
        features: numpy array of shape (12,)
        Returns float 0-1.
        """
        self.eval()
        with torch.no_grad():
            x = torch.FloatTensor(features).unsqueeze(0)
            return float(self.forward(x).squeeze())

    def save(self, path=None):
        """Save model weights and metadata."""
        os.makedirs(MODEL_DIR, exist_ok=True)

        if path is None:
            today = datetime.now().strftime('%Y-%m-%d')
            path  = os.path.join(MODEL_DIR, f"rightbrain_{today}.pt")

        torch.save({
            'state_dict':       self.state_dict(),
            'training_history': self.training_history
        }, path)

        # Always update current
        current_path = os.path.join(MODEL_DIR, "rightbrain_current.pt")
        torch.save({
            'state_dict':       self.state_dict(),
            'training_history': self.training_history
        }, current_path)

        log.info(f"Model saved: {path}")
        log.info(f"Sessions: {self.training_history['sessions']} | "
                 f"Samples: {self.training_history['total_samples']} | "
                 f"Last accuracy: {self.training_history['last_accuracy']}")

    def load(self, path=None):
        """Load model weights."""
        if path is None:
            path = os.path.join(MODEL_DIR, "rightbrain_current.pt")

        if not os.path.exists(path):
            log.info("No saved model found — starting fresh")
            return False

        checkpoint = torch.load(path, weights_only=False)
        self.load_state_dict(checkpoint['state_dict'])
        self.training_history = checkpoint.get('training_history', self.training_history)
        log.info(f"Model loaded: {path}")
        log.info(f"Sessions: {self.training_history['sessions']} | "
                 f"Samples: {self.training_history['total_samples']}")
        return True

def get_model():
    """Get rightbrain model — load if exists, create fresh if not."""
    model = RightBrain(input_size=12)
    model.load()
    return model

if __name__ == "__main__":
    log.info("Initializing rightbrain model...")
    model = RightBrain(input_size=12)

    # Count parameters
    params = sum(p.numel() for p in model.parameters())
    log.info(f"Parameters: {params:,}")

    # Test forward pass
    import numpy as np
    test_features = np.random.rand(12).astype(np.float32)
    score = model.score(test_features)
    log.info(f"Test score: {score:.4f}")

    # Save initial model
    model.save()
    log.info("rightbrain initialized and saved")