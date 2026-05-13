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

    # Feed agents
    "feed/scan",
    "feed/market_pull",
    "feed/opportunity",
    "feed/advisor",

    # Bird Brain
    "bird_brain/models",
    "bird_brain/training",
    "bird_brain/paper_account",

    # Trader
    "trader",

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
    "bird_brain",
    "bird_brain/training",
    "trader",
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

Watches the full US equity market, scores stocks daily, and feeds a trading bot.

## Architecture

**Feed** — the brain
- `scan/` — figures out what's worth tracking
- `market_pull/` — keeps data current
- `opportunity/` — spots intraday setups
- `advisor/` — System A rule based scorer

**Bird Brain** — the neural network advisor in training
- shadow mode only
- watches System A, learns from outcomes
- runs its own separate paper account
- graduates when it consistently outperforms System A

**Trader** — acts on what Feed finds

**Pipeline** — runs everything in order, generates reports

## Advisor Architecture

**System A — Rule Based Advisor**
Transparent scoring. Makes actual paper trade decisions.
Generates labeled training data for Bird Brain.

**Bird Brain — Neural Network Advisor**
Shadow mode only. Learns from System A's outcomes.
Runs separate paper account. Never makes live decisions.
Graduates after 30 consecutive days outperforming System A.

**Claude — Weekly Strategic Advisor**
Reads week's performance across four focused analyses.
Generates strategic recommendations every Sunday.
Feeds structured findings back to Bird Brain's training loop.

## Status

| Component | Status |
|---|---|
| Scan | done |
| Market Pull | done |
| Pre-market Opportunity | done |
| Open Scan | done |
| Daily Report | done |
| Weekly Report (Claude) | done |
| Intraday Scan | next |
| System A Advisor | planned |
| Bird Brain Neural Network | planned |
| Trader | planned |
| Pipeline Orchestrator | planned |

## Known Issues
- Volume ratio showing 0.0 — pipeline bug, fix before trading
- Gap threshold needs raising to 5%
- Catalyst tagging not yet implemented

## Data
~6,700 US stocks tracked. 10 years of daily history. Updated daily.
"""

readme_path = os.path.join(ROOT, "README.md")
with open(readme_path, "w") as f:
    f.write(readme)

print(f"\nREADME written to {readme_path}")
print("\nKestrel is ready.")