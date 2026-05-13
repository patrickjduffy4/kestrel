import logging
import os
from datetime import datetime
from alpaca.trading.client import TradingClient
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ROOT

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
log = logging.getLogger("kestrel.state")

# --- Alpaca client ---
client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)

# --- Shared state ---
_state = {
    'portfolio_value': 0.0,
    'buying_power':    0.0,
    'positions':       {},
    'watchlist':       [],
    'fetched_at':      None
}

REFRESH_SECONDS = 30

def refresh():
    """Fetch fresh account state from Alpaca."""
    try:
        account   = client.get_account()
        positions = client.get_all_positions()

        _state['portfolio_value'] = float(account.portfolio_value)
        _state['buying_power']    = float(account.buying_power)
        _state['fetched_at']      = datetime.now()

        _state['positions'] = {
            p.symbol: {
                'shares':          float(p.qty),
                'entry_price':     float(p.avg_entry_price),
                'current_price':   float(p.current_price),
                'market_value':    float(p.market_value),
                'unrealized_pl':   float(p.unrealized_pl),
                'unrealized_plpc': float(p.unrealized_plpc),
                'side':            p.side
            }
            for p in positions
        }

        log.info(
            f"State refreshed | "
            f"Portfolio: ${_state['portfolio_value']:,.2f} | "
            f"Buying power: ${_state['buying_power']:,.2f} | "
            f"Positions: {len(_state['positions'])}"
        )

    except Exception as e:
        log.error(f"State refresh failed: {e}")

def needs_refresh():
    if _state['fetched_at'] is None:
        return True
    elapsed = (datetime.now() - _state['fetched_at']).seconds
    return elapsed >= REFRESH_SECONDS

# --- Raw account data ---

def get_portfolio_value():
    if needs_refresh():
        refresh()
    return _state['portfolio_value']

def get_buying_power():
    if needs_refresh():
        refresh()
    return _state['buying_power']

def get_positions():
    if needs_refresh():
        refresh()
    return _state['positions']

def get_position(ticker):
    if needs_refresh():
        refresh()
    return _state['positions'].get(ticker, None)

def has_position(ticker):
    return ticker in get_positions()

# --- Portfolio awareness ---

def max_position_pct(portfolio_value):
    """Position size as percentage of portfolio. Scales down as portfolio grows."""
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

def get_max_position_dollars():
    """Maximum position size in dollars for current portfolio."""
    pv = get_portfolio_value()
    return min(pv * max_position_pct(pv), 2500)

def get_max_stock_price():
    """Maximum stock price eligible for current portfolio."""
    return min(get_portfolio_value() * 0.06, 500)

def is_price_eligible(stock_price):
    """Check if stock price is within portfolio-aware ceiling."""
    return stock_price <= get_max_stock_price()

# --- Watchlist ---

def update_watchlist(watchlist):
    _state['watchlist'] = watchlist
    log.info(f"Watchlist updated — {len(watchlist)} stocks")

def get_watchlist():
    return _state['watchlist']

def get_state():
    return _state.copy()

if __name__ == "__main__":
    refresh()
    print(f"Portfolio:        ${get_portfolio_value():,.2f}")
    print(f"Buying power:     ${get_buying_power():,.2f}")
    print(f"Max position:     ${get_max_position_dollars():,.2f}")
    print(f"Max stock price:  ${get_max_stock_price():,.2f}")
    print(f"Positions:        {len(get_positions())}")