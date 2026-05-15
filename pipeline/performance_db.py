import os
import sqlite3
import logging
from datetime import datetime
import pandas as pd

# --- Config ---
from config import ROOT

# --- Logging ---
LOG_PATH = os.path.join(ROOT, "logs/performance_db.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.performance_db")

DB_PATH = os.path.join(ROOT, "data/database/performance.db")

def initialize():
    """Create all performance database tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()

    # --- Trades ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date                TEXT,
            ticker              TEXT,
            direction           TEXT,
            entry_price         REAL,
            exit_price          REAL,
            shares              REAL,
            pnl                 REAL,
            pnl_pct             REAL,
            hold_time_minutes   REAL,
            entry_reason        TEXT,
            exit_reason         TEXT,
            system_a_score      REAL,
            system_b_score      REAL,
            outcome             TEXT,
            strategy            TEXT DEFAULT 'mean_reversion',
            created_at          TEXT
        )
    """)

    # --- Daily summary ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_summary (
            date                TEXT PRIMARY KEY,
            total_pnl           REAL,
            total_pnl_pct       REAL,
            win_rate            REAL,
            total_trades        INTEGER,
            winning_trades      INTEGER,
            losing_trades       INTEGER,
            avg_win             REAL,
            avg_loss            REAL,
            biggest_win         REAL,
            biggest_loss        REAL,
            avg_hold_minutes    REAL,
            gap_candidates      INTEGER,
            gaps_confirmed      INTEGER,
            premarket_accuracy  REAL,
            watchlist_size      INTEGER,
            system_a_pnl        REAL,
            system_b_pnl        REAL,
            system_a_win_rate   REAL,
            system_b_win_rate   REAL,
            agreements          INTEGER,
            disagreements       INTEGER,
            created_at          TEXT
        )
    """)

    # --- Report status ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS report_status (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT,
            type            TEXT,
            status          TEXT,
            generated_at    TEXT,
            path            TEXT,
            UNIQUE(date, type)
        )
    """)

    # --- Indexes ---
    c.execute("CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_trades_date_ticker ON trades(date, ticker)")

    conn.commit()
    conn.close()
    log.info("performance.db initialized")

def initialize_signals_db():
    """Create all signals database tables if they don't exist."""
    from config import DB_SIGNALS
    conn = sqlite3.connect(DB_SIGNALS)
    c    = conn.cursor()

    # --- Advisor log ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS advisor_log (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date                TEXT,
            time                TEXT,
            ticker              TEXT,
            system_a_score      REAL,
            system_b_score      REAL,
            agreement           INTEGER,
            predicted_direction TEXT,
            actual_direction    TEXT,
            correct             INTEGER,
            rescore_number      INTEGER,
            created_at          TEXT
        )
    """)

    # --- Watchlists ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS watchlists (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT,
            ticker          TEXT,
            rank            INTEGER,
            score           REAL,
            direction       TEXT,
            gap_pct         REAL,
            relative_gap    REAL,
            avg_volume      INTEGER,
            added_at        TEXT,
            removed_at      TEXT,
            removal_reason  TEXT
        )
    """)

    # --- Intraday signals ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS intraday_signals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT,
            time            TEXT,
            ticker          TEXT,
            signal_type     TEXT,
            signal_value    REAL,
            direction       TEXT,
            created_at      TEXT
        )
    """)

    # --- Indexes ---
    c.execute("CREATE INDEX IF NOT EXISTS idx_advisor_date ON advisor_log(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_advisor_ticker ON advisor_log(ticker)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_advisor_date_ticker ON advisor_log(date, ticker)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_date ON watchlists(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_signals_date ON intraday_signals(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_signals_ticker ON intraday_signals(ticker)")

    # --- Trader rejections (NN training data — what trader saw and skipped) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS trader_rejections (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT,
            date            TEXT,
            ticker          TEXT,
            current_price   REAL,
            score           REAL,
            strategy        TEXT,
            reason          TEXT
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_rej_date    ON trader_rejections(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_rej_ticker  ON trader_rejections(ticker)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_rej_reason  ON trader_rejections(reason)")

    # --- Missed opportunities (end-of-day sweep — what we should have traded) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS missed_opportunities (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            date              TEXT,
            ticker            TEXT,
            strategy          TEXT,
            score             REAL,
            day_open          REAL,
            day_high          REAL,
            day_low           REAL,
            day_close         REAL,
            max_up_pct        REAL,
            max_down_pct      REAL,
            close_return_pct  REAL,
            was_traded        INTEGER,
            swept_at          TEXT,
            UNIQUE(date, ticker)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_miss_date     ON missed_opportunities(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_miss_ticker   ON missed_opportunities(ticker)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_miss_strategy ON missed_opportunities(strategy)")

    conn.commit()
    conn.close()
    log.info("signals.db expanded with advisor_log, watchlists, intraday_signals, trader_rejections, missed_opportunities")

def initialize_market_data_db():
    """Create market data database tables."""
    from config import DB_MARKET_DATA
    conn = sqlite3.connect(DB_MARKET_DATA)
    c    = conn.cursor()

    # --- Intraday ticks ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS intraday_ticks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT,
            time        TEXT,
            ticker      TEXT,
            open        REAL,
            high        REAL,
            low         REAL,
            close       REAL,
            volume      REAL,
            vwap        REAL
        )
    """)

    # --- Indexes ---
    c.execute("CREATE INDEX IF NOT EXISTS idx_ticks_date ON intraday_ticks(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ticks_ticker ON intraday_ticks(ticker)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ticks_date_ticker ON intraday_ticks(date, ticker)")

    conn.commit()
    conn.close()
    log.info("market_data.db initialized with intraday_ticks")

# --- Report status helpers ---

def mark_report_pending(date, report_type):
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO report_status (date, type, status, generated_at, path)
        VALUES (?, ?, 'pending', null, null)
    """, (date, report_type))
    conn.commit()
    conn.close()

def mark_report_complete(date, report_type, path):
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("""
        UPDATE report_status
        SET status='complete', generated_at=?, path=?
        WHERE date=? AND type=?
    """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), path, date, report_type))
    conn.commit()
    conn.close()

def get_pending_reports():
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("SELECT date, type FROM report_status WHERE status='pending'")
    rows = c.fetchall()
    conn.close()
    return [{'date': r[0], 'type': r[1]} for r in rows]

# --- Data retrieval helpers ---

def get_daily_summary(date):
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("SELECT * FROM daily_summary WHERE date=?", (date,))
    row = c.fetchone()
    conn.close()
    return row

def get_week_summaries(start_date, end_date):
    conn = sqlite3.connect(DB_PATH)
    df   = pd.read_sql(
        "SELECT * FROM daily_summary WHERE date BETWEEN ? AND ?",
        conn, params=(start_date, end_date)
    )
    conn.close()
    return df

def get_week_trades(start_date, end_date):
    conn = sqlite3.connect(DB_PATH)
    df   = pd.read_sql(
        "SELECT * FROM trades WHERE date BETWEEN ? AND ?",
        conn, params=(start_date, end_date)
    )
    conn.close()
    return df

def get_week_advisor_log(start_date, end_date):
    from config import DB_SIGNALS
    conn = sqlite3.connect(DB_SIGNALS)
    df   = pd.read_sql(
        "SELECT * FROM advisor_log WHERE date BETWEEN ? AND ?",
        conn, params=(start_date, end_date)
    )
    conn.close()
    return df

if __name__ == "__main__":
    initialize()
    initialize_signals_db()
    initialize_market_data_db()