# Kestrel

Automated US market surveillance and day trading system.

Watches the full US equity market, scores stocks daily, and feeds a trading bot.

## Structure

**Feed** — the brain
- `scan/` — figures out what's worth tracking
- `market_pull/` — keeps data current
- `opportunity/` — spots intraday setups
- `advisor/` — scores and ranks candidates

**Trader** — acts on what Feed finds

**Pipeline** — runs everything in order

## Status

| Agent | status      | 
|---|-------------|
| Scan | done        |
| Market Pull | in progress |
| Opportunity | not started |
| Advisor | not started |
| Trader | not started |

## Data
- 6,046 US stocks tracked
- 10 years of daily OHLCV history
- Full US market universe (NYSE + NASDAQ + AMEX)