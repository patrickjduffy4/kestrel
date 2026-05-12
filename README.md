# Kestrel
An automated stock information retrieval, analysis, and trading agent series.

## Architecture
- **Feed** — watches, analyzes, and scores the entire US market daily
  - `scan/` — intelligent ticker intake and classification
  - `market_pull/` — daily price and fundamental data collection
  - `opportunity/` — real time opportunity detection
  - `advisor/` — neural network scoring and watchlist generation
- **Trader** — executes trades based on Feed signals
- **Pipeline** — orchestrates all agents in correct order

## Agents
| Agent | Status |
|---|---|
| Scan | ✅ Complete |
| Market Pull | 🔄 In Progress |
| Opportunity | ⬜ Planned |
| Advisor | ⬜ Planned |
| Trader | ⬜ Planned |

## Data
- 6,046 US stocks tracked
- 10 years of daily OHLCV history
- Full US market universe (NYSE + NASDAQ + AMEX)