"""
Holdings page: what you own, one row per stock per broker.

The same stock bought through two brokers shows as two rows; the Broker column
tells them apart. Rows come from the shared in-memory cache
(app_state.data_cache). Filtering and formatting run in a background thread and
only the finished rows are put into the table on the Tk thread, so the window
never freezes. The cache is reloaded from the database only when needed: on the
first visit if it is still empty, after an edit or delete made here, when
another page asks for it (view._data_loaded = False) or with ⟳ Refresh.

Row colours mean one thing only, the gain or loss on the shares still held:
light green = in profit, light red = down more than 10 %.
"""

import math
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from ui import dialogs, icons
from ui.icons import decorate_menu
from typing import Optional

import pandas as pd

import model.crud as crud
from model.app_settings import load_settings, save_settings
from model.applog import log
from model.data_cache import DataCache, HoldingsFilters, TradeHistoryFilters
from ui.ui_theme import ModernStyle
from ui.ui_utils import (HeadingTips, ToolTip, clear_skeleton, color_buy_sell, color_gain_loss, color_signals, enhance_table, format_money, run_in_background,
                         show_skeleton, show_toast, treeview_sort_column)
from ui.ui_widgets import (kpi_card, rounded_combobox, EmptyState, RoundedBox, ClearableEntry, ModernButton, ModernCard, Pill,
                           FilterBar, PillGroup, PremiumModal, action_button, add_broker_logos, header_button,
                           secondary_button)
from ui.broker_logos import logo_column, ordered, show_logos
from views.base_view import BaseView


# ── Settings and rules ────────────────────────────────────────────────────────
LOSS_TINT_PCT = -10.0          # rows losing more than this are tinted light red
WEIGHT_PCT_PER_BLOCK = 4.0     # weight bar: each ▰ is 4 % of the total (5 = 20 %)
FILTER_DEBOUNCE_MS = 250       # wait this long after the last filter change
HIDDEN_COLUMNS_KEY = "holdings_hidden_columns"

CURRENCY_SYMBOLS = {"INR": "₹", "JPY": "¥", "USD": "$", "GBP": "£", "CNY": "¥"}

# (column id, heading, sample text used to size the column, anchor)
COLUMNS = [
    ("num",      "#",              "999",              "center"),
    ("symbol",   "Symbol",         "BANDHANBNK",       "w"),
    ("broker",   "Broker",         "Mithun-Kite",      "w"),
    ("name",     "Name",           "Bharat Electronics", "w"),
    ("qty",      "Qty",            "12,345",           "center"),
    ("avg",      "Avg Cost",       "₹12,345.67",       "center"),
    ("price",    "Price",          "₹12,345.67",       "center"),
    ("day",      "Day Chg",        "▼ 12.34%",         "w"),
    ("unreal",   "Unrealised P&L", "▼ ₹123,456",       "w"),
    ("pnl_pct",  "P&L %",          "▼ 12.3%",          "w"),
    ("weight",   "Weight",         "▰▰▰▰▰  12.3%",     "w"),
    ("xirr",     "XIRR",           "-100.00%",         "center"),
    ("cagr",     "CAGR",           "-100.00%",         "center"),
    ("realised", "Realised P&L",   "▼ ₹123,456",       "w"),
    ("total",    "Total P&L",      "▼ ₹123,456",       "w"),
    ("fees",     "Fees",           "₹12,345.67",       "center"),
    ("pe",       "P/E",            "106.68",           "center"),
    ("fair",     "Fair Value",     "₹12,345.67",       "center"),
    ("upside",   "Upside %",       "▼ 12.3%",          "w"),
    ("signal",   "Signal",         "➕ Accumulate",    "center"),
]
COLUMN_IDS = [c[0] for c in COLUMNS]
HEADINGS = {c[0]: c[1] for c in COLUMNS}
ALWAYS_SHOWN = ("num", "symbol")
GAIN_LOSS_COLS = ("day", "unreal", "pnl_pct", "xirr", "cagr", "realised", "total", "upside")   # green / red text
# Hidden until the user turns them on, so the table fits a normal window.
DEFAULT_HIDDEN = ["day", "xirr", "cagr", "realised", "total", "fees", "pe"]

# What each column means, shown in the "Columns" menu.
COLUMN_HELP = {
    "broker":   "Broker (the account holding the shares)",
    "name":     "Name",
    "qty":      "Qty (shares held)",
    "avg":      "Avg Cost (average price paid)",
    "price":    "Price (latest market price)",
    "day":      "Day Chg (price change today)",
    "unreal":   "Unrealised P&L (on shares you still hold)",
    "pnl_pct":  "P&L % (gain or loss on shares you hold)",
    "weight":   "Weight (share of the total; each ▰ = 4%)",
    "xirr":     "XIRR (yearly return from your cash flows)",
    "cagr":     "CAGR (yearly growth; plain return if held under a year)",
    "realised": "Realised P&L (from shares already sold)",
    "total":    "Total P&L (realised + unrealised)",
    "fees":     "Fees (all brokerage and charges)",
    "pe":       "P/E (price ÷ earnings per share)",
    "fair":     "Fair Value (from the shared valuation rules; blank for losses and funds)",
    "upside":   "Upside % (fair value ÷ price − 1; negative when the price is above it)",
    "signal":   "Signal (model: price vs fair value)",
}

# Signal filter: button label → value stored in the database
SIGNAL_FILTERS = {
    "All": "All",
    "Accumulate": "ACCUMULATE",
    "Hold": "HOLD",
    "Reduce": "REDUCE",
    "No signal": "N/A",
}
STATUS_TEXT = {"Active": "active holding", "Closed": "closed position", "All": "holding (active + closed)"}


