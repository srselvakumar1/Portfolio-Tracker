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
from ui import icons
from ui.ui_theme import ModernStyle
from ui.ui_widgets import (GradientHeader, icon_tile, rounded_combobox, RoundedBox, ModernButton, ModernCard,
                           action_button, add_broker_logos, secondary_button)
from ui.broker_logos import logo_column, show_logos
from views.tax_report_view import fit_columns
from ui.ui_utils import (add_treeview_copy_menu, color_buy_sell, enhance_table, format_money, place_centered,
                         run_in_background, show_toast)

PASTE_HINT = "date,symbol,type,qty,price\n2024-01-15,TCS.NS,BUY,10,3500.00\n2024-01-20,INFY.NS,SELL,5,1800.50"
PREVIEW_READY_ROWS = 1000   # ready rows listed in the preview (problem rows are always all listed)


class TradeEntryView(BaseView):
    """Form for entering new trades."""

    _FIELD_IPADY = 9                       # text boxes as tall as the broker drop-down (44 px)
    _CSV_PROMPT = "Choose a CSV file of trades"
    _RECENT_ROWS = 30                      # trades listed under Recent Trades

    def build(self):
        """Build Trade Entry view with premium look."""
        self._data_loaded = False
        self._saving = False
        self._snapshot_gen = 0
        self._sum_tint = ModernStyle.SUCCESS_PALE
        self._recent_gen = 0
        self._brokers: list = []
        self.pending_csv_df = None
        self.pending_csv_name = ""
        self.pending_paste_df = None
        self._import_preview_win = None

        S = ModernStyle
        self.add_gradient_header(self, "❇️ Trade Entry", "Record one trade by hand, or import many at once",
                                 show_divider=False)

        # The page scrolls when the window is too short for it; otherwise it fills the window.
        scroller = tk.Frame(self, bg=S.BG_PRIMARY)
        scroller.pack(fill="both", expand=True)
        self._page_canvas = tk.Canvas(scroller, bg=S.BG_PRIMARY, highlightthickness=0, bd=0)
        self._page_vsb = ttk.Scrollbar(scroller, orient="vertical", command=self._page_canvas.yview)
        self._page_canvas.configure(yscrollcommand=self._page_vsb.set)
        self._page_canvas.pack(side="left", fill="both", expand=True)
        page = tk.Frame(self._page_canvas, bg=S.BG_PRIMARY)
        self._page = page
        self._page_item = self._page_canvas.create_window(0, 0, window=page, anchor="nw")
        self._page_canvas.bind("<Configure>", lambda e: self._fit_page())
        self._page_canvas.bind("<Enter>", lambda e: self._page_canvas.bind_all("<MouseWheel>", self._on_page_wheel))
        self._page_canvas.bind("<Leave>", lambda e: self._page_canvas.unbind_all("<MouseWheel>"))

        body = tk.Frame(page, bg=S.BG_PRIMARY)
        body.pack(fill="both", expand=True, padx=20, pady=(6, 12))
        body.grid_columnconfigure(0, weight=3, uniform="te")
        body.grid_columnconfigure(1, weight=2, uniform="te")
        body.grid_rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=S.BG_PRIMARY)
        right = tk.Frame(body, bg=S.BG_PRIMARY)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        right.grid(row=0, column=1, sticky="nsew")

        vcmd = (self.register(self._validate_number), "%P")
        vcmd_qty = (self.register(self._validate_qty), "%P")
        BG_SEC = S.BG_SECONDARY
        # The manual form sits on a mild tint of its blue; its "off" buttons are a shade stronger
        MANUAL_BG = ModernButton._blend(S.ACCENT_PRIMARY, BG_SEC, 0.06)
        self._toggle_off = ModernButton._blend(S.ACCENT_PRIMARY, BG_SEC, 0.14)

        def _glyph(parent, name, emoji, color, px, bg=BG_SEC):
            """A Lucide line icon as a label (the emoji when the icon font is missing)."""
            g = icons.glyph(name)
            return tk.Label(parent, text=g or emoji, fg=color, bg=bg, bd=0, padx=0, pady=0,
                            font=icons.font(px) if g else S.FONT_BODY)

        def _card(parent, title: str, subtitle: str, icon: str, emoji: str, accent, pale, tint_fg,
                  expand_height=False, bg=BG_SEC):
            """Section card: soft shadow, coloured top bar, icon tile, title and a short subtitle."""
            frame = ModernCard(parent, bg=bg, highlight_color=bg, highlight_thickness=1, shadow=True,
                               radius=ModernStyle.RADIUS_CARD, canvas_bg=S.BG_PRIMARY, expand_height=expand_height)
            tk.Frame(frame.content, bg=accent, height=ModernStyle.ACCENT_BAR).pack(fill="x")
            hdr = tk.Frame(frame.content, bg=bg)
            hdr.pack(fill="x", padx=16, pady=(12, 12))
            icon_tile(hdr, icon, emoji, tint_fg, pale).pack(side="left")
            words = tk.Frame(hdr, bg=bg)
            words.pack(side="left", padx=(10, 0))
            tk.Label(words, text=title, fg=S.TEXT_PRIMARY, bg=bg, font=S.FONT_CARD_TITLE).pack(anchor="w")
            if subtitle:
                tk.Label(words, text=subtitle, fg=S.TEXT_SECONDARY, bg=bg, font=S.FONT_SMALL).pack(anchor="w")
            inner = tk.Frame(frame.content, bg=bg)
            inner.pack(fill="both", expand=True, padx=16, pady=(0, 16))
            frame.header_frame = hdr
            return frame, inner

        def _caption(parent, text, icon, emoji, color):
            """A field label: small coloured icon and quiet bold text."""
            bg = parent.cget("bg")
            row = tk.Frame(parent, bg=bg)
            row.pack(anchor="w", pady=(0, 6))
            ico = _glyph(row, icon, emoji, color, 16, bg)
            ico.pack(side="left", padx=(0, 6))
            lbl = tk.Label(row, text=text, fg=S.TEXT_SECONDARY, bg=bg, font=S.FONT_SMALL_BOLD)
            lbl.pack(side="left")
            return lbl, ico

        def _styled_entry(parent, textvariable, placeholder: str, validate=None, vcmd=None):
            """Entry in a rounded box with grey hint text; the border is blue while typing, red when wrong."""
            wrap = RoundedBox(parent)
            wrap.pack(fill="x")
            kw = dict(textvariable=textvariable, bg=S.ENTRY_BG, fg=S.TEXT_PRIMARY, font=S.FONT_INPUT, relief=tk.FLAT,
                      insertbackground=S.ACCENT_PRIMARY, highlightthickness=0, bd=0)
            if validate:
                kw["validate"] = validate
            if vcmd:
                kw["validatecommand"] = vcmd
            ent = tk.Entry(wrap, **kw)
            ent.pack(fill="x", ipady=self._FIELD_IPADY, padx=10)
            wrap.watch(ent)

            hint = tk.Label(wrap, text=placeholder, fg=S.TEXT_TERTIARY, bg=S.ENTRY_BG, font=S.FONT_INPUT,
                            bd=0, padx=0, cursor="xterm")
            hint.bind("<Button-1>", lambda _e: ent.focus_set())

            def _sync_hint(*_):
                if textvariable.get():
                    hint.place_forget()
                else:
                    hint.place(in_=ent, x=1, rely=0.5, anchor="w")
            textvariable.trace_add("write", _sync_hint)
            _sync_hint()
            return ent, wrap

        def _row(parent, cols: int, pady=(0, 14)):
            """A row of equal-width cells."""
            bg = parent.cget("bg")
            row = tk.Frame(parent, bg=bg)
            row.pack(fill="x", pady=pady)
            cells = []
            for i in range(cols):
                row.grid_columnconfigure(i, weight=1, uniform=f"row{id(row)}")
                cell = tk.Frame(row, bg=bg)
                cell.grid(row=0, column=i, sticky="nsew", padx=(0, 12) if i < cols - 1 else 0)
                cells.append(cell)
            return cells

        def _toggle(parent, text, command, width, glyph=""):
            g = icons.glyph(glyph) if glyph else ""
            return ModernButton(parent, text=text, command=command, bg=self._toggle_off, fg=S.TEXT_SECONDARY,
                                canvas_bg=parent.cget("bg"), width=width, height=38, radius=16, font=S.FONT_BODY_BOLD,
                                glyph=g, glyph_font=icons.font(16))   # choices are pills; actions are rounded boxes

        # ===== Manual Entry Card =====
        manual_card, manual = _card(left, "Manual Trade Entry", "Record one buy or sell by hand",
                                    "square-pen", "✍️", S.ACCENT_PRIMARY, S.ACCENT_PRIMARY_PALE, S.TEXT_ACCENT,
                                    bg=MANUAL_BG)
        manual_card.pack(fill="x", pady=(0, 14))

        self.te_broker_var = tk.StringVar(value="")
        self.te_date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.te_symbol_var = tk.StringVar(value="")
        self.te_type_var = tk.StringVar(value="BUY")
        self.te_currency_var = tk.StringVar(value="INR")
        self.te_qty_var = tk.StringVar(value="")
        self.te_price_var = tk.StringVar(value="")

        # Row 1: Broker | Date
        broker_col, date_col = _row(manual, 2)
        _caption(broker_col, "Broker", "landmark", "🏦", S.TEXT_ACCENT)
        box, self.te_broker_cb = rounded_combobox(broker_col, textvariable=self.te_broker_var, width=18,
                                                  state="readonly")
        add_broker_logos(box, self.te_broker_cb)
        box.pack(fill="x")
        _caption(date_col, "Trade date", "calendar-days", "📅", S.ERROR)
        self.te_date_entry = _create_date_input(date_col, self.te_date_var, ipady=self._FIELD_IPADY)
        self.te_date_entry.pack(fill="x")

        # Row 2: Buy or sell | Currency (the currency follows the broker)
        type_col, cur_col = _row(manual, 2)
        _caption(type_col, "Buy or sell", "arrow-left-right", "🚦", S.WARNING)
        type_btn_frame = tk.Frame(type_col, bg=MANUAL_BG)
        type_btn_frame.pack(anchor="w")

        def _on_type_select(val):
            self.te_type_var.set(val)
            self._sync_te_type_buttons()
            self._update_summary()

        self.te_buy_btn = _toggle(type_btn_frame, "BUY", lambda: _on_type_select("BUY"), 104, "trending-up")
        self.te_buy_btn.pack(side="left", padx=(0, 8))
        self.te_sell_btn = _toggle(type_btn_frame, "SELL", lambda: _on_type_select("SELL"), 104, "trending-down")
        self.te_sell_btn.pack(side="left")

        # Currency toggles: INR and JPY, plus any other currency a broker uses (added in load_data)
        _caption(cur_col, "Currency", "coins", "💱", S.SUCCESS)
        self._currency_btn_frame = tk.Frame(cur_col, bg=MANUAL_BG)
        self._currency_btn_frame.pack(anchor="w")
        self._cur_btns: dict = {}
        self._make_toggle = _toggle

        # Row 3: Symbol | Quantity | Price
        sym_col, qty_col, price_col = _row(manual, 3, pady=(0, 16))
        _caption(sym_col, "Symbol", "tag", "🔠", S.INFO)
        self.te_symbol_entry, self._sym_wrap = _styled_entry(sym_col, self.te_symbol_var, "e.g. TCS.NS")
        _caption(qty_col, "Quantity", "hash", "💎", S.TEXT_PURPLE)
        self.te_qty_entry, self._qty_wrap = _styled_entry(qty_col, self.te_qty_var, "0",
                                                          validate="key", vcmd=vcmd_qty)
        self.lbl_price, self._price_icon = _caption(price_col, "Price (₹)", "indian-rupee", "💰", S.WARNING)
        self.te_price_entry, self._price_wrap = _styled_entry(price_col, self.te_price_var, "0.00",
                                                              validate="key", vcmd=vcmd)
        self._add_currency_buttons(["INR", "JPY"])
        self.te_inr_btn = self._cur_btns["INR"]
        self.te_jpy_btn = self._cur_btns["JPY"]

        # Footer: the fee estimate on the left, the buttons on the right
        tk.Frame(manual, bg=S.DIVIDER_COLOR, height=1).pack(fill="x", pady=(0, 14))
        foot = tk.Frame(manual, bg=MANUAL_BG)
        foot.pack(fill="x")
        self.te_save_btn = action_button(foot, "✓ Save Trade", self._save_trade, kind="success", width=150,
                                         canvas_bg=MANUAL_BG)
        self.te_save_btn.pack(side="right")
        secondary_button(foot, "Clear", self._clear_form, canvas_bg=MANUAL_BG,
                         icon="eraser").pack(side="right", padx=(0, 10))
        _glyph(foot, "receipt", "💸", S.TEXT_SECONDARY, 16, MANUAL_BG).pack(side="left", padx=(0, 6))
        self.te_fee_label = tk.Label(foot, text="Estimated fee ₹0.00", fg=S.TEXT_SECONDARY, bg=MANUAL_BG,
                                     font=S.FONT_SMALL_BOLD, anchor="w")
        self.te_fee_label.pack(side="left", fill="x", expand=True)

        # ===== Import Card: a CSV file or pasted rows, one tab each =====
        import_card, imp = _card(left, "Import Trades", "Add many trades at once", "upload", "📥",
                                 S.WARNING_FILL, S.WARNING_PALE, S.WARNING, expand_height=True)
        import_card.pack(fill="both", expand=True)
        tabs = tk.Frame(import_card.header_frame, bg=BG_SEC)
        tabs.pack(side="right")
        self._imp_tab_btns: dict = {}
        for key, text, icon, emoji in (("csv", "CSV file", "file-spreadsheet", "📄"),
                                       ("paste", "Paste rows", "clipboard-paste", "📋")):
            g = icons.glyph(icon)
            btn = ModernButton(tabs, text=text if g else f"{emoji} {text}",
                               command=lambda k=key: self._show_import_tab(k), bg=S.BG_TERTIARY,
                               fg=S.TEXT_SECONDARY, canvas_bg=BG_SEC, width=126, height=32, radius=14,
                               font=S.FONT_SMALL_BOLD, glyph=g, glyph_font=icons.font(14))
            btn.pack(side="left", padx=(6, 0))
            self._imp_tab_btns[key] = btn

        csv_tab = tk.Frame(imp, bg=BG_SEC)
        cols_hint = tk.Label(csv_tab,
                             text="Needed columns: date, symbol, type, qty, price. Optional: broker, fee, currency, "
                                  "trade_id. Dates like 2024-01-15 or 15-01-2024.",
                             fg=S.TEXT_SECONDARY, bg=BG_SEC, font=S.FONT_SMALL, justify="left",
                             anchor="w", wraplength=420)
        cols_hint.pack(fill="x", pady=(0, 10))
        self._auto_wrap(cols_hint)
        # The drop zone fills the card; its contents stay in the middle
        dropzone = RoundedBox(csv_tab, fill=S.BG_TERTIARY, padx=5, pady=5)
        dropzone.pack(fill="both", expand=True)
        tk.Frame(dropzone, bg=S.BG_TERTIARY).pack(fill="both", expand=True)
        _glyph(dropzone, "file-spreadsheet", "📄", S.WARNING, 30, S.BG_TERTIARY).pack(pady=(14, 4))
        self.import_path_label = tk.Label(dropzone, text=self._CSV_PROMPT, fg=S.TEXT_PRIMARY,
                                          bg=S.BG_TERTIARY, font=S.FONT_BODY_BOLD)
        self.import_path_label.pack(pady=(0, 10), padx=12)
        imp_btns = tk.Frame(dropzone, bg=S.BG_TERTIARY)
        imp_btns.pack(pady=(0, 14))
        action_button(imp_btns, "Select CSV", self._select_import_file, soft=True, icon="folder-open",
                      canvas_bg=S.BG_TERTIARY).pack(side="left", padx=(0, 10))
        self.import_confirm_btn = action_button(imp_btns, "Preview Import",
                                                lambda: self._open_import_preview_dialog(source="csv"),
                                                kind="success", icon="scan-eye", canvas_bg=S.BG_TERTIARY)
        self.import_confirm_btn.pack(side="left")
        self.import_confirm_btn.set_disabled(True)
        tk.Frame(dropzone, bg=S.BG_TERTIARY).pack(fill="both", expand=True)
        self.import_status = tk.Label(csv_tab, text="", fg=S.TEXT_SECONDARY, bg=BG_SEC,
                                      font=S.FONT_SMALL_BOLD, justify="left", anchor="w", wraplength=420)
        self.import_status.pack(fill="x", pady=(8, 0))
        self._auto_wrap(self.import_status)

        paste_tab = tk.Frame(imp, bg=BG_SEC)
        hint_text = tk.Text(paste_tab, height=2, bg=BG_SEC, font=S.FONT_SMALL, relief="flat",
                            highlightthickness=0, wrap="word", cursor="arrow")
        hint_text.pack(fill="x", pady=(0, 6))
        hint_text.tag_configure("normal", foreground=S.TEXT_SECONDARY)
        hint_text.tag_configure("highlight", foreground=S.TEXT_ACCENT)
        hint_text.insert("end", "Tab- or comma-separated", "highlight")
        hint_text.insert("end", " rows with a header: ", "normal")
        hint_text.insert("end", "date, symbol, type, qty, price, [broker], [fee], [trade_id]", "highlight")
        hint_text.config(state="disabled")

        paste_foot = tk.Frame(paste_tab, bg=BG_SEC)
        paste_foot.pack(side="bottom", fill="x", pady=(10, 0))
        action_button(paste_foot, "Parse & Preview", self._parse_and_preview_pasted, kind="success",
                      icon="scan-eye", canvas_bg=BG_SEC).pack(side="right")
        secondary_button(paste_foot, "Clear", self._clear_paste_area,
                         canvas_bg=BG_SEC, icon="eraser").pack(side="right", padx=(0, 10))
        self._paste_status = tk.Label(paste_foot, text="", fg=S.TEXT_SECONDARY, bg=BG_SEC,
                                      font=S.FONT_SMALL_BOLD, justify="left", anchor="w", wraplength=300)
        self._paste_status.pack(side="left", fill="x", expand=True)
        self._auto_wrap(self._paste_status)

        ta_box = RoundedBox(paste_tab)
        ta_box.pack(side="top", fill="both", expand=True)
        ta_scroll = ttk.Scrollbar(ta_box, orient="vertical")
        self._paste_area = tk.Text(ta_box, height=3, bg=S.ENTRY_BG, fg=S.TEXT_PRIMARY,
                                   font=S.FONT_TABLE, relief=tk.FLAT, wrap="none", undo=True, bd=0,
                                   highlightthickness=0, insertbackground=S.ACCENT_PRIMARY,
                                   yscrollcommand=ta_scroll.set)
        ta_scroll.config(command=self._paste_area.yview)
        ta_scroll.pack(side="right", fill="y", padx=(0, 2), pady=4)
        self._paste_area.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=6)
        ta_box.watch(self._paste_area)
        self._imp_tabs = {"csv": csv_tab, "paste": paste_tab}

        # The example rows are only a placeholder (grey); they are never imported.
        self._paste_hint_shown = False
        self._show_paste_hint()

        def _on_paste_focus_in(_e):
            if self._paste_hint_shown:
                self._paste_area.delete("1.0", "end")
                self._paste_area.config(fg=S.TEXT_PRIMARY)
                self._paste_hint_shown = False

        def _on_paste_focus_out(_e):
            if not self._paste_area.get("1.0", "end-1c").strip():
                self._show_paste_hint()
        self._paste_area.bind("<FocusIn>", _on_paste_focus_in, add="+")
        self._paste_area.bind("<FocusOut>", _on_paste_focus_out, add="+")

        # ===== Skipped Duplicates Card (shown after an import that skipped some) =====
        self.dupe_card, dupe_inner = _card(left, "Skipped Duplicates", "Already in your trades, so not imported",
                                           "triangle-alert", "⚠️", S.WARNING_FILL, S.WARNING_PALE, S.WARNING)
        dupe_cols = ("#", "Date", "Symbol", "Qty", "Why")
        self.dupe_table = ttk.Treeview(dupe_inner, columns=dupe_cols, show="headings", height=6)
        for c, w in zip(dupe_cols, (44, 100, 100, 60, 260)):
            anchor = "center" if c == "#" else ("e" if c == "Qty" else "w")
            self.dupe_table.heading(c, text=c, anchor="center")
            self.dupe_table.column(c, width=w, anchor=anchor)
        add_treeview_copy_menu(self.dupe_table)
        vsb = ttk.Scrollbar(dupe_inner, orient="vertical", command=self.dupe_table.yview)
        self.dupe_table.configure(yscroll=vsb.set)
        self.dupe_table.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # ===== Transaction Summary Card (right column) =====
        self.sum_card, sum_inner = _card(right, "Transaction Summary", "Updates as you type", "calculator", "🧮",
                                         S.INFO_FILL, S.INFO_PALE, S.INFO)
        self.sum_card.pack(fill="x", pady=(0, 14))

        def _sum_row(lbl: str, init: str):
            row = tk.Frame(sum_inner, bg=BG_SEC)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=lbl, fg=S.TEXT_SECONDARY, bg=BG_SEC, font=S.FONT_BODY).pack(side="left")
            val = tk.Label(row, text=init, fg=S.TEXT_PRIMARY, bg=BG_SEC, font=S.FONT_BODY_BOLD)
            val.pack(side="right")
            return val

        self.sum_type_label = _sum_row("Trade type", "BUY")
        self.sum_qty_label = _sum_row("Quantity", "—")
        self.sum_price_label = _sum_row("Unit price", "—")
        self.sum_subtotal_label = _sum_row("Subtotal", "—")
        self.sum_fee_label = _sum_row("Est. fee", "0.00")
        # The total on a soft green (BUY) or red (SELL) panel
        self._sum_total_box = RoundedBox(sum_inner, fill=S.SUCCESS_PALE, border=S.SUCCESS_PALE)
        self._sum_total_box.pack(fill="x", pady=(10, 0))
        self._sum_total_title = tk.Label(self._sum_total_box, text="Total value", fg=S.TEXT_PRIMARY,
                                         bg=S.SUCCESS_PALE, font=S.FONT_BODY_BOLD)
        self._sum_total_title.pack(side="left", padx=12, pady=10)
        self.sum_total_label = tk.Label(self._sum_total_box, text="0.00", fg=S.SUCCESS, bg=S.SUCCESS_PALE,
                                        font=S.FONT_KPI_VALUE)
        self.sum_total_label.pack(side="right", padx=12, pady=6)

        # ===== Portfolio Snapshot Card =====
        snap_card, snap_inner = _card(right, "Portfolio Snapshot", "All brokers, in ₹", "chart-pie", "📊",
                                      S.PURPLE_FILL, S.ACCENT_PURPLE_PALE, S.TEXT_PURPLE)
        snap_card.pack(fill="x", pady=(0, 14))
        snap_grid = tk.Frame(snap_inner, bg=BG_SEC)
        snap_grid.pack(fill="both", expand=True)
        snap_grid.grid_columnconfigure(0, weight=1, uniform="snap")
        snap_grid.grid_columnconfigure(1, weight=1, uniform="snap")
        self._snap_labels = {}

        def _snap_tile(row, col, icon, emoji, title, key, fg):
            tile = RoundedBox(snap_grid, fill=S.BG_TERTIARY, border=S.BG_TERTIARY, padx=5, pady=5)
            tile.grid(row=row, column=col, sticky="nsew", padx=(0, 8) if col == 0 else 0, pady=(0, 8) if row == 0 else 0)
            hdr = tk.Frame(tile, bg=S.BG_TERTIARY)
            hdr.pack(fill="x", padx=12, pady=(10, 0))
            _glyph(hdr, icon, emoji, fg, 16, S.BG_TERTIARY).pack(side="left", padx=(0, 6))
            tk.Label(hdr, text=title, fg=S.TEXT_SECONDARY, bg=S.BG_TERTIARY, font=S.FONT_SMALL_BOLD).pack(side="left")
            val_lbl = tk.Label(tile, text="—", fg=fg, bg=S.BG_TERTIARY, font=S.FONT_KPI_VALUE)
            val_lbl.pack(anchor="w", padx=12, pady=(2, 10))
            self._snap_labels[key] = val_lbl

        _snap_tile(0, 0, "layers", "📦", "Holdings", "snap_holdings", S.TEXT_ACCENT)
        _snap_tile(0, 1, "piggy-bank", "📥", "Invested", "snap_invested", S.SUCCESS)
        _snap_tile(1, 0, "wallet", "💼", "Current Value", "snap_current", S.INFO)
        _snap_tile(1, 1, "trending-up", "📈", "Overall P&L", "snap_pnl", S.TEXT_PURPLE)
        self._snap_hint = tk.Label(snap_inner, text="", fg=S.TEXT_SECONDARY, bg=BG_SEC, font=S.FONT_SMALL_BOLD)
        self._snap_hint.pack(anchor="w", pady=(8, 0))

        # ===== Recent Trades Card: fills the rest of the column (fewer rows on small windows) =====
        recent_card, recent_inner = _card(right, "Recent Trades", "The latest ones added", "history", "🕒",
                                          S.SUCCESS_FILL, S.SUCCESS_PALE, S.SUCCESS, expand_height=True)
        recent_card.pack(fill="both", expand=True)
        cols = (("date", "Date", 84, "w"), ("symbol", "Symbol", 104, "w"), ("type", "Type", 70, "w"),
                ("qty", "Qty", 56, "e"), ("price", "Price", 96, "e"))
        self.recent_table = ttk.Treeview(recent_inner, columns=[c[0] for c in cols], show="headings", height=1,
                                         selectmode="browse")
        for cid, text, width, anchor in cols:
            self.recent_table.heading(cid, text=text, anchor="center")
            self.recent_table.column(cid, width=width, minwidth=40, anchor=anchor, stretch=True)
        self.recent_table.tag_configure("evenrow", background=S.TABLE_ROW_ALT)
        self.recent_table.tag_configure("oddrow", background=BG_SEC)
        add_treeview_copy_menu(self.recent_table)
        self.recent_table.pack(fill="both", expand=True)

        # Cards change height as they lay out (or when one is shown): re-fit the scrolling page.
        self._fit_pending = False
        for card in (manual_card, import_card, self.dupe_card, self.sum_card, snap_card, recent_card):
            card.bind("<Configure>", lambda e: self._schedule_fit(), add="+")

        # Live updates. The currency follows the broker, and the buttons follow the currency.
        self.te_broker_var.trace_add("write", lambda *_: self._on_broker_change())
        self.te_currency_var.trace_add("write", lambda *_: self._on_currency_change())
        for v in (self.te_qty_var, self.te_price_var):
            v.trace_add("write", lambda *_: self._update_summary())

        self._show_import_tab("csv")
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
        currencies = [c for c in currencies if (c or "").strip().upper() in ("INR", "JPY")]
        for code in currencies:
            code = (code or "").strip().upper()
            if not code or code in self._cur_btns:
                continue
            sym = currency_symbol(code).strip()
            label_text = f"{sym} {code}".strip()
            btn = self._make_toggle(self._currency_btn_frame, label_text,
                                    lambda c=code: self.te_currency_var.set(c), 104)
            btn.pack(side="left", padx=(0, 8))
            self._cur_btns[code] = btn
        if hasattr(self, "lbl_price"):
            self._sync_currency_buttons()

    def _sync_te_type_buttons(self) -> None:
        """Colour the BUY/SELL toggles; the Save button takes the same green or red."""
        if (self.te_type_var.get() or "BUY").upper() == "BUY":
            self.te_buy_btn.set_palette(bg=ModernStyle.SUCCESS_FILL, fg=ModernStyle.TEXT_ON_ACCENT)
            self.te_sell_btn.set_palette(bg=self._toggle_off, fg=ModernStyle.TEXT_SECONDARY)
            self.te_save_btn.set_palette(bg=ModernStyle.SUCCESS_FILL, fg=ModernStyle.TEXT_ON_ACCENT)
        else:
            self.te_sell_btn.set_palette(bg=ModernStyle.ERROR_FILL, fg=ModernStyle.TEXT_ON_ACCENT)
            self.te_buy_btn.set_palette(bg=self._toggle_off, fg=ModernStyle.TEXT_SECONDARY)
            self.te_save_btn.set_palette(bg=ModernStyle.ERROR_FILL, fg=ModernStyle.TEXT_ON_ACCENT)

    def _sync_currency_buttons(self) -> None:
        """Colour the currency toggles and show the right symbol on the price label."""
        cur = (self.te_currency_var.get() or "INR").upper()
        fills = {"INR": ModernStyle.SUCCESS_FILL, "JPY": ModernStyle.PURPLE_FILL}
        for code, btn in self._cur_btns.items():
            sym = currency_symbol(code).strip()
            if code == cur:
                btn.set_palette(bg=fills.get(code, ModernStyle.ACCENT_PRIMARY), fg=ModernStyle.TEXT_ON_ACCENT)
                btn.set_text(f"✓ {sym} {code}")
            else:
                btn.set_palette(bg=self._toggle_off, fg=ModernStyle.TEXT_SECONDARY)
                btn.set_text(f"{sym} {code}")
        self.lbl_price.config(text=f"Price ({currency_symbol(cur).strip()})")
        glyph = icons.glyph("japanese-yen" if cur == "JPY" else "indian-rupee")
        if glyph:
            self._price_icon.config(text=glyph)

    def _broker_currencies(self) -> dict:
        try:
            if self.app_state is not None:
                return dict(self.app_state.get_broker_currencies_cached() or {})
        except Exception:
            log.exception("Reading broker currencies failed")
        return {}

    def _on_broker_change(self) -> None:
        cur = self._broker_currencies().get(self.te_broker_var.get())
        cur = (cur or "INR").upper()
        if cur not in ("INR", "JPY"):
            cur = "INR"
        self.te_currency_var.set(cur)

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
        self._load_recent()

    def _show_import_tab(self, key: str) -> None:
        """Show the CSV or the paste tab of the Import card."""
        for k, frame in self._imp_tabs.items():
            btn = self._imp_tab_btns[k]
            if k == key:
                frame.pack(fill="both", expand=True)
                btn.set_palette(bg=ModernStyle.WARNING_FILL, fg=ModernStyle.TEXT_ON_ACCENT)
            else:
                frame.pack_forget()
                btn.set_palette(bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_SECONDARY)
        self._schedule_fit()

    def _load_recent(self) -> None:
        """The latest trades added, newest first (in the background)."""
        self._recent_gen += 1
        gen = self._recent_gen
        limit = self._RECENT_ROWS

        def _work():
            from model.database import db_session
            with db_session() as conn:
                return conn.execute("SELECT date, symbol, type, qty, price, currency FROM trades "
                                    "ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()

        def _done(rows):
            if gen == self._recent_gen:
                self._apply_recent(rows)

        run_in_background(_work, _done, widget=self, name="trade-entry-recent")

    def _apply_recent(self, rows) -> None:
        tv = self.recent_table
        tv.delete(*tv.get_children())
        sides = []
        for i, (d, sym, t_type, qty, price, cur) in enumerate(rows):
            try:
                shown = datetime.strptime(str(d)[:10], "%Y-%m-%d").strftime("%d %b %y")
            except ValueError:
                shown = str(d)
            is_buy = str(t_type).upper() == "BUY"
            iid = tv.insert("", "end", values=(shown, sym, "▲ BUY" if is_buy else "▼ SELL", f"{float(qty or 0):g}",
                                               format_money(float(price or 0), (cur or "INR").upper())),
                            tags=("evenrow" if i % 2 == 0 else "oddrow", "buy" if is_buy else "sell"))
            sides.append((iid, is_buy))
        color_buy_sell(tv, sides, ("type", "qty", "price"))   # only these say Buy / Sell

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
            self._sum_total_box.set_fill(tint)
            self._sum_total_box.configure(bg=tint)
            self._sum_total_title.configure(bg=tint)
            self.sum_total_label.configure(bg=tint)

        if cur == "INR":
            self.te_fee_label.config(text=f"Estimated fee {format_money(fee, cur)}")
        else:
            self.te_fee_label.config(text=f"No fee estimate for {cur} trades")
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
            return self._toast(f"'{date}' isn't a date. Type it like 15 Jan 2024, or pick it with 📅.")
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
            self._toast(f"Saved {t_type} {qty:g} {symbol} @ {format_money(price, cur)}", "success")
            self._load_recent()
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
        top.withdraw()   # built hidden, then shown centred with a short fade
        self._import_preview_win = top
        top.title("Bulk Import Preview")
        ModernStyle.style_modal(top)
        top.minsize(820, 520)
        try:
            top.transient(self.winfo_toplevel())
        except tk.TclError:
            pass
        place_centered(top, min(1060, top.winfo_screenwidth() - 60), min(660, top.winfo_screenheight() - 100),
                       self.winfo_toplevel())

        BG = ModernStyle.BG_PRIMARY
        # The same banner as the other pop-ups: a frosted icon tile, the title and a subtitle
        banner = GradientHeader(top, title="Import Preview",
                                subtitle=f"{origin}  ·  {len(df):,} rows. Nothing is saved until you press Import.",
                                height=62, icon="file-spreadsheet" if source == "csv" else "clipboard-paste")
        banner.pack(fill="x")
        banner.set_icon_fill("#22C55E" if source == "csv" else "#F97316")
        tk.Frame(top, bg=BG, height=12).pack(fill="x")

        body = tk.Frame(top, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        # Broker choice + buttons
        opts = tk.Frame(body, bg=BG)
        opts.pack(fill="x", pady=(0, 6))
        btn_box = tk.Frame(opts, bg=BG)
        btn_box.pack(side="right")
        broker_glyph = icons.glyph("landmark")
        tk.Label(opts, text=broker_glyph or "🏦", fg=ModernStyle.TEXT_ACCENT, bg=BG,
                 font=icons.font(18) if broker_glyph else ModernStyle.FONT_HEADING).pack(side="left", padx=(0, 6))
        tk.Label(opts, text="Broker for rows without one:" if has_broker else "Broker:",
                 fg=ModernStyle.TEXT_SECONDARY, bg=BG, font=ModernStyle.FONT_FIELD_LABEL).pack(side="left")
        broker_var = tk.StringVar(value=self.te_broker_var.get() if self.te_broker_var.get() in self._brokers else "")
        box, broker_cb = rounded_combobox(opts, textvariable=broker_var, state="readonly", width=18,
                                          values=self._brokers)
        add_broker_logos(box, broker_cb)
        box.pack(side="left", padx=(8, 12))
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
            anchor = "center" if c == "#" else ("e" if c in ("Qty", "Price", "Fee") else "w")   # numbers line up
            tv.heading(c, text=c, anchor="center")
            tv.column(c, width=w, minwidth=40, anchor=anchor, stretch=(c == "Status"))
        logo_column(tv, "#", "Broker")   # a "Src" column with each row's broker logo
        fit_columns(tv, dict(zip(cols, widths)))   # all columns inside the popup's width
        tv.tag_configure("rejected", background=ModernStyle.ERROR_PALE, foreground=ModernStyle.ERROR)
        tv.tag_configure("dupe", background=ModernStyle.WARNING_PALE, foreground=ModernStyle.WARNING)
        enhance_table(tv, stripes=None)   # highlight under the mouse, click a heading to sort
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
        top.bind("<Escape>", lambda _e: _close())

        close_btn = secondary_button(btn_box, "✕ Close", _close, canvas_bg=BG)
        close_btn.pack(side="right")
        import_btn = action_button(btn_box, "Import", lambda: _import(), kind="success", width=190,
                                   canvas_bg=BG, disabled=True)
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
            ready = list(zip(r.valid_rows, r.valid))[:PREVIEW_READY_ROWS]
            for row_no, t in ready:
                tv.insert("", "end", iid=f"v{row_no}", tags=(t[4],), values=(row_no, "✓ Ready") + _trade_values(t))
            # Only Type, Qty and Price say Buy / Sell (rejected and duplicate rows keep their colours)
            color_buy_sell(tv, [(f"v{row_no}", {"BUY": True, "SELL": False}.get(str(t[4]).upper()))
                                for row_no, t in ready])
            show_logos(tv)

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

        def _reveal_preview():
            top.deiconify()
            try:
                top.grab_set()
            except tk.TclError:
                pass
        top.after_idle(_reveal_preview)

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
            self.import_path_label.config(text=self._CSV_PROMPT)
        self._set_dupes([(d.trade[2], d.trade[3], d.trade[5], d.reason) for d in skipped])
        if inserted > 0:
            self._invalidate_other_views()
            self._load_snapshot()
            self._load_recent()

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
