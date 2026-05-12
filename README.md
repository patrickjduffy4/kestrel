# Kestrel
Automated US market surveillance and day trading system.

Watches the full US equity market, scores stocks daily, and feeds a trading bot.

## Architecture

**Feed** — the brain
- `scan/` — figures out what's worth tracking
- `market_pull/` — keeps data current
- `opportunity/` — spots intraday setups
- `advisor/` — scores and ranks candidates

**Trader** — acts on what Feed finds

**Pipeline** — runs everything in order

## Advisor Architecture

Two parallel systems running simultaneously:

**System A — Rule Based Advisor**
Transparent scoring system. Makes actual paper trade decisions.
Generates labeled training data. Works immediately.

**System B — Neural Network Advisor**
Shadow mode only. Watches System A, learns from outcomes.
Runs its own separate paper account. Never makes live decisions.
Graduates to live when it consistently outperforms System A
over 30 consecutive trading days.

**Claude API — NN Overseer**
Runs nightly. Reads both systems' performance.
Analyzes disagreements. Suggests training adjustments.
Flags when System B is ready to graduate.

## Status

| Component | Status |
|---|---|
| Scan | done |
| Market Pull | done |
| Pre-market Opportunity | done |
| Open Scan | next |
| Intraday Scan | planned |
| System A Advisor | planned |
| System B Neural Network | planned |
| Claude Overseer | planned |
| Trader | planned |

## Data

~6,700 US stocks tracked. 10 years of daily history. Updated daily.