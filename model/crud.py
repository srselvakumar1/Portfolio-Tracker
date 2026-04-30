import sqlite3
from model.database import db_session, db_transaction

# Database operations now use the db_session() context manager for clean connections.

def add_trade(broker: str, date: str, symbol: str, trade_type: str, qty: float, price: float, fee: float, trade_id: str):
    sql = 'INSERT INTO trades (trade_id, broker, date, symbol, type, qty, price, fee) VALUES (?, ?, ?, ?, ?, ?, ?, ?)'
    params = (trade_id, broker, date, symbol, trade_type, qty, price, fee)
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)


def add_trades_batch(trades: list):
    """Insert multiple trades in a single transaction for much better throughput.

    Each item in `trades` should be a tuple:
        (trade_id, broker, date, symbol, trade_type, qty, price, fee)
    """
    if not trades:
        return
    sql = 'INSERT INTO trades (trade_id, broker, date, symbol, type, qty, price, fee) VALUES (?, ?, ?, ?, ?, ?, ?, ?)'
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.executemany(sql, trades)

def update_trade(broker: str, trade_id: str, date: str, symbol: str, trade_type: str, qty: float, price: float, fee: float):
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE trades
            SET date = ?, symbol = ?, type = ?, qty = ?, price = ?, fee = ?
            WHERE broker = ? AND trade_id = ?
        ''', (date, symbol, trade_type, qty, price, fee, broker, trade_id))

def update_holding_quantity_and_price(broker: str, symbol: str, new_qty: float, new_price: float):
    """Update holding quantity and average price for a broker/symbol pair."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE holdings
            SET qty = ?, avg_price = ?
            WHERE broker = ? AND symbol = ?
        ''', (new_qty, new_price, broker, symbol))

def update_holding_properties(broker: str, symbol: str, stock_name: str, avg_cost: float, total_fees: float):
    """Update holding properties: stock name (in marketdata), average cost, and total fees."""
    with db_session() as conn:
        cursor = conn.cursor()
        
        # Update holdings: avg_price and total_fees
        cursor.execute('''
            UPDATE holdings
            SET avg_price = ?, total_fees = ?
            WHERE broker = ? AND symbol = ?
        ''', (avg_cost, total_fees, broker, symbol))
        
        # Update or insert stock_name in marketdata
        if stock_name and stock_name.strip():
            cursor.execute('''
                INSERT INTO marketdata (symbol, stock_name)
                VALUES (?, ?)
                ON CONFLICT(symbol) DO UPDATE SET stock_name = excluded.stock_name
            ''', (symbol, stock_name.strip()))

def is_duplicate_trade(broker: str, trade_id: str) -> bool:
    """Returns True if a trade with identical trade_id already exists for this broker."""
    if not trade_id: return False
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM trades WHERE broker=? AND trade_id=?', (broker, trade_id))
        return cursor.fetchone()[0] > 0

def get_existing_trade_ids(broker: str) -> set:
    """Efficiently get all existing trade_ids for a broker in one query (for batch import validation)."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT trade_id FROM trades WHERE broker=?', (broker,))
        return {row[0] for row in cursor.fetchall()}

def delete_trade(broker: str, trade_id: str):
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trades WHERE broker = ? AND trade_id = ?", (broker, trade_id))

def delete_holding_and_trades(broker: str, symbol: str):
    """Deletes a holding and ALL its underlying trades (cascading)."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trades WHERE broker = ? AND symbol = ?", (broker, symbol))
        cursor.execute("DELETE FROM holdings WHERE broker = ? AND symbol = ?", (broker, symbol))
        cursor.execute("DELETE FROM marketdata WHERE symbol = ?", (symbol,))
        cursor.execute("DELETE FROM assets WHERE symbol = ?", (symbol,))

def get_all_brokers() -> list:
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM brokers ORDER BY name")
        return [row[0] for row in cursor.fetchall()]

def add_broker(name: str):
    with db_session() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO brokers (name) VALUES (?)", (name,))
        except sqlite3.IntegrityError:
            pass  # Already exists

def delete_broker(name: str):
    """Delete a broker and all its associated trades and holdings (cascading)."""
    with db_session() as conn:
        cursor = conn.cursor()
        # Get all symbols for this broker to potentially delete unused market data
        cursor.execute("SELECT DISTINCT symbol FROM trades WHERE broker = ?", (name,))
        symbols_for_broker = [row[0] for row in cursor.fetchall()]

        # Delete all trades for this broker
        cursor.execute("DELETE FROM trades WHERE broker = ?", (name,))

        # Delete all holdings for this broker
        cursor.execute("DELETE FROM holdings WHERE broker = ?", (name,))

        # Delete broker record
        cursor.execute("DELETE FROM brokers WHERE name = ?", (name,))

        # Cleanup unused market data in bulk (single query instead of N+1 loop)
        if symbols_for_broker:
            placeholders = ','.join('?' * len(symbols_for_broker))
            cursor.execute(f"""
                DELETE FROM marketdata WHERE symbol IN ({placeholders})
                AND symbol NOT IN (SELECT DISTINCT symbol FROM trades)
            """, symbols_for_broker)
            cursor.execute(f"""
                DELETE FROM assets WHERE symbol IN ({placeholders})
                AND symbol NOT IN (SELECT DISTINCT symbol FROM trades)
            """, symbols_for_broker)

def wipe_all_data():
    """Wipes all trades, holdings, and cached market/asset data. Leaves brokers intact."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trades")
        cursor.execute("DELETE FROM holdings")
        cursor.execute("DELETE FROM marketdata")
        cursor.execute("DELETE FROM assets")

def get_all_table_stats() -> dict:
    """Returns a dictionary of table_name -> row_count."""
    stats = {}
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [row[0] for row in cursor.fetchall()]
        for table in tables:
            # Note: direct string interpolation of table name here is safe because
            # we just queried it from sqlite_master (no user input).
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cursor.fetchone()[0]
    return stats

def get_all_trades_for_export() -> list:
    """Returns all trades formatted for CSV export (matching import format)."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT broker, trade_id, date, symbol, type, qty, price, fee FROM trades ORDER BY date DESC")
        return cursor.fetchall()
