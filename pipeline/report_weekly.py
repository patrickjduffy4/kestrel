import os
import sqlite3
import logging
import pandas as pd
from datetime import datetime, date, timedelta
import anthropic

# --- Config ---
from config import ROOT, DB_SIGNALS, ANTHROPIC_API_KEY
from pipeline.performance_db import (
    mark_report_pending,
    mark_report_complete,
    get_pending_reports,
    get_week_summaries,
    get_week_trades,
    get_week_advisor_log
)

# --- Logging ---
LOG_PATH = os.path.join(ROOT, "logs/report_weekly.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.report_weekly")

DB_PERF    = os.path.join(ROOT, "data/database/performance.db")
REPORT_DIR = os.path.join(ROOT, "reports/weekly")
claude     = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def get_week_dates():
    """Get Monday-Friday dates for the most recent trading week."""
    today  = date.today()
    monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)
    return monday.strftime('%Y-%m-%d'), friday.strftime('%Y-%m-%d')

def get_week_scan_results(start_date, end_date):
    """Pull scan results for the week."""
    conn = sqlite3.connect(DB_SIGNALS)
    try:
        candidates = pd.read_sql(
            "SELECT * FROM pre_market_gaps WHERE DATE(scan_time) BETWEEN ? AND ?",
            conn, params=(start_date, end_date)
        )
        confirmed = pd.read_sql(
            "SELECT * FROM confirmed_gaps WHERE DATE(confirmed_at) BETWEEN ? AND ?",
            conn, params=(start_date, end_date)
        )
        return candidates, confirmed
    except Exception as e:
        log.error(f"Failed to get scan results: {e}")
        return pd.DataFrame(), pd.DataFrame()
    finally:
        conn.close()

def call_claude(system_prompt, user_prompt):
    """Make a single Claude API call."""
    try:
        message = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=5000,
            messages=[
                {
                    "role": "user",
                    "content": f"{system_prompt}\n\n{user_prompt}"
                }
            ]
        )
        return message.content[0].text
    except Exception as e:
        log.error(f"Claude API call failed: {e}")
        return f"_Analysis unavailable: {e}_"

def analyze_opportunity(candidates, confirmed, start_date, end_date):
    """Claude call 1 — Opportunity agent analysis."""
    log.info("Claude call 1: Opportunity analysis...")

    if candidates.empty:
        return "_No opportunity data available for this week._"

    confirmation_rate = round(len(confirmed) / len(candidates) * 100, 1) if len(candidates) > 0 else 0
    avg_accuracy      = round(confirmed['gap_accuracy'].mean() * 100, 1) if not confirmed.empty and 'gap_accuracy' in confirmed.columns else 0
    direction_breakdown = confirmed['direction'].value_counts().to_dict() if not confirmed.empty else {}

    system = """You are analyzing the performance of a pre-market gap detection system
for a day trading bot called Kestrel. Be concise, specific, and actionable.
Focus on patterns, accuracy trends, and what can be improved."""

    user = f"""Week: {start_date} to {end_date}

OPPORTUNITY AGENT STATS:
- Total gap candidates identified: {len(candidates)}
- Confirmed at open: {len(confirmed)}
- Confirmation rate: {confirmation_rate}%
- Pre-market accuracy: {avg_accuracy}%
- Direction breakdown: {direction_breakdown}

Top 10 confirmed gaps this week:
{confirmed.head(10)[['ticker', 'direction', 'real_gap_pct', 'volume_ratio', 'gap_accuracy']].to_string() if not confirmed.empty else 'None'}

Analyze:
1. How well is the pre-market scan predicting real gaps?
2. Are there patterns in which gaps confirm vs fade?
3. What should be adjusted to improve opportunity detection?"""

    return call_claude(system, user)

