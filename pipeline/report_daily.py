import os
import sqlite3
import logging
import pandas as pd
from datetime import datetime, date

# --- Config ---
from config import ROOT, DB_SIGNALS
from pipeline.performance_db import (
    mark_report_pending,
    mark_report_complete,
    get_pending_reports
)

# --- Logging ---
LOG_PATH = os.path.join(ROOT, "logs/report_daily.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.report_daily")

DB_PERF    = os.path.join(ROOT, "data/database/performance.db")
REPORT_DIR = os.path.join(ROOT, "reports/daily")

def get_opportunity_stats(report_date):
    """Pull gap candidate and confirmation stats for the day."""
    conn = sqlite3.connect(DB_SIGNALS)
    try:
        candidates = pd.read_sql(
            "SELECT * FROM pre_market_gaps WHERE DATE(scan_time) = ?",
            conn, params=(report_date,)
        )
        confirmed = pd.read_sql(
            "SELECT * FROM confirmed_gaps WHERE DATE(confirmed_at) = ?",
            conn, params=(report_date,)
        )
        watchlist = pd.read_sql(
            "SELECT * FROM watchlists WHERE date = ?",
            conn, params=(report_date,)
        )
        return candidates, confirmed, watchlist
    except Exception as e:
        log.error(f"Failed to get opportunity stats: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    finally:
        conn.close()

def get_trade_stats(report_date):
    """Pull all trades for the day."""
    conn = sqlite3.connect(DB_PERF)
    try:
        trades = pd.read_sql(
            "SELECT * FROM trades WHERE date = ?",
            conn, params=(report_date,)
        )
        return trades
    except Exception as e:
        log.error(f"Failed to get trade stats: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def get_advisor_stats(report_date):
    """Pull advisor log for the day."""
    conn = sqlite3.connect(DB_SIGNALS)
    try:
        advisor = pd.read_sql(
            "SELECT * FROM advisor_log WHERE date = ?",
            conn, params=(report_date,)
        )
        return advisor
    except Exception as e:
        log.error(f"Failed to get advisor stats: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def calculate_daily_summary(trades_df):
    """Calculate key performance metrics from trades."""
    if trades_df.empty:
        return {
            'total_pnl':      0,
            'total_trades':   0,
            'win_rate':       0,
            'avg_win':        0,
            'avg_loss':       0,
            'biggest_win':    0,
            'biggest_loss':   0,
            'avg_hold':       0,
            'system_a_pnl':   0,
            'system_b_pnl':   0,
        }

    wins   = trades_df[trades_df['pnl'] > 0]
    losses = trades_df[trades_df['pnl'] <= 0]

    return {
        'total_pnl':    round(trades_df['pnl'].sum(), 2),
        'total_trades': len(trades_df),
        'win_rate':     round(len(wins) / len(trades_df) * 100, 1) if len(trades_df) > 0 else 0,
        'avg_win':      round(wins['pnl'].mean(), 2) if not wins.empty else 0,
        'avg_loss':     round(losses['pnl'].mean(), 2) if not losses.empty else 0,
        'biggest_win':  round(trades_df['pnl'].max(), 2),
        'biggest_loss': round(trades_df['pnl'].min(), 2),
        'avg_hold':     round(trades_df['hold_time_minutes'].mean(), 1) if 'hold_time_minutes' in trades_df else 0,
        'system_a_pnl': round(trades_df['pnl'].sum(), 2),
        'system_b_pnl': 0,  # populated once System B is live
    }

def save_daily_summary(report_date, summary):
    """Write daily summary to performance.db."""
    conn = sqlite3.connect(DB_PERF)
    c    = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO daily_summary (
            date, total_pnl, win_rate, total_trades,
            avg_win, avg_loss, biggest_win, biggest_loss,
            avg_hold_minutes, system_a_pnl, system_b_pnl,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        report_date,
        summary['total_pnl'],
        summary['win_rate'],
        summary['total_trades'],
        summary['avg_win'],
        summary['avg_loss'],
        summary['biggest_win'],
        summary['biggest_loss'],
        summary['avg_hold'],
        summary['system_a_pnl'],
        summary['system_b_pnl'],
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ))
    conn.commit()
    conn.close()

def generate_markdown(report_date, summary, candidates, confirmed, watchlist, trades, advisor):
    """Generate the daily markdown report."""

    # Opportunity section
    confirmation_rate = round(len(confirmed) / len(candidates) * 100, 1) if len(candidates) > 0 else 0
    premarket_accuracy = round(confirmed['gap_accuracy'].mean() * 100, 1) if not confirmed.empty and 'gap_accuracy' in confirmed.columns else 0

    # Advisor section
    if not advisor.empty and 'agreement' in advisor.columns:
        agreement_rate = round(advisor['agreement'].mean() * 100, 1)
        disagreements  = len(advisor[advisor['agreement'] == 0])
    else:
        agreement_rate = 0
        disagreements  = 0

    # Build markdown
    md = f"""# Kestrel Daily Report
## {report_date}
---

## P&L Summary

| Metric | Value |
|---|---|
| Total P&L | ${summary['total_pnl']:,.2f} |
| Total Trades | {summary['total_trades']} |
| Win Rate | {summary['win_rate']}% |
| Avg Win | ${summary['avg_win']:,.2f} |
| Avg Loss | ${summary['avg_loss']:,.2f} |
| Biggest Win | ${summary['biggest_win']:,.2f} |
| Biggest Loss | ${summary['biggest_loss']:,.2f} |
| Avg Hold Time | {summary['avg_hold']} min |

---

## Opportunity Agent

| Metric | Value |
|---|---|
| Gap Candidates | {len(candidates)} |
| Confirmed at Open | {len(confirmed)} |
| Confirmation Rate | {confirmation_rate}% |
| Pre-market Accuracy | {premarket_accuracy}% |
| Watchlist Size | {len(watchlist)} |

"""

    # Top gap candidates
    if not confirmed.empty:
        md += "### Top Gap Candidates\n\n"
        md += "| Ticker | Direction | Gap % | Vol Ratio | Accuracy |\n"
        md += "|---|---|---|---|---|\n"
        for _, row in confirmed.head(10).iterrows():
            md += f"| {row['ticker']} | {row['direction']} | {row.get('real_gap_pct', 0):+.2f}% | {row.get('volume_ratio', 0):.1f}x | {row.get('gap_accuracy', 0)*100:.0f}% |\n"
        md += "\n"

    md += f"""---

## Advisor Performance

| Metric | Value |
|---|---|
| System A P&L | ${summary['system_a_pnl']:,.2f} |
| System B P&L | ${summary['system_b_pnl']:,.2f} |
| Agreement Rate | {agreement_rate}% |
| Disagreements | {disagreements} |

---

## Trade Log

"""

    if trades.empty:
        md += "_No trades today._\n\n"
    else:
        md += "| Ticker | Direction | Entry | Exit | P&L | Hold |\n"
        md += "|---|---|---|---|---|---|\n"
        for _, row in trades.iterrows():
            md += f"| {row['ticker']} | {row['direction']} | ${row['entry_price']:.2f} | ${row['exit_price']:.2f} | ${row['pnl']:.2f} | {row['hold_time_minutes']:.0f}m |\n"
        md += "\n"

    md += f"""---

## System Health

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} PT
"""

    return md

def generate(report_date=None):
    """Generate daily report for a given date. Defaults to today."""
    if report_date is None:
        report_date = date.today().strftime('%Y-%m-%d')

    log.info(f"Generating daily report for {report_date}")

    # Pull data
    candidates, confirmed, watchlist = get_opportunity_stats(report_date)
    trades                           = get_trade_stats(report_date)
    advisor                          = get_advisor_stats(report_date)

    # Calculate summary
    summary = calculate_daily_summary(trades)

    # Save to performance.db
    save_daily_summary(report_date, summary)

    # Generate markdown
    md   = generate_markdown(report_date, summary, candidates, confirmed, watchlist, trades, advisor)
    path = os.path.join(REPORT_DIR, f"{report_date}.md")

    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(path, 'w') as f:
        f.write(md)

    log.info(f"Report saved to {path}")
    return path

def run():
    """
    Check for pending reports and generate them.
    This runs at startup and after market close.
    """
    today = date.today().strftime('%Y-%m-%d')

    # Mark today as pending
    mark_report_pending(today, 'daily')

    # Generate all pending reports
    pending = get_pending_reports()
    log.info(f"Found {len(pending)} pending reports")

    for report in pending:
        if report['type'] == 'daily':
            try:
                path = generate(report['date'])
                mark_report_complete(report['date'], 'daily', path)
                log.info(f"Report complete: {path}")
            except Exception as e:
                log.error(f"Failed to generate report for {report['date']}: {e}")

if __name__ == "__main__":
    run()