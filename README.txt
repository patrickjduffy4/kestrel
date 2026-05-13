
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
