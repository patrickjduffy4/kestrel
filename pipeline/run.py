import sys
sys.path.insert(0, "D:/Kestrel")

import os
import time
import logging
import asyncio
import sqlite3
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from config import ROOT, DB_MARKET, DB_SIGNALS
from trader.rule_engine.state import refresh, get_portfolio_value, get_buying_power, get_positions

# --- Logging ---
LOG_PATH = os.path.join(ROOT, "logs/pipeline.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.pipeline")

# --- Timezone ---
PT = ZoneInfo("America/Los_Angeles")

# --- Schedule ---
MARKET_PULL_TIME  = dtime(5, 45)
PRE_MARKET_TIME   = dtime(6,  0)
OPEN_SCAN_TIME    = dtime(6, 30)
MARKET_CLOSE_TIME = dtime(13,  0)
DAILY_REPORT_TIME = dtime(13, 15)
WEEKLY_REPORT_DAY = 6   # Sunday
WEEKLY_REPORT_TIME= dtime(20,  0)

def now_pt():
    return datetime.now(PT)

def today_at(t):
    """Return today's date at a specific time in PT."""
    return datetime.combine(now_pt().date(), t, tzinfo=PT)

def seconds_until(target_time):
    """Seconds until a specific time today. Negative if already passed."""
    target = today_at(target_time)
    return (target - now_pt()).total_seconds()

def next_trading_day():
    """Get the next weekday date."""
    day = now_pt().date() + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day

def is_trading_day():
    """Is today a weekday?"""
    return now_pt().weekday() < 5

