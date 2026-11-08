"""
Trade History view for TKinter-based PTracker application.

Loading never blocks the window: the filters are read on the Tk thread, changes are
debounced (a burst of changes causes one load), the work runs in a background thread,
and a generation number makes sure an older, slower result never replaces a newer one.
Changing a filter only filters the in-memory data cache; the database is read again
only after trades change, when another page says the data is stale, or on ⟳ Refresh.
"""

import tkinter as tk
from tkinter import ttk
from ui import dialogs
from ui import icons as lucide   # (build() has its own `icons` table)
from ui.icons import decorate_menu
import calendar
from datetime import datetime, timedelta

from model.applog import log
from model.data_cache import TradeHistoryFilters
from views.base_view import BaseView, _create_date_input
from views.shared_trade_edit import (
    TradeForm, check_trade_fields, confirm_unusual, currency_choices, currency_symbol, currency_toggle, dialog_button,
    dialog_footer, dialog_header, follow_broker_currency, friendly_error, known_brokers, make_dialog,
    number_text, refresh_after_change, save_trade_edit, show_stale_warning,
)
from ui.ui_theme import ModernStyle
from ui.ui_widgets import (kpi_card, rounded_combobox, EmptyState, FilterBar, PillGroup, RoundedBox, ModernButton,
                           ModernCard, action_button, add_broker_logos, header_button)
from ui.broker_logos import ordered
from ui.ui_utils import (HeadingTips, ToolTip, add_treeview_copy_menu, clear_skeleton, format_money,
                         color_buy_sell, color_gain_loss, run_in_background, show_skeleton, show_toast, treeview_sort_column)

# Table columns: (id, width). Money headings get the currency symbol added (see
# _update_column_headings); "native" money is in each trade's own currency, the P&L
# columns are converted to INR when all currencies are shown together.
COLUMNS = (
    ("#", 44), ("Date", 104), ("Symbol", 96), ("Type", 62), ("Qty", 60), ("Price", 92),
    ("Trade Value", 110), ("Running Qty", 86), ("AvgCost", 92), ("Trade P&L", 118),
    ("Running PnL", 124), ("Fees", 80), ("Cum. Fees", 92),
)
NATIVE_MONEY = ("Price", "Trade Value", "AvgCost", "Fees", "Cum. Fees")
PNL_MONEY = ("Trade P&L", "Running PnL")
TYPE_INDEX = [c for c, _w in COLUMNS].index("Type")
SORTABLE = ("Symbol", "Date", "Type")
DATE_RANGES = ("1M", "3M", "YTD", "1Y", "All")   # the quick date pills

# Fill of the selected currency pill (ModernStyle attribute names)
_PILL_FILLS = {"All": "ACCENT_PRIMARY", "INR": "SUCCESS_FILL", "JPY": "PURPLE_FILL", "USD": "INFO_FILL"}


def _whole_money(value: float, currency: str) -> str:
    """Money rounded to whole units for the summary cards: ₹84,969."""
    text = format_money(round(value), currency)
    return text[:-3] if text.endswith(".00") else text


def _count(value: float) -> str:
    """A count or quantity with thousands commas: 499,947 (fractions kept: 1,234.5623)."""
    value = round(value, 4) + 0.0   # + 0.0 turns -0.0 into 0.0
    return f"{value:,.0f}" if value == int(value) else f"{value:,.4f}".rstrip("0").rstrip(".")


def _arrow_money(value: float, currency: str) -> str:
    return f"{'▲' if value >= 0 else '▼'} {format_money(abs(value), currency)}"


