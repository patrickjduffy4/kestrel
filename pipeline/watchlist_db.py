import sys
sys.path.insert(0, "D:/Kestrel")

import sqlite3
import logging
import os
from datetime import datetime
from config import ROOT, DB_WATCHLIST

LOG_PATH = os.path.join(ROOT, "logs/watchlist.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kestrel.watchlist")

DEFAULT_STRATEGY = 'mean_reversion'

def initialize():
    """Create watchlist database."""
    conn = sqlite3.connect(DB_WATCHLIST)
    c    = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            rank        INTEGER,
            ticker      TEXT PRIMARY KEY,
            score       REAL,
            direction   TEXT,
            gap_pct     REAL,
            avg_volume  INTEGER,
            notes       TEXT,
            added_at    TEXT,
            status      TEXT,
            strategy    TEXT DEFAULT 'mean_reversion'
        )
    """)

    conn.commit()
    conn.close()
    log.info("watchlist.db initialized")

def set_watchlist(candidates, strategy=DEFAULT_STRATEGY):
    """
    Replace this strategy's portion of the watchlist with new candidates.
    Open positions (status='LONG') are preserved across runs.
    Other strategies' rows are untouched.
    """
    conn = sqlite3.connect(DB_WATCHLIST)
    c    = conn.cursor()

    # Clear only THIS strategy's non-position rows
    c.execute(
        "DELETE FROM watchlist WHERE status != 'LONG' AND strategy = ?",
        (strategy,)
    )

    for candidate in candidates:
        c.execute("""
            INSERT OR REPLACE INTO watchlist
            (rank, ticker, score, direction, gap_pct, avg_volume, notes, added_at, status, strategy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            candidate.get('rank'),
            candidate['ticker'],
            candidate['score'],
            candidate.get('direction', 'up'),
            candidate.get('gap_pct', 0),
            candidate.get('avg_volume', 0),
            candidate.get('notes', ''),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'WATCHING',
            candidate.get('strategy', strategy)
        ))

    conn.commit()
    conn.close()
    # Log snapshot to signals.db for birdbrain training
    try:
        from config import DB_SIGNALS
        import pandas as pd
        snapshot_df = pd.DataFrame(candidates)
        if 'strategy' not in snapshot_df.columns:
            snapshot_df['strategy'] = strategy
        snapshot_df['snapshot_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn_signals = sqlite3.connect(DB_SIGNALS)
        snapshot_df.to_sql('watchlist_history', conn_signals,
                           if_exists='append', index=False)
        conn_signals.close()
    except Exception as e:
        log.debug(f"Watchlist history log failed: {e}")
    log.info(f"Watchlist updated [{strategy}] — {len(candidates)} stocks")

def get_watchlist(strategy=None):
    """Get current watchlist. Optionally filter to one strategy."""
    conn = sqlite3.connect(DB_WATCHLIST)
    import pandas as pd
    if strategy is None:
        df = pd.read_sql(
            "SELECT * FROM watchlist WHERE status != 'CLOSED' ORDER BY rank",
            conn
        )
    else:
        df = pd.read_sql(
            "SELECT * FROM watchlist WHERE status != 'CLOSED' AND strategy = ? ORDER BY rank",
            conn, params=(strategy,)
        )
    conn.close()
    return df

def get_active_tickers(strategy=None):
    """Get list of active tickers. Optionally filter to one strategy."""
    conn = sqlite3.connect(DB_WATCHLIST)
    c    = conn.cursor()
    if strategy is None:
        c.execute("SELECT ticker FROM watchlist WHERE status != 'CLOSED'")
    else:
        c.execute(
            "SELECT ticker FROM watchlist WHERE status != 'CLOSED' AND strategy = ?",
            (strategy,)
        )
    tickers = [row[0] for row in c.fetchall()]
    conn.close()
    return tickers

def update_status(ticker, status):
    """Update position status for a ticker."""
    conn = sqlite3.connect(DB_WATCHLIST)
    c    = conn.cursor()
    c.execute(
        "UPDATE watchlist SET status=? WHERE ticker=?",
        (status, ticker)
    )
    conn.commit()
    conn.close()

def remove_ticker(ticker):
    """Remove a ticker from watchlist."""
    conn = sqlite3.connect(DB_WATCHLIST)
    c    = conn.cursor()
    c.execute("DELETE FROM watchlist WHERE ticker=?", (ticker,))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    initialize()
    print("watchlist.db ready")