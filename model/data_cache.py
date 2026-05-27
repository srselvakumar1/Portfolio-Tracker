import threading
from dataclasses import dataclass

import pandas as pd

from model.database import db_session


@dataclass(frozen=True)
class HoldingsFilters:
    broker: str = "All"
    symbol_like: str = ""
    iv_signal: str = "All"
    exclude_zero_qty: bool = False
    zero_qty_only: bool = False
    start_date: str | None = None  # YYYY-MM-DD (optional date filter)
    end_date: str | None = None    # YYYY-MM-DD (optional date filter)


@dataclass(frozen=True)
class TradeHistoryFilters:
    broker: str = "All"
    symbol_like: str = ""
    trade_type: str = "All"
    start_date: str | None = None  # YYYY-MM-DD
    end_date: str | None = None    # YYYY-MM-DD


class DataCache:
    """Small-app in-memory cache for fast view switching.

    This cache is populated from SQLite once (or on invalidation) and then views
    filter/summarize in-memory instead of querying SQLite on every navigation.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._version = 0
        self._loaded = False

        self._holdings_df = pd.DataFrame()
        self._trades_df = pd.DataFrame()

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    @property
    def loaded(self) -> bool:
        with self._lock:
            return self._loaded

    def refresh_from_db(self) -> None:
        """Reload all cached datasets from SQLite."""
        with db_session() as conn:
            holdings_query = """
                SELECT
                    h.broker,
                    h.symbol,
                    h.currency,
                    h.qty,
                    h.avg_price,
                    h.realized_pnl,
                    h.running_pnl,
                    h.xirr,
                    h.cagr,
                    h.earliest_date,
                    h.total_fees,
                    a.action_signal,
                    COALESCE(m.current_price, 0) as market_price,
                    COALESCE(m.previous_close, 0) as previous_close,
                    m.pe_ratio,
                    m.stock_name,
                    (h.qty * CASE WHEN COALESCE(NULLIF(m.current_price, 0), 0) > 0 THEN m.current_price ELSE h.avg_price END) AS current_value
                FROM holdings h
                LEFT JOIN assets a ON h.symbol = a.symbol
                LEFT JOIN marketdata m ON h.symbol = m.symbol
            """
            holdings_df = pd.read_sql_query(holdings_query, conn)

            trades_query = """
                SELECT
                    t.trade_id, t.date, t.symbol, t.type, t.qty, t.price, t.fee, t.broker, t.currency,
                    COALESCE(c.run_qty, 0.0) AS run_qty,
                    COALESCE(c.avg_cost, 0.0) AS avg_cost,
                    COALESCE(c.running_pnl, 0.0) AS running_pnl,
                    COALESCE(c.trade_pnl, 0.0) AS trade_pnl
                FROM trades t
                LEFT JOIN trade_calcs c
                    ON c.broker = t.broker AND c.trade_id = t.trade_id
                ORDER BY t.date ASC, t.type ASC, t.trade_id ASC
            """
            trades_df = pd.read_sql_query(trades_query, conn)

        # Normalize types (cheap) so downstream filtering/summaries are stable.
        try:
            if not holdings_df.empty:
                holdings_df["qty"] = holdings_df["qty"].astype(float)
                holdings_df["avg_price"] = holdings_df["avg_price"].astype(float)
                holdings_df["realized_pnl"] = holdings_df["realized_pnl"].astype(float)
                holdings_df["running_pnl"] = holdings_df["running_pnl"].astype(float)
                holdings_df["xirr"] = holdings_df["xirr"].astype(float)
                holdings_df["cagr"] = holdings_df["cagr"].astype(float)
                holdings_df["total_fees"] = holdings_df["total_fees"].astype(float)
                holdings_df["market_price"] = holdings_df["market_price"].astype(float)
                holdings_df["previous_close"] = holdings_df["previous_close"].astype(float)
                holdings_df["pe_ratio"] = holdings_df["pe_ratio"].astype(float)
                holdings_df["current_value"] = holdings_df["current_value"].astype(float)
        except Exception:
            pass

        try:
            if not trades_df.empty:
                trades_df["qty"] = trades_df["qty"].astype(float)
                trades_df["price"] = trades_df["price"].astype(float)
                trades_df["fee"] = trades_df["fee"].astype(float)
                trades_df["type"] = trades_df["type"].astype(str).str.upper()
                trades_df["run_qty"] = trades_df["run_qty"].astype(float)
                trades_df["avg_cost"] = trades_df["avg_cost"].astype(float)
                trades_df["running_pnl"] = trades_df["running_pnl"].astype(float)
                trades_df["trade_pnl"] = trades_df["trade_pnl"].astype(float)
        except Exception:
            pass

        with self._lock:
            self._holdings_df = holdings_df
            self._trades_df = trades_df
            self._version += 1
            self._loaded = True

    def get_holdings_filtered(self, filters: HoldingsFilters) -> tuple[pd.DataFrame, dict]:
        """Return (filtered_df, summary_dict)."""
        with self._lock:
            df0 = self._holdings_df

        if df0 is None or df0.empty:
            return pd.DataFrame(), {"cnt": 0, "invested": 0.0, "pnl": 0.0, "current": 0.0}

        df = df0

        if filters.broker and filters.broker != "All":
            df = df[df["broker"] == filters.broker]

        if filters.symbol_like:
            sym = filters.symbol_like.strip().upper()
            if sym:
                df = df[df["symbol"].astype(str).str.upper().str.contains(sym, na=False)]

        if filters.iv_signal and filters.iv_signal != "All":
            if filters.iv_signal == "N/A":
                df = df[(df["action_signal"].isna()) | (df["action_signal"].astype(str) == "N/A")]
            else:
                df = df[df["action_signal"].astype(str) == filters.iv_signal]

        if filters.zero_qty_only:
            df = df[df["qty"] <= 0]
        elif filters.exclude_zero_qty:
            df = df[df["qty"] > 0]

        # Summary in-memory
        invested = float((df["qty"] * df["avg_price"]).sum()) if not df.empty else 0.0
        pnl = float(df["running_pnl"].sum()) if not df.empty else 0.0
        current = float(df["current_value"].sum()) if not df.empty else 0.0
        summary = {"cnt": int(len(df)), "invested": invested, "pnl": pnl, "current": current}
        return df.reset_index(drop=True), summary

    def get_tradehistory_filtered(self, filters: TradeHistoryFilters) -> tuple[pd.DataFrame, dict]:
        """Return (filtered_df, summary_dict)."""
        with self._lock:
            df0 = self._trades_df

        if df0 is None or df0.empty:
            return pd.DataFrame(), {
                "qty_buy": 0.0,
                "qty_sell": 0.0,
                "fee_buy": 0.0,
                "fee_sell": 0.0,
                "total_pnl": 0.0,
            }

        df = df0

        if filters.broker and filters.broker != "All":
            df = df[df["broker"] == filters.broker]

        if filters.symbol_like:
            sym = filters.symbol_like.strip().upper()
            if sym:
                df = df[df["symbol"].astype(str).str.upper().str.contains(sym, na=False)]

        if filters.trade_type and filters.trade_type != "All":
            df = df[df["type"].astype(str).str.upper() == filters.trade_type]

        if filters.start_date:
            df = df[df["date"].astype(str) >= filters.start_date]

        if filters.end_date:
            df = df[df["date"].astype(str) <= filters.end_date]

        # Summary matches old SQL semantics:
        # - qty/fee by BUY/SELL
        # - total_pnl = sum of last running_pnl per symbol (by date, trade_id)
        if df.empty:
            return df.reset_index(drop=True), {
                "qty_buy": 0.0,
                "qty_sell": 0.0,
                "fee_buy": 0.0,
                "fee_sell": 0.0,
                "total_pnl": 0.0,
            }

        type_u = df["type"].astype(str).str.upper()
        qty_buy = float(df.loc[type_u == "BUY", "qty"].sum())
        qty_sell = float(df.loc[type_u == "SELL", "qty"].sum())
        fee_buy = float(df.loc[type_u == "BUY", "fee"].sum())
        fee_sell = float(df.loc[type_u == "SELL", "fee"].sum())

        # Total P&L of the filtered view (matches the cumulative 'Running PnL' column in the table)
        total_pnl = float(df["trade_pnl"].sum()) if not df.empty else 0.0

        return df.reset_index(drop=True), {
            "qty_buy": qty_buy,
            "qty_sell": qty_sell,
            "fee_buy": fee_buy,
            "fee_sell": fee_sell,
            "total_pnl": total_pnl,
        }

    def get_holdings_symbols(self) -> list[str]:
        with self._lock:
            df0 = self._holdings_df
        if df0 is None or df0.empty:
            return []
        try:
            return sorted({str(s) for s in df0["symbol"].dropna().tolist()})
        except Exception:
            return []
