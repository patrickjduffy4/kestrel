# Kestrel
Automated US market surveillance and day trading system.

Watches the full US equity market, scores stocks daily, and feeds an aggressive day trading bot.

## What's in this repo

Infrastructure (data pull, orchestration, db wrappers, broker adapters, reporting) is public. Strategy (scoring rubrics, entry/exit rules, NN models) is gated — that's the part you can't recover from an architecture diagram.

## Setup

```bash
git clone <repo>
cd kestrel
python -m venv .venv
.venv\Scripts\activate           # or: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # fill in your API keys
python kestrel.py
```

Windows by default — first run drops a desktop shortcut + .bat launcher. Skip those on macOS/Linux and update paths in `config.py`.

## Architecture

### Feed — market intelligence
- `scan/` — classifies and tracks the full US equity universe
- `market_pull/` — keeps price and fundamental data current
- `opportunity/` — detects gap and intraday trading setups
- `advisor/` — rule-based scorers, build daily watchlist

### Trader — execution
- `rule_engine/` — rule-based buy/sell/stop logic
- `nn_engine/` — Left Brain NN execution (build after rule engine)

### Bird Brain — learning systems
- `leftbrain/` — NN trader, learns from rule_engine + Claude
- `rightbrain/` — NN advisor, learns from advisor + Claude

### Pipeline — orchestration
Runs all agents in correct order. Generates reports. Manages scheduling.

## Advisor Architecture

**Rule-based Advisor** — two scorers, one shared watchlist. Mean-reversion (the "bounce list") and momentum (the "breakout list"). Transparent, tunable, runs in production. Generates labeled training data, plus an end-of-day sweep that logs what the system *didn't* trade — so the NNs learn from inaction too.

**Right Brain** — NN advisor in shadow mode.
Watches rule-based advisor, learns from outcomes.
Runs separate paper account. Graduates after 30 days outperforming rules.

## Trader Architecture

**Rule Engine** — one trader process, two strategies. Mean-reversion and momentum each own their entry rules. Positions remember which strategy created them; reporting breaks P&L out per strategy. Shared position cap. All positions closed by 1pm PT.

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

## Status

| Component              | Status   | Code   |
|------------------------|----------|--------|
| Scan                   | done     | public |
| Market Pull            | done     | public |
| Pre-market Opportunity | done     | public |
| Open Scan              | done     | public |
| Pipeline Orchestrator  | done     | public |
| Daily Report           | done     | public |
| Weekly Report (Claude) | done     | public |
| Rule-based Advisor     | done     | gated  |
| Rule Engine Trader     | done     | gated  |
| Right Brain NN Advisor | training | gated  |
| Left Brain NN Trader   | dev      | gated  |

## Known Issues
- Volume ratio showing 0.0 — needs minute bar history
- QUCY data quality ghost slipping through z-score
- Catalyst tagging not yet implemented

## Data
~6,700 US stocks tracked. 10 years of daily history. Updated daily.
