"""Kestrel configuration.

Secrets live in `.env` (gitignored). This file pulls them into module globals
so the rest of the codebase can keep using `from config import KEY` unchanged.

Copy `.env.example` to `.env` and fill in your own keys before first run.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing env var {name!r}. Copy .env.example to .env and fill it in."
        )
    return val


# --- Alpaca (paper trading by default) ---
ALPACA_API_KEY    = _require("ALPACA_API_KEY")
ALPACA_SECRET_KEY = _require("ALPACA_SECRET_KEY")
ALPACA_BASE_URL   = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
ALPACA_DATA_URL   = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets")

# --- Market data ---
FINNHUB_API_KEY   = _require("FINNHUB_API_KEY")
ALPHA_VANTAGE_KEY = _require("ALPHA_VANTAGE_KEY")

# --- Claude (weekly strategic advisor) ---
ANTHROPIC_API_KEY = _require("ANTHROPIC_API_KEY")

# --- Paths ---
ROOT           = os.environ.get("KESTREL_ROOT", "D:/Kestrel")
DB_MARKET      = f"{ROOT}/data/database/market.db"
DB_MARKET_DATA = f"{ROOT}/data/database/market_data.db"
DB_SIGNALS     = f"{ROOT}/data/database/signals.db"
DB_PERF        = f"{ROOT}/data/database/performance.db"
DB_FUND        = f"{ROOT}/data/database/fundamentals.db"
DB_WATCHLIST   = f"{ROOT}/data/database/watchlist.db"
RAW_DATA       = f"{ROOT}/data/raw"
TRAINING_DATA  = f"{ROOT}/data/training"
INTRADAY_DATA  = f"{ROOT}/data/training/intraday"
LOGS           = f"{ROOT}/logs"
MODELS         = f"{ROOT}/models"
WATCHLISTS     = f"{ROOT}/watchlists"
REPORTS        = f"{ROOT}/reports"

# --- Market pull ---
HISTORY_YEARS    = 10
MIN_HISTORY_DAYS = 200

# --- Scan thresholds (Layer 1: liquidity gate) ---
LAYER1_VOLUME       = 100_000
LAYER1_DOLLAR_VOL   = 1_000_000
LAYER1_MARKET_CAP   = 100_000_000
LAYER1_HISTORY_DAYS = 200