def build_rows(df, *, c_filter: str, calc_unrealized: bool, market_prices: dict, rates: dict) -> list:
    """Turn the filtered trades into (iid, values, tags) rows. No Tk: runs in the worker."""
    rows = []
    current_date = None
    buy_count = sell_count = 0
    running_tpnl = 0.0
    cum_fees: dict = {}
    for idx, row in enumerate(df.itertuples(index=False)):
        row_date = str(getattr(row, "date", ""))
        try:
            disp_date = datetime.strptime(row_date, "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            disp_date = row_date
        if row_date != current_date:
            current_date = row_date
            buy_count = sell_count = 0

        row_type = str(getattr(row, "type", "")).upper()
        qty = float(getattr(row, "qty", 0.0) or 0.0)
        price = float(getattr(row, "price", 0.0) or 0.0)
        fee = float(getattr(row, "fee", 0.0) or 0.0)
        run_qty = float(getattr(row, "run_qty", 0.0) or 0.0)
        avg_cost = float(getattr(row, "avg_cost", 0.0) or 0.0)
        trade_pnl = float(getattr(row, "trade_pnl", 0.0) or 0.0)
        broker = str(getattr(row, "broker", "") or "").strip()
        symbol_val = str(getattr(row, "symbol", "") or "").strip()
        currency = str(getattr(row, "currency", "") or "INR").strip().upper()

        fee_key = (broker, symbol_val)
        cum_fees[fee_key] = cum_fees.get(fee_key, 0.0) + fee

        # Mixed currencies: show P&L in INR so the running total adds up
        rate = rates.get(currency, 1.0) if c_filter == "All" else 1.0
        pnl_currency = "INR" if c_filter == "All" else currency
        tp_val = trade_pnl * rate
        running_tpnl += tp_val

        current_price = market_prices.get(symbol_val.upper(), 0.0)
        if row_type == "SELL":
            pnl_disp = _arrow_money(running_tpnl, pnl_currency)
            tp_disp = _arrow_money(tp_val, pnl_currency) if tp_val != 0.0 else "—"
        elif row_type == "BUY" and calc_unrealized and current_price > 0.0:
            lot_pnl = (current_price - price) * qty * rate
            run_pnl = (current_price - avg_cost) * run_qty * rate
            tp_disp = _arrow_money(lot_pnl, pnl_currency) + " (U)"
            pnl_disp = _arrow_money(run_pnl, pnl_currency) + " (U)"
        else:
            pnl_disp = tp_disp = "—"

        if row_type == "BUY":
            buy_count += 1
            type_disp, stripe = "Buy", ("buy_odd" if buy_count % 2 else "buy_even")
        elif row_type == "SELL":
            sell_count += 1
            type_disp, stripe = "Sell", ("sell_odd" if sell_count % 2 else "sell_even")
        else:
            type_disp, stripe = row_type, "buy_odd"

        trade_id = str(getattr(row, "trade_id", "") or "").strip()
        values = (
            str(idx + 1), disp_date, symbol_val, type_disp, f"{qty:g}",
            format_money(price, currency), format_money(qty * price, currency), f"{run_qty:g}",
            format_money(avg_cost, currency), tp_disp, pnl_disp,
            format_money(fee, currency), format_money(cum_fees[fee_key], currency),
        )
        rows.append((TradeHistoryView._make_trade_iid(broker, trade_id), values, (stripe,)))
    return rows



# What the columns mean (shown when the pointer rests on a heading)
_COLUMN_TIPS = {
    "Trade Value": "Qty × price for this trade",
    "Running Qty": "Shares of this stock at this broker after this trade",
    "AvgCost": "Average price paid per share after this trade",
    "Trade P&L": "Profit (▲) or loss (▼) made by this sell",
    "Running PnL": "Profit or loss so far on this stock at this broker",
    "Fees": "Brokerage and charges on this trade",
    "Cum. Fees": "Fees so far on this stock at this broker",
}

# What the summary pills mean (shown on hover)
_STAT_TIPS = {
    "live_qty": "Shares bought minus shares sold, counting only the trades shown",
    "pnl": "Profit or loss from the trades shown",
    "fees": "Brokerage and charges on the trades shown",
}

class TradeHistoryView(BaseView):
    """View all trades in history."""

    # ── Header (currency pills + refresh) ───────────────────────────────────────
    def _build_right(self, parent):
        # The header paints its children in the gradient colour; this frame keeps its own colours.
        self._curr_frame = tk.Frame(parent, bg=ModernStyle.BG_SECONDARY)
        self._curr_frame.pack(side="left", padx=(0, 12))
        self._curr_buttons = {}
        self._set_currency_options(self._initial_currencies())

        header_button(parent, "↻ Refresh", self.refresh, main=True, width=128).pack(side="right")
        header_button(parent, "Delete", self._delete_selected, icon="trash-2").pack(side="right", padx=(0, 8))
        header_button(parent, "+ Add trade", self._open_add_trade_dialog).pack(side="right", padx=(0, 8))

    def _initial_currencies(self) -> list:
        cache = getattr(self.app_state, "broker_currencies_cache", None) if self.app_state else None
        found = [str(c).upper() for c in (cache or {}).values() if c]
        return found

    def _set_currency_options(self, currencies=None) -> None:
        """Pills: INR and JPY only. Matching the My Holdings pill style."""
        opts = ["INR", "JPY"]
        if list(self._curr_buttons) == opts:
            return
        for b in self._curr_buttons.values():
            b.destroy()
        self._curr_buttons = {}
        canvas_bg = str(self._curr_frame.cget("bg"))
        for name in opts:
            sym = currency_symbol(name).strip()
            label_text = f"{sym} {name}".strip()
            btn = ModernButton(
                self._curr_frame, text=label_text, command=lambda n=name: self.th_currency_var.set(n),
                bg=ModernStyle.NEUTRAL_FILL, fg=ModernStyle.TEXT_ON_ACCENT,
                canvas_bg=canvas_bg, width=86, height=32, radius=14,
                font=ModernStyle.FONT_BODY_BOLD,
            )
            btn.pack(side="left", padx=(0, 6) if name != opts[-1] else 0)
            self._curr_buttons[name] = btn
        self._sync_currency_pills()

    def _sync_currency_pills(self, *_):
        cur = self.th_currency_var.get()
        fills = {"INR": ModernStyle.SUCCESS_FILL, "JPY": ModernStyle.PURPLE_FILL}
        for name, btn in self._curr_buttons.items():
            sym = currency_symbol(name).strip()
            if name == cur:
                btn.set_palette(bg=fills.get(name, ModernStyle.ACCENT_PRIMARY), fg=ModernStyle.TEXT_ON_ACCENT)
                btn.set_text(f"✓ {sym} {name}")
            else:
                btn.set_palette(bg=ModernStyle.NEUTRAL_FILL, fg=ModernStyle.TEXT_ON_ACCENT)
                btn.set_text(f"{sym} {name}")

    # ── Build ───────────────────────────────────────────────────────────────────
    def build(self):
        self._th_edit_popup = None
        self._th_search_timer = None
        self._th_gen = 0                 # newest load request; older results are dropped
        self._shown_version = None       # data-cache version of the rows on screen
        self._edit_saving = False
        self._edit_orig_date = None
        self._add_saving = False

        self.th_broker_var = tk.StringVar(value="All")
        self.th_currency_var = tk.StringVar(value="INR")

        self._th_header = self.add_gradient_header(self, "🔷 Trade History", "All trades with running stats",
                                                   right_widget_func=self._build_right)
        self._th_header.pack_configure(pady=(6, 0))   # tight spacing: the table gets the room

        today = datetime.now()
        self.th_symbol_var = tk.StringVar(value="")
        self.th_type_var = tk.StringVar(value="All")
        # Start with every trade shown, so nothing older is quietly hidden
        self._first_trade_date = self._earliest_trade_date() or (today - timedelta(days=270)).strftime("%Y-%m-%d")
        self.th_start_var = tk.StringVar(value=self._first_trade_date)
        self.th_end_var = tk.StringVar(value=today.strftime("%Y-%m-%d"))

        # Filters: three rounded tiles, each softly tinted in its own colour, on one slim line
        bar = self._filter_bar = FilterBar(
            self, is_default=self._filters_are_default, on_reset=self._reset_filters,
            reset_tip="Reset the filters: every broker, symbol, type and date")
        bar.pack(fill="x", padx=20, pady=(4, 2))

        # Broker and symbol
        find = bar.tile("Broker", "landmark", "#2563EB",
                        "Show one broker's trades, or All; type part of a symbol to search", weight=1)
        brokers = list(getattr(self.app_state, "brokers_cache", None) or []) if self.app_state else []
        box, self.th_broker_cb = rounded_combobox(find.body, textvariable=self.th_broker_var,
                                                  values=ordered(["All"] + list(set(brokers))), state="readonly",
                                                  width=11, font=ModernStyle.FONT_TABLE, box_pady=2, cb_pady=0, ipady=0)
        add_broker_logos(box, self.th_broker_cb)
        box.pack(side="left", padx=(0, 8))

        sym_wrap = RoundedBox(find.body)
        sym_wrap.pack(side="left", fill="x", expand=True)   # the spare width
        glyph = lucide.glyph("search")
        if glyph:
            tk.Label(sym_wrap, text=glyph, font=lucide.font(14), fg=ModernStyle.TEXT_TERTIARY,
                     bg=ModernStyle.ENTRY_BG).pack(side="left", padx=(8, 0))
        self.th_symbol_entry = tk.Entry(sym_wrap, textvariable=self.th_symbol_var, bg=ModernStyle.ENTRY_BG,
                                        fg=ModernStyle.TEXT_PRIMARY, font=ModernStyle.FONT_TABLE, relief=tk.FLAT,
                                        bd=0, width=10, highlightthickness=0,
                                        insertbackground=ModernStyle.ACCENT_PRIMARY)
        self.th_symbol_entry.pack(side="left", fill="x", expand=True, padx=(6, 0), pady=4)
        sym_wrap.watch(self.th_symbol_entry)
        ToolTip(self.th_symbol_entry, "Symbol: type part of it, e.g. HDFC")
        # ✕ clears the search (always there, so the box keeps its width; shown only with text)
        clear = tk.Label(sym_wrap, text="✕", fg=ModernStyle.ENTRY_BG, bg=ModernStyle.ENTRY_BG,
                         font=ModernStyle.FONT_SMALL, cursor="hand2", padx=6)
        clear.pack(side="left")
        clear.bind("<Button-1>", lambda _e: (self.th_symbol_var.set(""), self.th_symbol_entry.focus_set()))
        self.th_symbol_var.trace_add("write", lambda *_: clear.configure(
            fg=ModernStyle.TEXT_TERTIARY if self.th_symbol_var.get() else ModernStyle.ENTRY_BG))

        # Type: ▲ Buy green, ▼ Sell red
        kind = bar.tile("Type", "arrow-left-right", "#7C3AED", "Type: every trade, only buys or only sells", weight=0)
        PillGroup(kind.body, ["All", "Buy", "Sell"], self.th_type_var, command=lambda: self._schedule_filter(0),
                  colours={"All": "#2563EB", "Buy": ModernStyle.SUCCESS_FILL, "Sell": ModernStyle.ERROR_FILL},
                  labels={"Buy": "▲ Buy", "Sell": "▼ Sell"}).pack(side="left")

        # Dates: From – To, and quick ranges
        dates = bar.tile("Dates", "calendar-range", "#D97706",
                         "Dates: trades from the first day to the last day (both included). "
                         "1M, 3M and 1Y end today; YTD starts on 1 January; All shows every trade.",
                         weight=0, wraps=True)
        self.th_start_entry = _create_date_input(dates.body, self.th_start_var, ipady=1)
        self.th_start_entry.pack(side="left")
        tk.Label(dates.body, text="–", bg=dates.tint, fg=ModernStyle.TEXT_SECONDARY,
                 font=ModernStyle.FONT_BODY).pack(side="left", padx=4)
        self.th_end_entry = _create_date_input(dates.body, self.th_end_var, ipady=1)
        self.th_end_entry.pack(side="left", padx=(0, 8))
        self._range_var = tk.StringVar(value="All")
        PillGroup(dates.body, list(DATE_RANGES), self._range_var, command=self._apply_range,
                  colours={k: "#D97706" for k in DATE_RANGES}).pack(side="left")

        # Every filter change goes through one debounced, generation-checked load
        self.th_broker_var.trace_add("write", lambda *_: self._on_broker_selected())
        self.th_currency_var.trace_add("write", self._sync_currency_pills)
        self.th_currency_var.trace_add("write", lambda *_: self._schedule_filter(60))
        self.th_symbol_var.trace_add("write", lambda *_: self._schedule_filter(300))
        self.th_start_var.trace_add("write", lambda *_: self._schedule_filter(400))
        self.th_end_var.trace_add("write", lambda *_: self._schedule_filter(400))
        self.th_start_var.trace_add("write", lambda *_: self._sync_range_pill())
        self.th_end_var.trace_add("write", lambda *_: self._sync_range_pill())
        self._update_date_range_info()
        self._sync_currency_pills()

        # Summary pills / KPI cards
        sum_row = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        sum_row.pack(fill="x", padx=20, pady=2)

        stat_configs = [  # (label, key, bar colour, text colour)
            ("Trades",       "trades",   ModernStyle.ACCENT_PRIMARY, ModernStyle.TEXT_ACCENT),
            ("Net Buy Qty",  "buy_qty",  ModernStyle.SUCCESS_FILL,   ModernStyle.SUCCESS),
            ("Net Sell Qty", "sell_qty", ModernStyle.ERROR_FILL,     ModernStyle.ERROR),
            ("Qty Left",     "live_qty", ModernStyle.PURPLE_FILL,    ModernStyle.TEXT_PURPLE),
            ("Net Fees",     "fees",     ModernStyle.WARNING_FILL,   ModernStyle.WARNING),
            ("Running PnL",  "pnl",      ModernStyle.INFO_FILL,      ModernStyle.INFO),
        ]
        icons = {"trades": "list-ordered", "buy_qty": "arrow-down-to-line", "sell_qty": "arrow-up-from-line",
                 "live_qty": "package", "fees": "receipt", "pnl": "activity"}
        for col, (label, key, bar, color) in enumerate(stat_configs):
            sum_row.grid_columnconfigure(col, weight=1, uniform="kpi")
            card, body, title_lbl = kpi_card(sum_row, label, bar, icons[key])
            card.grid(row=0, column=col, sticky="nsew", padx=3, pady=3)
            if key in _STAT_TIPS:
                ToolTip(title_lbl, _STAT_TIPS[key])
            val_label = tk.Label(body, text="—", bg=card.tint, fg=color, font=ModernStyle.FONT_KPI_VALUE, anchor="w")
            val_label.pack(pady=(1, 0), anchor="w")
            setattr(self, f"sum_{key}", val_label)

        # Table
        table_frame = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        table_frame.pack(fill="both", expand=True, padx=20, pady=(4, 12))
        self.trade_table = ttk.Treeview(table_frame, columns=tuple(c for c, _ in COLUMNS), show="headings",
                                        height=18, selectmode="extended")
        HeadingTips(self.trade_table, _COLUMN_TIPS)
        for col, w in COLUMNS:
            # centred: row numbers, side, type, qty, prices and fees; on the left: text and
            # values with a ▲/▼ indicator; other numbers on the right so their digits line up
            if col in ("#", "Buy/Sell", "Type", "Qty", "Price", "AvgCost", "Fees", "Cum. Fees"):
                anchor = "center"
            elif col in ("Date", "Symbol", "Trade P&L", "Running PnL"):
                anchor = "w"
            else:
                anchor = "e"
            self.trade_table.heading(col, anchor="center")
            if col in SORTABLE:
                self.trade_table.heading(col, command=lambda c=col: treeview_sort_column(self.trade_table, c, False))
            self.trade_table.column(col, width=w, minwidth=40, anchor=anchor)
        self._update_column_headings("INR")

        style = ttk.Style()
        style.configure("TH.Treeview", font=ModernStyle.FONT_TABLE, rowheight=ModernStyle.TABLE_ROW_HEIGHT + 1)   # same as Holdings
        style.configure("TH.Treeview.Heading", font=ModernStyle.FONT_TABLE_BOLD)
        self.trade_table.configure(style="TH.Treeview")

        # Plain striped rows (alternating shades within each date); only Type, Qty and Price say
        # Buy (green) or Sell (red), and the P&L columns gain (green) or loss (red)
        for tag, bg in (("buy_odd", ModernStyle.BG_SECONDARY), ("buy_even", ModernStyle.TABLE_ROW_ALT),
                        ("sell_odd", ModernStyle.BG_SECONDARY), ("sell_even", ModernStyle.TABLE_ROW_ALT)):
            self.trade_table.tag_configure(tag, background=bg, foreground=ModernStyle.TEXT_PRIMARY)

        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.trade_table.yview)
        self.trade_table.configure(yscroll=vsb.set)
        self.trade_table.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # Empty-state overlay (shown when the filters match nothing)
        self._empty = EmptyState(table_frame)

        self.trade_table.bind("<Double-1>", self._on_double_click)
        # Right-click (Button-2 on Mac mouse, Button-3 on Windows/Linux, Control-Button-1 on Mac trackpad)
        for seq in ("<Button-2>", "<Button-3>", "<Control-Button-1>"):
            self.trade_table.bind(seq, self._show_trade_context_menu)

    def _update_column_headings(self, c_filter: str) -> None:
        native = "" if c_filter == "All" else currency_symbol(c_filter)
        pnl = currency_symbol("INR" if c_filter == "All" else c_filter)
        for col, _w in COLUMNS:
            text = col
            if col in NATIVE_MONEY and native:
                text = f"{col} {native}"
            elif col in PNL_MONEY:
                text = f"{col} {pnl}"
            if col in SORTABLE:
                text += " ↕"
            self.trade_table.heading(col, text=text)

    # ── Row ids ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _make_trade_iid(broker: str, trade_id: str) -> str:
        # Keep an internal unique ID so we can edit/delete reliably.
        b = (broker or "").replace("|", "/").strip()
        t = (trade_id or "").replace("|", "/").strip()
        return f"{b}|{t}"

    @staticmethod
    def _split_trade_iid(iid: str) -> tuple[str, str]:
        s = str(iid or "")
        if "|" not in s:
            return "", s
        b, t = s.split("|", 1)
        return b, t

    @staticmethod
    def _parse_float(s: str) -> float:
        v = (s or "").strip().replace(",", "")
        if not v:
            return 0.0
        return float(v)

    # ── Edit ────────────────────────────────────────────────────────────────────
    @staticmethod
    def _fetch_trade(broker: str, trade_id: str):
        """The editable fields of one trade straight from the database (a single-row lookup)."""
        from model.database import db_session
        with db_session() as conn:
            row = conn.execute("SELECT date, symbol, type, qty, price, fee, currency FROM trades "
                               "WHERE broker=? AND trade_id=?", (broker, trade_id)).fetchone()
        if not row:
            return None
        return dict(date=row[0], symbol=row[1], trade_type=row[2], qty=str(row[3]), price=str(row[4]),
                    fee=str(row[5]), currency=str(row[6] or "INR"))

    def _on_double_click(self, event=None) -> None:
        try:
            if event is not None and self.trade_table.identify_region(event.x, event.y) != "cell":
                return
        except tk.TclError:
            pass
        iid = self.trade_table.focus()
        if not iid:
            return
        # The row id is "broker|trade_id", which is all the edit needs
        broker, trade_id = self._split_trade_iid(iid)
        if broker and trade_id:
            self._edit_from_context(iid)

    def _edit_from_context(self, iid: str) -> None:
        """Open the edit form for a row ("broker|trade_id"), reading the trade from the database."""
        broker, trade_id = self._split_trade_iid(iid)
        if not broker or not trade_id:
            dialogs.showerror("Edit Trade", "This row has no broker or trade id, so it can't be edited.")
            return
        try:
            trade = self._fetch_trade(broker, trade_id)
        except Exception:
            log.exception("Reading trade %s|%s for editing failed", broker, trade_id)
            dialogs.showerror("Edit Trade", "This trade couldn't be read from the database. Please try again.")
            return
        if trade is None:
            dialogs.showerror("Edit Trade", "This trade isn't in the database any more. Press ⟳ Refresh.")
            return
        self._open_edit_trade_dialog(broker=broker, trade_id=str(trade_id), **trade)

    def _close_popup(self) -> None:
        try:
            if self._th_edit_popup is not None and self._th_edit_popup.winfo_exists():
                self._th_edit_popup.destroy()
        except tk.TclError:
            pass

    def _open_edit_trade_dialog(self, *, broker: str, trade_id: str, date: str, symbol: str, trade_type: str,
                                qty: str, price: str, fee: str, currency: str = "INR") -> None:
        if not broker or not trade_id:
            dialogs.showerror("Edit Trade", "This row has no broker or trade id, so it can't be edited.")
            return
        self._close_popup()
        self._edit_saving = False

        win = make_dialog(self, "✏️ Edit Trade", "700x400", ModernStyle.ACCENT_PRIMARY)
        self._th_edit_popup = win
        head_row, _ = dialog_header(win, symbol.upper() if symbol else "Edit Trade",
                                    f"✏️  Editing Trade  ·  {trade_id}", ModernStyle.TEXT_ACCENT)

        card = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
        card.pack(fill="both", expand=True, padx=24, pady=16)

        _num = number_text
        self._edit_broker_var = tk.StringVar(value=(broker or "").strip())
        self._edit_date_var = tk.StringVar(value=(date or "").strip())
        self._edit_symbol_var = tk.StringVar(value=(symbol or "").strip().upper())
        self._edit_type_var = tk.StringVar(value=(trade_type or "BUY").strip().upper())
        self._edit_qty_var = tk.StringVar(value=_num(qty))
        self._edit_price_var = tk.StringVar(value=_num(price))
        self._edit_fee_var = tk.StringVar(value=_num(fee))
        self._edit_currency_var = tk.StringVar(value=(currency or "INR").strip().upper())
        self._edit_orig_date = (date or "").strip()

        currency_toggle(head_row, self._edit_currency_var,
                        currency_choices(self.app_state, self._edit_currency_var.get())).pack(side="right")
        form = TradeForm(card)
        form.frame.pack(fill="x")
        form.three_rows(broker_var=self._edit_broker_var, brokers=known_brokers(self.app_state, broker),
                        date_var=self._edit_date_var, qty_var=self._edit_qty_var, price_var=self._edit_price_var,
                        fee_var=self._edit_fee_var, type_var=self._edit_type_var,
                        currency_var=self._edit_currency_var, symbol_var=self._edit_symbol_var)

        status, actions = dialog_footer(win)
        self._edit_save_btn = dialog_button(actions, "✓ Update Trade",
                                            lambda: self._save_trade_edits(broker, trade_id, symbol, status, win),
                                            ModernStyle.ACCENT_PRIMARY, 160)
        self._edit_save_btn.pack(side="right")
        dialog_button(actions, "✕ Cancel", win.destroy, ModernStyle.NEUTRAL_FILL, 120).pack(side="right", padx=(0, 12))

    def _set_edit_busy(self, busy: bool) -> None:
        self._edit_saving = busy
        btn = getattr(self, "_edit_save_btn", None)
        try:
            if btn is not None and btn.winfo_exists():
                btn.set_disabled(busy)
        except tk.TclError:
            pass

    def _save_trade_edits(self, broker_old: str, trade_id: str, symbol_old: str, status_label: tk.Label,
                          dialog: tk.Toplevel) -> None:
        if self._edit_saving:
            return   # a save is already running (double click)
        try:
            # Strict date check (year-month-day); the date filters are more forgiving while typing.
            values = check_trade_fields(
                broker=self._edit_broker_var.get(), date=self._edit_date_var.get(),
                symbol=self._edit_symbol_var.get(), trade_type=self._edit_type_var.get(),
                qty=self._edit_qty_var.get(), price=self._edit_price_var.get(), fee=self._edit_fee_var.get(),
                currency=self._edit_currency_var.get(), original_date=self._edit_orig_date)
        except ValueError as e:
            status_label.configure(text=str(e), fg=ModernStyle.ERROR)
            return

        rename_all = False
        if values["symbol"] != (symbol_old or "").strip().upper():
            rename_all = dialogs.askyesno(
                "Rename Symbol",
                f"You changed the symbol from '{symbol_old}' to '{values['symbol']}'.\n\n"
                f"Rename ALL trades for '{symbol_old}' under broker '{broker_old}'? (No = only this trade)",
                parent=dialog)

        self._set_edit_busy(True)
        status_label.configure(text="Updating…", fg=ModernStyle.TEXT_SECONDARY)
        app_state = self.app_state

        def _work():
            # One transaction: a broker move is a single UPDATE, so if it fails
            # (e.g. that broker already has this trade id) the trade is untouched.
            save_trade_edit(broker_old=broker_old, trade_id=trade_id, symbol_old=symbol_old,
                            values=values, rename_all=rename_all)
            return refresh_after_change(app_state)

        def _done(warning):
            self._set_edit_busy(False)
            try:
                dialog.destroy()
            except tk.TclError:
                pass
            self._apply_filters()
            show_stale_warning(self, warning)

        def _failed(e):
            self._set_edit_busy(False)
            try:
                status_label.configure(
                    text=f"Update failed: {friendly_error(e, broker=values['broker'], trade_id=trade_id)}",
                    fg=ModernStyle.ERROR)
            except tk.TclError:
                pass

        run_in_background(_work, _done, _failed, widget=self, name="history-edit")

    # ── Add ─────────────────────────────────────────────────────────────────────
    def _open_add_trade_dialog(self) -> None:
        self._close_popup()
        self._add_saving = False
        win = make_dialog(self, "➕ New Trade", "700x400", ModernStyle.SUCCESS_FILL)
        self._th_edit_popup = win
        head_row, name_lbl = dialog_header(win, "➕  New Trade", "Add a new historical or manual trade entry",
                                           ModernStyle.SUCCESS)

        card = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
        card.pack(fill="both", expand=True, padx=24, pady=16)

        initial_broker = self.th_broker_var.get()
        if initial_broker == "All":
            initial_broker = ""
        self._add_broker_var = tk.StringVar(value=initial_broker)
        self._add_date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self._add_symbol_var = tk.StringVar(value="")
        self._add_type_var = tk.StringVar(value="BUY")
        self._add_qty_var = tk.StringVar(value="")
        self._add_price_var = tk.StringVar(value="")
        self._add_fee_var = tk.StringVar(value="0.0")
        self._add_currency_var = tk.StringVar(value="INR")

        currency_toggle(head_row, self._add_currency_var, currency_choices(self.app_state)).pack(side="right")
        form = TradeForm(card, accent=ModernStyle.SUCCESS_FILL)
        form.frame.pack(fill="x")
        sym_ent, _qty = form.three_rows(
            broker_var=self._add_broker_var, brokers=known_brokers(self.app_state, initial_broker),
            date_var=self._add_date_var, qty_var=self._add_qty_var, price_var=self._add_price_var,
            fee_var=self._add_fee_var, type_var=self._add_type_var, currency_var=self._add_currency_var,
            symbol_var=self._add_symbol_var)
        # The currency follows the broker (NOMURA -> JPY ...)
        follow_broker_currency(self._add_broker_var, self._add_currency_var, self.app_state)
        if initial_broker:
            self._add_broker_var.set(initial_broker)

        def _on_symbol_focusout(_e):
            sym = self._add_symbol_var.get().strip().upper()
            if not sym:
                return
            name_lbl.configure(text="⏳ Looking up the stock name…")

            def _fetch():   # network: worker thread only
                import yfinance as yf
                info = yf.Ticker(sym + ".NS").info
                name = info.get("longName") or info.get("shortName") or ""
                if not name:
                    info = yf.Ticker(sym).info
                    name = info.get("longName") or info.get("shortName") or ""
                return name

            def _show(name):
                try:
                    name_lbl.configure(text=name or "Add a new historical or manual trade entry")
                except tk.TclError:
                    pass
            run_in_background(_fetch, _show, lambda e: _show(""), widget=win, name="stock-name")
        sym_ent.bind("<FocusOut>", _on_symbol_focusout, add="+")

        status, actions = dialog_footer(win)
        self._add_save_btn = dialog_button(actions, "✓ Add Trade", lambda: self._save_new_trade(status, win),
                                           ModernStyle.SUCCESS_FILL, 160)
        self._add_save_btn.pack(side="right")
        dialog_button(actions, "✕ Cancel", win.destroy, ModernStyle.NEUTRAL_FILL, 120).pack(side="right", padx=(0, 12))

    def _set_add_busy(self, busy: bool) -> None:
        self._add_saving = busy
        btn = getattr(self, "_add_save_btn", None)
        try:
            if btn is not None and btn.winfo_exists():
                btn.set_disabled(busy)
        except tk.TclError:
            pass

    def _save_new_trade(self, status_label: tk.Label, dialog: tk.Toplevel) -> None:
        if self._add_saving:
            return   # already saving (double click)
        try:
            values = check_trade_fields(
                broker=self._add_broker_var.get(), date=self._add_date_var.get(),
                symbol=self._add_symbol_var.get(), trade_type=self._add_type_var.get(),
                qty=self._add_qty_var.get(), price=self._add_price_var.get(), fee=self._add_fee_var.get(),
                currency=self._add_currency_var.get(), new_trade=True)
        except ValueError as e:
            status_label.configure(text=str(e), fg=ModernStyle.ERROR)
            return
        if not confirm_unusual(dialog, values["qty"], values["price"], values["currency"]):
            return

        self._set_add_busy(True)
        status_label.configure(text="Saving trade…", fg=ModernStyle.TEXT_SECONDARY)
        app_state = self.app_state

        def _work():
            import uuid
            import model.crud as crud
            v = values
            crud.add_trade(v["broker"], v["date"], v["symbol"], v["trade_type"], v["qty"], v["price"], v["fee"],
                           str(uuid.uuid4())[:8], currency=v["currency"])
            return refresh_after_change(app_state)

        def _done(warning):
            self._set_add_busy(False)
            try:
                dialog.destroy()
            except tk.TclError:
                pass
            self._apply_filters()
            show_stale_warning(self, warning)

        def _failed(e):
            self._set_add_busy(False)
            try:
                status_label.configure(text=f"Save failed: {friendly_error(e)}", fg=ModernStyle.ERROR)
            except tk.TclError:
                pass

        run_in_background(_work, _done, _failed, widget=self, name="history-add")

    # ── Delete / copy / context menu ────────────────────────────────────────────
    def _delete_selected(self) -> None:
        items = list(self.trade_table.selection() or [])
        if not items:
            dialogs.showinfo("Trade History", "Select one or more rows to delete (Cmd-click / Shift-click).")
            return
        pairs = [p for p in (self._split_trade_iid(i) for i in items) if p[0] and p[1]]
        if not pairs:
            dialogs.showinfo("Trade History", "These rows have no trade id, so they can't be deleted here.")
            return
        if len(items) == 1:
            vals = self.trade_table.item(items[0], "values")
            what = f"{vals[3]} {vals[4]} {vals[2]} on {vals[1]}" if len(vals) > 4 else "this trade"
            title, msg = "Delete Trade", f"Delete this trade?\n\n{what}"
        else:
            title, msg = f"Delete {len(items)} Trades", f"Delete the {len(items)} selected trades?"
        msg += "\n\nA backup is saved first, so you can undo this from Settings (Restore…)."
        if not dialogs.askyesno(title, msg, parent=self.winfo_toplevel()):
            return

        app_state = self.app_state

        def _work():
            from model.backup import safety_backup
            try:
                safety_backup("delete-trade")
            except Exception as e:
                raise RuntimeError("Couldn't save a backup first, so nothing was deleted.") from e
            from model.database import db_session
            with db_session() as conn:   # one transaction for all rows
                conn.executemany("DELETE FROM trades WHERE broker = ? AND trade_id = ?", pairs)
            return refresh_after_change(app_state)

        def _done(warning):
            self._apply_filters()
            show_stale_warning(self, warning)

        def _failed(e):
            msg = str(e) if isinstance(e, RuntimeError) else f"Delete failed: {friendly_error(e)}"
            dialogs.showerror("Delete Trades", msg, parent=self.winfo_toplevel())

        run_in_background(_work, _done, _failed, widget=self, name="history-delete")

    def _copy_selected(self) -> None:
        items = list(self.trade_table.selection() or [])
        if not items:
            dialogs.showinfo("Trade History", "No rows selected.")
            return
        self._copy_items(items)

    def _copy_all(self) -> None:
        items = list(self.trade_table.get_children() or [])
        if not items:
            dialogs.showinfo("Trade History", "No data to copy.")
            return
        self._copy_items(items)

    def _copy_items(self, items: list) -> None:
        cols = [self.trade_table.heading(c, "text").replace(" ↕", "") for c in self.trade_table["columns"]]
        lines = ["\t".join(cols)]
        for iid in items:
            vals = self.trade_table.item(iid, "values")
            lines.append("\t".join(str(v).replace("₹", "").replace("¥", "").replace("$", "").replace(",", "")
                                   .replace("%", "").strip() for v in vals))
        try:
            self.clipboard_clear()
            self.clipboard_append("\n".join(lines))
            show_toast(self.winfo_toplevel(), f"Copied {len(items)} row(s) to the clipboard.", type="success")
        except tk.TclError:
            log.exception("Copying rows failed")
            dialogs.showerror("Trade History", "The rows couldn't be copied. Please try again.")

    def _show_trade_context_menu(self, event) -> None:
        """Right-click menu: Edit (when a single trade is selected), Copy, Copy All, Delete."""
        iid = self.trade_table.identify_row(event.y)
        if iid and iid not in self.trade_table.selection():
            self.trade_table.selection_set(iid)

        sel = list(self.trade_table.selection() or [])
        menu = tk.Menu(self.trade_table, tearoff=False)

        if sel:
            if len(sel) == 1:
                broker, trade_id = self._split_trade_iid(sel[0])
                if broker and trade_id:
                    menu.add_command(label="Edit", command=lambda: self._edit_from_context(sel[0]))
            menu.add_command(label="Copy", command=self._copy_selected)
            menu.add_command(label="Copy All", command=self._copy_all)
            menu.add_separator()
            menu.add_command(label="Delete", command=self._delete_selected)
        else:
            menu.add_command(label="Copy All", command=self._copy_all)

        try:
            decorate_menu(menu)   # a small coloured icon on each item
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except tk.TclError:
                pass

    # ── Showing / loading ───────────────────────────────────────────────────────
    def on_show(self):
        self._is_active = True
        self._refresh_broker_list()
        cache = getattr(self.app_state, "data_cache", None) if self.app_state else None
        version = cache.version if cache is not None else None
        if not self._data_loaded:
            # Another page marked the data stale. If nobody refreshed the cache since
            # we last drew, read the database again; otherwise just filter.
            self._apply_filters(reload_db=self._shown_version is not None and version == self._shown_version)
        elif version != self._shown_version:
            self._apply_filters()

    def on_hide(self):
        self._is_active = False

    def refresh(self):
        """⟳ Refresh: read the database again."""
        self._refresh_broker_list()
        self._apply_filters(reload_db=True)

    def load_data(self):
        self._apply_filters()

    def _refresh_broker_list(self) -> None:
        """Broker list and the currencies in use, read in the background."""
        app_state = self.app_state

        def _work():
            from model.database import db_session
            if app_state is not None:
                brokers = list(app_state.get_brokers_cached(force_refresh=True) or [])
                currencies = list((app_state.get_broker_currencies_cached() or {}).values())
            else:
                import model.crud as crud
                brokers = list(crud.get_all_brokers())
                currencies = list(crud.get_broker_currencies().values())
            with db_session() as conn:
                currencies += [r[0] for r in conn.execute(
                    "SELECT DISTINCT UPPER(currency) FROM trades WHERE currency IS NOT NULL AND currency != ''")]
            return brokers, currencies

        def _done(res):
            brokers, currencies = res
            values = ordered(["All"] + list(set(brokers)))
            if list(self.th_broker_cb.cget("values")) != values:
                self.th_broker_cb["values"] = values
            if self.th_broker_var.get() not in values:
                self.th_broker_var.set("All")
            self._set_currency_options(currencies)

        run_in_background(_work, _done, widget=self, name="history-brokers")

    def _on_broker_selected(self):
        """Picking a broker shows that broker's currency."""
        broker = self.th_broker_var.get()
        cur_now = self.th_currency_var.get()
        if broker != "All":
            mapping = getattr(self.app_state, "broker_currencies_cache", None) if self.app_state else None
            cur = str((mapping or {}).get(broker) or "").upper()
            if cur in ("INR", "JPY") and cur != cur_now:
                self.th_currency_var.set(cur)   # its trace schedules the load
        elif cur_now not in ("INR", "JPY"):
            self.th_currency_var.set("INR")
        self._schedule_filter(60)

    def _schedule_filter(self, delay_ms: int = 150) -> None:
        """Debounce: many quick changes (typing, broker + currency) cause one load."""
        if hasattr(self, "_filter_bar"):
            self._filter_bar.sync_reset()
        if self._th_search_timer is not None:
            try:
                self.after_cancel(self._th_search_timer)
            except tk.TclError:
                pass
        self._th_search_timer = self.after(delay_ms, self._run_scheduled_filter)

    def _run_scheduled_filter(self) -> None:
        self._th_search_timer = None
        self._apply_filters()

    @staticmethod
    def _parse_date_or_none(s: str) -> str | None:
        """A YYYY-MM-DD date, or None when blank or not a complete date (e.g. while typing)."""
        val = (s or "").strip()
        try:
            datetime.strptime(val, "%Y-%m-%d")
            return val
        except ValueError:
            return None

    @staticmethod
    def _earliest_trade_date() -> str | None:
        """Date of the oldest trade (YYYY-MM-DD), or None when there are none."""
        try:
            from model.database import db_session
            with db_session() as conn:
                row = conn.execute("SELECT MIN(date) FROM trades WHERE date GLOB '[0-9][0-9][0-9][0-9]-*'").fetchone()
            first = str(row[0])[:10] if row and row[0] else ""
            datetime.strptime(first, "%Y-%m-%d")
            return first
        except Exception:
            return None

    def _reset_filters(self) -> None:
        """Every broker, symbol, type and date (the empty screen's button)."""
        self.th_broker_var.set("All")
        self.th_symbol_var.set("")
        self.th_type_var.set("All")
        self._show_all_dates()
        self._schedule_filter(0)

    def _show_all_dates(self) -> None:
        self._first_trade_date = self._earliest_trade_date() or self._first_trade_date
        self.th_start_var.set(self._first_trade_date)
        self.th_end_var.set(datetime.now().strftime("%Y-%m-%d"))

    def _range_start(self, key: str) -> str | None:
        """First day of a quick date range (YYYY-MM-DD; each ends today)."""
        today = datetime.now()
        if key == "All":
            return self._first_trade_date
        if key == "YTD":
            return f"{today.year}-01-01"
        months = {"1M": 1, "3M": 3, "1Y": 12}.get(key)
        if months is None:
            return None
        year, month = divmod(today.month - 1 - months, 12)
        year, month = today.year + year, month + 1
        day = min(today.day, calendar.monthrange(year, month)[1])
        return f"{year:04d}-{month:02d}-{day:02d}"

    def _apply_range(self) -> None:
        """A quick date pill was picked: its dates (the From / To boxes follow)."""
        key = self._range_var.get()
        if key == "All":   # looks up the first trade again (one may have been added)
            if (self.th_start_var.get(), self.th_end_var.get()) != (self._first_trade_date,
                                                                    datetime.now().strftime("%Y-%m-%d")):
                self._show_all_dates()
            return
        start = self._range_start(key)
        if start is None:
            return
        end = datetime.now().strftime("%Y-%m-%d")
        if self.th_start_var.get() != start:
            self.th_start_var.set(start)
        if self.th_end_var.get() != end:
            self.th_end_var.set(end)

    def _sync_range_pill(self) -> None:
        """Light the quick pill that matches the dates typed or picked (none if no match)."""
        if not hasattr(self, "_range_var"):
            return
        start, end = self.th_start_var.get(), self.th_end_var.get()
        today = datetime.now().strftime("%Y-%m-%d")
        match = next((k for k in DATE_RANGES if end == today and self._range_start(k) == start), "")
        if self._range_var.get() != match:
            self._range_var.set(match)

    def _filters_are_default(self) -> bool:
        return (self.th_broker_var.get() in ("", "All") and not self.th_symbol_var.get().strip()
                and self.th_type_var.get() == "All" and getattr(self, "_range_var", None) is not None
                and self._range_var.get() == "All")

    def _update_date_range_info(self) -> bool:
        """Show the chosen range; returns False when a date can't be read yet."""
        start_s, end_s = self.th_start_var.get().strip(), self.th_end_var.get().strip()
        start, end = self._parse_date_or_none(start_s), self._parse_date_or_none(end_s)
        if (start_s and not start) or (end_s and not end):
            self._th_header.set_note("⚠ Check the dates (e.g. 15 Jan 2024)", ModernStyle.HEADER_WARN_FG)
            return False
        if start and end:
            s_dt, e_dt = datetime.strptime(start, "%Y-%m-%d"), datetime.strptime(end, "%Y-%m-%d")
            if s_dt > e_dt:
                self._th_header.set_note("⚠ 'From' is after 'To'", ModernStyle.HEADER_WARN_FG)
            else:   # the boxes show the range and the summary the trades' dates: no third copy
                self._th_header.set_note("")
        else:
            self._th_header.set_note("")
        return True

    def _apply_filters(self, reload_db: bool = False) -> None:
        """Read the filters now (Tk thread), then load and build the rows in a worker."""
        if self.app_state is None or not hasattr(self.app_state, "data_cache"):
            return
        if not self._update_date_range_info():
            return
        type_raw = self.th_type_var.get()
        c_filter = self.th_currency_var.get() or "All"
        broker = self.th_broker_var.get() or "All"
        symbol_like = self.th_symbol_var.get().strip()
        filters = TradeHistoryFilters(
            broker=broker, symbol_like=symbol_like,
            trade_type={"Buy": "BUY", "Sell": "SELL"}.get(type_raw, "All"),
            start_date=self._parse_date_or_none(self.th_start_var.get()),
            end_date=self._parse_date_or_none(self.th_end_var.get()),
            currency=c_filter,
        )
        calc_unrealized = bool(symbol_like) and broker != "All"
        self._data_loaded = True
        show_skeleton(self.trade_table)   # grey bars while an empty table loads
        self._th_gen += 1
        gen = self._th_gen
        app_state = self.app_state

        def _work():
            cache = app_state.data_cache
            if reload_db or not cache.loaded:
                from model.database import _invalidate_thread_connection
                _invalidate_thread_connection()
                app_state.refresh_data_cache()
            version = cache.version
            df, summary = cache.get_tradehistory_filtered(filters)
            market_prices, rates = {}, {}
            if calc_unrealized:
                from model.database import db_session
                with db_session() as conn:
                    market_prices = {str(s).upper(): float(p or 0.0)
                                     for s, p in conn.execute("SELECT symbol, current_price FROM marketdata")}
            if c_filter == "All" and df is not None and not df.empty and "currency" in df.columns:
                from model.engine import get_exchange_rate
                rates = {str(c).strip().upper(): get_exchange_rate(str(c).strip().upper())
                         for c in df["currency"].dropna().unique()}
            rows = [] if df is None or df.empty else build_rows(
                df, c_filter=c_filter, calc_unrealized=calc_unrealized, market_prices=market_prices, rates=rates)
            return version, summary, rows

        def _done(res):
            if gen != self._th_gen:
                return   # a newer load was started; this result is out of date
            self._show_result(*res, c_filter=c_filter)

        def _failed(e):
            if gen == self._th_gen:
                self._data_loaded = False
                clear_skeleton(self.trade_table)
                self._empty.show("⚠️", "Trades couldn't be loaded",
                                 "Something went wrong while reading your trades.", "↻ Try again", self.refresh)

        run_in_background(_work, _done, _failed, widget=self, name="history-load")

    def _show_result(self, version, summary: dict, rows: list, *, c_filter: str) -> None:
        tv = self.trade_table
        children = tv.get_children()
        if children:
            tv.delete(*children)
        self._shown_version = version
        self._update_column_headings(c_filter)

        disp_cur = "INR" if c_filter == "All" else c_filter
        qty_buy = float(summary.get("qty_buy", 0.0) or 0.0)
        qty_sell = float(summary.get("qty_sell", 0.0) or 0.0)
        fees = float(summary.get("fee_buy", 0.0) or 0.0) + float(summary.get("fee_sell", 0.0) or 0.0)
        total_pnl = float(summary.get("total_pnl", 0.0) or 0.0)
        self.sum_trades.config(text=_count(len(rows)))
        self.sum_buy_qty.config(text=_count(qty_buy))
        self.sum_sell_qty.config(text=_count(qty_sell))
        self.sum_live_qty.config(text=_count(qty_buy - qty_sell))
        self.sum_fees.config(text=_whole_money(fees, disp_cur))
        self.sum_pnl.config(text=f"{'▲' if total_pnl >= 0 else '▼'} {_whole_money(abs(total_pnl), disp_cur)}",
                            fg=ModernStyle.SUCCESS if total_pnl >= 0 else ModernStyle.ERROR)

        self.set_header_summary(self._range_summary(rows))
        if not rows and not self._has_any_trades():
            self._empty.show("🧾", "No trades yet",
                             "Add your first trade by hand, or import a CSV file on the Trade Entry page.",
                             "+ Add a trade", self._open_add_trade_dialog)
            return
        if not rows:
            self._empty.show("🔍", "No trades match these filters",
                             "Try another broker, symbol, type or date range.", "↺ Show all trades",
                             self._reset_filters)
            return
        self._empty.hide()
        for iid, values, tags in rows:
            try:
                tv.insert("", "end", iid=iid, values=values, tags=tags)
            except tk.TclError:
                tv.insert("", "end", values=values, tags=tags)   # duplicate id (should not happen)
        color_gain_loss(tv, PNL_MONEY, rows=[(iid, values) for iid, values, _tags in rows])
        side = {"Buy": True, "Sell": False}
        color_buy_sell(tv, [(iid, side.get(values[TYPE_INDEX])) for iid, values, _tags in rows])

    def _has_any_trades(self) -> bool:
        """Whether there is at least one trade at all (filters aside)."""
        try:
            from model.database import db_session
            with db_session() as conn:
                return conn.execute("SELECT 1 FROM trades LIMIT 1").fetchone() is not None
        except Exception:
            log.exception("Trade History: could not check for trades")
            return True   # then the filters message, as before

    @staticmethod
    def _range_summary(rows: list) -> str:
        """For the header: how many trades, from which day to which ("" when none)."""
        days = []
        for _iid, values, _tags in rows:
            try:
                days.append(datetime.strptime(str(values[1]), "%d %b %Y"))
            except (ValueError, IndexError):
                pass
        if not days:
            return ""
        first, last = min(days), max(days)
        span = first.strftime("%d %b %Y") if first == last else f"{first:%d %b %Y} to {last:%d %b %Y}"
        return f"{len(rows):,} {'trade' if len(rows) == 1 else 'trades'}  ·  {span}"
