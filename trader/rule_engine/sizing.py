from config import ALPACA_API_KEY, ALPACA_SECRET_KEY
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest

# --- Alpaca client ---
trading_client = TradingClient(
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    paper=True
)


def get_portfolio_value():
    """Get current portfolio value from Alpaca."""
    account = trading_client.get_account()
    return float(account.portfolio_value)


def get_buying_power():
    """Get current buying power from Alpaca."""
    account = trading_client.get_account()
    return float(account.buying_power)


def max_position_pct(portfolio_value):
    if portfolio_value <= 1000:
        return 0.20
    elif portfolio_value <= 2000:
        return 0.18
    elif portfolio_value <= 3000:
        return 0.16
    elif portfolio_value <= 5000:
        return 0.14
    elif portfolio_value <= 7500:
        return 0.12
    elif portfolio_value <= 10000:
        return 0.10
    elif portfolio_value <= 15000:
        return 0.08
    elif portfolio_value <= 20000:
        return 0.07
    elif portfolio_value <= 30000:
        return 0.06
    elif portfolio_value <= 40000:
        return 0.05
    elif portfolio_value <= 50000:
        return 0.04
    else:
        return 2500 / portfolio_value


def max_stock_price(portfolio_value):
    """
    Maximum stock price we'll consider.
    Scales with portfolio, hard cap $500.
    """
    return min(portfolio_value * 0.06, 500)


def position_size(portfolio_value, stock_price, score):
    """
    Calculate position size in shares.

    Score adjusts position size:
    score 1.0 → full max position
    score 0.4 → 50% of max position

    Returns:
        shares    → number of shares to buy
        dollars   → dollar value of position
    """
    # Base max position
    max_pct = max_position_pct(portfolio_value)
    max_dollars = min(portfolio_value * max_pct, 2500)

    # Score adjustment — higher score = larger position
    # Linear scale from 50% at min score (0.40) to 100% at max (1.0)
    score_factor = 0.5 + (score - 0.40) * (0.5 / 0.60)
    score_factor = max(0.5, min(1.0, score_factor))

    # Adjusted position
    adjusted_dollars = max_dollars * score_factor

    # Can't exceed buying power
    buying_power = get_buying_power()
    adjusted_dollars = min(adjusted_dollars, buying_power * 0.95)

    # Calculate shares
    shares = int(adjusted_dollars / stock_price)

    # Need at least 10 shares
    if shares < 10:
        return 0, 0

    actual_dollars = shares * stock_price
    return shares, actual_dollars


def is_price_eligible(stock_price, portfolio_value):
    """Check if stock price is within portfolio-aware ceiling."""
    ceiling = max_stock_price(portfolio_value)
    return stock_price <= ceiling


if __name__ == "__main__":
    portfolio = get_portfolio_value()
    buying = get_buying_power()

    print(f"Portfolio value:  ${portfolio:,.2f}")
    print(f"Buying power:     ${buying:,.2f}")
    print(f"Max stock price:  ${max_stock_price(portfolio):,.2f}")
    print(f"Max position:     ${min(portfolio * max_position_pct(portfolio), 2500):,.2f}")
    print(f"Max position pct: {max_position_pct(portfolio) * 100:.0f}%")