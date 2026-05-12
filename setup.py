import os

ROOT = "D:/Kestrel"

folders = [
    # Feed agent folders
    "feed/scan",
    "feed/market_pull",
    "feed/opportunity",
    "feed/advisor",

    # Trader
    "trader",

    # Pipeline
    "pipeline",

    # Data storage
    "data/raw",
    "data/features",
    "data/database",

    # Models
    "models/current",
    "models/checkpoints",

    # Outputs
    "watchlists",
    "reports",
    "logs",
]

print("Initializing Kestrel...\n")

for folder in folders:
    path = os.path.join(ROOT, folder)
    os.makedirs(path, exist_ok=True)
    print(f"  Created: {path}")

# Initialize Python modules
modules = [
    "feed/scan",
    "feed/market_pull",
    "feed/opportunity",
    "feed/advisor",
    "trader",
    "pipeline",
]

for module in modules:
    init_path = os.path.join(ROOT, module, "__init__.py")
    if not os.path.exists(init_path):
        with open(init_path, "w") as f:
            f.write(f"# Kestrel {module.split('/')[-1]} module\n")
        print(f"  Initialized module: {module}")

readme = """
KESTREL — US MARKET TRADING SYSTEM
====================================
Watches everything. Waits. Strikes on the right stock at the right moment.

ARCHITECTURE
------------
Feed            — the brain. Watches, analyzes, decides.
Trader          — the hands. Executes trades, manages positions.

FEED AGENTS
-----------
scan/           — finds and classifies new tickers
market_pull/    — pulls fresh market data daily
opportunity/    — flags interesting stocks
advisor/        — scores flagged stocks, generates watchlist

TRADER
------
trader/         — receives watchlist, executes trades, logs results

PIPELINE
--------
pipeline/       — orchestrates all agents in correct order

STORAGE
-------
data/raw/               — raw OHLCV parquet files per ticker
data/features/          — engineered features per ticker
data/database/          — four databases:
                          market.db
                          fundamentals.db
                          signals.db
                          performance.db

models/current/         — today's active model
models/checkpoints/     — daily model snapshots

watchlists/             — daily ranked watchlists (CSV)
reports/                — advisor reports (CSV)
logs/                   — one log file per agent
"""

with open(os.path.join(ROOT, "README.txt"), "w") as f:
    f.write(readme)

print(f"\nREADME updated.")
print(f"\nKestrel is ready.")