import os

ROOT = "D:/Kestrel"

folders = [
    # Data storage
    "data/raw",
    "data/features",
    "data/database",

    # Models
    "models/current",
    "models/checkpoints",

    # Outputs
    "watchlists",
    "reports/daily",
    "reports/weekly",
    "logs",

    # Feed
    "feed/scan",
    "feed/market_pull",
    "feed/opportunity",
    "feed/advisor",

    # Bird Brain
    "birdbrain/leftbrain",    # NN trader
    "birdbrain/rightbrain",   # NN advisor

    # Trader
    "trader/rule_engine",
    "trader/nn_engine",

    # Pipeline
    "pipeline",

    # Utils
    "utils",
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
    "birdbrain",
    "birdbrain/leftbrain",
    "birdbrain/rightbrain",
    "trader",
    "trader/rule_engine",
    "trader/nn_engine",
    "pipeline",
    "utils",
]

for module in modules:
    init_path = os.path.join(ROOT, module, "__init__.py")
    if not os.path.exists(init_path):
        with open(init_path, "w") as f:
            f.write(f"# Kestrel {module.split('/')[-1]} module\n")
        print(f"  Initialized module: {module}")

readme = """# Kestrel
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
- `leftbrain/` — NN trader, learns from rule_engine + Claude
- `rightbrain/` — NN advisor, learns from advisor + Claude

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
1. feed/advisor/       rule-based scorer         ← next
2. trader/rule_engine  rule-based execution
3. pipeline            orchestration
4. birdbrain/rightbrain  NN advisor
5. birdbrain/leftbrain   NN trader

## Status

| Component | Status |
|---|---|
| Scan | done |
| Market Pull | done |
| Pre-market Opportunity | done |
| Open Scan | done |
| Daily Report | done |
| Weekly Report (Claude) | done |
| Rule-based Advisor | next |
| Rule Engine Trader | planned |
| Pipeline | planned |
| Right Brain NN Advisor | planned |
| Left Brain NN Trader | planned |

## Known Issues
- Volume ratio showing 0.0 — needs minute bar history
- QUCY data quality ghost slipping through z-score
- Catalyst tagging not yet implemented

## Data
~6,700 US stocks tracked. 10 years of daily history. Updated daily.
"""

readme_path = os.path.join(ROOT, "README.md")
with open(readme_path, "w", encoding='utf-8') as f:
    f.write(readme)

print(f"\nREADME written to {readme_path}")
print("\nKestrel is ready.")