import logging
import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus
from datetime import datetime

# --- Config ---
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ROOT

# --- Logging ---
LOG_PATH = os.path.join(ROOT, "logs/execution.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.execution")

# --- Alpaca client ---
client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)

def get_account():
    """Get current account state."""
    return client.get_account()

def get_positions():
    """Get all open positions."""
    return client.get_all_positions()

def get_position(ticker):
    """Get a specific open position."""
    try:
        return client.get_open_position(ticker)
    except Exception:
        return None

def place_buy(ticker, shares):
    """
    Place a market buy order.
    Returns order object or None if failed.
    """
    try:
        order = client.submit_order(
            MarketOrderRequest(
                symbol=ticker,
                qty=shares,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY
            )
        )
        log.info(f"BUY {shares} shares of {ticker} — order ID: {order.id}")
        return order
    except Exception as e:
        log.error(f"BUY failed for {ticker}: {e}")
        return None

def place_sell(ticker, shares):
    """
    Place a market sell order.
    Returns order object or None if failed.
    """
    try:
        order = client.submit_order(
            MarketOrderRequest(
                symbol=ticker,
                qty=shares,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
        )
        log.info(f"SELL {shares} shares of {ticker} — order ID: {order.id}")
        return order
    except Exception as e:
        log.error(f"SELL failed for {ticker}: {e}")
        return None

def close_position(ticker):
    """
    Close entire position in a ticker.
    Returns True if successful.
    """
    try:
        client.close_position(ticker)
        log.info(f"CLOSED position in {ticker}")
        return True
    except Exception as e:
        log.error(f"CLOSE failed for {ticker}: {e}")
        return False

def close_all_positions():
    """
    Close all open positions.
    Used at end of day 12:45pm PT.
    """
    try:
        positions = get_positions()
        if not positions:
            log.info("No open positions to close")
            return True
        client.close_all_positions(cancel_orders=True)
        log.info(f"Closed all positions — {len(positions)} positions")
        return True
    except Exception as e:
        log.error(f"CLOSE ALL failed: {e}")
        return False

def get_order_status(order_id):
    """Check status of a specific order."""
    try:
        order = client.get_order_by_id(order_id)
        return order.status
    except Exception as e:
        log.error(f"Order status check failed: {e}")
        return None

def cancel_all_orders():
    """Cancel all open orders."""
    try:
        client.cancel_orders()
        log.info("Cancelled all open orders")
        return True
    except Exception as e:
        log.error(f"Cancel all orders failed: {e}")
        return False

if __name__ == "__main__":
    # Test connection
    account   = get_account()
    positions = get_positions()

    print(f"Account status:   {account.status}")
    print(f"Portfolio value:  ${float(account.portfolio_value):,.2f}")
    print(f"Buying power:     ${float(account.buying_power):,.2f}")
    print(f"Open positions:   {len(positions)}")