def analyze_advisor(advisor_df, start_date, end_date):
    """Claude call 2 — Advisor/NN analysis."""
    log.info("Claude call 2: Advisor analysis...")

    if advisor_df.empty:
        return "_No advisor data available for this week._"

    agreement_rate = round(advisor_df['agreement'].mean() * 100, 1) if 'agreement' in advisor_df.columns else 0
    disagreements  = advisor_df[advisor_df['agreement'] == 0] if 'agreement' in advisor_df.columns else pd.DataFrame()
    correct_rate   = round(advisor_df['correct'].mean() * 100, 1) if 'correct' in advisor_df.columns else 0

    system = """You are analyzing the performance of two parallel trading advisors:
System A (rule-based) and System B (neural network in training) for Kestrel.
Be concise and focus on what the neural network appears to be learning
and where it diverges from the rule-based system."""

    user = f"""Week: {start_date} to {end_date}

ADVISOR STATS:
- Total scoring decisions: {len(advisor_df)}
- System A vs B agreement rate: {agreement_rate}%
- Total disagreements: {len(disagreements)}
- Overall prediction accuracy: {correct_rate}%

Sample disagreements (where systems differed):
{disagreements.head(10)[['ticker', 'system_a_score', 'system_b_score', 'predicted_direction', 'actual_direction', 'correct']].to_string() if not disagreements.empty else 'None'}

Analyze:
1. What patterns is System B appearing to learn?
2. Where is it outperforming System A?
3. Where is it underperforming?
4. Is System B ready to be trusted more, or does it need more training?"""

    return call_claude(system, user)

def analyze_trading(trades_df, summaries_df, start_date, end_date):
    """Claude call 3 — Trading performance analysis."""
    log.info("Claude call 3: Trading performance analysis...")

    if trades_df.empty:
        return "_No trade data available for this week._"

    total_pnl = round(trades_df['pnl'].sum(), 2)
    win_rate  = round(len(trades_df[trades_df['pnl'] > 0]) / len(trades_df) * 100, 1)
    avg_win   = round(trades_df[trades_df['pnl'] > 0]['pnl'].mean(), 2) if len(trades_df[trades_df['pnl'] > 0]) > 0 else 0
    avg_loss  = round(trades_df[trades_df['pnl'] <= 0]['pnl'].mean(), 2) if len(trades_df[trades_df['pnl'] <= 0]) > 0 else 0

    system = """You are analyzing the trading performance of Kestrel,
an automated day trading system. Be direct and specific.
Focus on what's working, what isn't, and concrete improvements."""

    user = f"""Week: {start_date} to {end_date}

TRADING STATS:
- Total P&L: ${total_pnl:,.2f}
- Total trades: {len(trades_df)}
- Win rate: {win_rate}%
- Avg win: ${avg_win:,.2f}
- Avg loss: ${avg_loss:,.2f}
- Best trade: ${trades_df['pnl'].max():,.2f}
- Worst trade: ${trades_df['pnl'].min():,.2f}

Daily P&L breakdown:
{summaries_df[['date', 'total_pnl', 'win_rate', 'total_trades']].to_string() if not summaries_df.empty else 'None'}

Top 10 trades by P&L:
{trades_df.nlargest(10, 'pnl')[['ticker', 'direction', 'entry_price', 'exit_price', 'pnl', 'hold_time_minutes']].to_string()}

Analyze:
1. What setups are generating the most profit?
2. What setups are causing losses?
3. Is hold time optimal or are we exiting too early/late?
4. What should the Trader focus on next week?"""

    return call_claude(system, user)

def analyze_strategy(opportunity_analysis, advisor_analysis,
                     trading_analysis, start_date, end_date):
    """Claude call 4 — Strategic recommendations."""
    log.info("Claude call 4: Strategic recommendations...")

    system = """You are the strategic advisor for Kestrel, an automated day trading system.
You have read three separate analyses of this week's performance.
Synthesize them into clear, prioritized recommendations for next week.
Be specific and actionable. Maximum 5 recommendations."""

    user = f"""Week: {start_date} to {end_date}

OPPORTUNITY ANALYSIS:
{opportunity_analysis}

ADVISOR ANALYSIS:
{advisor_analysis}

TRADING PERFORMANCE:
{trading_analysis}

Based on all three analyses:
1. What are the top 3-5 priorities for next week?
2. What is the single most important thing to fix or improve?
3. Is System B making progress toward graduation?
4. Any systemic risks or concerns to watch?"""

    return call_claude(system, user)

