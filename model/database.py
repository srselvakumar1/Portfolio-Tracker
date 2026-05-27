import sqlite3
import os
import threading
from contextlib import contextmanager

import sys
import shutil

# Project-local assets directory
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Prioritize the specified development assets path if it exists
DEV_ASSETS_DIR = "/Users/selvakumar/Downloads/PROJECTS/assets"
if os.path.exists(DEV_ASSETS_DIR):
    LOCAL_ASSETS_DIR = DEV_ASSETS_DIR
else:
    LOCAL_ASSETS_DIR = os.path.join(project_root, "assets")

DB_PATH = None

# 1. Prioritize local assets folder (standard dev/portable mode)
if os.path.exists(LOCAL_ASSETS_DIR):
    DB_PATH = os.path.join(LOCAL_ASSETS_DIR, "portfolio.db")

# 2. Fallback to app-specific behavior if LOCAL_ASSETS_DIR is missing or if frozen
if getattr(sys, 'frozen', False):
    # We are running as a compiled macOS .app
    app_support = os.path.expanduser("~/Library/Application Support/PTracker")
    os.makedirs(app_support, exist_ok=True)
    DB_PATH = os.path.join(app_support, "portfolio.db")
    
    # If the database doesn't exist in App Support yet, copy the pre-packaged one from the bundle
    if not os.path.exists(DB_PATH):
        bundle_db = os.path.join(sys._MEIPASS, "assets", "portfolio.db")
        if os.path.exists(bundle_db):
            shutil.copy2(bundle_db, DB_PATH)
elif not DB_PATH:
    # Running in normal Python development mode: use the project local assets
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(project_root, "assets", "portfolio.db")


# ── Connection pool: reuse connections per-thread instead of open/close on every call ──
_local = threading.local()
_pool_lock = threading.Lock()

def _get_connection() -> sqlite3.Connection:
    """Return a per-thread reusable connection. PRAGMAs are set once per connection."""
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except Exception:
            # Connection is dead, create a new one
            try:
                conn.close()
            except Exception:
                pass
            _local.conn = None

    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=10000")
    conn.execute("PRAGMA temp_store=MEMORY")
    _local.conn = conn
    return conn


def _invalidate_thread_connection() -> None:
    """Close and discard the per-thread cached connection.

    Call this before reading data that was committed by a different thread,
    to ensure a fresh connection is opened that will see the latest WAL state.
    """
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None


@contextmanager
def db_session():
    """Context manager for SQLite connections with WAL mode enabled.

    Uses per-thread connection pooling so PRAGMAs are only set once per thread
    instead of on every call.
    """
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


@contextmanager
def db_transaction():
    """Context manager for explicit transactions — used for batch operations.

    Wraps multiple writes in a single BEGIN/COMMIT for much better throughput.
    """
    conn = _get_connection()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def close_all_connections(optimize: bool = False):
    """Close the current thread's pooled connection.

    Args:
        optimize: If True, runs `PRAGMA optimize` before closing. This can be
            expensive on larger databases, so keep it False for fast app exit.
    """
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        try:
            if optimize:
                conn.execute("PRAGMA optimize")
            conn.close()
        except Exception:
            pass
        _local.conn = None


_SCHEMA_VERSION = 6  # Bump when schema changes


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: list[tuple[str, str]]):
    """Ensure `table` has all columns, adding any missing ones.

    Args:
        conn: SQLite connection
        table: table name
        columns: list of (column_name, sql_type_fragment) e.g. ("foo", "REAL DEFAULT 0.0")
    """
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cur.fetchall()}  # row[1] = name
        for col, col_def in columns:
            if col not in existing:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
    except Exception:
        # Best-effort: schema guard should never crash the app
        pass


