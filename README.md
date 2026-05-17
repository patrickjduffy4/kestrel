# Kestrel

Automated US market surveillance and day trading system. Watches the full US equity market, scores stocks daily, and feeds an aggressive day trading bot.

## What's here, what's not

Infrastructure (data pull, orchestration, db wrappers, broker adapters, reporting) is public. Strategy (scoring rubrics, entry/exit rules, NN models) is gated. That's the part you can't recover from a diagram.

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

Windows by default. First run drops a desktop shortcut and a .bat launcher. On macOS/Linux, skip those and fix the paths in `config.py`.

## Architecture

Four departments.

**Feed** is the market intelligence layer. `scan/` classifies and tracks the full US equity universe. `market_pull/` keeps price and fundamental data current. `opportunity/` detects gap and intraday trading setups. `advisor/` runs two rule-based scorers and builds the daily watchlist.

**Trader** does execution. `rule_engine/` handles buy/sell/stop logic and runs the live loop. `nn_engine/` is reserved for the Left Brain NN once the rule engine is mature.

**Bird Brain** is the learning side. `leftbrain/` is the NN trader, learning from the rule engine and Claude. `rightbrain/` is the NN advisor, learning from the rule-based advisor and Claude.

**Pipeline** is orchestration. Runs all agents in order, generates reports, manages scheduling.

## Strategy

Two strategies, running in parallel. The mean-reversion list (the "bounce list") and the momentum list (the "breakout list"). Each gets its own scorer with different qualification rules, but they share one watchlist, one trader process, and one position cap.

Inside the trader, each strategy has its own entry rules. Positions remember which one created them so reports can break out P&L per strategy. Multiple trades per stock per day is fine. All positions close by 1pm PT.

Both NN trainers also consume an end-of-day sweep that logs what the system *didn't* trade, so they learn from inaction as well as from trades that happened.

## The NNs

Both run in shadow mode against a separate paper account. They watch their rule-based counterpart, score every decision, and only graduate after 30 days of outperforming the rules.

## Claude

Four analyses every Sunday: opportunity agent performance, advisor performance (rule vs NN), trading performance (rule vs NN), and strategic recommendations. Findings feed back into both NN training loops.

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

## Known issues

Volume ratio is showing 0.0; needs minute bar history. QUCY data quality ghost slipping through the z-score gate. Catalyst tagging isn't implemented yet.

## Data

~6,700 US stocks. 10 years of daily history. Updated daily.