def generate_markdown(start_date, end_date, summaries, trades,
                      opportunity_analysis, advisor_analysis,
                      trading_analysis, strategy_analysis):
    """Compile all four analyses into one weekly markdown report."""

    total_pnl    = round(trades['pnl'].sum(), 2) if not trades.empty else 0
    total_trades = len(trades)
    win_rate     = round(len(trades[trades['pnl'] > 0]) / len(trades) * 100, 1) if len(trades) > 0 else 0

    md = f"""# Kestrel Weekly Report
## Week of {start_date} to {end_date}

---

## Week at a Glance

| Metric | Value |
|---|---|
| Total P&L | ${total_pnl:,.2f} |
| Total Trades | {total_trades} |
| Win Rate | {win_rate}% |
| Trading Days | {len(summaries)} |

### Daily P&L
| Date | P&L | Trades | Win Rate |
|---|---|---|---|
"""

    if not summaries.empty:
        for _, row in summaries.iterrows():
            md += f"| {row['date']} | ${row.get('total_pnl', 0):,.2f} | {row.get('total_trades', 0)} | {row.get('win_rate', 0)}% |\n"

    md += f"""
---

## Opportunity Agent Analysis

{opportunity_analysis}

---

## Advisor Analysis — System A vs System B

{advisor_analysis}

---

## Trading Performance Analysis

{trading_analysis}

---

## Strategic Recommendations for Next Week

{strategy_analysis}

---

_Generated by Claude on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} PT_
"""

    return md

def generate(start_date=None, end_date=None):
    """Generate weekly report. Defaults to most recent trading week."""
    if start_date is None or end_date is None:
        start_date, end_date = get_week_dates()

    log.info(f"Generating weekly report for {start_date} to {end_date}")

    summaries             = get_week_summaries(start_date, end_date)
    trades                = get_week_trades(start_date, end_date)
    advisor               = get_week_advisor_log(start_date, end_date)
    candidates, confirmed = get_week_scan_results(start_date, end_date)

    opportunity_analysis = analyze_opportunity(candidates, confirmed, start_date, end_date)
    advisor_analysis     = analyze_advisor(advisor, start_date, end_date)
    trading_analysis     = analyze_trading(trades, summaries, start_date, end_date)
    strategy_analysis    = analyze_strategy(
        opportunity_analysis, advisor_analysis,
        trading_analysis, start_date, end_date
    )

    md = generate_markdown(
        start_date, end_date, summaries, trades,
        opportunity_analysis, advisor_analysis,
        trading_analysis, strategy_analysis
    )

    week_num = datetime.strptime(start_date, '%Y-%m-%d').isocalendar()[1]
    year     = datetime.strptime(start_date, '%Y-%m-%d').year
    path     = os.path.join(REPORT_DIR, f"{year}-W{week_num:02d}.md")

    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(md)

    log.info(f"Weekly report saved to {path}")
    return path

def run():
    """Check for pending weekly reports and generate them."""
    start_date, end_date = get_week_dates()
    week_num = datetime.strptime(start_date, '%Y-%m-%d').isocalendar()[1]
    year     = datetime.strptime(start_date, '%Y-%m-%d').year
    week_id  = f"{year}-W{week_num:02d}"

    mark_report_pending(week_id, 'weekly')

    pending = get_pending_reports()
    log.info(f"Found {len(pending)} pending reports")

    for report in pending:
        if report['type'] == 'weekly':
            try:
                path = generate()
                mark_report_complete(report['date'], 'weekly', path)
                log.info(f"Weekly report complete: {path}")
            except Exception as e:
                log.error(f"Failed to generate weekly report: {e}")

if __name__ == "__main__":
    path = generate()
    print(f"Report generated: {path}")