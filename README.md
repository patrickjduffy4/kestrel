# Kestrel
Automated US market surveillance and day trading system.

Watches the full US equity market, scores stocks daily, and feeds an aggressive day trading bot.

## Architecture

### Feed — market intelligence
- `scan/` — classifies and tracks the full US equity universe
- `market_pull/` — keeps price and fundamental data current
- `opportunity/` — detects gap and intraday trading setups
- `advisor/` — rule-based scorer, builds daily watchlist

### Trader — execution
- `rule_engine/` — rule-based buy/sell/stop logic
- `nn_engine/` — Left Brain NN execution (build after rule engine)

### Bird Brain — learning systems
- `left_brain/` — NN trader, learns from rule_engine + Claude
- `right_brain/` — NN advisor, learns from advisor + Claude

### Pipeline — orchestration
Runs all agents in correct order. Generates reports. Manages scheduling.

## Advisor Architecture

**Rule-based Advisor** — scores gap candidates, maintains 20 stock watchlist.
Transparent, tunable, works immediately. Generates labeled training data.

**Right Brain** — NN advisor in shadow mode.
Watches rule-based advisor, learns from outcomes.
Runs separate paper account. Graduates after 30 days outperforming rules.

## Trader Architecture

**Rule Engine** — executes trades based on watchlist and signals.
Manages entries, exits, stop losses, take profits.
Aggressive day trader — multiple trades per stock per day, all closed by 1pm PT.

**Left Brain** — NN trader in shadow mode.
Watches rule engine, learns better entry/exit timing.
Runs separate paper account. Graduates after 30 days outperforming rules.

## Claude — Weekly Strategic Advisor
Four focused analyses every Sunday:
1. Opportunity agent performance
2. Advisor performance — rule vs NN
3. Trading performance — rule vs NN
4. Strategic recommendations

Findings feed back into both NN training loops.

## Build Order
1. trader/rule_engine  rule-based execution     ← current
2. feed/advisor/       rule-based scorer
3. pipeline            orchestration
4. bird_brain/right_brain  NN advisor
5. bird_brain/left_brain   NN trader

## Status

| Component | Status |
|---|---|
| Scan | done |
| Market Pull | done |
| Pre-market Opportunity | done |
| Open Scan | done |
| Performance Databases | done |
| Daily Report | done |
| Weekly Report (Claude) | done |
| sizing.py | done |
| Rule Engine Trader | in progress |
| Rule-based Advisor | planned |
| Pipeline | planned |
| Right Brain NN Advisor | planned |
| Left Brain NN Trader | planned |

## Known Issues
- Volume ratio showing 0.0 — needs minute bar history
- QUCY data quality ghost slipping through z-score
- Catalyst tagging not yet implemented

## Data
~6,700 US stocks tracked. 10 years of daily history. Updated daily.
