"""
Watchlist CRUD operations — thin data-access layer for the watchlist feature.
All functions use the shared db_session from model.database.

Saving rules (so a save never loses data):
  * add_watchlist() writes the values it is given; anything not given keeps
    the column default ('' / 0.0).
  * update_watchlist() changes ONLY the columns it is given. A column that is
    not passed (or passed as None) is left exactly as it is, so a form save
    can no longer blank stock_name, tags or the target price by accident.
  * Keys that are not columns of the watchlist table are ignored (and
    logged), so a newer view never breaks an older database.
"""
from __future__ import annotations

from datetime import datetime

from model.applog import log
from model.database import db_session

# All metric column names (alphabetical groups for maintainability)
_METRIC_COLS = [
    "pe_ratio", "peg_ratio", "eps", "debt_to_equity", "book_value", "intrinsic_value",
    "roe", "roce", "opm", "free_cash_flow", "inventory_days", "sales_growth", "profit_growth",
    "promoter_holding", "pledged_shares", "fii_dii_holding", "order_book", "dma_50_200", "rsi", "volume",
    "ebitda_margin", "capex", "net_profit_margin", "sharpe_ratio", "qoq_op_profit",
    "beta", "week52_range", "current_ratio", "dividend_yield", "pb_ratio",
    "analyst_target", "market_cap", "action_signal",
    "sector", "industry", "current_value", "stock_name",
]

# Metrics the view can compute but that only some databases have columns for.
# They are stored when model/database.py has added the column, and skipped
# (not computed) otherwise. See watchlist_columns().
OPTIONAL_METRIC_COLS = ["macd", "support_resistance", "revenue_cagr_3y", "profit_cagr_3y"]

_BASE_COLS = ("symbol", "notes", "tags", "target_price")


def watchlist_columns() -> set[str]:
    """Names of the columns the watchlist table has in this database."""
    with db_session() as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(watchlist)").fetchall()}


def _metric_text(value) -> str:
    return "" if value is None else str(value).strip()


def _target_value(value) -> float:
    """Turn '₹1,234.50' / '1234.5' / '' into a float (0.0 = no target)."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    for ch in "₹¥$£€, ":
        text = text.replace(ch, "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        raise ValueError("Target price must be a number, e.g. 1250 or 1250.50.") from None


def get_all_watchlist() -> list[dict]:
    """Return all watchlist rows (every column) ordered by symbol."""
    with db_session() as conn:
        cur = conn.execute("SELECT * FROM watchlist ORDER BY symbol COLLATE NOCASE")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def add_watchlist(symbol: str, notes: str = "", tags: str = "",
                  target_price: float | str = 0.0, **metrics) -> int:
    """Insert a new watchlist entry and return its id.

    Raises ValueError (with a message for the user) on a duplicate symbol or
    an invalid target price.
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("Symbol cannot be empty.")
    target = _target_value(target_price)
    added_on = datetime.now().strftime("%Y-%m-%d")

    with db_session() as conn:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(watchlist)").fetchall()}
        cols = ["symbol", "notes", "tags", "target_price", "added_on"]
        vals: list = [symbol, str(notes or "").strip(), str(tags or "").strip(), target, added_on]
        for key, value in metrics.items():
            if key in cols or value is None:
                continue
            if key not in existing:
                log.debug("Watchlist: no column %r in this database; value not stored", key)
                continue
            cols.append(key)
            vals.append(_metric_text(value))
        try:
            cur = conn.execute(
                f"INSERT INTO watchlist ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                vals,
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError(f"'{symbol}' is already on your watchlist.") from exc
            raise
        return int(cur.lastrowid)


def update_watchlist(row_id: int, symbol: str | None = None, notes: str | None = None,
                     tags: str | None = None, target_price: float | str | None = None,
                     **metrics) -> int:
    """Update ONLY the given columns of watchlist row `row_id`.

    Pass None (or leave out) anything that should stay as it is. Passing ''
    clears a text column on purpose. Returns the number of columns written.
    """
    sets: list[str] = []
    vals: list = []

    if symbol is not None:
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError("Symbol cannot be empty.")
        sets.append("symbol=?")
        vals.append(symbol)
    if notes is not None:
        sets.append("notes=?")
        vals.append(str(notes).strip())
    if tags is not None:
        sets.append("tags=?")
        vals.append(str(tags).strip())
    if target_price is not None:
        sets.append("target_price=?")
        vals.append(_target_value(target_price))

    with db_session() as conn:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(watchlist)").fetchall()}
        for key, value in metrics.items():
            if value is None or key in _BASE_COLS or key in ("id", "added_on"):
                continue
            if key not in existing:
                log.debug("Watchlist: no column %r in this database; value not stored", key)
                continue
            sets.append(f"{key}=?")
            vals.append(_metric_text(value))

        if not sets:
            return 0
        if symbol is not None:
            conflict = conn.execute(
                "SELECT id FROM watchlist WHERE symbol=? AND id!=?", (symbol, row_id)
            ).fetchone()
            if conflict:
                raise ValueError(f"'{symbol}' is already on your watchlist.")
        conn.execute(f"UPDATE watchlist SET {', '.join(sets)} WHERE id=?", (*vals, row_id))
        return len(sets)


def delete_watchlist(row_id: int) -> None:
    """Delete a watchlist entry by id."""
    with db_session() as conn:
        conn.execute("DELETE FROM watchlist WHERE id=?", (row_id,))
