import logging
import os
from config import ROOT
from trader.rule_engine.state import (
    get_portfolio_value,
    get_buying_power,
    get_max_position_dollars,
    get_max_stock_price,
    is_price_eligible
)

# --- Logging ---
LOG_PATH = os.path.join(ROOT, "logs/trader.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.sizing")

def position_size(stock_price, score):
    """
    Calculate position size in shares.

    Score adjusts position size:
    score 1.0 → full max position
    score 0.4 → 50% of max position

    Returns:
        shares    → number of shares to buy
        dollars   → dollar value of position
    """
    if not is_price_eligible(stock_price):
        log.debug(f"Stock price ${stock_price} exceeds ceiling ${get_max_stock_price():.2f}")
        return 0, 0

    # Base max position
    max_dollars = get_max_position_dollars()

    # Score adjustment
    score_factor = 0.5 + (score - 0.40) * (0.5 / 0.60)
    score_factor = max(0.5, min(1.0, score_factor))

    # Adjusted position
    adjusted_dollars = max_dollars * score_factor

    # Can't exceed buying power
    buying_power     = get_buying_power()
    adjusted_dollars = min(adjusted_dollars, buying_power * 0.95)

    # Calculate shares
    shares = int(adjusted_dollars / stock_price)

    # Need at least 10 shares
    if shares < 5:
        log.debug(f"Insufficient shares ({shares}) for {stock_price} at current portfolio size")
        return 0, 0

    actual_dollars = shares * stock_price
    return shares, actual_dollars

if __name__ == "__main__":
    from trader.rule_engine.state import refresh
    refresh()

    print(f"Portfolio:        ${get_portfolio_value():,.2f}")
    print(f"Buying power:     ${get_buying_power():,.2f}")
    print(f"Max position:     ${get_max_position_dollars():,.2f}")
    print(f"Max stock price:  ${get_max_stock_price():,.2f}")

    # Test sizing for a few prices
    for price, score in [(3.20, 0.85), (15.00, 0.65), (55.00, 0.45)]:
        shares, dollars = position_size(price, score)
        print(f"  ${price} stock, score {score} → {shares} shares (${dollars:.2f})")