# ── Small pure helpers (safe to call from worker threads) ─────────────────────
def _num(value) -> float:
    """float(value), with None / NaN / text turned into 0.0."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if f != f else f


def _money0(value: float, currency: str) -> str:
    """Money without paise/sen, e.g. ₹1,234 or -¥56,000."""
    s = format_money(round(value), currency)
    return s[:-3] if s.endswith(".00") else s


def _pnl_text(value: float, currency: str) -> str:
    """▲ ₹1,234 for a gain, ▼ ₹1,234 for a loss (the arrow carries the sign)."""
    if abs(value) < 0.5:
        return _money0(0, currency)
    return f"{'▲' if value > 0 else '▼'} {_money0(abs(value), currency)}"


def _pct_text(pct: float, decimals: int = 2) -> str:
    """▲ 1.23% / ▼ 1.23% / 0.00% (the arrow carries the sign)."""
    if abs(pct) < 0.5 * 10 ** -decimals:
        return f"{0:.{decimals}f}%"
    return f"{'▲' if pct > 0 else '▼'} {abs(pct):.{decimals}f}%"


def _qty_text(qty: float) -> str:
    return f"{qty:,.0f}" if float(qty).is_integer() else f"{qty:,.2f}"


def _weight_text(pct: float) -> str:
    """A 5-block bar (each block = 4 % of the total) followed by the percentage."""
    filled = 0 if pct < 0.5 else min(5, math.ceil(pct / WEIGHT_PCT_PER_BLOCK))
    return "▰" * filled + "▱" * (5 - filled) + f"  {pct:.1f}%"


def _signal_text(signal) -> str:
    s = str(signal if signal is not None else "").strip().upper()
    if s in {"ACCUMULATE", "BUY", "ADD"}:
        return "➕ Accumulate"
    if s in {"SELL"}:
        return "⛔ Sell"          # bad news only: a loss, a big fair-value cut, or quality newly failed
    if s in {"REDUCE", "TRIM"}:
        return "➖ Reduce"
    if s in {"HOLD", "WAIT"}:
        return "⏸ Hold"
    if s in {"", "N/A", "NA", "NAN", "NONE"}:
        return "No signal"
    return str(signal).title()


def _clean_name(value) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def _short(text: str, limit: int = 28) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _cur_symbol(currency: str) -> str:
    return CURRENCY_SYMBOLS.get(str(currency or "INR").upper(), str(currency or "INR").upper() + " ")


def _refresh_shared_cache(cache: DataCache, app_state) -> None:
    """Reload the shared cache (and the broker list) from the database. Worker thread only."""
    try:
        from model.database import _invalidate_thread_connection
        _invalidate_thread_connection()
    except Exception:
        pass
    if app_state is not None and getattr(app_state, "data_cache", None) is cache \
            and hasattr(app_state, "refresh_data_cache"):
        app_state.refresh_data_cache()
    else:
        cache.refresh_from_db()


def _broker_info(app_state) -> tuple[list, dict]:
    """(broker names, {broker: currency}). Worker thread only."""
    try:
        if app_state is not None and hasattr(app_state, "get_brokers_cached"):
            brokers = list(app_state.get_brokers_cached() or [])
            currencies = dict(app_state.get_broker_currencies_cached() or {})
        else:
            brokers = list(crud.get_all_brokers())
            currencies = dict(crud.get_broker_currencies())
        return brokers, currencies
    except Exception:
        log.warning("Holdings: could not read the broker list", exc_info=True)
        return [], {}


def _compute_holdings(cache: DataCache, p: dict) -> dict:
    """Filter the cache and build every table row and total. Worker thread only.

    `p` holds plain filter values read from the Tk variables beforehand.
    """
    from model.engine import get_exchange_rate

    state = p["state"]
    filters = HoldingsFilters(
        broker=p["broker"], currency=p["currency"], symbol_like=p["symbol"].upper(),
        iv_signal=p["signal"], exclude_zero_qty=(state == "Active"), zero_qty_only=(state == "Closed"),
    )
    df, summary = cache.get_holdings_filtered(filters)
    if p["symbol"] or p["signal"] != "All":
        # Weight % is measured against everything you hold, not just the matches
        base = HoldingsFilters(broker=p["broker"], currency=p["currency"],
                               exclude_zero_qty=(state == "Active"), zero_qty_only=(state == "Closed"))
        _, base_summary = cache.get_holdings_filtered(base)
    else:
        base_summary = summary
    total_value = _num(base_summary.get("current"))

    convert = p["currency"] == "All"     # mixed currencies are added up in ₹
    rates: dict = {}

    def rate(cur: str) -> float:
        if not convert:
            return 1.0
        if cur not in rates:
            rates[cur] = _num(get_exchange_rate(cur)) or 1.0
        return rates[cur]

    if df is not None and not df.empty and "symbol" in df.columns:
        df = df.sort_values(["symbol", "broker"], kind="stable")

    rows = []
    unreal_total = real_total = fee_total = 0.0
    for row in (df.itertuples(index=False) if df is not None and not df.empty else ()):
        cur = str(getattr(row, "currency", "") or "INR").strip().upper()
        if cur in ("NAN", "NONE"):
            cur = "INR"
        qty = _num(getattr(row, "qty", 0))
        avg = _num(getattr(row, "avg_price", 0))
        mkt = _num(getattr(row, "market_price", 0))
        prev = _num(getattr(row, "previous_close", 0))
        running = _num(getattr(row, "running_pnl", 0))
        realised = _num(getattr(row, "realized_pnl", 0))
        fees = _num(getattr(row, "total_fees", 0))
        pe = _num(getattr(row, "pe_ratio", 0))
        xirr = _num(getattr(row, "xirr", 0))
        cagr = _num(getattr(row, "cagr", 0))
        value = _num(getattr(row, "current_value", 0))
        symbol = str(getattr(row, "symbol", "") or "")
        broker = str(getattr(row, "broker", "") or "")
        stock_name = _clean_name(getattr(row, "stock_name", ""))
        signal = getattr(row, "action_signal", None)
        # Fair value stored by the last price refresh (model/valuation.py), and the upside
        # to it at this price: the same figures the signal was decided on
        fair = _num(getattr(row, "intrinsic_value", 0))
        upside = (fair / mkt - 1.0) * 100.0 if fair > 0 and mkt > 0 else None

        held = qty > 0
        unreal = (mkt - avg) * qty if held and mkt > 0 else None
        pnl_pct = ((mkt / avg) - 1.0) * 100.0 if held and mkt > 0 and avg > 0 else None
        day_pct = ((mkt - prev) / prev) * 100.0 if mkt > 0 and prev > 0 else None
        weight = (value * rate(cur) / total_value) * 100.0 if held and total_value > 0 else None

        r = rate(cur)
        unreal_total += (unreal or 0.0) * r
        real_total += realised * r
        fee_total += fees * r

        if pnl_pct is not None and pnl_pct > 0:
            tint = "gain"
        elif pnl_pct is not None and pnl_pct < LOSS_TINT_PCT:
            tint = "loss"
        else:
            tint = None

        values = (
            "",                                                   # row number, set on display
            symbol or "—",
            broker or "—",
            _short(stock_name) if stock_name else "—",
            _qty_text(qty),
            format_money(avg, cur) if avg > 0 else "—",
            format_money(mkt, cur) if mkt > 0 else "—",
            _pct_text(day_pct) if day_pct is not None else "—",
            _pnl_text(unreal, cur) if unreal is not None else "—",
            _pct_text(pnl_pct, 1) if pnl_pct is not None else "—",
            _weight_text(weight) if weight is not None else "—",
            f"{xirr:.2f}%" if held and xirr != -100 else "—",
            f"{cagr:.2f}%" if held else "—",
            _pnl_text(realised, cur) if realised else "—",
            _pnl_text(running, cur),
            format_money(fees, cur),
            f"{pe:.2f}" if pe > 0 else "—",
            format_money(fair, cur) if fair > 0 else "—",
            _pct_text(upside, 1) if upside is not None else "—",
            _signal_text(signal),
        )
        meta = {
            "broker": broker, "symbol": symbol, "stock_name": stock_name, "currency": cur,
            "qty": qty, "avg_price": avg, "market_price": mkt, "running_pnl": running,
            "realized_pnl": realised, "total_fees": fees, "tint": tint,
        }
        rows.append((values, meta))

    return {
        "rows": rows,
        "invested": _num(summary.get("invested")),
        "current": _num(summary.get("current")),
        "unrealised": unreal_total,
        "realised": real_total,
        "fees": fee_total,
    }


def _trade_rows(tdf: pd.DataFrame, fallback_currency: str) -> list:
    """Rows for the drill-down trade table. Worker thread only."""
    from datetime import datetime
    rows = []
    if tdf is None or tdf.empty:
        return rows
    for i, r in enumerate(tdf.itertuples(index=False)):
        rtype = str(getattr(r, "type", "")).upper()
        cur = str(getattr(r, "currency", "") or fallback_currency).strip().upper() or fallback_currency
        if rtype in {"BUY", "B"}:
            type_disp, tag = "▲ BUY", "buy"
        elif rtype in {"SELL", "S"}:
            type_disp, tag = "▼ SELL", "sell"
        else:
            type_disp, tag = rtype, ""
        raw_d = str(getattr(r, "date", ""))
        try:
            disp_d = datetime.strptime(raw_d, "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            disp_d = raw_d
        rows.append(((
            str(i + 1),
            disp_d,
            str(getattr(r, "trade_id", "")),
            type_disp,
            _qty_text(_num(getattr(r, "qty", 0))),
            format_money(_num(getattr(r, "price", 0)), cur),
            format_money(_num(getattr(r, "fee", 0)), cur),
            _qty_text(_num(getattr(r, "run_qty", 0))),
            format_money(_num(getattr(r, "avg_cost", 0)), cur),
            _pnl_text(_num(getattr(r, "running_pnl", 0)), cur),
            str(getattr(r, "broker", "")),
        ), tag))
    return rows


def _copy_cell(value) -> str:
    """A table cell as a plain number/text for pasting into a spreadsheet."""
    s = str(value)
    negative = "▼" in s
    for ch in ("₹", "¥", "$", "£", ",", "%", "▲", "▼", "▰", "▱"):
        s = s.replace(ch, "")
    s = s.strip()
    if negative and s and not s.startswith("-"):
        s = "-" + s   # ▼ shows a loss without a minus sign; keep it negative when pasted
    return s


# ── The page ──────────────────────────────────────────────────────────────────
class HoldingsView(BaseView):
    def build(self):
        self._row_meta: dict[str, dict] = {}
        self._own_cache: Optional[DataCache] = None

        # Loading state: one background load at a time, newest filters win
        self._load_gen = 0
        self._load_running = False
        self._want_refresh = False
        self._filter_timer = None
        self._shown_version = None      # cache version the table was built from
        self._shown_params = None       # filters the table was built with
        self._refreshing = False        # ⟳ Refresh (prices) in progress
        self._brokers: list = []
        self._broker_currency: dict = {}

        # Sorting
        self._sort_col: Optional[str] = None
        self._sort_reverse = False

        # Fonts for measuring column / KPI widths
        self._font_table = tkfont.Font(font=ModernStyle.FONT_TABLE)
        self._font_table_bold = tkfont.Font(font=ModernStyle.FONT_TABLE_BOLD)
        self._font_kpi_big = tkfont.Font(font=ModernStyle.FONT_KPI_VALUE)
        self._font_kpi_label = tkfont.Font(font=ModernStyle.FONT_KPI_TITLE)
        self._kpi_big = True

        self.currency_var = tk.StringVar(value="INR")
        self.currency_var.trace_add("write", lambda *_: self._on_currency_changed())

        self._hidden_cols = self._load_hidden_columns()

        self._build_header()
        self._build_filter_panel()
        self._build_stats_card()
        self._build_info_bar()
        self._build_table()

        # main.py calls on_show() right after building; this covers any other path.
        self.after_idle(self._first_load_if_needed)

    # ── Data source ───────────────────────────────────────────────────────
    def _cache(self) -> DataCache:
        """The app's shared cache (a private one only if there is no app_state)."""
        cache = getattr(self.app_state, "data_cache", None) if self.app_state is not None else None
        if cache is not None:
            return cache
        if self._own_cache is None:
            self._own_cache = DataCache()
        return self._own_cache

    # ── Header ────────────────────────────────────────────────────────────
    def _build_header(self):
        def _build_right(parent):
            self._currency_btns = {}
            for code in ("INR", "JPY"):
                btn = ModernButton(
                    parent, text=f"{_cur_symbol(code)} {code}",
                    command=lambda c=code: self.currency_var.set(c),
                    bg=ModernStyle.NEUTRAL_FILL, fg=ModernStyle.TEXT_ON_ACCENT,
                    width=86, height=32, radius=14, font=ModernStyle.FONT_BODY_BOLD,
                )
                btn.pack(side="left", padx=(0, 6))
                ToolTip(btn, f"Show holdings bought in {'Indian rupees' if code == 'INR' else 'Japanese yen'}")
                self._currency_btns[code] = btn
            self._update_currency_buttons()

            self._refresh_btn = header_button(parent, "↻ Refresh", self.refresh, main=True, width=128)
            self._refresh_btn.pack(side="left", padx=(10, 0))
            # Stash original palette so refresh() can restore it without guessing
            self._refresh_btn_orig_bg = self._refresh_btn._bg_normal
            self._refresh_btn_orig_fg = self._refresh_btn._fg
            ToolTip(self._refresh_btn, "Fetch the latest prices from the internet and recalculate every holding")

        self.add_gradient_header(
            self,
            "💹 Holdings",
            "What you own, one row per stock per broker",
            show_divider=True,
            right_widget_func=_build_right,
        )

    def _update_currency_buttons(self):
        sel = self.currency_var.get()
        fills = {"INR": ModernStyle.SUCCESS_FILL, "JPY": ModernStyle.PURPLE_FILL}
        for code, btn in getattr(self, "_currency_btns", {}).items():
            if code == sel:
                btn.set_palette(bg=fills.get(code, ModernStyle.ACCENT_PRIMARY))
                btn.set_text(f"✓ {_cur_symbol(code)} {code}")
            else:
                btn.set_palette(bg=ModernStyle.NEUTRAL_FILL)
                btn.set_text(f"{_cur_symbol(code)} {code}")

    def _on_currency_changed(self):
        self._update_currency_buttons()
        self.on_filter_change()

    # ── Filter bar ────────────────────────────────────────────────────────
    def _build_filter_panel(self):
        """Broker and symbol, signal and status: three rounded tiles, each softly tinted in
        its own colour, with the caption beside the controls (one slim line). The symbol
        search takes the spare width; ↺ Reset shows while a filter is set."""
        self._filter_bar = bar = FilterBar(
            self, is_default=self._filters_are_default, on_reset=self._reset_filters,
            reset_tip="Reset the filters: every broker and signal, no search, active holdings")
        bar.pack(fill="x", padx=20, pady=(4, 2))

        # ── Broker and symbol ─────────────────────────────────────────────
        find = bar.tile("Broker", "landmark", "#2563EB",
                        "Show one broker's account, or All; type part of a symbol to search", weight=1)
        self.broker_var = tk.StringVar(value="All")
        box, self.broker_combo = rounded_combobox(
            find.body, textvariable=self.broker_var, values=["All"],
            state="readonly", width=11, font=ModernStyle.FONT_TABLE,
            box_pady=2, cb_pady=0, ipady=0,
        )
        add_broker_logos(box, self.broker_combo)
        box.pack(side="left", padx=(0, 8))
        self.broker_var.trace_add("write", lambda *_: self._on_broker_selected())
        self._symbol_bar = ClearableEntry(
            find.body, placeholder="Search…", on_change=self._on_symbol_search,
            bg=ModernStyle.ENTRY_BG, fg=ModernStyle.TEXT_ACCENT,
            font=ModernStyle.FONT_TABLE, width=10,
        )
        self._symbol_bar.pack(side="left", fill="x", expand=True)   # the spare width
        self.symbol_entry = self._symbol_bar.entry
        glyph = icons.glyph("search")
        if glyph:   # a proper search icon in front of the text
            tk.Label(self.symbol_entry.master, text=glyph, font=icons.font(14), fg=ModernStyle.TEXT_TERTIARY,
                     bg=ModernStyle.ENTRY_BG).pack(side="left", padx=(8, 0), before=self.symbol_entry)

        # ── Signal: each pill in its own traffic-light colour ─────────────
        signal = bar.tile("Signal", "traffic-cone", "#7C3AED",
                          "Signal: what the advisor suggests. Accumulate (buy more), Hold, Reduce (sell some), "
                          "or No signal (the advisor has no view on this stock)", weight=0, wraps=True)
        self.signal_var = tk.StringVar(value="All")
        self._signal_pills = PillGroup(
            signal.body, list(SIGNAL_FILTERS), self.signal_var, command=self.on_filter_change,
            colours={"All": "#2563EB", "Accumulate": ModernStyle.SUCCESS_FILL, "Hold": ModernStyle.WARNING_FILL,
                     "Reduce": ModernStyle.ERROR_FILL, "No signal": ModernStyle.NEUTRAL_FILL},
        )
        self._signal_pills.pack(side="left")

        # ── Status ────────────────────────────────────────────────────────
        status = bar.tile("Status", "layers", "#0D9488",
                          "Status. Active: shares you still hold. Closed: everything sold. All: both.", weight=0)
        self.holding_state_var = tk.StringVar(value="Active")
        self._status_pills = PillGroup(
            status.body, ["All", "Active", "Closed"], self.holding_state_var, command=self.on_filter_change,
            colours={"All": "#2563EB", "Active": ModernStyle.SUCCESS_FILL, "Closed": ModernStyle.NEUTRAL_FILL},
        )
        self._status_pills.pack(side="left")

    def _filters_are_default(self) -> bool:
        return (self.broker_var.get() in ("", "All") and not (self._symbol_bar.get() or "").strip()
                and self.signal_var.get() == "All" and self.holding_state_var.get() == "Active")

    def _reset_filters(self) -> None:
        """↺ Reset: every broker and signal, no search, active holdings."""
        self.broker_var.set("All")
        self.signal_var.set("All")
        self.holding_state_var.set("Active")
        self._symbol_bar.clear()

    # ── KPI strip ─────────────────────────────────────────────────────────
    def _build_stats_card(self):
        self._stats_frame = stats_frame = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        stats_frame.pack(fill=tk.X, padx=20, pady=2)

        self.stats_labels = {}
        self._kpi_names = []
        stat_configs = [
            ("Holdings",       "count",          ModernStyle.ACCENT_PRIMARY, ModernStyle.TEXT_ACCENT,
             "Number of rows shown (a stock held at two brokers counts twice)"),
            ("Invested",       "invested",       ModernStyle.PURPLE_FILL,    ModernStyle.TEXT_PURPLE,
             "Money put into the shares you still hold (quantity × average cost)"),
            ("Current Value",  "current",        ModernStyle.INFO_FILL,      ModernStyle.INFO,
             "What the shares you hold are worth at the latest prices"),
            ("Realised P&L",   "realized_pnl",   ModernStyle.SUCCESS_FILL,   ModernStyle.SUCCESS,
             "Profit or loss already booked by selling shares"),
            ("Unrealised P&L", "unrealized_pnl", ModernStyle.WARNING_FILL,   ModernStyle.SUCCESS,
             "Profit or loss on the shares you still hold, at the latest prices"),
            ("Total Fees",     "fees",           ModernStyle.ERROR_FILL,     ModernStyle.WARNING,
             "All brokerage and charges paid on these holdings"),
        ]
        icons = {"count": "layers", "invested": "wallet", "current": "briefcase",
                 "realized_pnl": "badge-check", "unrealized_pnl": "trending-up", "fees": "receipt"}
        for col, (label, key, bar, color, tip) in enumerate(stat_configs):
            stats_frame.grid_columnconfigure(col, weight=1, uniform="kpi")
            card, body, name_lbl = kpi_card(stats_frame, label, bar, icons[key])
            card.grid(row=0, column=col, sticky="nsew", padx=3, pady=3)
            ToolTip(name_lbl, tip)
            self._kpi_names.append(name_lbl)
            val = tk.Label(body, text="—", bg=card.tint, fg=color, font=ModernStyle.FONT_KPI_VALUE, anchor="w")
            val.pack(pady=(1, 0), anchor="w")
            self.stats_labels[key] = val
        stats_frame.bind("<Configure>", lambda _e: self._fit_kpi_fonts())

    def _fit_kpi_fonts(self):
        """Use the big KPI fonts when every value fits, smaller ones in a narrow window."""
        width = self._stats_frame.winfo_width()
        if width <= 1:
            return
        room = width / max(1, len(self.stats_labels)) - 36
        need = max(self._font_kpi_big.measure(lbl.cget("text")) for lbl in self.stats_labels.values())
        # a title shares its row with the 26 px icon tile
        need = max(need, max(self._font_kpi_label.measure(lbl.cget("text")) + 32 for lbl in self._kpi_names))
        big = need <= room
        if big != self._kpi_big:
            self._kpi_big = big
            value_font = ModernStyle.FONT_KPI_VALUE if big else ModernStyle.FONT_TITLE
            name_font = ModernStyle.FONT_KPI_TITLE if big else ModernStyle.FONT_SMALL
            for lbl in self.stats_labels.values():
                lbl.configure(font=value_font)
            for lbl in self._kpi_names:
                lbl.configure(font=name_font)

    def _set_label(self, lbl: tk.Label, text: str, fg: Optional[str] = None) -> None:
        """Configure a label only when something changed (each change redraws the window)."""
        kw = {}
        if lbl.cget("text") != text:
            kw["text"] = text
        if fg is not None and str(lbl.cget("fg")) != fg:
            kw["fg"] = fg
        if kw:
            lbl.configure(**kw)

    # ── Scope line, colour legend and Columns button ───────────────────────
    def _build_info_bar(self):
        BG = ModernStyle.BG_PRIMARY
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill=tk.X, padx=23, pady=(2, 0))
        bar.grid_columnconfigure(0, weight=1)    # in a narrow window the scope text gives way first

        self._scope_lbl = tk.Label(bar, text="⏳ Loading holdings…", bg=BG,
                                   fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_SMALL_BOLD, anchor="w")
        self._scope_lbl.grid(row=0, column=0, sticky="ew")
        self._scope_tip = ToolTip(self._scope_lbl, "What the totals above and the table below cover")

        self._columns_btn = action_button(bar, "▤ Columns ▾", self._show_columns_menu_at_button, soft=True,
                                          size="sm", canvas_bg=BG)
        self._columns_btn.grid(row=0, column=2, sticky="e")
        ToolTip(self._columns_btn, "Choose which columns to show. You can also right-click the column headings.")

        legend = tk.Frame(bar, bg=BG)
        legend.grid(row=0, column=1, sticky="e", padx=(12, 12))
        tk.Label(legend, text="Row colour:", bg=BG, fg=ModernStyle.TEXT_SECONDARY,
                 font=ModernStyle.FONT_SMALL).pack(side=tk.LEFT, padx=(0, 6))
        for fill, edge, text in (
            (ModernStyle.TABLE_ROW_GAIN, ModernStyle.SUCCESS, "In profit"),
            (ModernStyle.TABLE_ROW_LOSS, ModernStyle.ERROR, f"Down more than {abs(LOSS_TINT_PCT):.0f}%"),
        ):
            tk.Frame(legend, bg=fill, width=14, height=14, highlightthickness=1,
                     highlightbackground=edge).pack(side=tk.LEFT, padx=(4, 4))
            tk.Label(legend, text=text, bg=BG, fg=ModernStyle.TEXT_SECONDARY,
                     font=ModernStyle.FONT_SMALL).pack(side=tk.LEFT, padx=(0, 8))
        ToolTip(legend, "Colour shows the gain or loss on the shares you still hold (the P&L % column). "
                        "Rows with a smaller loss, and closed positions, have no colour.")

    # ── Table ─────────────────────────────────────────────────────────────
    def _build_table(self):
        table_frame = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=4)
        inner = tk.Frame(table_frame, bg=ModernStyle.BG_PRIMARY)
        inner.pack(fill=tk.BOTH, expand=True)

        style = ttk.Style()
        style.configure("Holdings.Treeview", font=ModernStyle.FONT_TABLE,
                        rowheight=ModernStyle.TABLE_ROW_HEIGHT + 1)   # 34 px at Small text, grows with it
        style.configure("Holdings.Treeview.Heading", font=ModernStyle.FONT_TABLE_BOLD,
                        background=ModernStyle.TABLE_HEADER_BG, foreground=ModernStyle.TABLE_HEADER_FG,
                        relief="flat")
        style.map("Holdings.Treeview.Heading",
                  background=[("active", ModernStyle.TABLE_HEADER_HOVER)],
                  foreground=[("active", ModernStyle.TABLE_HEADER_FG)])

        self.tree = ttk.Treeview(inner, columns=COLUMN_IDS, height=12, show="headings",
                                 style="Holdings.Treeview")
        HeadingTips(self.tree, COLUMN_HELP)
        arrow_w = self._font_table_bold.measure(" ▼")
        for cid, heading, sample, anchor in COLUMNS:
            width = max(self._font_table.measure(sample), self._font_table_bold.measure(heading) + arrow_w) + 16
            self.tree.heading(cid, text=heading, anchor="center", command=lambda c=cid: self._sort_and_remember(c))
            if cid == "name":
                self.tree.column(cid, width=width, minwidth=100, anchor=anchor, stretch=True)
            else:
                self.tree.column(cid, width=width, minwidth=40, anchor=anchor, stretch=False)
        logo_column(self.tree, "num", "broker")   # a "Src" column with each row's broker logo
        self._apply_displaycolumns()
        self.tree.bind("<Configure>", self._fit_name_column, add="+")

        # One tag per row: P&L tint, or a zebra stripe
        self.tree.tag_configure("gain", background=ModernStyle.TABLE_ROW_GAIN, foreground=ModernStyle.TEXT_PRIMARY)
        self.tree.tag_configure("loss", background=ModernStyle.TABLE_ROW_LOSS, foreground=ModernStyle.TEXT_PRIMARY)
        self.tree.tag_configure("odd", background=ModernStyle.BG_SECONDARY)
        self.tree.tag_configure("even", background=ModernStyle.TABLE_ROW_ALT)

        vsb = ttk.Scrollbar(inner, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(inner, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscroll=vsb.set, xscroll=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        inner.grid_rowconfigure(0, weight=1)
        inner.grid_columnconfigure(0, weight=1)

        # Empty / loading message shown over the table
        self._empty = EmptyState(inner)
        self._empty_shown = None
        show_skeleton(self.tree)   # grey bars until the holdings arrive

        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Return>", lambda _e: self._open_drilldown_selected())
        for seq in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            self.tree.bind(seq, self._on_tree_right_click)

    def _show_empty(self, icon: Optional[str], title: str = "", hint: str = "",
                    button: Optional[str] = None, command=None) -> None:
        """Show a friendly message over the table, or hide it when icon is None."""
        state = (icon, title, hint, button)
        if state == self._empty_shown:
            return
        self._empty_shown = state
        if icon is None:
            self._empty.hide()
            return
        self._empty.show(icon, title, hint, button, command)

    def _clear_filters(self) -> None:
        """Every broker, symbol, signal and status (the empty screen's button)."""
        self.broker_var.set("All")
        self.signal_var.set("All")
        self._symbol_bar.clear()

    # ── Column chooser ────────────────────────────────────────────────────
    def _load_hidden_columns(self) -> list:
        try:
            saved = load_settings().get(HIDDEN_COLUMNS_KEY)
        except Exception:
            log.warning("Holdings: could not read the column settings", exc_info=True)
            saved = None
        if not isinstance(saved, list):
            return list(DEFAULT_HIDDEN)
        return [c for c in saved if c in COLUMN_IDS and c not in ALWAYS_SHOWN]

    def _apply_displaycolumns(self) -> None:
        visible = [c for c in COLUMN_IDS if c not in self._hidden_cols]
        self.tree.configure(displaycolumns=visible)
        self._fit_name_column()

    def _fit_name_column(self, _e=None) -> None:
        """Give Name the room the other columns leave, so the last column is never cut off."""
        tv = self.tree
        cols = self._visible_columns()
        w = tv.winfo_width() - 4
        if w < 200 or "name" not in cols:
            return
        others = int(tv.column("#0", "width")) + sum(int(tv.column(c, "width")) for c in cols if c != "name")
        want = max(100, w - others)
        if int(tv.column("name", "width")) != want:
            tv.column("name", width=want)

    def _set_hidden_columns(self, hidden: list) -> None:
        self._hidden_cols = [c for c in COLUMN_IDS if c in hidden and c not in ALWAYS_SHOWN]
        self._apply_displaycolumns()
        try:
            save_settings({HIDDEN_COLUMNS_KEY: list(self._hidden_cols)})
        except Exception:
            log.exception("Holdings: could not save the column choice")
            show_toast(self, "Couldn't save your column choice; it will reset next time.", type="warning")

    def _columns_menu(self) -> tk.Menu:
        menu = tk.Menu(self, tearoff=False)
        shown = len(COLUMN_IDS) - len(self._hidden_cols)
        menu.add_command(label=f"Show columns ({shown} of {len(COLUMN_IDS)} shown)", state="disabled")
        menu.add_separator()
        self._col_vars = {}
        for cid in COLUMN_IDS:
            if cid in ALWAYS_SHOWN:
                continue
            var = tk.BooleanVar(master=self, value=cid not in self._hidden_cols)
            self._col_vars[cid] = var
            menu.add_checkbutton(label=COLUMN_HELP.get(cid, HEADINGS[cid]), variable=var,
                                 onvalue=True, offvalue=False,
                                 command=lambda c=cid: self._toggle_column(c))
        menu.add_separator()
        menu.add_command(label="Show all columns", command=lambda: self._set_hidden_columns([]))
        menu.add_command(label="Back to the standard columns",
                         command=lambda: self._set_hidden_columns(list(DEFAULT_HIDDEN)))
        return menu

    def _toggle_column(self, cid: str) -> None:
        var = self._col_vars.get(cid)
        visible = bool(var.get()) if var is not None else cid in self._hidden_cols
        hidden = [c for c in self._hidden_cols if c != cid]
        if not visible:
            hidden.append(cid)
        self._set_hidden_columns(hidden)

    def _show_columns_menu(self, x: int, y: int) -> None:
        menu = self._columns_menu()
        try:
            decorate_menu(menu)   # a small coloured icon on each item
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _show_columns_menu_at_button(self) -> None:
        btn = self._columns_btn
        self._show_columns_menu(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())

    # ── Sorting ───────────────────────────────────────────────────────────
    def _sort_and_remember(self, col: str):
        """Sort by a column; clicking the same column again reverses the order."""
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = False
        self._apply_sort()

    def _apply_sort(self) -> None:
        if self._sort_col:
            treeview_sort_column(self.tree, self._sort_col, self._sort_reverse)
        for cid in COLUMN_IDS:
            # treeview_sort_column replaces the heading command; put ours back
            text = HEADINGS[cid]
            if cid == self._sort_col:
                text += " ▼" if self._sort_reverse else " ▲"
            self.tree.heading(cid, text=text, command=lambda c=cid: self._sort_and_remember(c))
        self._retag_rows()

    def _retag_rows(self) -> None:
        """Number the rows 1..n in their current order and give each its one tag."""
        for i, iid in enumerate(self.tree.get_children("")):
            meta = self._row_meta.get(iid, {})
            tag = meta.get("tint") or ("even" if i % 2 else "odd")
            self.tree.item(iid, tags=(tag,))
            self.tree.set(iid, "num", str(i + 1))
        show_logos(self.tree)

    # ── Copy ──────────────────────────────────────────────────────────────
    def _visible_columns(self) -> list:
        shown = list(self.tree["displaycolumns"])
        return COLUMN_IDS if shown in (["#all"], []) else shown

    def _copy_selected(self) -> None:
        items = list(self.tree.selection() or [])
        if not items:
            show_toast(self, "Select one or more rows first.", type="info")
            return
        self._copy_items(items)

    def _copy_all(self) -> None:
        items = list(self.tree.get_children() or [])
        if not items:
            show_toast(self, "There are no rows to copy.", type="info")
            return
        self._copy_items(items)

    def _copy_items(self, items: list) -> None:
        cols = self._visible_columns()
        lines = ["\t".join(HEADINGS[c] for c in cols)]
        for iid in items:
            lines.append("\t".join(_copy_cell(self.tree.set(iid, c)) for c in cols))
        try:
            self.clipboard_clear()
            self.clipboard_append("\n".join(lines))
            show_toast(self, f"Copied {len(items)} row{'s' if len(items) != 1 else ''} to the clipboard.")
        except tk.TclError as e:
            log.exception("Holdings: copy failed")
            dialogs.showerror("Holdings", f"Couldn't copy: {e}")

    # ── Right-click / double-click ────────────────────────────────────────
    def _on_tree_right_click(self, event) -> str:
        region = self.tree.identify_region(event.x, event.y)
        if region in ("heading", "separator"):
            self._show_columns_menu(event.x_root, event.y_root)
        else:
            self._show_holdings_context_menu(event)
        return "break"

    def _on_tree_double_click(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) in ("cell", "tree"):
            self._open_drilldown_selected()

    def _show_holdings_context_menu(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        if iid not in self.tree.selection():
            self.tree.selection_set(iid)
        menu = tk.Menu(self.tree, tearoff=False)
        menu.add_command(label="📊  View trades", command=self._open_drilldown_selected)
        menu.add_command(label="➕  Add a trade…", command=lambda: self._open_add_trade_from_holding(iid))
        menu.add_command(label="✏️  Edit holding…", command=lambda: self._edit_holding_properties(iid))
        menu.add_separator()
        menu.add_command(label="📋  Copy selected rows", command=self._copy_selected)
        menu.add_command(label="📝  Copy all rows shown", command=self._copy_all)
        menu.add_command(label="☰  Choose columns…", command=lambda: self._show_columns_menu(event.x_root, event.y_root))
        menu.add_separator()
        menu.add_command(label="🗑  Delete holding…", command=self._delete_selected_holding)
        try:
            decorate_menu(menu)   # a small coloured icon on each item
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ── After a change to the data ────────────────────────────────────────
    def _invalidate_other_views(self) -> None:
        """Ask every other page to reload next time it is shown, and refresh the sidebar."""
        try:
            app = getattr(self.winfo_toplevel(), "_ptracker_app", None)
            if app is None:
                return
            for view in app.view_manager.views.values():
                if view is not self and hasattr(view, "_data_loaded"):
                    view._data_loaded = False
            if hasattr(app, "sidebar") and hasattr(app.sidebar, "refresh_sidebar_data"):
                app.sidebar.refresh_sidebar_data()
        except Exception:
            log.warning("Holdings: could not tell the other pages to reload", exc_info=True)

    def _after_data_change(self, mark: list, then=None) -> None:
        """Called after a pop-up changed trades. `mark` = [cache version before the change].

        The shared pop-ups normally reload the cache themselves; if this one
        did not (version unchanged), reload it here, once, in the background.
        """
        cache = self._cache()

        def _done(_result=None):
            mark[0] = cache.version
            self._invalidate_other_views()
            self.load_data(refresh=False)
            if then:
                then()

        def _failed(exc):
            show_toast(self, f"Couldn't reload the data: {exc}", type="error")
            _done()

        if cache.version != mark[0]:
            _done()
        else:
            app_state = self.app_state
            run_in_background(lambda: _refresh_shared_cache(cache, app_state), on_done=_done,
                              on_error=_failed, widget=self, name="holdings-cache-refresh")

    # ── Add Trade (shared pop-up) ─────────────────────────────────────────
    def _open_add_trade_from_holding(self, iid: str, *, keep_open: bool = False,
                                     symbol: str = "", broker: str = "", stock_name: str = "",
                                     currency: str = "", on_success=None) -> None:
        """Open the shared Add Trade pop-up, filled in from the holding row."""
        meta = self._row_meta.get(iid, {}) if iid else {}
        symbol = symbol or str(meta.get("symbol") or "").strip()
        broker = broker or str(meta.get("broker") or "").strip()
        stock_name = stock_name or str(meta.get("stock_name") or "").strip()
        currency = currency or str(meta.get("currency") or self._broker_currency.get(broker) or
                                   self.currency_var.get() or "INR")
        from views.shared_trade_edit import open_quick_add_trade_modal
        mark = [self._cache().version]
        open_quick_add_trade_modal(
            self, lambda: self._after_data_change(mark, on_success),
            symbol=symbol, broker=broker, stock_name=stock_name, keep_open=keep_open,
            app_state=self.app_state, trade_type="BUY", currency=currency,
        )

    # ── Edit Holding ──────────────────────────────────────────────────────
    def _edit_holding_properties(self, iid: str) -> None:
        """Edit a holding's stock name and total fees. Average cost is shown, not edited:
        it is always worked out from the trades."""
        meta = self._row_meta.get(iid)
        if not meta or not meta.get("symbol") or not meta.get("broker"):
            dialogs.showerror("Edit Holding", "Could not tell which holding this row is.")
            return
        symbol, broker = meta["symbol"], meta["broker"]
        currency = meta.get("currency") or "INR"
        old_name = meta.get("stock_name") or ""
        old_fees = float(meta.get("total_fees") or 0.0)
        avg_cost = float(meta.get("avg_price") or 0.0)
        cur_sym = _cur_symbol(currency)
        BG = ModernStyle.BG_SECONDARY

        scale = ModernStyle.TEXT_SCALE
        win = PremiumModal(self, title="Edit Holding", geometry=f"{round(580 * scale)}x{round(640 * scale)}",
                           icon="square-pen", icon_color="#F97316")
        for text, fill in ((f"📈 {symbol}", ModernStyle.ACCENT_PRIMARY), (f"🏦 {broker}", ModernStyle.PURPLE_FILL),
                           (f"💱 {currency}", ModernStyle.INFO_FILL)):
            Pill(win.chips_row, text=text, fill=fill, fg=ModernStyle.TEXT_ON_ACCENT).pack(side="left", padx=(0, 6),
                                                                                         pady=(0, 6))

        form = win.content_frame
        form.grid_columnconfigure(0, weight=1)

        def _title(row, emoji, text, hint=""):
            lrow = tk.Frame(form, bg=BG)
            lrow.grid(row=row, column=0, sticky="w", pady=(0, 4))
            tk.Label(lrow, text=emoji, bg=BG, fg=ModernStyle.TEXT_ACCENT,
                     font=ModernStyle.FONT_HEADING).pack(side="left", padx=(0, 6))
            tk.Label(lrow, text=text, bg=BG, fg=ModernStyle.TEXT_PRIMARY,
                     font=ModernStyle.FONT_SUBHEADING).pack(side="left")
            if hint:
                tk.Label(lrow, text=hint, bg=BG, fg=ModernStyle.TEXT_TERTIARY,
                         font=ModernStyle.FONT_SMALL).pack(side="left", padx=(6, 0))

        def _entry(row, var):
            # 1-px border frame (turns blue while typing) around an entry-coloured box
            wrap = RoundedBox(form)
            wrap.grid(row=row, column=0, sticky="ew", pady=(0, 4))
            box = tk.Frame(wrap, bg=ModernStyle.ENTRY_BG)
            box.pack(fill="both", expand=True)
            ent = tk.Entry(box, textvariable=var, bg=ModernStyle.ENTRY_BG, fg=ModernStyle.TEXT_PRIMARY,
                           font=ModernStyle.FONT_INPUT, relief=tk.FLAT, bd=0,
                           insertbackground=ModernStyle.TEXT_ACCENT, highlightthickness=0)
            ent.bind("<FocusIn>", lambda _e: wrap.configure(bg=ModernStyle.ACCENT_PRIMARY))
            ent.bind("<FocusOut>", lambda _e: wrap.configure(bg=ModernStyle.BORDER_COLOR))
            ent.pack(fill="both", expand=True, ipady=5, padx=10)
            return ent

        def _note(row, text):
            tk.Label(form, text=text, bg=BG, fg=ModernStyle.TEXT_TERTIARY, font=ModernStyle.FONT_SMALL,
                     wraplength=round(480 * scale), justify="left").grid(row=row, column=0, sticky="w", pady=(0, 10))

        stock_name_var = tk.StringVar(master=win, value=old_name)
        total_fees_var = tk.StringVar(master=win, value=f"{old_fees:.2f}")

        _title(0, "💠", "Stock name", "(optional)")
        name_entry = _entry(1, stock_name_var)
        _note(2, "Shown for this stock at every broker.")

        _title(3, "💎", "Average cost", f"({cur_sym})")
        tk.Label(form, text=format_money(avg_cost, currency), bg=ModernStyle.BG_TERTIARY,
                 fg=ModernStyle.TEXT_PRIMARY, font=ModernStyle.FONT_HEADING, anchor="w",
                 padx=10, pady=6).grid(row=4, column=0, sticky="ew", pady=(0, 4))
        _note(5, "Average cost is worked out from your trades. To change it, "
                 "edit the trades (right-click the holding → View trades).")

        _title(6, "💙", "Total fees", f"({cur_sym})")
        _entry(7, total_fees_var)
        _note(8, "Changing this rewrites the fee on every trade of this holding. You'll be asked first.")

        def _close():
            win.destroy()

        def _write(new_name, new_fees, fees_changed):
            """Save in the background; returns a warning text or None."""
            app_state = self.app_state
            cache = self._cache()

            def work():
                from model.database import db_session
                from model.engine import rebuild_holdings
                if fees_changed:
                    from model.backup import safety_backup
                    try:
                        safety_backup("edit-fees")
                    except Exception as e:
                        raise RuntimeError(f"Couldn't save a backup first, so nothing was changed. ({e})") from e
                # Name goes to marketdata; avg/fees written back unchanged here and
                # recomputed from the trades by rebuild_holdings() below.
                crud.update_holding_properties(broker, symbol, new_name, avg_cost, old_fees)
                warning = None
                if fees_changed:
                    with db_session() as conn:
                        cur = conn.cursor()
                        if old_fees > 0:
                            cur.execute("UPDATE trades SET fee = ROUND(fee * ?, 2) WHERE broker = ? AND symbol = ?",
                                        (new_fees / old_fees, broker, symbol))
                        else:
                            cur.execute("SELECT COUNT(*) FROM trades WHERE broker = ? AND symbol = ?", (broker, symbol))
                            n = cur.fetchone()[0] or 1
                            cur.execute("UPDATE trades SET fee = ? WHERE broker = ? AND symbol = ?",
                                        (round(new_fees / n, 2), broker, symbol))
                    try:
                        rebuild_holdings()
                    except Exception as e:
                        log.exception("Holdings: rebuild after a fee change failed")
                        warning = f"Fees saved, but recalculating the holdings failed ({e}). Use ⟳ Refresh to try again."
                _refresh_shared_cache(cache, app_state)
                return warning

            def done(warning):
                try:
                    win.destroy()
                except tk.TclError:
                    pass
                if warning:
                    show_toast(self, warning, type="warning")
                else:
                    show_toast(self, f"{symbol} ({broker}) updated.")
                self._invalidate_other_views()
                self.load_data(refresh=False)

            def failed(exc):
                try:
                    win.set_status(f"❌ Save failed: {exc}", is_error=True)
                except tk.TclError:
                    show_toast(self, f"Save failed: {exc}", type="error")

            win.set_status("⏳ Saving…")
            run_in_background(work, on_done=done, on_error=failed, widget=self, name="holdings-edit")

        def _confirm_fees(new_name, new_fees, trade_count):
            if trade_count <= 0:
                win.set_status("This holding has no trades, so its fees can't be changed.", is_error=True)
                return
            plural = "s" if trade_count != 1 else ""
            if old_fees > 0:
                how = (f"Each trade's fee is multiplied by {new_fees / old_fees:.3f} "
                       f"so that together they add up to {format_money(new_fees, currency)}.")
            else:
                how = f"Each trade gets the same fee of {format_money(new_fees / trade_count, currency)}."
            ok = dialogs.askyesno(
                "Change total fees?",
                f"Change the total fees of {symbol} ({broker}) from {format_money(old_fees, currency)} "
                f"to {format_money(new_fees, currency)}?\n\n"
                f"This rewrites the fee on all {trade_count} trade{plural} of this holding. {how}\n\n"
                "A backup is saved first, so you can undo this from Settings (Restore…).",
                parent=win,
            )
            if ok:
                _write(new_name, new_fees, True)
            else:
                win.set_status("Fees not changed.")

        def _save():
            new_name = (stock_name_var.get() or "").strip()
            raw = (total_fees_var.get() or "0").replace(",", "").replace(cur_sym.strip(), "").strip()
            try:
                new_fees = float(raw or 0)
            except ValueError:
                win.set_status("Total fees must be a number, e.g. 125.50", is_error=True)
                return
            if new_fees < 0:
                win.set_status("Total fees cannot be negative.", is_error=True)
                return
            fees_changed = abs(new_fees - old_fees) > 0.005
            name_changed = bool(new_name) and new_name != old_name
            if not fees_changed and not name_changed:
                win.destroy()
                return
            if not fees_changed:
                _write(new_name, new_fees, False)
                return

            win.set_status("⏳ Counting this holding's trades…")

            def count():
                from model.database import db_session
                with db_session() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM trades WHERE broker = ? AND symbol = ?", (broker, symbol))
                    return int(cur.fetchone()[0] or 0)

            run_in_background(count, on_done=lambda n: _confirm_fees(new_name, new_fees, n),
                              on_error=lambda e: win.set_status(f"❌ {e}", is_error=True),
                              widget=win, name="holdings-count-trades")

        actions = win.actions_frame
        secondary_button(actions, "✕ Cancel", _close, width=120, canvas_bg=BG).pack(side="right")
        action_button(actions, "✓ Save", _save, width=120, canvas_bg=BG).pack(side="right", padx=(0, 10))
        win.bind("<Escape>", lambda _e: _close())
        win.bind("<Return>", lambda _e: _save())   # Enter saves, as in the other forms
        name_entry.focus_set()

    # ── Drill-down ────────────────────────────────────────────────────────
    def _open_drilldown_selected(self) -> None:
        sel = list(self.tree.selection() or [])
        if not sel:
            dialogs.showinfo("Trades", "Select a holding row first.")
            return
        meta = self._row_meta.get(sel[0])
        if not meta or not meta.get("symbol"):
            dialogs.showerror("Trades", "Could not tell which holding this row is.")
            return
        self._open_drilldown(meta)

    def _open_drilldown(self, meta: dict) -> None:
        symbol = meta["symbol"]
        broker = meta.get("broker") or ""
        stock_name = meta.get("stock_name") or ""
        dd = {"currency": meta.get("currency") or "INR", "reload": lambda refresh=False: None}

        def build_header_actions(parent):
            modal = parent.winfo_toplevel()
            header_button(
                parent, "+ Add Trade", main=True,
                command=lambda: self._open_add_trade_from_holding(
                    "", symbol=symbol, broker=broker, stock_name=stock_name,
                    currency=dd["currency"], on_success=lambda: dd["reload"]()),
            ).pack(side="left", padx=(0, 6))
            # On the gradient banner Close takes the banner's frosted "glass" look
            header_button(parent, "✕ Close", modal.close).pack(side="left")

        top = PremiumModal(self, title="Trade Drilldown", geometry="1100x600", icon="history", icon_color="#14B8A6",
                           right_widget_func=build_header_actions)
        top.header.set_title(f"📊  {stock_name or symbol}")
        top.header.set_subtitle(symbol if stock_name else "Trades")
        top.bind("<Escape>", lambda _e: top.destroy())

        # Summary chips, created once and updated in place
        chips = {}
        for key, bg, fg in (
            ("symbol", ModernStyle.ACCENT_PRIMARY, ModernStyle.TEXT_ON_ACCENT),
            ("broker", ModernStyle.PURPLE_FILL, ModernStyle.TEXT_ON_ACCENT),
            ("qty", ModernStyle.BG_SECONDARY, ModernStyle.TEXT_PRIMARY),
            ("avg", ModernStyle.BG_SECONDARY, ModernStyle.TEXT_PRIMARY),
            ("mkt", ModernStyle.BG_SECONDARY, ModernStyle.TEXT_PRIMARY),
            ("fees", ModernStyle.BG_SECONDARY, ModernStyle.WARNING),
            ("pnl", ModernStyle.BG_SECONDARY, ModernStyle.SUCCESS),
        ):
            lbl = Pill(top.chips_row, fill=bg, fg=fg)
            lbl.pack(side="left", padx=(0, 6))
            chips[key] = lbl

        def set_chips(info: dict) -> None:
            cur = info.get("currency") or dd["currency"]
            dd["currency"] = cur
            pnl = float(info.get("pnl") or 0.0)
            texts = {
                "symbol": f"📈 {symbol}",
                "broker": f"🏦 {broker or 'All brokers'}",
                "qty": f"Qty: {_qty_text(float(info.get('qty') or 0))}",
                "avg": f"Avg: {format_money(info.get('avg') or 0, cur)}",
                "mkt": f"Price: {format_money(info.get('mkt') or 0, cur)}",
                "fees": f"Fees: {format_money(info.get('fees') or 0, cur)}",
                "pnl": f"Total P&L: {_pnl_text(pnl, cur)}",
            }
            for key, text in texts.items():
                self._set_label(chips[key], text)
            self._set_label(chips["pnl"], texts["pnl"], ModernStyle.SUCCESS if pnl >= 0 else ModernStyle.ERROR)

        set_chips({"qty": meta.get("qty"), "avg": meta.get("avg_price"), "mkt": meta.get("market_price"),
                   "fees": meta.get("total_fees"), "pnl": meta.get("running_pnl"), "currency": dd["currency"]})

        # Hide the bottom action bar (buttons are in the header) and give the table the room
        for widget in top.actions_frame.winfo_children():
            widget.destroy()
        top.actions_frame.pack_forget()
        top.body_card.pack_configure(padx=8, pady=(0, 8))
        top.content_frame.pack_configure(padx=8, pady=(12, 8))

        table = tk.Frame(top.content_frame, bg=ModernStyle.BG_SECONDARY)
        table.pack(fill="both", expand=True)
        table.grid_rowconfigure(0, weight=1)
        table.grid_columnconfigure(0, weight=1)

        style = ttk.Style()
        style.configure("HoldingsTrades.Treeview", font=ModernStyle.FONT_TABLE,
                        rowheight=ModernStyle.TABLE_ROW_HEIGHT)
        style.configure("HoldingsTrades.Treeview.Heading", font=ModernStyle.FONT_TABLE_BOLD,
                        background=ModernStyle.TABLE_HEADER_BG, foreground=ModernStyle.TABLE_HEADER_FG)
        style.map("HoldingsTrades.Treeview.Heading",
                  background=[("active", ModernStyle.TABLE_HEADER_HOVER)],
                  foreground=[("active", ModernStyle.TABLE_HEADER_FG)])

        s = _cur_symbol(dd["currency"]).strip()
        cols = (("num", "#", 44, "center"), ("date", "Date", 110, "w"), ("tid", "Trade ID", 100, "w"),
                ("type", "Type", 80, "w"), ("qty", "Qty", 70, "e"), ("price", f"Price {s}", 100, "e"),
                ("fee", f"Fees {s}", 90, "e"), ("runqty", "Running Qty", 105, "e"),
                ("avg", f"Avg Cost {s}", 110, "e"), ("rpnl", f"Running P&L {s}", 130, "w"),
                ("broker", "Broker", 110, "w"))
        trade_tv = ttk.Treeview(table, columns=[c[0] for c in cols], show="headings", height=14,
                                style="HoldingsTrades.Treeview")
        for cid, heading, width, anchor in cols:
            trade_tv.heading(cid, text=heading, anchor="center")
            trade_tv.column(cid, width=width, anchor=anchor, stretch=True)
        logo_column(trade_tv, "num", "broker")
        # One holding is at one broker (named in the header): no Broker column. Its value
        # stays in each row, hidden, for the logo in the "Src" column.
        trade_tv.configure(displaycolumns=[c[0] for c in cols if c[0] != "broker"])
        trade_tv.tag_configure("odd", background=ModernStyle.BG_SECONDARY)
        trade_tv.tag_configure("even", background=ModernStyle.TABLE_ROW_ALT)
        enhance_table(trade_tv, stripes=("odd", "even"))   # highlight under the mouse, click a heading to sort

        vsb = ttk.Scrollbar(table, orient="vertical", command=trade_tv.yview)
        hsb = ttk.Scrollbar(table, orient="horizontal", command=trade_tv.xview)
        trade_tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        trade_tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        status = tk.Label(top.content_frame, text="⏳ Loading trades…", bg=ModernStyle.BG_SECONDARY,
                          fg=ModernStyle.TEXT_TERTIARY, font=ModernStyle.FONT_SMALL, anchor="w")
        status.pack(fill="x", pady=(6, 0))

        cache = self._cache()

        def work():
            tdf, _ = cache.get_tradehistory_filtered(TradeHistoryFilters(
                broker=(broker or "All"), symbol_like=symbol, trade_type="All"))
            if tdf is not None and not tdf.empty:
                tdf = tdf[tdf["symbol"].astype(str).str.upper() == symbol.upper()]   # exact, not "contains"
            hdf, _ = cache.get_holdings_filtered(HoldingsFilters(broker=(broker or "All"), symbol_like=symbol))
            info = None
            if hdf is not None and not hdf.empty:
                hdf = hdf[hdf["symbol"].astype(str).str.upper() == symbol.upper()]
                if not hdf.empty:
                    qty = float(hdf["qty"].sum())
                    cost = float((hdf["qty"] * hdf["avg_price"]).sum())
                    info = {
                        "qty": qty, "avg": cost / qty if qty > 0 else 0.0,
                        "mkt": float(hdf["market_price"].max() or 0.0),
                        "fees": float(hdf["total_fees"].sum()), "pnl": float(hdf["running_pnl"].sum()),
                        "currency": str(hdf["currency"].iloc[0] or "INR").upper(),
                    }
            fallback = (info or {}).get("currency") or dd["currency"]
            return info, _trade_rows(tdf, fallback)

        def apply(result):
            info, rows = result
            if info:
                set_chips(info)
            trade_tv.delete(*trade_tv.get_children())
            if rows:   # trade ids can be long (e.g. PT_1783826722_23): make them fit
                longest = max(self._font_table.measure(str(v[2])) for v, _t in rows)
                trade_tv.column("tid", width=max(100, longest + 20))
            sides = []
            for i, (vals, tag) in enumerate(rows):
                iid = trade_tv.insert("", "end", values=vals, tags=(tag, "even" if i % 2 else "odd"))
                sides.append((iid, {"buy": True, "sell": False}.get(tag)))
            color_buy_sell(trade_tv, sides, ("type", "qty", "price"))   # only these say Buy / Sell
            color_gain_loss(trade_tv, ("rpnl",))
            show_logos(trade_tv)
            n = len(rows)
            status.configure(text=(f"{n} trade{'s' if n != 1 else ''}. Double-click a trade to edit it; "
                                   "right-click for more.") if n else "No trades found for this holding.")

        def reload(refresh: bool = False):
            app_state = self.app_state

            def _work():
                if refresh:
                    _refresh_shared_cache(cache, app_state)
                return work()
            run_in_background(_work, on_done=apply,
                              on_error=lambda e: status.configure(text=f"❌ Couldn't load the trades: {e}",
                                                                  fg=ModernStyle.ERROR),
                              widget=trade_tv, name="holdings-drilldown")

        dd["reload"] = reload
        trade_tv.bind("<Double-1>", lambda e: self._edit_trade_focus_handler(trade_tv, reload))
        for seq in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            trade_tv.bind(seq, lambda e: self._show_drilldown_context_menu(e, trade_tv, reload))
        reload()

    def _edit_trade_focus_handler(self, trade_tv, reload_cb):
        iid = trade_tv.focus()
        if not iid:
            return
        vals = trade_tv.item(iid, "values")
        if not vals or len(vals) < 11:
            return
        broker = str(vals[10]).strip()
        trade_id = str(vals[2]).strip()

        # Read the editable fields from the database (one row by key: instant),
        # never from the formatted table cells.
        from model.database import db_session
        try:
            with db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT symbol, date, type, qty, price, fee, currency FROM trades "
                            "WHERE broker=? AND trade_id=?", (broker, trade_id))
                row = cur.fetchone()
        except Exception as e:
            log.exception("Holdings: could not read trade %s", trade_id)
            dialogs.showerror("Edit Trade", f"Couldn't read this trade: {e}", parent=trade_tv.winfo_toplevel())
            return
        if not row:
            dialogs.showinfo("Edit Trade", "This trade no longer exists. The list will be reloaded.",
                                parent=trade_tv.winfo_toplevel())
            if reload_cb:
                reload_cb()
            return
        symbol, date, ttype = row[0], row[1], row[2]
        qty, price, fee = str(row[3]), str(row[4]), str(row[5])
        currency = str(row[6] or "INR").strip().upper()

        from views.shared_trade_edit import open_edit_trade_modal
        mark = [self._cache().version]
        open_edit_trade_modal(self, lambda: self._after_data_change(mark, reload_cb), broker, trade_id, date,
                              symbol, ttype, qty, price, fee, currency, self.app_state)

    def _show_drilldown_context_menu(self, event, trade_tv, reload_cb) -> str:
        iid = trade_tv.identify_row(event.y)
        if not iid:
            return "break"
        if iid not in trade_tv.selection():
            trade_tv.selection_set(iid)
        trade_tv.focus(iid)
        headings = [trade_tv.heading(c, "text") for c in trade_tv["columns"]]

        def _copy(items):
            lines = ["\t".join(headings)] + ["\t".join(_copy_cell(v) for v in trade_tv.item(it, "values"))
                                             for it in items]
            try:
                self.clipboard_clear()
                self.clipboard_append("\n".join(lines))
                show_toast(trade_tv.winfo_toplevel(), f"Copied {len(items)} row{'s' if len(items) != 1 else ''}.")
            except tk.TclError:
                log.exception("Holdings: copy from drill-down failed")

        menu = tk.Menu(trade_tv, tearoff=False)
        menu.add_command(label="📋  Copy selected rows", command=lambda: _copy(list(trade_tv.selection())))
        menu.add_command(label="📝  Copy all rows", command=lambda: _copy(list(trade_tv.get_children())))
        menu.add_separator()
        menu.add_command(label="✏️  Edit trade…", command=lambda: self._edit_trade_focus_handler(trade_tv, reload_cb))
        menu.add_separator()
        menu.add_command(label="🗑  Delete trade…", command=lambda: self._delete_trade_from_drilldown(trade_tv, iid, reload_cb))
        try:
            decorate_menu(menu)   # a small coloured icon on each item
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    # ── Delete ────────────────────────────────────────────────────────────
    def _delete_selected_holding(self) -> None:
        sel = list(self.tree.selection() or [])
        if not sel:
            dialogs.showinfo("Delete Holding", "Select a holding row first.")
            return
        meta = self._row_meta.get(sel[0], {})
        symbol = str(meta.get("symbol") or "").strip()
        broker = str(meta.get("broker") or "").strip()
        if not symbol or not broker:
            dialogs.showerror("Delete Holding", "Could not tell which holding this row is.")
            return
        if not dialogs.askyesno(
            "Delete Holding",
            f"Delete holding {symbol} ({broker}) and ALL its underlying trades?\n\n"
            "A backup is saved first, so you can undo this from Settings (Restore…).",
        ):
            return

        cache, app_state = self._cache(), self.app_state

        def work():
            from model.backup import safety_backup
            try:
                safety_backup("delete-holding")
            except Exception as e:
                raise RuntimeError(f"Couldn't save a backup first, so nothing was deleted. ({e})") from e
            try:
                crud.delete_holding_and_trades(broker, symbol)
            except Exception as e:
                raise RuntimeError(f"Failed to delete: {e}") from e
            warning = None
            try:
                from model.engine import rebuild_holdings
                rebuild_holdings()
            except Exception as e:
                log.exception("Holdings: rebuild after deleting %s/%s failed", broker, symbol)
                warning = f"Deleted, but recalculating the holdings failed ({e}). Use ⟳ Refresh to try again."
            _refresh_shared_cache(cache, app_state)
            return warning

        def done(warning):
            show_toast(self, warning or f"Deleted {symbol} ({broker}).", type="warning" if warning else "success")
            self._invalidate_other_views()
            self.load_data(refresh=False)

        run_in_background(work, on_done=done,
                          on_error=lambda e: dialogs.showerror("Delete Holding", str(e)),
                          widget=self, name="holdings-delete")

    def _delete_trade_from_drilldown(self, trade_tv, iid, reload_cb):
        selected = list(trade_tv.selection()) or ([iid] if iid else [])
        if not selected:
            return
        trades = []
        for item in selected:
            vals = trade_tv.item(item, "values")
            if vals and len(vals) >= 11:
                trades.append((str(vals[10]).strip(), str(vals[2]).strip()))
        if not trades:
            return
        parent = trade_tv.winfo_toplevel()
        if len(trades) == 1:
            title, msg = "Delete Trade", f"Are you sure you want to delete trade {trades[0][1]}?"
        else:
            title, msg = f"Delete {len(trades)} Trades", f"Are you sure you want to delete {len(trades)} selected trades?"
        msg += "\n\nA backup is saved first, so you can undo this from Settings (Restore…)."
        if not dialogs.askyesno(title, msg, parent=parent):
            return

        cache, app_state = self._cache(), self.app_state

        def work():
            from model.backup import safety_backup
            try:
                safety_backup("delete-trade")
            except Exception as e:
                raise RuntimeError(f"Couldn't save a backup first, so nothing was deleted. ({e})") from e
            for broker, trade_id in trades:
                crud.delete_trade(broker, trade_id)
            warning = None
            try:
                from model.engine import rebuild_holdings
                rebuild_holdings()
            except Exception as e:
                log.exception("Holdings: rebuild after deleting trades failed")
                warning = f"Deleted, but recalculating the holdings failed ({e}). Use ⟳ Refresh to try again."
            _refresh_shared_cache(cache, app_state)
            return warning

        def done(warning):
            n = len(trades)
            show_toast(self, warning or f"Deleted {n} trade{'s' if n != 1 else ''}.",
                       type="warning" if warning else "success")
            self._invalidate_other_views()
            if reload_cb:
                reload_cb()
            self.load_data(refresh=False)

        def failed(exc):
            try:
                dialogs.showerror("Delete Trade", f"Failed to delete: {exc}", parent=parent)
            except tk.TclError:
                dialogs.showerror("Delete Trade", f"Failed to delete: {exc}")

        run_in_background(work, on_done=done, on_error=failed, widget=self, name="holdings-delete-trade")

    # ── Filters ───────────────────────────────────────────────────────────
    def _on_broker_selected(self):
        """Picking a broker switches to that broker's currency."""
        broker = self.broker_var.get()
        if broker != "All":
            currency = str(self._broker_currency.get(broker) or "").upper()
            if currency in ("INR", "JPY") and currency != self.currency_var.get():
                self.currency_var.set(currency)      # its trace schedules the reload
        elif self.currency_var.get() == "JPY":
            self.currency_var.set("INR")
        self.on_filter_change()

    def _load_brokers(self):
        """Kept for older callers: the broker list now arrives with each background load."""
        self.load_data(refresh=False)

    def _on_symbol_search(self, event=None):
        self.on_filter_change()

    def on_filter_change(self):
        """A filter changed: reload once the user pauses for FILTER_DEBOUNCE_MS."""
        self._filter_bar.sync_reset()
        if self._filter_timer is not None:
            try:
                self.after_cancel(self._filter_timer)
            except tk.TclError:
                pass
        self._filter_timer = self.after(FILTER_DEBOUNCE_MS, self._run_filter_change)

    def _run_filter_change(self):
        self._filter_timer = None
        if (not self._load_running and self._read_filters() == self._shown_params
                and self._cache().version == self._shown_version):
            return       # nothing changed (e.g. the search box just lost focus)
        self.load_data(refresh=False)

    def _read_filters(self) -> dict:
        """Plain filter values, read from the Tk variables on the Tk thread."""
        return {
            "broker": self.broker_var.get() or "All",
            "currency": self.currency_var.get() or "INR",
            "symbol": (self._symbol_bar.get() or "").strip(),
            "signal": SIGNAL_FILTERS.get(self.signal_var.get(), "All"),
            "signal_label": self.signal_var.get(),
            "state": self.holding_state_var.get() or "Active",
        }

    # ── Loading ───────────────────────────────────────────────────────────
    def _first_load_if_needed(self):
        if self._shown_version is None and not self._load_running:
            self.load_data()

    def on_show(self):
        """Called by main.py when this page is shown."""
        self._is_active = True
        cache = self._cache()
        if not self._data_loaded or not cache.loaded:
            self.load_data()
        elif cache.version != self._shown_version:
            self.load_data(refresh=False)     # another page reloaded the cache: just re-filter
        # else: the table already shows the latest data

    def load_data(self, refresh: Optional[bool] = None):
        """Rebuild the table for the current filters, in the background.

        refresh=True reloads the shared cache from the database first;
        refresh=False only re-filters what is in memory; None decides: reload
        when the cache is empty, or when another page set _data_loaded = False
        without reloading the cache itself.
        """
        cache = self._cache()
        if refresh is None:
            asked_again = (not self._data_loaded and self._shown_version is not None
                           and cache.version == self._shown_version)
            refresh = (not cache.loaded) or asked_again
        self._data_loaded = True
        self._want_refresh = self._want_refresh or bool(refresh)
        self._load_gen += 1
        if not self._load_running:
            self._start_load()
        # else: the running load sees a newer generation when it finishes and loads again

    def _start_load(self):
        gen = self._load_gen
        refresh, self._want_refresh = self._want_refresh, False
        params = self._read_filters()
        cache, app_state = self._cache(), self.app_state
        self._load_running = True
        if refresh and not self._refreshing:
            self._set_label(self._scope_lbl, "⏳ Loading holdings…")

        def work():
            if refresh or not cache.loaded:
                _refresh_shared_cache(cache, app_state)
            version = cache.version
            result = _compute_holdings(cache, params)
            result["version"] = version
            result["brokers"], result["broker_currency"] = _broker_info(app_state)
            return result

        run_in_background(work, on_done=lambda res: self._on_load_done(gen, params, res),
                          on_error=lambda exc: self._on_load_failed(gen, exc),
                          widget=self, name="holdings-load")

    def _on_load_done(self, gen: int, params: dict, res: dict) -> None:
        self._load_running = False
        if gen != self._load_gen:
            self._start_load()        # filters changed meanwhile: these rows are stale
            return
        self._apply_result(params, res)

    def _on_load_failed(self, gen: int, exc: Exception) -> None:
        self._load_running = False
        if gen != self._load_gen:
            self._start_load()
            return
        self._data_loaded = False      # try again next time the page is shown
        self._set_label(self._scope_lbl, "❌ Couldn't load holdings", ModernStyle.ERROR)
        if not self.tree.get_children():
            clear_skeleton(self.tree)
            self._show_empty("⚠️", "Couldn't load holdings", str(exc))
        show_toast(self, f"Couldn't load holdings: {exc}", type="error")

    def _apply_result(self, params: dict, res: dict) -> None:
        """Put a finished load into the table and the totals (Tk thread)."""
        self._shown_version = res["version"]
        self._shown_params = params
        self._broker_currency = res.get("broker_currency") or {}
        brokers = ordered(["All"] + [b for b in (res.get("brokers") or []) if b])
        if brokers != self._brokers:
            self._brokers = brokers
            self.broker_combo.configure(values=brokers)

        # Rows (keep the selection when the same holdings are still there)
        selected = {(m["broker"], m["symbol"]) for m in (self._row_meta.get(i) for i in self.tree.selection()) if m}
        self.tree.delete(*self.tree.get_children())
        self._row_meta = {}
        reselect = []
        for i, (values, meta) in enumerate(res["rows"]):
            iid = f"h{i}"
            self.tree.insert("", "end", iid=iid, values=values)
            self._row_meta[iid] = meta
            if (meta["broker"], meta["symbol"]) in selected:
                reselect.append(iid)
        color_gain_loss(self.tree, GAIN_LOSS_COLS)
        color_signals(self.tree, "signal")
        self._apply_sort()
        if reselect:
            self.tree.selection_set(reselect)

        self._update_totals(params, res)

        n = len(res["rows"])
        if n:
            self._show_empty(None)
        elif params["broker"] == "All" and not params["symbol"] and params["signal"] == "All":
            # Nothing filtered out: there is simply nothing held in this currency yet
            self._show_empty("💼", f"No {params['currency']} holdings yet",
                             "Record a trade and the shares you hold show up here, priced every day.",
                             "+ Add a trade", lambda: self.go_to("trade_entry"))
        else:
            hint = "Clear the symbol search, or pick “All” for Signal and Status."
            broker_cur = str(self._broker_currency.get(params["broker"]) or "").upper()
            if params["broker"] != "All" and broker_cur and broker_cur != params["currency"]:
                hint = f"{params['broker']} holds {broker_cur} shares: switch the currency at the top right to {broker_cur}."
            self._show_empty("🔍", "No holdings match these filters", hint, "↺ Clear filters", self._clear_filters)

    def _update_totals(self, params: dict, res: dict) -> None:
        cur = params["currency"] if params["currency"] != "All" else "INR"
        n = len(res["rows"])
        self._set_label(self.stats_labels["count"], str(n))
        self._set_label(self.stats_labels["invested"], _money0(res["invested"], cur))
        self._set_label(self.stats_labels["current"], _money0(res["current"], cur))
        for key, value in (("realized_pnl", res["realised"]), ("unrealized_pnl", res["unrealised"])):
            self._set_label(self.stats_labels[key], _pnl_text(value, cur),
                            ModernStyle.SUCCESS if value >= 0 else ModernStyle.ERROR)
        self._set_label(self.stats_labels["fees"], _money0(res["fees"], cur))
        self._fit_kpi_fonts()
        if n:   # in the header: what the tiles don't say, the overall return
            pct = res["unrealised"] / res["invested"] * 100 if res["invested"] else 0.0
            self.set_header_summary(f"{n} {'holding' if n == 1 else 'holdings'}  ·  worth "
                                    f"{_money0(res['current'], cur)}  ·  {_pct_text(pct, 1)} on what you paid")
        else:
            self.set_header_summary("")

        parts = [f"📌 {_cur_symbol(cur).strip()} {cur}",
                 "All brokers" if params["broker"] == "All" else params["broker"]]
        if params["signal"] != "All":
            parts.append(f"Signal: {params['signal_label']}")
        if params["symbol"]:
            parts.append(f"“{params['symbol'].upper()}”")
        noun = STATUS_TEXT.get(params["state"], "holding")
        if n != 1:
            noun = noun.replace("holding", "holdings").replace("position", "positions")
        parts.append(f"{n} {noun}")
        text = "  ·  ".join(parts)
        self._set_label(self._scope_lbl, text, ModernStyle.TEXT_SECONDARY)
        self._scope_tip.text = f"The totals above and the table below cover: {text.replace('📌 ', '')}"

    # ── ⟳ Refresh: latest prices, then recalculate ────────────────────────
    def refresh(self):
        if self._refreshing:
            return
        self._refreshing = True          # also stops a second click from starting another run
        btn = getattr(self, "_refresh_btn", None)
        if btn is not None:
            # Use a solid near-white so the button stays legible anywhere on the
            # indigo-to-pink gradient header. Dark indigo text on near-white gives
            # strong contrast regardless of the gradient position.
            btn.set_palette(bg="#EEF0FF", fg="#312E81",
                            hover_bg="#E0E4FF", pressed_bg="#D0D4F8")
            btn.set_text("⏳ Refreshing…")
        self._set_label(self._scope_lbl, "⏳ Fetching the latest prices… this can take a minute.",
                        ModernStyle.TEXT_ACCENT)
        cache, app_state = self._cache(), self.app_state

        def work():
            from model.database import db_session
            from model.engine import fetch_and_update_market_data, rebuild_holdings
            price_error = None
            symbols = []
            try:
                with db_session() as conn:
                    c = conn.cursor()
                    c.execute("SELECT DISTINCT symbol FROM trades UNION SELECT DISTINCT symbol FROM watchlist")
                    symbols = [r[0] for r in c.fetchall() if r[0]]
                if symbols:
                    fetch_and_update_market_data(list(symbols))
            except Exception as e:
                log.exception("Holdings: fetching prices failed")
                price_error = str(e)
            rebuild_holdings()
            _refresh_shared_cache(cache, app_state)
            return len(symbols), price_error

        def finish():
            self._refreshing = False
            if btn is not None:
                orig_bg = getattr(self, "_refresh_btn_orig_bg", ModernStyle.HEADER_FG)
                orig_fg = getattr(self, "_refresh_btn_orig_fg", None)
                btn.set_palette(bg=orig_bg, fg=orig_fg)
                btn.set_text("↻ Refresh")

        def done(result):
            count, price_error = result
            finish()
            if price_error:
                show_toast(self, f"Couldn't fetch new prices ({price_error}). Holdings were recalculated "
                                 "with the last saved prices.", type="warning")
            else:
                show_toast(self, f"Prices updated for {count} stocks and holdings recalculated.")
            self._invalidate_other_views()
            self.load_data(refresh=False)

        def failed(exc):
            finish()
            self._set_label(self._scope_lbl, "❌ Refresh failed", ModernStyle.ERROR)
            show_toast(self, f"Refresh failed: {exc}", type="error")
            self.load_data(refresh=False)

        run_in_background(work, on_done=done, on_error=failed, widget=self, name="holdings-refresh")
