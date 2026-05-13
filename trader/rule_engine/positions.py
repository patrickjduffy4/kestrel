import logging
import os
from datetime import datetime
from config import ROOT
from trader.rule_engine.state import (
    get_positions,
    get_position,
    has_position,
    refresh
)
from trader.rule_engine.execution import place_sell, close_position

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
log = logging.getLogger("kestrel.positions")

# --- Settings ---
HARD_STOP_PCT      = 0.02   # 2% hard stop loss
INITIAL_TRAIL_PCT  = 0.02   # 2% initial trailing stop
TRAIL_LOOSEN_PCT   = 0.01   # loosen by 1% when volume increasing
TRAIL_TIGHTEN_PCT  = 0.01   # tighten by 1% when volume fading
MIN_TRAIL_PCT      = 0.01   # never tighter than 1%
MAX_TRAIL_PCT      = 0.05   # never looser than 5%

# --- Active position tracking ---
# Tracks trailing stop state for each open position
_position_state = {}

def init_position(ticker, entry_price, shares, score):
    """
    Initialize tracking for a new position.
    Called immediately after a buy order fills.
    """
    _position_state[ticker] = {
        'entry_price':    entry_price,
        'shares':         shares,
        'score':          score,
        'high_price':     entry_price,
        'trail_pct':      INITIAL_TRAIL_PCT,
        'stop_price':     entry_price * (1 - INITIAL_TRAIL_PCT),
        'hard_stop':      entry_price * (1 - HARD_STOP_PCT),
        'entered_at':     datetime.now(),
        'last_updated':   datetime.now()
    }
    log.info(
        f"Position initialized: {ticker} | "
        f"Entry: ${entry_price:.2f} | "
        f"Shares: {shares} | "
        f"Stop: ${_position_state[ticker]['stop_price']:.2f}"
    )

def update_trail(ticker, current_price, volume_trend):
    """
    Update trailing stop based on current price and volume.

    volume_trend > 1.2  → volume increasing → loosen trail
    volume_trend < 0.8  → volume fading    → tighten trail
    otherwise           → neutral          → no change
    """
    if ticker not in _position_state:
        return

    state      = _position_state[ticker]
    entry      = state['entry_price']
    high       = state['high_price']
    trail_pct  = state['trail_pct']

    # Update high water mark
    if current_price > high:
        state['high_price'] = current_price
        high = current_price

    # Adjust trail based on volume
    if volume_trend > 1.2:
        # Volume increasing — loosen trail, give it room
        trail_pct = min(trail_pct + TRAIL_LOOSEN_PCT, MAX_TRAIL_PCT)
    elif volume_trend < 0.8:
        # Volume fading — tighten trail, protect gains
        trail_pct = max(trail_pct - TRAIL_TIGHTEN_PCT, MIN_TRAIL_PCT)

    # Calculate new stop price based on high water mark
    new_stop = high * (1 - trail_pct)

    # Hard stop — never below entry * (1 - HARD_STOP_PCT)
    hard_stop = entry * (1 - HARD_STOP_PCT)
    new_stop  = max(new_stop, hard_stop)

    # Trailing stop never moves down
    new_stop = max(new_stop, state['stop_price'])

    state['trail_pct']    = trail_pct
    state['stop_price']   = new_stop
    state['hard_stop']    = hard_stop
    state['last_updated'] = datetime.now()

def should_exit(ticker, current_price, volume_trend):
    """
    Check if position should be exited.

    Returns:
        exit:   bool   → should we exit?
        reason: str    → why
    """
    if ticker not in _position_state:
        return False, None

    state     = _position_state[ticker]
    entry     = state['entry_price']
    hard_stop = state['hard_stop']
    stop      = state['stop_price']

    # Hard stop — always enforced
    if current_price <= hard_stop:
        return True, f"hard_stop hit at ${current_price:.2f} (stop: ${hard_stop:.2f})"

    # Trailing stop
    if current_price <= stop:
        return True, f"trailing_stop hit at ${current_price:.2f} (stop: ${stop:.2f})"

    # Volume collapsing — exit regardless of price
    if volume_trend < 0.3:
        return True, f"volume_collapse (trend: {volume_trend:.2f})"

    return False, None

def process_position(ticker, current_price, volume_trend):
    """
    Main position management loop for one ticker.
    Called on every price update from WebSocket.

    Returns:
        action: str    → 'hold', 'exit'
        reason: str    → why
    """
    if ticker not in _position_state:
        return 'hold', None

    # Update trailing stop
    update_trail(ticker, current_price, volume_trend)

    # Check exit conditions
    exit_now, reason = should_exit(ticker, current_price, volume_trend)

    if exit_now:
        shares = _position_state[ticker]['shares']
        result = close_position(ticker)
        if result:
            entry  = _position_state[ticker]['entry_price']
            pnl    = (current_price - entry) * shares
            pnl_pct = ((current_price - entry) / entry) * 100
            log.info(
                f"EXITED {ticker} | "
                f"Reason: {reason} | "
                f"Entry: ${entry:.2f} | "
                f"Exit: ${current_price:.2f} | "
                f"P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)"
            )
            del _position_state[ticker]
            return 'exit', reason
        else:
            log.error(f"Failed to exit {ticker}")
            return 'hold', None

    return 'hold', None

def get_position_state(ticker):
    """Get current trailing stop state for a position."""
    return _position_state.get(ticker, None)

def get_all_position_states():
    """Get trailing stop state for all positions."""
    return _position_state.copy()

def clear_position(ticker):
    """Remove position from tracking."""
    if ticker in _position_state:
        del _position_state[ticker]

def end_of_day_close():
    """
    Hard close all positions at 12:45pm PT.
    No exceptions.
    """
    from trader.rule_engine.execution import close_all_positions
    positions = list(_position_state.keys())
    if not positions:
        log.info("End of day — no open positions")
        return

    log.info(f"End of day close — closing {len(positions)} positions")
    close_all_positions()

    for ticker in positions:
        clear_position(ticker)

    log.info("End of day close complete")

if __name__ == "__main__":
    # Test position tracking logic without live trades
    print("Testing position tracking logic...\n")

    # Simulate a position
    init_position("PLUG", entry_price=3.20, shares=54, score=0.85)

    # Simulate price rising with good volume
    print("Price rising, volume good:")
    for price, vol in [(3.25, 1.3), (3.30, 1.5), (3.35, 1.4)]:
        update_trail("PLUG", price, vol)
        state = get_position_state("PLUG")
        print(f"  Price: ${price} | Stop: ${state['stop_price']:.3f} | Trail: {state['trail_pct']*100:.1f}%")

    # Simulate volume fading
    print("\nVolume fading:")
    for price, vol in [(3.33, 0.7), (3.31, 0.6), (3.28, 0.5)]:
        update_trail("PLUG", price, vol)
        state = get_position_state("PLUG")
        print(f"  Price: ${price} | Stop: ${state['stop_price']:.3f} | Trail: {state['trail_pct']*100:.1f}%")

    # Check exit
    exit_now, reason = should_exit("PLUG", 3.28, 0.5)
    print(f"\nShould exit? {exit_now} | Reason: {reason}")