def sleep_until(target_time, label):
    """Sleep until a specific time today, logging progress hourly."""
    secs = seconds_until(target_time)
    if secs <= 0:
        return

    target = today_at(target_time)
    hours   = int(secs // 3600)
    minutes = int((secs % 3600) // 60)
    log.info(f"Waiting for {label} at {target.strftime('%I:%M%p PT')} — {hours}h {minutes}m")

    while True:
        secs = seconds_until(target_time)
        if secs <= 0:
            return
        time.sleep(min(secs, 3600))
        if secs > 3600:
            remaining = seconds_until(target_time)
            h = int(remaining // 3600)
            m = int((remaining % 3600) // 60)
            log.info(f"{label} in {h}h {m}m")

def get_universe_count():
    """Get total tracked tickers from manifest."""
    try:
        conn = sqlite3.connect(DB_MARKET)
        c    = conn.cursor()
        c.execute("SELECT COUNT(*) FROM manifest")
        count = c.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0

def get_pending_reports():
    """Get count of pending reports."""
    try:
        from config import DB_PERF
        conn = sqlite3.connect(DB_PERF)
        c    = conn.cursor()
        c.execute("SELECT COUNT(*) FROM report_status WHERE status='pending'")
        count = c.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0

def get_last_run(agent):
    """Get last run time for an agent from logs."""
    log_file = os.path.join(ROOT, f"logs/{agent}.log")
    if not os.path.exists(log_file):
        return "never"
    try:
        with open(log_file, 'rb') as f:
            f.seek(-2, 2)
            while f.read(1) != b'\n':
                f.seek(-2, 1)
            last_line = f.readline().decode()
        return last_line[:19]
    except Exception:
        return "unknown"

def print_startup():
    """Print startup state."""
    refresh()
    portfolio  = get_portfolio_value()
    buying     = get_buying_power()
    positions  = get_positions()
    universe   = get_universe_count()
    pending    = get_pending_reports()

    next_day   = next_trading_day()
    next_open  = datetime.combine(next_day, dtime(6, 30), tzinfo=PT)
    secs_open  = (next_open - now_pt()).total_seconds()
    h_open     = int(secs_open // 3600)
    m_open     = int((secs_open % 3600) // 60)

    print("""
╔══════════════════════════════════════════════════════╗
║                    KESTREL v1.0                      ║
║         US Market Surveillance & Trading System      ║
╚══════════════════════════════════════════════════════╝
""")
    print(f"  Portfolio:        ${portfolio:,.2f}")
    print(f"  Buying Power:     ${buying:,.2f}")
    print(f"  Open Positions:   {len(positions)}")
    print()
    print(f"  Universe:         {universe:,} stocks tracked")
    print(f"  Last Market Pull: {get_last_run('market_pull')}")
    print(f"  Last Scan:        {get_last_run('pre_market_scan')}")
    print()
    print(f"  Pending Reports:  {pending}")
    print()
    if is_trading_day() and seconds_until(MARKET_CLOSE_TIME) > 0:
        secs_pre = seconds_until(PRE_MARKET_TIME)
        if secs_pre > 0:
            h = int(secs_pre // 3600)
            m = int((secs_pre % 3600) // 60)
            print(f"  Next Event:       Pre-market scan in {h}h {m}m")
        print(f"  Market Open:      {next_open.strftime('%A %B %d at %I:%M%p PT')}")
        print(f"                    in {h_open}h {m_open}m")
        print(f"\n  Status:           STARTING — trading day ahead")
    else:
        print(f"  Next Open:        {next_open.strftime('%A %B %d at %I:%M%p PT')}")
        print(f"                    in {h_open}h {m_open}m")
        print(f"\n  Status:           SLEEPING — market closed")

    print("\n══════════════════════════════════════════════════════\n")

def print_end_of_day():
    """Print end of day summary."""
    try:
        from config import DB_PERF
        conn   = sqlite3.connect(DB_PERF)
        today  = now_pt().strftime('%Y-%m-%d')

        import pandas as pd
        trades = pd.read_sql(
            "SELECT * FROM trades WHERE date = ?",
            conn, params=(today,)
        )
        conn.close()

        refresh()
        portfolio = get_portfolio_value()

        total_pnl   = round(trades['pnl'].sum(), 2) if not trades.empty else 0
        win_rate    = round(len(trades[trades['pnl'] > 0]) / len(trades) * 100) if len(trades) > 0 else 0
        best_trade  = trades.loc[trades['pnl'].idxmax()] if not trades.empty else None
        worst_trade = trades.loc[trades['pnl'].idxmin()] if not trades.empty else None

        next_day  = next_trading_day()
        next_open = datetime.combine(next_day, dtime(6, 30), tzinfo=PT)
        secs      = (next_open - now_pt()).total_seconds()
        h         = int(secs // 3600)
        m         = int((secs % 3600) // 60)

        print("""
╔══════════════════════════════════════════════════════╗
║                 KESTREL END OF DAY                   ║""")
        print(f"║            {now_pt().strftime('%Y-%m-%d %I:%M%p PT')}                 ║")
        print("""╚══════════════════════════════════════════════════════╝
""")
        print(f"  Portfolio:        ${portfolio:,.2f}  ({'+' if total_pnl >= 0 else ''}{total_pnl:.2f} today)")
        print(f"  Open Positions:   0 (all closed)")
        print()
        print(f"  Today's Trades:   {len(trades)}")
        print(f"  Win Rate:         {win_rate}%")

        if best_trade is not None:
            print(f"  Best Trade:       {best_trade['ticker']}  +${best_trade['pnl']:.2f}")
        if worst_trade is not None:
            print(f"  Worst Trade:      {worst_trade['ticker']}  ${worst_trade['pnl']:.2f}")

        print()
        print(f"  Daily Report:     generating...")
        print(f"  Next Open:        {next_open.strftime('%A %B %d at %I:%M%p PT')}")
        print(f"                    sleeping in {h}h {m}m")
        print("\n══════════════════════════════════════════════════════\n")

    except Exception as e:
        log.error(f"End of day print failed: {e}")

def run_market_pull():
    """Run market pull agent."""
    log.info("Running market pull...")
    try:
        from feed.market_pull.price_download import run
        run()
        log.info("Market pull complete")
    except Exception as e:
        log.error(f"Market pull failed: {e}")

def run_pre_market_scan():
    """Run pre-market scan."""
    log.info("Running pre-market scan...")
    try:
        from feed.opportunity.pre_market_scan import run
        run()
        log.info("Pre-market scan complete")
    except Exception as e:
        log.error(f"Pre-market scan failed: {e}")

def run_open_scan():
    """Run open scan."""
    log.info("Running open scan...")
    try:
        from feed.opportunity.open_scan import run
        run()
        log.info("Open scan complete")
    except Exception as e:
        log.error(f"Open scan failed: {e}")

def run_daily_report():
    """Run daily report generator."""
    log.info("Generating daily report...")
    try:
        from pipeline.report_daily import run
        run()
        log.info("Daily report complete")
    except Exception as e:
        log.error(f"Daily report failed: {e}")

def run_weekly_report():
    """Run weekly Claude report."""
    log.info("Generating weekly report...")
    try:
        from pipeline.report_weekly import run
        run()
        log.info("Weekly report complete")
    except Exception as e:
        log.error(f"Weekly report failed: {e}")

def run_pending_reports():
    """Generate any pending reports from missed sessions."""
    pending = get_pending_reports()
    if pending > 0:
        log.info(f"Found {pending} pending reports — generating now")
        run_daily_report()

async def run_trader():
    """Run the trading loop."""
    from trader.rule_engine.trader import run
    await run()

def daily_cycle():
    """
    One full trading day cycle.
    Runs all agents in correct order.
    """
    log.info(f"=== DAILY CYCLE STARTING {now_pt().strftime('%Y-%m-%d')} ===")

    # Generate any pending reports first
    run_pending_reports()

    # 5:45am — market pull
    sleep_until(MARKET_PULL_TIME, "market pull")
    run_market_pull()

    # 6:00am — pre-market scan
    sleep_until(PRE_MARKET_TIME, "pre-market scan")
    run_pre_market_scan()

    # 6:30am — open scan + trader
    sleep_until(OPEN_SCAN_TIME, "market open")
    run_open_scan()

    log.info("Starting trader...")
    asyncio.run(run_trader())

    # 1:00pm — market closes, trader handles its own close
    # 1:15pm — daily report
    sleep_until(DAILY_REPORT_TIME, "daily report")
    print_end_of_day()
    run_daily_report()

    # Sunday 8pm — weekly report
    if now_pt().weekday() == WEEKLY_REPORT_DAY:
        sleep_until(WEEKLY_REPORT_TIME, "weekly report")
        run_weekly_report()

    log.info(f"=== DAILY CYCLE COMPLETE {now_pt().strftime('%Y-%m-%d')} ===")

def sleep_until_tomorrow():
    """Sleep until next trading day's market pull time."""
    next_day  = next_trading_day()
    next_run  = datetime.combine(next_day, MARKET_PULL_TIME, tzinfo=PT)
    secs      = (next_run - now_pt()).total_seconds()
    h         = int(secs // 3600)
    m         = int((secs % 3600) // 60)
    log.info(f"Sleeping until {next_run.strftime('%A %B %d at %I:%M%p PT')} ({h}h {m}m)")
    time.sleep(secs)

def run():
    """
    Main pipeline loop.
    Runs forever — one trading day at a time.
    """
    print_startup()

    while True:
        if is_trading_day():
            # Check if we're before market pull time
            secs_to_pull = seconds_until(MARKET_PULL_TIME)
            secs_to_close = seconds_until(MARKET_CLOSE_TIME)

            if secs_to_close > 0:
                # Trading day ahead or in progress
                daily_cycle()
            else:
                # Market already closed today
                log.info("Market already closed for today")
                run_pending_reports()
                sleep_until_tomorrow()
        else:
            # Weekend
            log.info(f"Weekend — {now_pt().strftime('%A')}. Sleeping until Monday.")
            sleep_until_tomorrow()

if __name__ == "__main__":
    run()