import os
import sqlite3
import logging
import pandas as pd
from datetime import datetime, date

# --- Config ---
from config import ROOT, DB_SIGNALS
from pipeline.scribe import ask_deepseek
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

def get_missed_opportunities(report_date):
    """Pull today's missed-opp sweep results."""
    conn = sqlite3.connect(DB_SIGNALS)
    try:
        return pd.read_sql(
            "SELECT * FROM missed_opportunities WHERE date = ? ORDER BY max_up_pct DESC",
            conn, params=(report_date,)
        )
    except Exception as e:
        log.error(f"Failed to get missed opportunities: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def get_trader_rejections(report_date):
    """Pull today's trader rejections."""
    conn = sqlite3.connect(DB_SIGNALS)
    try:
        return pd.read_sql(
            "SELECT * FROM trader_rejections WHERE date = ? ORDER BY timestamp",
            conn, params=(report_date,)
        )
    except Exception as e:
        log.error(f"Failed to get trader rejections: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def per_strategy_stats(trades_df):
    """Group trades by strategy for the per-strategy table."""
    if trades_df.empty or 'strategy' not in trades_df.columns:
        return {}
    out = {}
    for strat, sub in trades_df.groupby('strategy'):
        wins = sub[sub['pnl'] > 0]
        out[strat] = {
            'trades':   len(sub),
            'pnl':      round(sub['pnl'].sum(), 2),
            'win_rate': round(len(wins) / len(sub) * 100, 1) if len(sub) > 0 else 0,
            'avg_win':  round(wins['pnl'].mean(), 2) if not wins.empty else 0,
            'avg_loss': round(sub[sub['pnl'] <= 0]['pnl'].mean(), 2) if (sub['pnl'] <= 0).any() else 0,
        }
    return out

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

def generate_narrative(report_date, summary, candidates, confirmed, watchlist, trades, advisor):
    """Ask local DeepSeek for a concise analysis of the day."""
    top_gaps = ""
    if not confirmed.empty:
        top = confirmed.head(8)
        for _, row in top.iterrows():
            top_gaps += (
                f"  - {row['ticker']:6} {row.get('direction',''):4} "
                f"gap {row.get('real_gap_pct', 0):+.2f}%  "
                f"accuracy {row.get('gap_accuracy', 0)*100:.0f}%\n"
            )

    trade_summary = ""
    if not trades.empty:
        for _, row in trades.iterrows():
            trade_summary += (
                f"  - {row['ticker']:6} {row.get('direction',''):4} "
                f"entry ${row.get('entry_price',0):.2f} -> exit ${row.get('exit_price',0):.2f}  "
                f"P&L ${row.get('pnl',0):+.2f}  hold {row.get('hold_time_minutes',0):.0f}m\n"
            )
    else:
        trade_summary = "  (no trades)\n"

    confirmation_rate = round(len(confirmed) / len(candidates) * 100, 1) if len(candidates) > 0 else 0

    system = (
        "You are the in-house analyst for Kestrel, an automated US-equity day trading bot. "
        "Write a tight 200-300 word daily debrief for the operator (Patrick). "
        "Be direct, specific, and grounded in the numbers provided. No filler, no hedging. "
        "Cover: what worked, what didn't, the most useful pattern to notice, and one thing to "
        "watch tomorrow. Plain markdown, no headings, no bullet lists unless you really need them."
    )
    user = f"""DATE: {report_date}

P&L
  total: ${summary['total_pnl']:,.2f}   trades: {summary['total_trades']}   win rate: {summary['win_rate']}%
  avg win: ${summary['avg_win']:,.2f}   avg loss: ${summary['avg_loss']:,.2f}
  best: ${summary['biggest_win']:,.2f}   worst: ${summary['biggest_loss']:,.2f}
  avg hold: {summary['avg_hold']} min

OPPORTUNITY
  gap candidates: {len(candidates)}    confirmed: {len(confirmed)}    confirmation rate: {confirmation_rate}%
  watchlist size: {len(watchlist)}

TOP GAPS
{top_gaps if top_gaps else "  (none)"}

TRADES
{trade_summary}
"""
    return ask_deepseek(system, user, max_tokens=900, temperature=0.4)

def generate_markdown(report_date, summary, candidates, confirmed, watchlist, trades, advisor,
                      missed=None, rejections=None, narrative=""):
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

    # --- Per-strategy breakdown ---
    strat_stats = per_strategy_stats(trades)
    if strat_stats:
        md += "---\n\n## P&L by Strategy\n\n"
        md += "| Strategy | Trades | P&L | Win Rate | Avg Win | Avg Loss |\n"
        md += "|---|---|---|---|---|---|\n"
        for strat, s in strat_stats.items():
            md += (f"| {strat} | {s['trades']} | ${s['pnl']:,.2f} | "
                   f"{s['win_rate']}% | ${s['avg_win']:,.2f} | ${s['avg_loss']:,.2f} |\n")
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
        md += "| Ticker | Strategy | Entry | Exit | P&L | Hold | Exit Reason |\n"
        md += "|---|---|---|---|---|---|---|\n"
        for _, row in trades.iterrows():
            md += (f"| {row['ticker']} | {row.get('strategy','?')} | "
                   f"${row['entry_price']:.2f} | ${row['exit_price']:.2f} | "
                   f"${row['pnl']:.2f} | {row['hold_time_minutes']:.0f}m | "
                   f"{row.get('exit_reason','')} |\n")
        md += "\n"

    # --- Missed opportunities ---
    if missed is not None and not missed.empty:
        un_traded = missed[missed['was_traded'] == 0]
        if not un_traded.empty:
            md += "---\n\n## Missed Opportunities\n\n"
            md += "_Watchlist tickers we didn't trade and what they did intraday._\n\n"
            md += "| Ticker | Strategy | Score | Max Up | Close | Worst Down |\n"
            md += "|---|---|---|---|---|---|\n"
            for _, row in un_traded.head(15).iterrows():
                md += (f"| {row['ticker']} | {row['strategy']} | {row['score']:.2f} | "
                       f"{row['max_up_pct']:+.2f}% | {row['close_return_pct']:+.2f}% | "
                       f"{row['max_down_pct']:+.2f}% |\n")
            md += "\n"

    # --- Trader rejections ---
    if rejections is not None and not rejections.empty:
        md += "---\n\n## Trader Rejections (Top Reasons)\n\n"
        md += "_How often each rejection reason fired today (state-change-only logging)._\n\n"
        # Strip parameterized parts for grouping (e.g. "price_above_5d_avg ($X >= $Y)" -> "price_above_5d_avg")
        reasons = rejections['reason'].str.split(' ').str[0].fillna('unknown')
        counts  = reasons.value_counts().head(10)
        md += "| Reason | Count |\n|---|---|\n"
        for reason, count in counts.items():
            md += f"| {reason} | {count} |\n"
        md += "\n"

    if narrative:
        md += f"""---

## Analyst Note — DeepSeek

{narrative}

"""

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
    missed                           = get_missed_opportunities(report_date)
    rejections                       = get_trader_rejections(report_date)

    # Calculate summary
    summary = calculate_daily_summary(trades)

    # Save to performance.db
    save_daily_summary(report_date, summary)

    # Ask DeepSeek for the narrative
    narrative = generate_narrative(report_date, summary, candidates, confirmed, watchlist, trades, advisor)

    # Generate markdown
    md   = generate_markdown(
        report_date, summary, candidates, confirmed, watchlist, trades, advisor,
        missed=missed, rejections=rejections, narrative=narrative,
    )
    path = os.path.join(REPORT_DIR, f"{report_date}.md")

    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
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