def ensure_marketdata_schema():
    """Best-effort schema guard for market/asset tables.

    This is intentionally safe to call from *manual refresh paths*.
    It does not fetch any data; it only ensures columns exist so refreshed
    data can be persisted.
    """
    with db_session() as conn:
        _ensure_columns(conn, "marketdata", [
            ("symbol", "TEXT"),
            ("current_price", "REAL"),
            ("previous_close", "REAL"),
            ("low_52w", "REAL"),
            ("high_52w", "REAL"),
            ("pe_ratio", "REAL"),
            ("eps", "REAL"),
            ("pb_ratio", "REAL"),
            ("roe", "REAL"),
            ("roce", "REAL"),
            ("debt_to_equity", "REAL"),
            ("dividend_yield", "REAL"),
            ("description", "TEXT"),
            ("stock_name", "TEXT"),
            ("sector", "TEXT"),
            ("last_updated", "TEXT"),
        ])
        _ensure_columns(conn, "assets", [
            ("symbol", "TEXT"),
            ("intrinsic_value", "REAL"),
            ("action_signal", "TEXT"),
            ("promoter_holding", "REAL"),
            ("fii_holding", "REAL"),
            ("dii_holding", "REAL"),
            ("last_updated", "TEXT"),
        ])

def initialize_database(reset=False):
    """Initializes the database schema. If reset=True, wipes all tables except brokers."""
    with db_session() as conn:
        cursor = conn.cursor()

        # Check schema version to skip redundant DDL on subsequent launches
        current_version = 0
        try:
            current_version = conn.execute("PRAGMA user_version").fetchone()[0]
        except Exception:
            pass

        if reset:
            cursor.execute("DROP TABLE IF EXISTS trades")
            cursor.execute("DROP TABLE IF EXISTS holdings")
            cursor.execute("DROP TABLE IF EXISTS marketdata")
            cursor.execute("DROP TABLE IF EXISTS assets")
            cursor.execute("DROP TABLE IF EXISTS dashboard_metrics")
            cursor.execute("DROP TABLE IF EXISTS trade_calcs")
            current_version = 0

        # 1. Brokers Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS brokers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        ''')

        # Seed default Brokers
        cursor.execute("SELECT COUNT(*) FROM brokers")
        if cursor.fetchone()[0] == 0:
            default_brokers = ['Selva-Kite', 'Bahee-Kite', 'Mithun-Kite', 'Upstox', 'ICICI', 'Nomura']
            for broker in default_brokers:
                cursor.execute("INSERT INTO brokers (name) VALUES (?)", (broker,))

        # 2. Trades Table (Composite Primary Key)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                broker TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                type TEXT NOT NULL,
                qty REAL NOT NULL,
                price REAL NOT NULL,
                fee REAL DEFAULT 0.0,
                currency TEXT DEFAULT 'INR',
                PRIMARY KEY (broker, trade_id),
                FOREIGN KEY(broker) REFERENCES brokers(name)
            )
        ''')

        # 3. MarketData Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS marketdata (
                symbol TEXT PRIMARY KEY,
                current_price REAL,
                previous_close REAL,
                low_52w REAL,
                high_52w REAL,
                pe_ratio REAL,
                eps REAL,
                pb_ratio REAL,
                roe REAL,
                roce REAL,
                debt_to_equity REAL,
                dividend_yield REAL,
                description TEXT,
                stock_name TEXT,
                sector TEXT,
                last_updated TEXT
            )
        ''')

        # 4. Global Dashboard Metrics Cache
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS dashboard_metrics (
                metric_key TEXT PRIMARY KEY,
                metric_value REAL,
                last_updated TEXT
            )
        ''')

        # 5. Assets Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS assets (
                symbol TEXT PRIMARY KEY,
                intrinsic_value REAL,
                action_signal TEXT,
                promoter_holding REAL,
                fii_holding REAL,
                dii_holding REAL,
                last_updated TEXT
            )
        ''')

        # 6. Holdings Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS holdings (
                broker TEXT NOT NULL,
                symbol TEXT NOT NULL,
                qty REAL NOT NULL,
                avg_price REAL NOT NULL,
                realized_pnl REAL DEFAULT 0.0,
                running_pnl REAL DEFAULT 0.0,
                xirr REAL DEFAULT 0.0,
                cagr REAL DEFAULT 0.0,
                earliest_date TEXT,
                total_fees REAL DEFAULT 0.0,
                currency TEXT DEFAULT 'INR',
                PRIMARY KEY (broker, symbol),
                FOREIGN KEY(broker) REFERENCES brokers(name)
            )
        ''')

        # 7. Precomputed per-trade running stats (materialized)
        # Used by Trade History to avoid recalculating running qty/avg cost/pnl on every filter.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trade_calcs (
                broker TEXT NOT NULL,
                trade_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                run_qty REAL DEFAULT 0.0,
                avg_cost REAL DEFAULT 0.0,
                running_pnl REAL DEFAULT 0.0,
                trade_pnl REAL DEFAULT 0.0,
                calc_ts TEXT,
                PRIMARY KEY (broker, trade_id)
            )
        ''')

        # 8. Watchlist Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS watchlist (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT NOT NULL UNIQUE,
                notes        TEXT DEFAULT '',
                tags         TEXT DEFAULT '',
                target_price REAL DEFAULT 0.0,
                added_on     TEXT DEFAULT '',
                pe_ratio           TEXT DEFAULT '',
                peg_ratio          TEXT DEFAULT '',
                eps                TEXT DEFAULT '',
                debt_to_equity     TEXT DEFAULT '',
                book_value         TEXT DEFAULT '',
                intrinsic_value    TEXT DEFAULT '',
                roe                TEXT DEFAULT '',
                roce               TEXT DEFAULT '',
                opm                TEXT DEFAULT '',
                free_cash_flow     TEXT DEFAULT '',
                inventory_days     TEXT DEFAULT '',
                sales_growth       TEXT DEFAULT '',
                profit_growth      TEXT DEFAULT '',
                promoter_holding   TEXT DEFAULT '',
                pledged_shares     TEXT DEFAULT '',
                fii_dii_holding    TEXT DEFAULT '',
                order_book         TEXT DEFAULT '',
                dma_50_200         TEXT DEFAULT '',
                rsi                TEXT DEFAULT '',
                volume             TEXT DEFAULT '',
                ebitda_margin      TEXT DEFAULT '',
                capex              TEXT DEFAULT '',
                net_profit_margin  TEXT DEFAULT '',
                sharpe_ratio       TEXT DEFAULT '',
                qoq_op_profit      TEXT DEFAULT '',
                beta               TEXT DEFAULT '',
                week52_range       TEXT DEFAULT '',
                current_ratio      TEXT DEFAULT '',
                dividend_yield     TEXT DEFAULT '',
                pb_ratio           TEXT DEFAULT '',
                analyst_target     TEXT DEFAULT '',
                market_cap         TEXT DEFAULT '',
                action_signal      TEXT DEFAULT '',
                sector             TEXT DEFAULT '',
                industry           TEXT DEFAULT '',
                current_value      TEXT DEFAULT '',
                stock_name         TEXT DEFAULT ''
            )
        ''')

        # Migration: Add running_pnl column if it doesn't exist (for existing databases)
        if current_version < 1:
            try:
                cursor.execute("PRAGMA table_info(holdings)")
                columns = [col[1] for col in cursor.fetchall()]
                if 'running_pnl' not in columns:
                    cursor.execute("ALTER TABLE holdings ADD COLUMN running_pnl REAL DEFAULT 0.0")
                    cursor.execute("UPDATE holdings SET running_pnl = realized_pnl")
            except Exception:
                pass

        # Migration: Add stock_name to watchlist
        try:
            cursor.execute("PRAGMA table_info(watchlist)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'stock_name' not in columns:
                cursor.execute("ALTER TABLE watchlist ADD COLUMN stock_name TEXT DEFAULT ''")
        except Exception:
            pass

        # Migration: Add trade_pnl to trade_calcs
        try:
            cursor.execute("PRAGMA table_info(trade_calcs)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'trade_pnl' not in columns:
                cursor.execute("ALTER TABLE trade_calcs ADD COLUMN trade_pnl REAL DEFAULT 0.0")
                cursor.execute("DELETE FROM trade_calcs") # Force rebuild on next startup
        except Exception:
            pass

        # Multi-currency support
        _ensure_columns(conn, "trades", [("currency", "TEXT DEFAULT 'INR'")])
        _ensure_columns(conn, "holdings", [("currency", "TEXT DEFAULT 'INR'")])

        # Only create indexes on first run or after schema change
        if current_version < _SCHEMA_VERSION:
            # Useful composite indexes for trade queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_broker ON trades(broker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_broker_symbol ON trades(broker, symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_broker_date ON trades(broker, date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_date ON trades(symbol, date)")

            # Speed up joins from trades -> trade_calcs and symbol/date lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_calcs_symbol_date ON trade_calcs(symbol, date)")

            # holdings(symbol) index for queries filtering by symbol alone
            # Note: PK (broker, symbol) already covers broker+symbol lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_holdings_symbol ON holdings(symbol)")

            # assets action_signal for filter queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_action_signal ON assets(action_signal)")

            # Drop redundant indexes that duplicate PKs
            for idx_name in [
                'idx_holdings_broker_symbol',   # same as PK (broker, symbol)
                'idx_holdings_symbol_broker',    # reverse of PK, less useful than idx_holdings_symbol
                'idx_holdings_broker',           # prefix of PK
                'idx_marketdata_symbol',         # same as PK
                'idx_assets_symbol',             # same as PK
            ]:
                try:
                    cursor.execute(f"DROP INDEX IF EXISTS {idx_name}")
                except Exception:
                    pass

            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

if __name__ == "__main__":
    # Run with reset=True to fulfill user request
    initialize_database(reset=True)

def ensure_watchlist_schema():
    with db_session() as conn:
        _ensure_columns(conn, "watchlist", [
            ("pe_ratio", "TEXT DEFAULT ''"),
            ("peg_ratio", "TEXT DEFAULT ''"),
            ("eps", "TEXT DEFAULT ''"),
            ("debt_to_equity", "TEXT DEFAULT ''"),
            ("book_value", "TEXT DEFAULT ''"),
            ("intrinsic_value", "TEXT DEFAULT ''"),
            ("roe", "TEXT DEFAULT ''"),
            ("roce", "TEXT DEFAULT ''"),
            ("opm", "TEXT DEFAULT ''"),
            ("free_cash_flow", "TEXT DEFAULT ''"),
            ("inventory_days", "TEXT DEFAULT ''"),
            ("sales_growth", "TEXT DEFAULT ''"),
            ("profit_growth", "TEXT DEFAULT ''"),
            ("promoter_holding", "TEXT DEFAULT ''"),
            ("pledged_shares", "TEXT DEFAULT ''"),
            ("fii_dii_holding", "TEXT DEFAULT ''"),
            ("order_book", "TEXT DEFAULT ''"),
            ("dma_50_200", "TEXT DEFAULT ''"),
            ("rsi", "TEXT DEFAULT ''"),
            ("volume", "TEXT DEFAULT ''"),
            ("ebitda_margin", "TEXT DEFAULT ''"),
            ("capex", "TEXT DEFAULT ''"),
            ("net_profit_margin", "TEXT DEFAULT ''"),
            ("sharpe_ratio", "TEXT DEFAULT ''"),
            ("qoq_op_profit", "TEXT DEFAULT ''"),
            ("beta", "TEXT DEFAULT ''"),
            ("week52_range", "TEXT DEFAULT ''"),
            ("current_ratio", "TEXT DEFAULT ''"),
            ("dividend_yield", "TEXT DEFAULT ''"),
            ("pb_ratio", "TEXT DEFAULT ''"),
            ("analyst_target", "TEXT DEFAULT ''"),
            ("market_cap", "TEXT DEFAULT ''"),
            ("action_signal", "TEXT DEFAULT ''"),
            ("sector", "TEXT DEFAULT ''"),
            ("industry", "TEXT DEFAULT ''"),
            ("current_value", "TEXT DEFAULT ''")
        ])
