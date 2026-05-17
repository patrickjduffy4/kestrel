"""First-run scaffolding for Kestrel.

Creates the folder tree and empty __init__.py files. Idempotent — safe to
re-run. Called once by kestrel.py the first time you launch.
"""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))

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


def main():
    print("Initializing Kestrel...\n")

    for folder in folders:
        path = os.path.join(ROOT, folder)
        os.makedirs(path, exist_ok=True)
        print(f"  Created: {path}")

    for module in modules:
        init_path = os.path.join(ROOT, module, "__init__.py")
        if not os.path.exists(init_path):
            with open(init_path, "w") as f:
                f.write(f"# Kestrel {module.split('/')[-1]} module\n")
            print(f"  Initialized module: {module}")

    print("\nKestrel is ready.")


if __name__ == "__main__":
    main()
