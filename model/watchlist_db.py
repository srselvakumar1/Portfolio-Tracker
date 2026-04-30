"""
Watchlist CRUD operations — thin data-access layer for the watchlist feature.
All functions use the shared db_session from model.database.
"""
from __future__ import annotations

from datetime import datetime
from model.database import db_session

# All metric column names (alphabetical groups for maintainability)
_METRIC_COLS = [
    "pe_ratio", "peg_ratio", "eps", "debt_to_equity", "book_value", "intrinsic_value",
    "roe", "roce", "opm", "free_cash_flow", "inventory_days", "sales_growth", "profit_growth",
    "promoter_holding", "pledged_shares", "fii_dii_holding", "order_book", "dma_50_200", "rsi", "volume",
    "ebitda_margin", "capex", "net_profit_margin", "sharpe_ratio", "qoq_op_profit",
    "beta", "week52_range", "current_ratio", "dividend_yield", "pb_ratio",
    "analyst_target", "market_cap", "action_signal",
    "sector", "industry", "current_value", "stock_name"
]

_SELECT_COLS = (
    "id, symbol, notes, tags, target_price, added_on, "
    + ", ".join(_METRIC_COLS)
)

_INSERT_COLS = "symbol, notes, tags, target_price, added_on, " + ", ".join(_METRIC_COLS)
_INSERT_PLACEHOLDERS = "?, ?, ?, ?, ?" + ", ?" * len(_METRIC_COLS)

_UPDATE_SET = ", ".join(f"{c}=?" for c in _METRIC_COLS)


def get_all_watchlist() -> list[dict]:
    """Return all watchlist rows ordered by symbol."""
    with db_session() as conn:
        cur = conn.execute(
            f"SELECT {_SELECT_COLS} FROM watchlist ORDER BY symbol COLLATE NOCASE"
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def add_watchlist(symbol: str, notes: str = "", tags: str = "",
                  target_price: float = 0.0, **metrics) -> None:
    """Insert a new watchlist entry. Raises ValueError on duplicate symbol."""
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("Symbol cannot be empty.")
    added_on = datetime.now().strftime("%Y-%m-%d")

    m = lambda k: str(metrics.get(k, "")).strip()

    with db_session() as conn:
        try:
            conn.execute(
                f"INSERT INTO watchlist ({_INSERT_COLS}) VALUES ({_INSERT_PLACEHOLDERS})",
                (
                    symbol, notes.strip(), tags.strip(), float(target_price), added_on,
                    *[m(c) for c in _METRIC_COLS]
                ),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError(f"'{symbol}' is already on your watchlist.") from exc
            raise


def update_watchlist(row_id: int, symbol: str, notes: str = "",
                     tags: str = "", target_price: float = 0.0, **metrics) -> None:
    """Update an existing watchlist entry by id."""
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("Symbol cannot be empty.")

    m = lambda k: str(metrics.get(k, "")).strip()

    with db_session() as conn:
        conflict = conn.execute(
            "SELECT id FROM watchlist WHERE symbol=? AND id!=?", (symbol, row_id)
        ).fetchone()
        if conflict:
            raise ValueError(f"'{symbol}' is already on your watchlist.")
        conn.execute(
            f"UPDATE watchlist SET symbol=?, notes=?, tags=?, target_price=?, {_UPDATE_SET} WHERE id=?",
            (
                symbol, notes.strip(), tags.strip(), float(target_price),
                *[m(c) for c in _METRIC_COLS],
                row_id
            ),
        )


def delete_watchlist(row_id: int) -> None:
    """Delete a watchlist entry by id."""
    with db_session() as conn:
        conn.execute("DELETE FROM watchlist WHERE id=?", (row_id,))
