"""
Trade Entry view for TKinter-based PTracker application.

Three ways to add trades: the manual form, a CSV file, or rows pasted into the box.
Imports are checked by model/importer.py before anything is saved; the preview
window says how many rows will be imported, which are rejected (and why) and which
look like duplicates of trades you already have.
"""

import sys
import tkinter as tk
from tkinter import ttk
from datetime import date as _date, datetime

from model.applog import log
from model.importer import (
    ImportProblem, existing_trade_index, missing_columns, parse_pasted_text, read_csv_file, validate_rows,
)
from views.base_view import BaseView, _create_date_input
from views.shared_trade_edit import (
    confirm_unusual, currency_symbol, friendly_error, refresh_after_change, show_stale_warning,
)
from ui.ui_theme import ModernStyle
from ui.ui_widgets import RoundedBox, ModernButton, ModernCard
from ui.ui_utils import add_treeview_copy_menu, center_window, format_money, run_in_background, show_toast

PASTE_HINT = "date,symbol,type,qty,price\n2024-01-15,TCS.NS,BUY,10,3500.00\n2024-01-20,INFY.NS,SELL,5,1800.50"
PREVIEW_READY_ROWS = 1000   # ready rows listed in the preview (problem rows are always all listed)


class TradeEntryView(BaseView):
    """Form for entering new trades."""

    def build(self):
        """Build Trade Entry view with premium look."""
        self._data_loaded = False
        self._saving = False
        self._snapshot_gen = 0
        self._sum_tint = None
        self._brokers: list = []
        self.pending_csv_df = None
        self.pending_csv_name = ""
        self.pending_paste_df = None
        self._import_preview_win = None

        self.add_gradient_header(self, "❇️ Trade Entry", "Record a manual trade or bulk-import via CSV",
                                 show_divider=False)

        # The page scrolls when the window is too short for it; otherwise it fills the window.
        scroller = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        scroller.pack(fill="both", expand=True)
        self._page_canvas = tk.Canvas(scroller, bg=ModernStyle.BG_PRIMARY, highlightthickness=0, bd=0)
        self._page_vsb = ttk.Scrollbar(scroller, orient="vertical", command=self._page_canvas.yview)
        self._page_canvas.configure(yscrollcommand=self._page_vsb.set)
        self._page_canvas.pack(side="left", fill="both", expand=True)
        page = tk.Frame(self._page_canvas, bg=ModernStyle.BG_PRIMARY)
        self._page = page
        self._page_item = self._page_canvas.create_window(0, 0, window=page, anchor="nw")
        self._page_canvas.bind("<Configure>", lambda e: self._fit_page())
        self._page_canvas.bind("<Enter>", lambda e: self._page_canvas.bind_all("<MouseWheel>", self._on_page_wheel))
        self._page_canvas.bind("<Leave>", lambda e: self._page_canvas.unbind_all("<MouseWheel>"))

        body = tk.Frame(page, bg=ModernStyle.BG_PRIMARY)
        body.pack(fill="both", expand=True, padx=20, pady=10)
        body.grid_columnconfigure(0, weight=3, uniform="te")
        body.grid_columnconfigure(1, weight=2, uniform="te")
        body.grid_rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=ModernStyle.BG_PRIMARY)
        right = tk.Frame(body, bg=ModernStyle.BG_PRIMARY)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right.grid(row=0, column=1, sticky="nsew")

        vcmd = (self.register(self._validate_number), "%P")
        vcmd_qty = (self.register(self._validate_qty), "%P")
        BG_SEC = ModernStyle.BG_SECONDARY

        def _card(parent, title: str, icon: str = "", bar=ModernStyle.ACCENT_PRIMARY,
                  fg=ModernStyle.TEXT_ACCENT, expand_height=False):
            """Section card: coloured top bar (`bar`) and title text (`fg`)."""
            frame = ModernCard(parent, bg=BG_SEC, highlight_color=ModernStyle.BORDER_COLOR, highlight_thickness=1,
                               radius=10, canvas_bg=ModernStyle.BG_PRIMARY, expand_height=expand_height)
            tk.Frame(frame.content, bg=bar, height=3).pack(fill="x")
            hdr = tk.Frame(frame.content, bg=BG_SEC)
            hdr.pack(fill="x", padx=14, pady=(10, 6))
            if icon:
                tk.Label(hdr, text=icon, fg=fg, bg=BG_SEC, font=ModernStyle.FONT_TITLE).pack(side="left", padx=(0, 6))
            tk.Label(hdr, text=title, fg=fg, bg=BG_SEC, font=ModernStyle.FONT_TITLE).pack(side="left")
            tk.Frame(frame.content, bg=ModernStyle.DIVIDER_COLOR, height=1).pack(fill="x", padx=12)
            inner = tk.Frame(frame.content, bg=BG_SEC)
            inner.pack(fill="both", expand=True, padx=14, pady=(10, 14))
            frame.header_frame = hdr
            return frame, inner

        def _caption(parent, text, **grid):
            lbl = tk.Label(parent, text=text, fg=ModernStyle.TEXT_SECONDARY, bg=BG_SEC, font=ModernStyle.FONT_HEADING)
            if grid:
                lbl.grid(**grid)
            else:
                lbl.pack(anchor="w", pady=(0, 4))
            return lbl

        def _styled_entry(parent, textvariable, validate=None, vcmd=None):
            """Entry with a focus ring (the ring turns red when the value is wrong)."""
            wrap = RoundedBox(parent)
            wrap.pack(fill="x")
            kw = dict(textvariable=textvariable, bg=ModernStyle.ENTRY_BG, fg=ModernStyle.TEXT_ACCENT,
                      font=ModernStyle.FONT_INPUT, relief=tk.FLAT, insertbackground=ModernStyle.ACCENT_PRIMARY,
                      highlightthickness=0)
            if validate:
                kw["validate"] = validate
            if vcmd:
                kw["validatecommand"] = vcmd
            ent = tk.Entry(wrap, **kw)

            def _fi(e, w=wrap):
                if w.cget("bg") != ModernStyle.ERROR:
                    w.configure(bg=ModernStyle.ACCENT_PRIMARY)

            def _fo(e, w=wrap):
                if w.cget("bg") != ModernStyle.ERROR:
                    w.configure(bg=ModernStyle.BORDER_COLOR)
            ent.bind("<FocusIn>", _fi)
            ent.bind("<FocusOut>", _fo)
            ent.pack(fill="x", ipady=5, padx=8)
            return ent, wrap

        # ===== Manual Entry Card =====
        manual_card, manual = _card(left, "Manual Trade Entry", "✍️")
        manual_card.pack(fill="x", pady=(0, 10))

        r1 = tk.Frame(manual, bg=BG_SEC)
        r1.pack(fill="x", pady=(0, 12))
        r1.grid_columnconfigure(0, weight=1, uniform="r1")
        r1.grid_columnconfigure(1, weight=1, uniform="r1")
        self.te_broker_var = tk.StringVar(value="")
        self.te_date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))

        broker_col = tk.Frame(r1, bg=BG_SEC)
        broker_col.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        _caption(broker_col, "🏦 Broker")
        self.te_broker_cb = ttk.Combobox(broker_col, textvariable=self.te_broker_var, width=18, state="readonly",
                                         font=ModernStyle.FONT_SUBHEADING)
        self.te_broker_cb.pack(fill="x", ipady=2, pady=5)

        date_col = tk.Frame(r1, bg=BG_SEC)
        date_col.grid(row=0, column=1, sticky="nsew")
        _caption(date_col, "📅 Date")
        self.te_date_entry = _create_date_input(date_col, self.te_date_var)
        self.te_date_entry.pack(fill="x", pady=(2, 0))

        # Row 2: Type | Currency (the currency follows the broker)
        r2 = tk.Frame(manual, bg=BG_SEC)
        r2.pack(fill="x", pady=(0, 10))
        r2.grid_columnconfigure(0, weight=1, uniform="r2")
        r2.grid_columnconfigure(1, weight=1, uniform="r2")
        self.te_symbol_var = tk.StringVar(value="")
        self.te_type_var = tk.StringVar(value="BUY")
        self.te_currency_var = tk.StringVar(value="INR")

        type_col = tk.Frame(r2, bg=BG_SEC)
        type_col.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        _caption(type_col, "🚦 Type")
        type_btn_frame = tk.Frame(type_col, bg=BG_SEC)
        type_btn_frame.pack(anchor="w", pady=(2, 0))

        def _on_type_select(val):
            self.te_type_var.set(val)
            self._sync_te_type_buttons()
            self._update_summary()

        def _toggle(parent, text, command, width):
            return ModernButton(parent, text=text, command=command, bg=ModernStyle.BG_TERTIARY,
                                fg=ModernStyle.TEXT_SECONDARY, canvas_bg=BG_SEC, width=width, height=30, radius=6,
                                font=ModernStyle.FONT_TABLE_BOLD)

        self.te_buy_btn = _toggle(type_btn_frame, "BUY", lambda: _on_type_select("BUY"), 64)
        self.te_buy_btn.pack(side="left", padx=(0, 6))
        self.te_sell_btn = _toggle(type_btn_frame, "SELL", lambda: _on_type_select("SELL"), 64)
        self.te_sell_btn.pack(side="left")

        # Currency toggles: INR and JPY, plus any other currency a broker uses (added in load_data)
        cur_col = tk.Frame(r2, bg=BG_SEC)
        cur_col.grid(row=0, column=1, sticky="nsew")
        _caption(cur_col, "💱 Currency")
        self._currency_btn_frame = tk.Frame(cur_col, bg=BG_SEC)
        self._currency_btn_frame.pack(anchor="w", pady=(2, 0))
        self._cur_btns: dict = {}
        self._make_toggle = _toggle
        self._add_currency_buttons(["INR", "JPY"])
        self.te_inr_btn = self._cur_btns["INR"]
        self.te_jpy_btn = self._cur_btns["JPY"]

        # Row 3: Symbol | Quantity | Price
        r3 = tk.Frame(manual, bg=BG_SEC)
        r3.pack(fill="x", pady=(0, 10))
        for i in range(3):
            r3.grid_columnconfigure(i, weight=1, uniform="r3")
        self.te_qty_var = tk.StringVar(value="")
        self.te_price_var = tk.StringVar(value="")

        sym_col = tk.Frame(r3, bg=BG_SEC)
        sym_col.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        _caption(sym_col, "🔠 Symbol")
        self.te_symbol_entry, self._sym_wrap = _styled_entry(sym_col, self.te_symbol_var)

        qty_col = tk.Frame(r3, bg=BG_SEC)
        qty_col.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        _caption(qty_col, "💎 Quantity")
        self.te_qty_entry, self._qty_wrap = _styled_entry(qty_col, self.te_qty_var, validate="key", vcmd=vcmd_qty)

        price_col = tk.Frame(r3, bg=BG_SEC)
        price_col.grid(row=0, column=2, sticky="nsew")
        self.lbl_price = _caption(price_col, "💰 Price (₹)")
        self.te_price_entry, self._price_wrap = _styled_entry(price_col, self.te_price_var, validate="key", vcmd=vcmd)

        self.te_fee_label = tk.Label(manual, text="💸  Estimated Fee: ₹0.00", fg=ModernStyle.TEXT_SECONDARY,
                                     bg=BG_SEC, font=ModernStyle.FONT_HEADING)
        self.te_fee_label.pack(anchor="w", pady=(4, 0))
        tk.Frame(manual, bg=ModernStyle.DIVIDER_COLOR, height=1).pack(fill="x", pady=(8, 0))

        btns = tk.Frame(manual, bg=BG_SEC)
        btns.pack(fill="x", pady=(8, 0))
        tk.Frame(btns, bg=BG_SEC).pack(side="left", expand=True, fill="x")
        ModernButton(btns, text="Clear Form", command=self._clear_form, bg=ModernStyle.BG_TERTIARY,
                     fg=ModernStyle.TEXT_SECONDARY, canvas_bg=BG_SEC, width=120, height=40).pack(side="left", padx=(0, 12))
        self.te_save_btn = ModernButton(btns, text="✓ Save Trade", command=self._save_trade,
                                        bg=ModernStyle.SUCCESS_FILL, fg=ModernStyle.TEXT_ON_ACCENT,
                                        canvas_bg=BG_SEC, width=160, height=40)
        self.te_save_btn.pack(side="left")

        self.recent_trades_label = tk.Label(manual, text="", fg=ModernStyle.SUCCESS, bg=BG_SEC,
                                            font=ModernStyle.FONT_BODY_BOLD, anchor="w", justify="left")

        # ===== Bulk Import Card =====
        import_card, import_inner = _card(left, "Bulk Import (CSV)", "📥", bar=ModernStyle.WARNING_FILL,
                                          fg=ModernStyle.WARNING)
        import_card.pack(fill="x", pady=(0, 10))
        cols_hint = tk.Label(import_inner,
                             text="Columns: date, symbol, type, qty, price (needed); broker, fee, currency, trade_id "
                                  "(optional). Dates like 2024-01-15 or 15-01-2024.",
                             fg=ModernStyle.TEXT_SECONDARY, bg=BG_SEC, font=ModernStyle.FONT_SMALL, justify="left",
                             anchor="w", wraplength=420)
        cols_hint.pack(fill="x", pady=(0, 10))
        self._auto_wrap(cols_hint)

        dropzone = tk.Frame(import_inner, bg=ModernStyle.BG_TERTIARY, highlightbackground=ModernStyle.BORDER_COLOR,
                            highlightthickness=1)
        dropzone.pack(fill="x", pady=(2, 4), ipady=4)
        self.import_path_label = tk.Label(dropzone, text="Select a CSV file to import trades", fg=ModernStyle.TEXT_SECONDARY,
                                          bg=ModernStyle.BG_TERTIARY, font=ModernStyle.FONT_BODY_BOLD)
        self.import_path_label.pack(pady=(8, 8))
        imp_btns = tk.Frame(dropzone, bg=ModernStyle.BG_TERTIARY)
        imp_btns.pack(fill="x")
        tk.Frame(imp_btns, bg=ModernStyle.BG_TERTIARY).pack(side="left", expand=True, fill="x")
        ModernButton(imp_btns, text="Select CSV", variant="soft", command=self._select_import_file, bg=ModernStyle.WARNING_FILL,
                     fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_TERTIARY, width=148, height=36
                     ).pack(side="left", padx=(0, 10))
        self.import_confirm_btn = ModernButton(imp_btns, text="Preview Import",
                                               command=lambda: self._open_import_preview_dialog(source="csv"),
                                               bg=ModernStyle.SUCCESS_FILL, fg=ModernStyle.TEXT_ON_ACCENT,
                                               canvas_bg=ModernStyle.BG_TERTIARY, width=160, height=36)
        self.import_confirm_btn.pack(side="left")
        self.import_confirm_btn.set_disabled(True)
        tk.Frame(imp_btns, bg=ModernStyle.BG_TERTIARY).pack(side="left", expand=True, fill="x")

        self.import_status = tk.Label(import_inner, text="", fg=ModernStyle.TEXT_SECONDARY, bg=BG_SEC,
                                      font=ModernStyle.FONT_SMALL_BOLD, justify="left", anchor="w", wraplength=420)
        self.import_status.pack(fill="x", pady=(2, 0))
        self._auto_wrap(self.import_status)

        # ===== Paste Import Card =====
        paste_card, paste_inner = _card(left, "Paste Import", "📋", bar=ModernStyle.PURPLE_FILL,
                                        fg=ModernStyle.TEXT_PURPLE, expand_height=True)
        paste_card.pack(fill="both", expand=True, pady=(0, 5))

        hint_text = tk.Text(paste_inner, height=2, bg=BG_SEC, font=ModernStyle.FONT_SMALL, relief="flat",
                            highlightthickness=0, wrap="word", cursor="arrow")
        hint_text.pack(fill="x", pady=(0, 5))
        hint_text.tag_configure("normal", foreground=ModernStyle.TEXT_SECONDARY)
        hint_text.tag_configure("highlight", foreground=ModernStyle.TEXT_ACCENT)
        hint_text.insert("end", "Tab- or comma-separated", "highlight")
        hint_text.insert("end", " rows with a header: ", "normal")
        hint_text.insert("end", "date, symbol, type, qty, price, [broker], [fee], [trade_id]", "highlight")
        hint_text.config(state="disabled")

        ModernButton(paste_card.header_frame, text="Parse & Preview", command=self._parse_and_preview_pasted,
                     bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=BG_SEC, width=150,
                     height=32, font=ModernStyle.FONT_SMALL_BOLD).pack(side="right", padx=(10, 0))
        ModernButton(paste_card.header_frame, text="Clear", command=self._clear_paste_area, bg=ModernStyle.BG_TERTIARY,
                     fg=ModernStyle.TEXT_SECONDARY, canvas_bg=BG_SEC, width=80, height=32,
                     font=ModernStyle.FONT_SMALL_BOLD).pack(side="right")

        self._paste_status = tk.Label(paste_inner, text="", fg=ModernStyle.TEXT_SECONDARY, bg=BG_SEC,
                                      font=ModernStyle.FONT_SMALL_BOLD, justify="left", anchor="w", wraplength=420)
        self._paste_status.pack(side="bottom", fill="x", pady=(8, 0))
        self._auto_wrap(self._paste_status)

        ta_frame = tk.Frame(paste_inner, bg=ModernStyle.BORDER_COLOR, padx=1, pady=1)
        ta_frame.pack(side="top", fill="both", expand=True)
        ta_scroll = ttk.Scrollbar(ta_frame, orient="vertical")
        self._paste_area = tk.Text(ta_frame, height=5, bg=ModernStyle.ENTRY_BG, fg=ModernStyle.TEXT_PRIMARY,
                                   font=ModernStyle.FONT_TABLE, relief=tk.FLAT, wrap="none", undo=True,
                                   insertbackground=ModernStyle.ACCENT_PRIMARY, yscrollcommand=ta_scroll.set)
        ta_scroll.config(command=self._paste_area.yview)
        self._paste_area.pack(side="left", fill="both", expand=True, padx=6, ipady=3)
        ta_scroll.pack(side="right", fill="y")

        # The example rows are only a placeholder (grey); they are never imported.
        self._paste_hint_shown = False
        self._show_paste_hint()

        def _on_paste_focus_in(_e):
            if self._paste_hint_shown:
                self._paste_area.delete("1.0", "end")
                self._paste_area.config(fg=ModernStyle.TEXT_PRIMARY)
                self._paste_hint_shown = False

        def _on_paste_focus_out(_e):
            if not self._paste_area.get("1.0", "end-1c").strip():
                self._show_paste_hint()
        self._paste_area.bind("<FocusIn>", _on_paste_focus_in)
        self._paste_area.bind("<FocusOut>", _on_paste_focus_out)

        # ===== Skipped Duplicates Card =====
        self.dupe_card, dupe_inner = _card(left, "Skipped Duplicates", "⚠️", bar=ModernStyle.WARNING_FILL,
                                           fg=ModernStyle.WARNING)
        dupe_cols = ("#", "Date", "Symbol", "Qty", "Why")
        self.dupe_table = ttk.Treeview(dupe_inner, columns=dupe_cols, show="headings", height=6)
        for c, w in zip(dupe_cols, (44, 100, 100, 60, 260)):
            anchor = "center" if c == "#" else "w"
            self.dupe_table.heading(c, text=c, anchor=anchor)
            self.dupe_table.column(c, width=w, anchor=anchor)
        add_treeview_copy_menu(self.dupe_table)
        vsb = ttk.Scrollbar(dupe_inner, orient="vertical", command=self.dupe_table.yview)
        self.dupe_table.configure(yscroll=vsb.set)
        self.dupe_table.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # ===== Transaction Summary Card (right column) =====
        self.sum_card, sum_inner = _card(right, "Transaction Summary", "")
        self.sum_card.pack(fill="x", pady=(0, 14))

        def _sum_row(lbl: str, init: str):
            row = tk.Frame(sum_inner, bg=BG_SEC)
            row.pack(fill="x", pady=6)
            tk.Label(row, text=lbl, fg=ModernStyle.TEXT_SECONDARY, bg=BG_SEC, font=ModernStyle.FONT_BODY).pack(side="left")
            val = tk.Label(row, text=init, fg=ModernStyle.TEXT_PRIMARY, bg=BG_SEC, font=ModernStyle.FONT_BODY_BOLD)
            val.pack(side="right")
            return val

        self.sum_type_label = _sum_row("Trade type", "BUY")
        self.sum_qty_label = _sum_row("Quantity", "—")
        self.sum_price_label = _sum_row("Unit price", "—")
        self.sum_subtotal_label = _sum_row("Subtotal", "—")
        self.sum_fee_label = _sum_row("Est. fee", "0.00")
        tk.Frame(sum_inner, bg=ModernStyle.DIVIDER_COLOR, height=1).pack(fill="x", pady=(8, 6))
        total_row = tk.Frame(sum_inner, bg=BG_SEC)
        total_row.pack(fill="x", pady=(4, 0))
        tk.Label(total_row, text="Total value", fg=ModernStyle.TEXT_PRIMARY, bg=BG_SEC,
                 font=ModernStyle.FONT_SUBHEADING).pack(side="left")
        self.sum_total_label = tk.Label(total_row, text="0.00", fg=ModernStyle.SUCCESS, bg=BG_SEC,
                                        font=ModernStyle.FONT_KPI_VALUE)
        self.sum_total_label.pack(side="right")

        # ===== Portfolio Snapshot Card =====
        snap_card, snap_inner = _card(right, "Portfolio Snapshot", "📊", bar=ModernStyle.INFO_FILL, fg=ModernStyle.INFO)
        snap_card.pack(fill="x")
        snap_grid = tk.Frame(snap_inner, bg=BG_SEC)
        snap_grid.pack(fill="both", expand=True)
        snap_grid.grid_columnconfigure(0, weight=1, uniform="snap")
        snap_grid.grid_columnconfigure(1, weight=1, uniform="snap")
        self._snap_labels = {}

        def _snap_tile(row, col, icon, title, key, bar, fg):
            tile = tk.Frame(snap_grid, bg=ModernStyle.BG_TERTIARY, padx=1, pady=1)
            tile.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)
            inner = tk.Frame(tile, bg=BG_SEC)
            inner.pack(fill="both", expand=True, padx=1, pady=1)
            tk.Frame(inner, bg=bar, height=3).pack(fill="x")
            tbody = tk.Frame(inner, bg=BG_SEC)
            tbody.pack(fill="both", expand=True, padx=10, pady=(8, 10))
            hdr = tk.Frame(tbody, bg=BG_SEC)
            hdr.pack(fill="x")
            tk.Label(hdr, text=icon, fg=fg, bg=BG_SEC, font=ModernStyle.FONT_BODY).pack(side="left", padx=(0, 4))
            tk.Label(hdr, text=title, fg=ModernStyle.TEXT_SECONDARY, bg=BG_SEC,
                     font=ModernStyle.FONT_KPI_LABEL).pack(side="left")
            val_lbl = tk.Label(tbody, text="—", fg=fg, bg=BG_SEC, font=ModernStyle.FONT_KPI_VALUE)
            val_lbl.pack(anchor="w", pady=(4, 0))
            self._snap_labels[key] = val_lbl

        _snap_tile(0, 0, "📦", "Holdings", "snap_holdings", ModernStyle.ACCENT_PRIMARY, ModernStyle.TEXT_ACCENT)
        _snap_tile(0, 1, "📥", "Invested", "snap_invested", ModernStyle.SUCCESS_FILL, ModernStyle.SUCCESS)
        _snap_tile(1, 0, "💼", "Current Value", "snap_current", ModernStyle.INFO_FILL, ModernStyle.INFO)
        _snap_tile(1, 1, "📈", "Overall P&L", "snap_pnl", ModernStyle.PURPLE_FILL, ModernStyle.TEXT_PURPLE)
        self._snap_hint = tk.Label(snap_inner, text="", fg=ModernStyle.TEXT_SECONDARY, bg=BG_SEC,
                                   font=ModernStyle.FONT_BODY_BOLD)
        self._snap_hint.pack(anchor="w", pady=(6, 0))

        # Cards change height as they lay out (or when one is shown): re-fit the scrolling page.
        self._fit_pending = False
        for card in (manual_card, import_card, paste_card, self.dupe_card, self.sum_card, snap_card):
            card.bind("<Configure>", lambda e: self._schedule_fit(), add="+")

        # Live updates. The currency follows the broker, and the buttons follow the currency.
        self.te_broker_var.trace_add("write", lambda *_: self._on_broker_change())
        self.te_currency_var.trace_add("write", lambda *_: self._on_currency_change())
        for v in (self.te_qty_var, self.te_price_var):
            v.trace_add("write", lambda *_: self._update_summary())

        self._sync_te_type_buttons()
        self._on_currency_change()

    # ── Small helpers ───────────────────────────────────────────────────────────
    def _fit_page(self) -> None:
        """Give the page the window's size, or its own height when that is taller (then it scrolls)."""
        c = self._page_canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w <= 1:
            return
        need = self._page.winfo_reqheight()
        height = max(h, need)
        c.itemconfigure(self._page_item, width=w, height=height)
        c.configure(scrollregion=(0, 0, w, height))
        if need > h + 2:
            if not self._page_vsb.winfo_ismapped():
                self._page_vsb.pack(side="right", fill="y")
        else:
            if self._page_vsb.winfo_ismapped():
                self._page_vsb.pack_forget()
            c.yview_moveto(0)

    def _schedule_fit(self) -> None:
        if not self._fit_pending:
            self._fit_pending = True

            def _run():
                self._fit_pending = False
                self._fit_page()
            self.after_idle(_run)

    def _on_page_wheel(self, event) -> None:
        """Scroll the page, except over the paste box and tables (they scroll themselves)."""
        if isinstance(event.widget, (tk.Text, ttk.Treeview)) or not self._page_vsb.winfo_ismapped():
            return
        try:
            step = -1 if event.delta > 0 else 1
            if sys.platform != "darwin":
                step = int(-event.delta / 120) or step
            self._page_canvas.yview_scroll(step * 2, "units")
        except tk.TclError:
            pass

    @staticmethod
    def _auto_wrap(label: tk.Label) -> None:
        """Wrap a label's text to its own width (packed with fill="x")."""
        label.bind("<Configure>", lambda e: e.width > 40 and label.configure(wraplength=e.width - 8))

    def _toast(self, msg: str, kind: str = "error") -> None:
        show_toast(self.winfo_toplevel(), msg, type=kind)

    def _validate_number(self, value: str) -> bool:
        """Allow only numeric input (integers or decimals) in entry fields."""
        if value == "":
            return True
        try:
            float(value)
            return True
        except ValueError:
            return value.count(".") == 1 and value.replace(".", "").isdigit()

    def _validate_qty(self, value: str) -> bool:
        """INR quantities are whole shares; other currencies may have fractions (fund units)."""
        if value == "":
            return True
        if (self.te_currency_var.get() or "INR").upper() == "INR":
            return value.isdigit()
        return self._validate_number(value)

    @staticmethod
    def _parse_float(s: str) -> float:
        try:
            return float(str(s).strip())
        except ValueError:
            return 0.0

    def _add_currency_buttons(self, currencies) -> None:
        for code in currencies:
            code = (code or "").strip().upper()
            if not code or code in self._cur_btns:
                continue
            btn = self._make_toggle(self._currency_btn_frame, code, lambda c=code: self.te_currency_var.set(c), 58)
            btn.pack(side="left", padx=(0, 6))
            self._cur_btns[code] = btn
        if hasattr(self, "lbl_price"):
            self._sync_currency_buttons()

    def _sync_te_type_buttons(self) -> None:
        """Colour the BUY/SELL toggles."""
        if (self.te_type_var.get() or "BUY").upper() == "BUY":
            self.te_buy_btn.set_palette(bg=ModernStyle.SUCCESS_FILL, fg=ModernStyle.TEXT_ON_ACCENT)
            self.te_sell_btn.set_palette(bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_SECONDARY)
        else:
            self.te_sell_btn.set_palette(bg=ModernStyle.ERROR_FILL, fg=ModernStyle.TEXT_ON_ACCENT)
            self.te_buy_btn.set_palette(bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_SECONDARY)

    def _sync_currency_buttons(self) -> None:
        """Colour the currency toggles and show the right symbol on the price label."""
        cur = (self.te_currency_var.get() or "INR").upper()
        for code, btn in self._cur_btns.items():
            if code == cur:
                btn.set_palette(bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT)
            else:
                btn.set_palette(bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_SECONDARY)
        self.lbl_price.config(text=f"💰 Price ({currency_symbol(cur)})")

    def _broker_currencies(self) -> dict:
        try:
            if self.app_state is not None:
                return dict(self.app_state.get_broker_currencies_cached() or {})
        except Exception:
            log.exception("Reading broker currencies failed")
        return {}

    def _on_broker_change(self) -> None:
        cur = self._broker_currencies().get(self.te_broker_var.get())
        self.te_currency_var.set((cur or "INR").upper())

    def _on_currency_change(self) -> None:
        cur = (self.te_currency_var.get() or "INR").upper()
        if cur not in self._cur_btns:
            self._add_currency_buttons([cur])
        self._sync_currency_buttons()
        if cur == "INR":   # INR quantities are whole shares
            qty_str = self.te_qty_var.get()
            if "." in qty_str:
                try:
                    self.te_qty_var.set(str(int(float(qty_str))))
                except ValueError:
                    self.te_qty_var.set("")
        self._update_summary()

    def _invalidate_other_views(self):
        """Tell the other pages their data is stale, so they reload when shown."""
        vm = None
        w = self
        while w is not None:
            vm = getattr(w, "view_manager", None) or getattr(getattr(w, "_ptracker_app", None), "view_manager", None)
            if vm is not None:
                break
            w = getattr(w, "master", None)
        for view in getattr(vm, "views", {}).values():
            if view is not self and hasattr(view, "_data_loaded"):
                view._data_loaded = False

    # ── Showing ─────────────────────────────────────────────────────────────────
    def on_show(self):
        self._data_loaded = False
        self.load_data()

    def load_data(self):
        if getattr(self, "_data_loaded", False):
            return
        self._data_loaded = True
        try:
            brokers = list(self.app_state.get_brokers_cached()) if self.app_state is not None else []
        except Exception:
            log.exception("Reading the broker list failed")
            brokers = []
        self._brokers = brokers
        self.te_broker_cb["values"] = brokers
        self._add_currency_buttons(sorted(set(c.upper() for c in self._broker_currencies().values() if c)))
        if brokers and self.te_broker_var.get() not in brokers:
            self.te_broker_var.set(brokers[0])
        self._load_snapshot()

    def _load_snapshot(self) -> None:
        """Portfolio KPIs in the background; only the newest result is shown."""
        self._snapshot_gen += 1
        gen = self._snapshot_gen

        def _work():
            from model.engine import get_dashboard_metrics
            from model.database import db_session
            metrics = get_dashboard_metrics()
            with db_session() as conn:
                row = conn.execute("SELECT COUNT(*) FROM holdings WHERE qty > 0").fetchone()
            return metrics, (row[0] if row else 0)

        def _done(res):
            if gen == self._snapshot_gen:
                self._apply_snapshot(*res)

        run_in_background(_work, _done, widget=self, name="trade-entry-snapshot")

    def _apply_snapshot(self, metrics: dict, holdings_count: int) -> None:
        invested = float(metrics.get("total_invested", 0.0) or 0.0)
        current_val = float(metrics.get("total_value", 0.0) or 0.0)
        pnl = float(metrics.get("overall_pnl", 0.0) or 0.0)
        pnl_pct = (pnl / invested * 100.0) if invested > 0 else 0.0

        def _compact(v):
            """Portfolio totals are INR-converted: ₹89.27L, ₹12.5K, ₹950."""
            f = abs(float(v or 0.0))
            if f >= 1_00_000:
                return f"₹{f / 1_00_000:.2f}L"
            if f >= 1_000:
                return f"₹{f / 1_000:.1f}K"
            return f"₹{f:,.0f}"

        self._snap_labels["snap_holdings"].config(text=str(holdings_count))
        self._snap_labels["snap_invested"].config(text=_compact(invested))
        self._snap_labels["snap_current"].config(text=_compact(current_val))
        self._snap_labels["snap_pnl"].config(text=f"{'▲' if pnl >= 0 else '▼'} {_compact(pnl)}",
                                             fg=ModernStyle.SUCCESS if pnl >= 0 else ModernStyle.ERROR)
        self._snap_hint.config(text=f"Return: {pnl_pct:+.2f}%  •  Updated {datetime.now().strftime('%H:%M')}")

    # ── Manual entry ────────────────────────────────────────────────────────────
    def _estimated_fee(self, t_type: str, qty: float, price: float, currency: str) -> float:
        """Indian (NSE) charges apply to INR trades only."""
        if currency != "INR" or qty <= 0 or price <= 0:
            return 0.0
        try:
            from model.engine import calculate_trade_fees
            return float(calculate_trade_fees(t_type, qty, price, is_delivery=True) or 0.0)
        except Exception:
            log.exception("Fee estimate failed")
            return 0.0

    def _update_summary(self) -> None:
        t_type = (self.te_type_var.get() or "BUY").upper()
        cur = (self.te_currency_var.get() or "INR").upper()
        qty_str = self.te_qty_var.get().strip()
        price_str = self.te_price_var.get().strip()
        qty = self._parse_float(qty_str)
        price = self._parse_float(price_str)

        # Focus ring: red when the value is wrong
        focus = self.focus_get()
        for wrap, text, val, entry in ((self._qty_wrap, qty_str, qty, self.te_qty_entry),
                                       (self._price_wrap, price_str, price, self.te_price_entry)):
            if text and val <= 0:
                want = ModernStyle.ERROR
            else:
                want = ModernStyle.ACCENT_PRIMARY if focus == entry else ModernStyle.BORDER_COLOR
            if wrap.cget("bg") != want:
                wrap.configure(bg=want)

        subtotal = qty * price
        fee = self._estimated_fee(t_type, qty, price, cur)
        total = subtotal + fee if t_type == "BUY" else max(0.0, subtotal - fee)
        color = ModernStyle.SUCCESS if t_type == "BUY" else ModernStyle.ERROR

        tint = ModernStyle.SUCCESS_PALE if t_type == "BUY" else ModernStyle.ERROR_PALE
        if tint != self._sum_tint:   # only when BUY/SELL changes (each change redraws the window)
            self._sum_tint = tint
            self.sum_card.content.configure(bg=tint)

        if cur == "INR":
            self.te_fee_label.config(text=f"💸  Estimated Fee: {format_money(fee, cur)}")
        else:
            self.te_fee_label.config(text="💸  Estimated Fee: none (Indian charges apply to INR trades only)")
        self.sum_type_label.config(text=t_type, fg=color)
        self.sum_qty_label.config(text=f"{qty:g}" if qty > 0 else "—")
        self.sum_price_label.config(text=format_money(price, cur) if price > 0 else "—")
        self.sum_subtotal_label.config(text=format_money(subtotal, cur) if subtotal > 0 else "—")
        self.sum_fee_label.config(text=format_money(fee, cur))
        self.sum_total_label.config(text=format_money(total, cur), fg=color)

    def _clear_form(self) -> None:
        self.te_symbol_var.set("")
        self.te_qty_var.set("")
        self.te_price_var.set("")
        self.te_type_var.set("BUY")
        self._sync_te_type_buttons()
        self._update_summary()

    def _set_saving(self, busy: bool) -> None:
        self._saving = busy
        try:
            self.te_save_btn.set_disabled(busy)
        except tk.TclError:
            pass

    def _save_trade(self) -> None:
        if self._saving:
            return   # a save is already running (double click)
        broker = (self.te_broker_var.get() or "").strip()
        date = (self.te_date_var.get() or "").strip()
        symbol = (self.te_symbol_var.get() or "").strip().upper()
        t_type = (self.te_type_var.get() or "BUY").strip().upper()
        cur = (self.te_currency_var.get() or "INR").strip().upper()
        qty_str = self.te_qty_var.get().strip()
        price_str = self.te_price_var.get().strip()

        if not broker:
            return self._toast("Please select a broker.")
        if not date:
            return self._toast("Please select or enter a date.")
        try:
            trade_day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return self._toast(f"'{date}' isn't a date. Use year-month-day, like 2024-01-15.")
        if trade_day > _date.today():
            return self._toast("The date is in the future.")
        if not symbol:
            return self._toast("Please enter a trading symbol.")
        if not qty_str:
            return self._toast("Please enter a quantity.")
        if not price_str:
            return self._toast("Please enter a price.")
        qty = self._parse_float(qty_str)
        price = self._parse_float(price_str)
        if qty <= 0:
            return self._toast("Quantity must be more than 0.")
        if cur == "INR" and qty != int(qty):
            return self._toast("INR quantities must be whole shares.")
        if price <= 0:
            return self._toast("Price must be more than 0.")
        fee = self._estimated_fee(t_type, qty, price, cur)

        self._set_saving(True)
        recent = (_date.today() - trade_day).days <= 60

        def _last_price():
            """The latest known market price, to catch a typo like 35000 for 3500 (recent trades only)."""
            if not recent:
                return None
            from model.database import db_session
            with db_session() as conn:
                row = conn.execute("SELECT current_price FROM marketdata WHERE symbol = ?", (symbol,)).fetchone()
            return float(row[0]) if row and row[0] else None

        def _write():
            import time
            import uuid
            import model.crud as crud
            manual_id = f"MT_{date.replace('-', '')}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}"
            crud.add_trade(broker, date, symbol, t_type, qty, price, fee, manual_id, currency=cur)

        def _saved(_):
            self._set_saving(False)
            self._toast(f"Saved {t_type} {symbol}", "success")
            self.recent_trades_label.config(
                text=f"✓ {datetime.now().strftime('%H:%M:%S')} - Saved {t_type} {qty:g} {symbol} @ {format_money(price, cur)}")
            if not self.recent_trades_label.winfo_ismapped():
                self.recent_trades_label.pack(anchor="w", pady=(10, 0))
                self._schedule_fit()
            self._clear_form()
            app_state = self.app_state

            def _after_refresh(warning):
                self._invalidate_other_views()
                self._load_snapshot()
                show_stale_warning(self, warning)
            run_in_background(lambda: refresh_after_change(app_state), _after_refresh, widget=self, name="after-save")

        def _failed(e):
            self._set_saving(False)
            self._toast(f"The trade wasn't saved: {friendly_error(e)}")

        def _checked(last):
            if not confirm_unusual(self.winfo_toplevel(), qty, price, cur, last):
                self._set_saving(False)
                return
            run_in_background(_write, _saved, _failed, widget=self, name="save-trade")

        run_in_background(_last_price, _checked, lambda e: _checked(None), widget=self, name="last-price")

    # ── Paste import ────────────────────────────────────────────────────────────
    def _show_paste_hint(self) -> None:
        self._paste_area.delete("1.0", "end")
        self._paste_area.insert("1.0", PASTE_HINT)
        self._paste_area.config(fg=ModernStyle.TEXT_TERTIARY)
        self._paste_hint_shown = True

    def _pasted_text(self) -> str:
        """What the user pasted; the grey example rows count as nothing."""
        if self._paste_hint_shown:
            return ""
        text = self._paste_area.get("1.0", "end-1c").strip()
        return "" if text == PASTE_HINT.strip() else text

    def _clear_paste_area(self) -> None:
        self._paste_area.delete("1.0", "end")
        self._paste_area.config(fg=ModernStyle.TEXT_PRIMARY)
        self._paste_hint_shown = False
        self._paste_status.config(text="")
        if self.focus_get() is not self._paste_area:
            self._show_paste_hint()

    def _parse_and_preview_pasted(self) -> None:
        """Read the pasted rows and open the preview (the checks run there, in the background)."""
        raw = self._pasted_text()
        if not raw:
            self._paste_status.config(text="⚠️ Nothing pasted yet. Paste rows with a header line first.",
                                      fg=ModernStyle.WARNING)
            return
        try:
            df = parse_pasted_text(raw)
        except ImportProblem as e:
            self._paste_status.config(text=f"❌ {e}", fg=ModernStyle.ERROR)
            return
        except Exception:
            log.exception("Reading pasted rows failed")
            self._paste_status.config(text="❌ The rows couldn't be read. Check the header line.", fg=ModernStyle.ERROR)
            return
        missing = missing_columns(df)
        if missing:
            self._paste_status.config(text=f"❌ Missing columns: {', '.join(missing)}", fg=ModernStyle.ERROR)
            return
        if df.empty:
            self._paste_status.config(text="❌ There are no rows under the header.", fg=ModernStyle.ERROR)
            return
        self.pending_paste_df = df
        self._paste_status.config(text=f"📋 {len(df)} rows read — checking them in the preview…", fg=ModernStyle.INFO)
        self._open_import_preview_dialog(source="paste")

    # ── CSV import ──────────────────────────────────────────────────────────────
    def _select_import_file(self) -> None:
        from tkinter import filedialog
        import os

        path = filedialog.askopenfilename(title="Select CSV", filetypes=[("CSV files", "*.csv"), ("All files", "*")])
        if not path:
            return
        self.import_status.config(text="⏳ Loading CSV…", fg=ModernStyle.INFO)

        def _work():
            df = read_csv_file(path)
            missing = missing_columns(df)
            if missing:
                raise ImportProblem(f"The file has no {', '.join(missing)} column. "
                                    "The first line must be a header like: date,symbol,type,qty,price")
            if df.empty:
                raise ImportProblem("The file has no rows under the header.")
            return df

        def _done(df):
            self.pending_csv_df = df
            self.pending_csv_name = os.path.basename(path)
            self.import_path_label.config(text=f"{self.pending_csv_name} • {len(df)} rows")
            self.import_status.config(text="✅ File read. Check the preview, then press Import.", fg=ModernStyle.SUCCESS)
            self.import_confirm_btn.set_disabled(False)
            self._open_import_preview_dialog(source="csv", auto=True)

        def _failed(e):
            msg = str(e) if isinstance(e, ImportProblem) else "The file couldn't be read. Is it a CSV file?"
            self.import_status.config(text=f"❌ {msg}", fg=ModernStyle.ERROR)

        run_in_background(_work, _done, _failed, widget=self, name="read-csv")

    # ── Preview + import ────────────────────────────────────────────────────────
    def _open_import_preview_dialog(self, source: str = "csv", auto: bool = False) -> None:
        if source == "csv":
            df, origin = self.pending_csv_df, f"From {self.pending_csv_name or 'the CSV file'}"
            err_msg = "Select a CSV file first"
        else:
            df, origin = self.pending_paste_df, "From the pasted rows"
            err_msg = "Paste some rows and press Parse & Preview first"
        if df is None:
            if not auto:
                self._toast(err_msg)
            return

        win = self._import_preview_win
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_force()
            return

        has_broker = "broker" in df.columns
        app_state = self.app_state
        broker_currencies = self._broker_currencies()

        top = tk.Toplevel(self)
        self._import_preview_win = top
        top.title("Bulk Import Preview")
        ModernStyle.style_modal(top)
        top.geometry("1060x660")
        top.minsize(820, 520)
        try:
            top.transient(self.winfo_toplevel())
            top.grab_set()
        except tk.TclError:
            pass
        center_window(top, parent=self.winfo_toplevel())

        BG = ModernStyle.BG_PRIMARY
        tk.Frame(top, bg=ModernStyle.SUCCESS_FILL, height=4).pack(fill="x")
        hdr = tk.Frame(top, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(hdr, text="Bulk Import • Preview", fg=ModernStyle.TEXT_PRIMARY, bg=BG,
                 font=ModernStyle.FONT_TITLE).pack(anchor="w")
        tk.Label(hdr, text=f"{origin} • {len(df):,} rows. Nothing is saved until you press Import.",
                 fg=ModernStyle.TEXT_SECONDARY, bg=BG, font=ModernStyle.FONT_BODY).pack(anchor="w")

        body = tk.Frame(top, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        # Broker choice + buttons
        opts = tk.Frame(body, bg=BG)
        opts.pack(fill="x", pady=(0, 6))
        btn_box = tk.Frame(opts, bg=BG)
        btn_box.pack(side="right")
        tk.Label(opts, text="🏦  Broker for rows without one:" if has_broker else "🏦  Broker:",
                 fg=ModernStyle.TEXT_SECONDARY, bg=BG, font=ModernStyle.FONT_HEADING).pack(side="left")
        broker_var = tk.StringVar(value=self.te_broker_var.get() if self.te_broker_var.get() in self._brokers else "")
        broker_cb = ttk.Combobox(opts, textvariable=broker_var, state="readonly", width=18, values=self._brokers)
        broker_cb.pack(side="left", padx=(8, 12))
        currency_lbl = tk.Label(opts, text="", fg=ModernStyle.TEXT_SECONDARY, bg=BG, font=ModernStyle.FONT_BODY)
        currency_lbl.pack(side="left")

        # Counts: "N will be imported, M rejected, D look like duplicates"
        counts = tk.Frame(body, bg=BG)
        counts.pack(fill="x", pady=(4, 2))
        count_lbls = {}
        for key, fg in (("ok", ModernStyle.SUCCESS), ("bad", ModernStyle.ERROR), ("dup", ModernStyle.WARNING)):
            count_lbls[key] = tk.Label(counts, text="", fg=fg, bg=BG, font=ModernStyle.FONT_HEADING)
            count_lbls[key].pack(side="left", padx=(0, 18))
        skip_saved_var = tk.BooleanVar(value=True)
        skip_repeats_var = tk.BooleanVar(value=False)
        checks = tk.Frame(body, bg=BG)
        checks.pack(fill="x")
        cb_kw = dict(bg=BG, fg=ModernStyle.TEXT_PRIMARY, activebackground=BG, activeforeground=ModernStyle.TEXT_PRIMARY,
                     selectcolor=ModernStyle.ENTRY_BG, font=ModernStyle.FONT_BODY, anchor="w", justify="left")
        saved_chk = tk.Checkbutton(checks, variable=skip_saved_var, **cb_kw)
        repeats_chk = tk.Checkbutton(checks, variable=skip_repeats_var, **cb_kw)
        notes_lbl = tk.Label(body, text="", fg=ModernStyle.TEXT_SECONDARY, bg=BG, font=ModernStyle.FONT_SMALL,
                             justify="left", anchor="w", wraplength=980)
        notes_lbl.pack(fill="x", pady=(2, 4))

        # Table
        table = tk.Frame(body, bg=BG)
        table.pack(fill="both", expand=True)
        cols = ("#", "Status", "Broker", "Date", "Symbol", "Type", "Qty", "Price", "Fee", "Currency", "Trade ID")
        widths = (50, 270, 100, 96, 100, 56, 64, 90, 70, 70, 130)
        style = ttk.Style(table)
        style.configure("BulkPreview.Treeview", font=ModernStyle.FONT_TABLE, rowheight=ModernStyle.TABLE_ROW_HEIGHT)
        style.configure("BulkPreview.Treeview.Heading", font=ModernStyle.FONT_TABLE_BOLD)
        tv = ttk.Treeview(table, style="BulkPreview.Treeview", columns=cols, show="headings", height=12)
        for c, w in zip(cols, widths):
            tv.heading(c, text=c, anchor="w")
            tv.column(c, width=w, minwidth=40, anchor="w", stretch=(c == "Status"))
        tv.tag_configure("BUY", foreground=ModernStyle.SUCCESS)
        tv.tag_configure("SELL", foreground=ModernStyle.ERROR)
        tv.tag_configure("rejected", background=ModernStyle.ERROR_PALE, foreground=ModernStyle.ERROR)
        tv.tag_configure("dupe", background=ModernStyle.WARNING_PALE, foreground=ModernStyle.WARNING)
        add_treeview_copy_menu(tv)
        vsb = ttk.Scrollbar(table, orient="vertical", command=tv.yview)
        hsb = ttk.Scrollbar(table, orient="horizontal", command=tv.xview)
        tv.configure(yscroll=vsb.set, xscroll=hsb.set)
        tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table.grid_rowconfigure(0, weight=1)
        table.grid_columnconfigure(0, weight=1)

        footer = tk.Frame(body, bg=BG)
        footer.pack(fill="x", pady=(8, 0))
        status = tk.Label(footer, text="", fg=ModernStyle.TEXT_SECONDARY, bg=BG, font=ModernStyle.FONT_BODY_BOLD,
                          justify="left", anchor="w", wraplength=760)
        status.pack(side="left", fill="x", expand=True)

        state = {"result": None, "gen": 0, "index": None, "busy": False}

        def _close():
            if not state["busy"]:
                top.destroy()
        top.protocol("WM_DELETE_WINDOW", _close)

        close_btn = ModernButton(btn_box, text="Close", command=_close, bg=ModernStyle.NEUTRAL_FILL,
                                 fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=BG, width=96, height=36)
        close_btn.pack(side="right")
        import_btn = ModernButton(btn_box, text="Import", command=lambda: _import(), bg=ModernStyle.SUCCESS_FILL,
                                  fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=BG, width=190, height=36, disabled=True)
        import_btn.pack(side="right", padx=(0, 10))

        def _trade_values(t):
            trade_id, broker, d, sym, typ, q, p, fee, cur = t
            return (broker, d, sym, typ, f"{q:g}", format_money(p, cur), format_money(fee, cur), cur, trade_id)

        def _dupe_status(d):
            skipped = d.kind == "id" or (d.kind == "saved" and skip_saved_var.get()) or \
                (d.kind == "file" and skip_repeats_var.get())
            return ("⚠ Skipped: " if skipped else "⚠ Will import: ") + d.reason

        def _update_counts():
            r = state["result"]
            if r is None:
                return
            skip_saved, skip_repeats = skip_saved_var.get(), skip_repeats_var.get()
            n = len(r.trades_to_import(skip_saved, skip_repeats))
            d = len(r.duplicates)
            count_lbls["ok"].config(text=f"✅ {n:,} will be imported")
            count_lbls["bad"].config(text=f"⛔ {len(r.rejected):,} rejected")
            count_lbls["dup"].config(text=f"⚠️ {d:,} {'looks like a duplicate' if d == 1 else 'look like duplicates'}")
            import_btn.set_text(f"Import {n:,} trade{'s' if n != 1 else ''}")
            import_btn.set_disabled(n == 0 or state["busy"])
            for dd in r.duplicates:
                iid = f"d{dd.row}"
                if tv.exists(iid):
                    tv.set(iid, "Status", _dupe_status(dd))

        def _show(r):
            state["result"] = r
            children = tv.get_children()
            if children:
                tv.delete(*children)
            for rej in r.rejected:
                raw = rej.raw
                tv.insert("", "end", iid=f"r{rej.row}", tags=("rejected",), values=(
                    rej.row, "⛔ " + rej.reason, raw.get("broker", "") or broker_var.get(), raw.get("date", ""),
                    raw.get("symbol", ""), raw.get("type", ""), raw.get("qty", ""), raw.get("price", ""),
                    raw.get("fee", ""), raw.get("currency", ""), raw.get("trade_id", "")))
            for d in r.duplicates:
                tv.insert("", "end", iid=f"d{d.row}", tags=("dupe",),
                          values=(d.row, _dupe_status(d)) + _trade_values(d.trade))
            for row_no, t in list(zip(r.valid_rows, r.valid))[:PREVIEW_READY_ROWS]:
                tv.insert("", "end", iid=f"v{row_no}", tags=(t[4],), values=(row_no, "✓ Ready") + _trade_values(t))

            n_saved, n_rep = r.duplicate_count("saved"), r.duplicate_count("file")
            saved_chk.config(text=f"Skip the {n_saved} row{'s that match' if n_saved != 1 else ' that matches'} "
                                  "trades you already have (recommended)")
            repeats_chk.config(text=f"Skip the {n_rep} row{'s that repeat' if n_rep != 1 else ' that repeats'} an "
                                    "earlier row of this file (one order filled in parts can look like this)")
            saved_chk.pack_forget()
            repeats_chk.pack_forget()
            if n_saved:
                saved_chk.pack(anchor="w")
            if n_rep:
                repeats_chk.pack(anchor="w")

            notes = []
            if r.rejected or r.duplicates:
                notes.append("Rows with problems are listed first.")
            if len(r.valid) > PREVIEW_READY_ROWS:
                notes.append(f"Showing the first {PREVIEW_READY_ROWS:,} of {len(r.valid):,} ready rows.")
            if r.warnings:
                more = f" (+{len(r.warnings) - 3} more)" if len(r.warnings) > 3 else ""
                notes.append("Please check: " + " • ".join(r.warnings[:3]) + more)
            notes_lbl.config(text="  ".join(notes), fg=ModernStyle.WARNING if r.warnings else ModernStyle.TEXT_SECONDARY)
            status.config(text="")
            _update_counts()

        def _validate(*_):
            chosen = broker_var.get()
            cur = broker_currencies.get(chosen, "")
            currency_lbl.config(text=f"💱 Currency: {cur} ({chosen}'s currency)" if cur and not has_broker
                                else "💱 Currency: from the file, else each broker's currency")
            state["gen"] += 1
            gen = state["gen"]
            import_btn.set_disabled(True)
            status.config(text="⏳ Checking the rows…", fg=ModernStyle.INFO)

            def _work():
                if state["index"] is None:   # the saved trades, read once per preview
                    from model.database import db_session
                    with db_session() as conn:
                        rows = conn.execute("SELECT broker, trade_id, date, symbol, type, qty, price FROM trades").fetchall()
                    state["index"] = existing_trade_index(rows)
                keys, ids = state["index"]
                return validate_rows(df, default_broker=chosen, default_currency="INR",
                                     broker_currencies=broker_currencies or None, existing_keys=keys,
                                     existing_ids=ids, today=_date.today())

            def _done(r):
                if gen == state["gen"]:
                    _show(r)

            def _failed(e):
                if gen == state["gen"]:
                    status.config(text="❌ The rows couldn't be checked. Close this window and try again.",
                                  fg=ModernStyle.ERROR)
            run_in_background(_work, _done, _failed, widget=top, name="check-import")

        def _import():
            r = state["result"]
            if r is None or state["busy"]:
                return
            skip_saved, skip_repeats = skip_saved_var.get(), skip_repeats_var.get()
            trades = r.trades_to_import(skip_saved, skip_repeats)
            if not trades:
                return
            skipped = r.skipped_duplicates(skip_saved, skip_repeats)
            state["busy"] = True
            import_btn.set_disabled(True)
            close_btn.set_disabled(True)
            broker_cb.config(state="disabled")
            status.config(text=f"⏳ Importing {len(trades):,} trades…", fg=ModernStyle.INFO)
            self.import_status.config(text="⏳ Importing…", fg=ModernStyle.INFO)

            def _work():
                from model.backup import safety_backup
                try:
                    safety_backup("import")
                except Exception as e:
                    raise RuntimeError("Couldn't save a backup first, so nothing was imported.") from e
                import model.crud as crud
                crud.add_trades_batch(trades)
                return len(trades), refresh_after_change(app_state)

            def _done(res):
                n, warning = res
                show_stale_warning(self, warning)
                state["busy"] = False
                if source == "csv":
                    self.pending_csv_df = None
                    self.import_confirm_btn.set_disabled(True)
                else:
                    self.pending_paste_df = None
                self._finish_import(n, skipped, len(r.rejected), source)
                try:
                    top.destroy()
                except tk.TclError:
                    pass

            def _failed(e):
                state["busy"] = False
                close_btn.set_disabled(False)
                broker_cb.config(state="readonly")
                _update_counts()
                import sqlite3
                if isinstance(e, RuntimeError):
                    msg = str(e)
                elif isinstance(e, sqlite3.IntegrityError):
                    msg = "Some of these trades were saved while this window was open. Nothing was imported; close it and preview again."
                else:
                    msg = f"Nothing was imported. {friendly_error(e)}"
                status.config(text=f"❌ {msg}", fg=ModernStyle.ERROR)
                self.import_status.config(text=f"❌ {msg}", fg=ModernStyle.ERROR)

            run_in_background(_work, _done, _failed, name="import-trades")

        skip_saved_var.trace_add("write", lambda *_: _update_counts())
        skip_repeats_var.trace_add("write", lambda *_: _update_counts())
        broker_cb.bind("<<ComboboxSelected>>", _validate)
        _validate()

    def _finish_import(self, inserted: int, skipped: list, rejected: int, source: str = "csv") -> None:
        parts = [f"✅ Imported {inserted} trade{'s' if inserted != 1 else ''}."]
        if skipped:
            parts.append(f"{len(skipped)} duplicate{'s' if len(skipped) != 1 else ''} skipped (listed below).")
        if rejected:
            parts.append(f"{rejected} row{'s' if rejected != 1 else ''} rejected.")
        text = " ".join(parts)
        if source == "paste":
            self._paste_area.delete("1.0", "end")
            self._paste_area.config(fg=ModernStyle.TEXT_PRIMARY)
            self._paste_hint_shown = False
            if self.focus_get() is not self._paste_area:
                self._show_paste_hint()
            self._paste_status.config(text=text, fg=ModernStyle.SUCCESS)
        else:
            self.import_status.config(text=text, fg=ModernStyle.SUCCESS)
            self.import_path_label.config(text="Select a CSV file to import trades")
        self._set_dupes([(d.trade[2], d.trade[3], d.trade[5], d.reason) for d in skipped])
        if inserted > 0:
            self._invalidate_other_views()
            self._load_snapshot()

    def _set_dupes(self, dupes: list) -> None:
        children = self.dupe_table.get_children()
        if children:
            self.dupe_table.delete(*children)
        if not dupes:
            self.dupe_card.pack_forget()
        else:
            for n, (d, s, q, why) in enumerate(dupes[:500], 1):
                self.dupe_table.insert("", "end", values=(n, str(d), str(s), f"{float(q):g}", why))
            self.dupe_card.pack(fill="x")
        self._schedule_fit()
