"""
Trade History view for TKinter-based PTracker application.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
from datetime import datetime, timedelta

from views.base_view import BaseView, _create_date_input
from ui_theme import ModernStyle
from ui_widgets import ModernButton, ModernEntry, ModernCard, ModernDropdown, ClearableEntry
from ui_utils import center_window, add_treeview_copy_menu, treeview_sort_column, fade_color_transition

class TradeHistoryView(BaseView):
    """View all trades in history."""
    
    def build(self):
        self._th_edit_popup = None
        self.add_gradient_header(
            self,
            "🔷 Trade History",
            "All trades with running stats"
        )

        # Filters card (enhanced with quick date filters and better styling)
        filters = ModernCard(self, bg=ModernStyle.BG_SECONDARY, highlight_color=ModernStyle.BORDER_COLOR, highlight_thickness=1, radius=10)
        filters.pack(fill="x", padx=15, pady=(0, 5))
        
        # Header with title and info
        header_row = tk.Frame(filters.content, bg=ModernStyle.BG_SECONDARY)
        header_row.pack(fill="x", padx=12, pady=(5, 0))
        tk.Label(header_row, text="🔍 Filters", fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SUBHEADING).pack(side="left")
        info_lbl = tk.Label(header_row, text="", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL)
        info_lbl.pack(side="right", padx=(10, 0))
        self.th_date_range_info = info_lbl

        today = datetime.now()
        # Start date: exactly one month ago (using timedelta)
        one_month_ago = today - timedelta(days=30)
        start_default = one_month_ago.strftime("%Y-%m-%d")
        end_default = today.strftime("%Y-%m-%d")
        # Default range: Last 30 days

        self.th_broker_var = tk.StringVar(value="All")
        self.th_symbol_var = tk.StringVar(value="")
        self.th_type_var = tk.StringVar(value="All")
        self.th_start_var = tk.StringVar(value=start_default)
        self.th_end_var = tk.StringVar(value=end_default)
        self._th_search_timer = None

        # Filter row with colored pills (matching Holdings view)
        filter_row = tk.Frame(filters.content, bg=ModernStyle.BG_SECONDARY)
        filter_row.pack(fill=tk.X, padx=12, pady=5)
        
        # Broker filter with background pill
        broker_pill = ModernCard(filter_row, bg=ModernStyle.BG_SECONDARY, highlight_color="#DBEAFE", highlight_thickness=1, radius=8)
        broker_pill.pack(side=tk.LEFT, padx=3, pady=3)
        tk.Label(broker_pill.content, text="🏦 Broker:", bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY, font=ModernStyle.FONT_HEADING).pack(side=tk.LEFT, padx=3, pady=3)
        self.th_broker_cb = ttk.Combobox(broker_pill.content, textvariable=self.th_broker_var, values=["All"], state="readonly", width=13, font=ModernStyle.FONT_TABLE)
        self.th_broker_cb.pack(side=tk.LEFT, padx=3, pady=5)
        try:
             self.th_broker_var.trace_add("write", lambda *args: self._apply_filters())
        except Exception:
             pass
        
        # Symbol filter with background pill
        symbol_pill = ModernCard(filter_row, bg=ModernStyle.BG_SECONDARY, highlight_color="#E9D5FF", highlight_thickness=1, radius=8)
        symbol_pill.pack(side=tk.LEFT, padx=3, pady=3)
        tk.Label(symbol_pill.content, text="📌 Symbol:", bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY, font=ModernStyle.FONT_HEADING).pack(side=tk.LEFT, padx=3, pady=3)
        self.th_symbol_entry = ClearableEntry(
            symbol_pill.content,
            placeholder="Search...",
            on_change=lambda e: self.th_symbol_var.set(self.th_symbol_entry.get()) or self._apply_filters(),
            bg=ModernStyle.ENTRY_BG,
            fg=ModernStyle.ACCENT_PRIMARY,
            font=ModernStyle.FONT_INPUT,
            width=11,
        ).entry
        self.th_symbol_entry.master.pack(side=tk.LEFT, padx=3, pady=3)
        self.th_symbol_entry.bind("<FocusIn>",  lambda e: fade_color_transition(symbol_pill, "#E9D5FF", "#D8B4FE", attr='highlight_color'), add="+")
        self.th_symbol_entry.bind("<FocusOut>", lambda e: fade_color_transition(symbol_pill, "#D8B4FE", "#E9D5FF", attr='highlight_color'), add="+")

        # Type filter with background pill (segmented radios)
        type_pill = ModernCard(filter_row, bg=ModernStyle.BG_SECONDARY, highlight_color="#DCFCE7", highlight_thickness=1, radius=8)
        type_pill.pack(side=tk.LEFT, padx=3, pady=3)
        tk.Label(type_pill.content, text="📊 Type:", bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY, font=ModernStyle.FONT_HEADING).pack(side=tk.LEFT, padx=3, pady=3)
        self.th_type_wrap = tk.Frame(type_pill.content, bg=ModernStyle.BG_SECONDARY)
        self.th_type_wrap.pack(side=tk.LEFT, padx=3, pady=3)
        
        # All / BUY / SELL segmented toggle — semantic colors (slate / green / red)
        _RB_UNSEL_BG  = ModernStyle.BG_TERTIARY
        _RB_UNSEL_FG  = ModernStyle.TEXT_SECONDARY
        _RB_ALL_SEL   = ModernStyle.ACCENT_PRIMARY    # blue when active
        _RB_BUY_SEL   = ModernStyle.ACCENT_SECONDARY  # green when active
        _RB_SELL_SEL  = ModernStyle.ERROR             # red when active

        self.th_type_all_rb = tk.Radiobutton(
            self.th_type_wrap,
            text="All",
            variable=self.th_type_var,
            value="All",
            indicatoron=0,
            width=4, padx=6, pady=4,
            font=ModernStyle.FONT_SUBHEADING,
            relief=tk.FLAT, bd=0,
            bg=_RB_UNSEL_BG, fg=_RB_UNSEL_FG,
            selectcolor=_RB_ALL_SEL,
            activebackground=_RB_UNSEL_BG,
            command=lambda: (self._sync_th_type_buttons(), self._apply_filters()),
        )
        self.th_type_buy_rb = tk.Radiobutton(
            self.th_type_wrap,
            text="BUY",
            variable=self.th_type_var,
            value="BUY",
            indicatoron=0,
            width=4, padx=6, pady=4,
            font=ModernStyle.FONT_SUBHEADING,
            relief=tk.FLAT, bd=0,
            bg=_RB_UNSEL_BG, fg=_RB_UNSEL_FG,
            selectcolor=_RB_BUY_SEL,
            activebackground=_RB_UNSEL_BG,
            command=lambda: (self._sync_th_type_buttons(), self._apply_filters()),
        )
        self.th_type_sell_rb = tk.Radiobutton(
            self.th_type_wrap,
            text="SELL",
            variable=self.th_type_var,
            value="SELL",
            indicatoron=0,
            width=4, padx=6, pady=4,
            font=ModernStyle.FONT_SUBHEADING,
            relief=tk.FLAT, bd=0,
            bg=_RB_UNSEL_BG, fg=_RB_UNSEL_FG,
            selectcolor=_RB_SELL_SEL,
            activebackground=_RB_UNSEL_BG,
            command=lambda: (self._sync_th_type_buttons(), self._apply_filters()),
        )
        self.th_type_all_rb.pack(side="left", padx=(0, 3))
        self.th_type_buy_rb.pack(side="left", padx=(0, 3))
        self.th_type_sell_rb.pack(side="left")
        
        # Date range filters with colored pills
        start_pill = ModernCard(filter_row, bg=ModernStyle.BG_SECONDARY, highlight_color="#FEF3C7", highlight_thickness=1, radius=8)
        start_pill.pack(side=tk.LEFT, padx=3, pady=3)
        tk.Label(start_pill.content, text="📅 Start Date:", bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY, font=ModernStyle.FONT_HEADING).pack(side=tk.LEFT, padx=3, pady=3)
        self.th_start_entry = _create_date_input(start_pill.content, self.th_start_var)
        self.th_start_entry.pack(side=tk.LEFT, padx=3, pady=3)
        
        end_pill = ModernCard(filter_row, bg=ModernStyle.BG_SECONDARY, highlight_color="#FEF3C7", highlight_thickness=1, radius=8)
        end_pill.pack(side=tk.LEFT, padx=3, pady=3)
        tk.Label(end_pill.content, text="📆 End Date:", bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY, font=ModernStyle.FONT_HEADING).pack(side=tk.LEFT, padx=3, pady=3)
        self.th_end_entry = _create_date_input(end_pill.content, self.th_end_var)
        self.th_end_entry.pack(side=tk.LEFT, padx=3, pady=3)
        
        # Spacer
        tk.Frame(filter_row, bg=ModernStyle.BG_SECONDARY).pack(side=tk.LEFT, expand=True)
        
        # Apply button at end of filter row
        ModernButton(
            filter_row,
            text="Apply",
            command=self._apply_filters,
            bg=ModernStyle.ACCENT_PRIMARY,
            fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.BG_SECONDARY,
            width=80,
            height=28,
        ).pack(side=tk.LEFT, padx=2, pady=3)

        _date_timer_id: list = [None]  # mutable cell to hold the after-id

        def _on_date_change(*_):
            start = self.th_start_var.get().strip()
            end   = self.th_end_var.get().strip()

            # Ignore blank / incomplete values that arrive during transitions
            if not start or not end or len(start) < 8 or len(end) < 8:
                return

            # Cancel any pending call and debounce by 300 ms
            if _date_timer_id[0] is not None:
                try:
                    self.after_cancel(_date_timer_id[0])
                except Exception:
                    pass
            _date_timer_id[0] = self.after(300, lambda: (
                self._update_date_range_info(),
                self._apply_filters(),
            ))

        try:
            self.th_start_var.trace_add("write", _on_date_change)
            self.th_end_var.trace_add("write", _on_date_change)
        except Exception as e:
                pass

        # Initialize date range info and load data
        self._update_date_range_info()
        self._apply_filters()  # Load initial data

        def _debounced_symbol(*_):
            try:
                if self._th_search_timer is not None:
                    self.after_cancel(self._th_search_timer)
            except Exception:
                pass
            self._th_search_timer = self.after(180, self._apply_filters)

        try:
            self.th_symbol_var.trace_add("write", _debounced_symbol)
        except Exception:
            pass

        self._sync_th_type_buttons()


        # Summary card (pill-style metrics - matching Holdings view)
        summary = tk.Frame(self, bg=ModernStyle.BG_PRIMARY, highlightbackground=ModernStyle.BORDER_COLOR, highlightthickness=0)
        summary.pack(fill="x", padx=15, pady=3)

        # Metrics and buttons in same row
        sum_row = tk.Frame(summary, bg=ModernStyle.BG_PRIMARY)
        sum_row.pack(fill="x", padx=0, pady=4)
        
        # Define colored pills for each stat (matching Holdings view)
        stat_configs = [
            ("Trades", "trades", ModernStyle.ACCENT_PRIMARY, "#DBEAFE"),        # Blue
            ("Net Buy Qty", "buy_qty", ModernStyle.SUCCESS, "#DCFCE7"),         # Green
            ("Net Sell Qty", "sell_qty", ModernStyle.ERROR, "#FEF2F2"),         # Red
            ("Live Qty", "live_qty", ModernStyle.ACCENT_PURPLE, "#E9D5FF"),     # Purple
            ("Net Fees", "fees", ModernStyle.ACCENT_TERTIARY, "#FEF3C7"),           # Amber
            ("Running PnL", "pnl", "#0891B2", "#CFFAFE"),                       # Cyan
        ]
        
        for label, key, color, pill_bg in stat_configs:
            stat_pill = ModernCard(sum_row, bg=ModernStyle.BG_SECONDARY, highlight_color=pill_bg, highlight_thickness=2, radius=8)
            stat_pill.pack(side=tk.LEFT, padx=3, pady=3, expand=True, fill=tk.BOTH)
            
            tk.Label(stat_pill.content, text=label, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_KPI_LABEL).pack(pady=(4, 0))
            
            val_label = tk.Label(stat_pill.content, text="—", bg=ModernStyle.BG_SECONDARY, fg=color, font=ModernStyle.FONT_KPI_VALUE)
            val_label.pack(pady=(2, 4))
            
            setattr(self, f"sum_{key}", val_label)

        # Spacer
        tk.Frame(sum_row, bg=ModernStyle.BG_PRIMARY).pack(side=tk.LEFT, expand=True)
        
        # Action buttons on same row as metrics (right side)
        actions = tk.Frame(sum_row, bg=ModernStyle.BG_PRIMARY)
        actions.pack(side=tk.RIGHT, padx=4)

        # Copy Selected button removed per user request
        ModernButton(
            actions,
            text=" ➕ ",
            command=self._open_add_trade_dialog,
            bg=ModernStyle.SUCCESS,
            fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.BG_PRIMARY,
            width=60,
            height=28,
        ).pack(side=tk.LEFT, padx=(0, 6))

        ModernButton(
            actions,
            text=" ➖ ",
            command=self._delete_selected,
            bg=ModernStyle.ERROR,
            fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.BG_PRIMARY,
            width=60,
            height=28,
        ).pack(side=tk.LEFT, padx=(0, 6))

        ModernButton(
            actions,
            text="Copy All",
            command=self._copy_all,
            bg=ModernStyle.ACCENT_PRIMARY,
            fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.BG_PRIMARY,
            width=90,
            height=28,
        ).pack(side=tk.LEFT)

        # Table frame
        table_frame = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        table_frame.pack(fill="both", expand=True, padx=15, pady=10)

        columns = (
            "#",
            "Date",
            "Trade ID",
            "Symbol",
            "Broker",
            "Type",
            "Qty",
            "Price ₹",
            "Trade Value ₹",
            "Running Qty",
            "AvgCost ₹",
            "Trade P&L ₹",
            "Running PnL ₹",
            "Fees ₹",
            "Cum. Fees ₹",
        )
        self.trade_table = ttk.Treeview(table_frame, columns=columns, show="headings", height=18, selectmode="extended")

        widths = [40, 100, 85, 80, 80, 60, 55, 85, 95, 70, 85, 100, 110, 70, 90]
        sortable_cols = ("Symbol", "Date", "Type")
        for col, w in zip(columns, widths):
            if col in sortable_cols:
                self.trade_table.heading(col, text=f"{col} ↕", command=lambda c=col: treeview_sort_column(self.trade_table, c, False))
            else:
                self.trade_table.heading(col, text=col)
            self.trade_table.column(col, width=w)

        try:
            # Custom style to increase font size
            style = ttk.Style()
            style.configure("TH.Treeview", font=ModernStyle.FONT_TABLE, rowheight=30)
            style.configure("TH.Treeview.Heading", font=ModernStyle.FONT_TABLE_BOLD)
            self.trade_table.configure(style="TH.Treeview")
            
            add_treeview_copy_menu(self.trade_table)

            # Semantic BUY/SELL row tinting with alternating shades
            self.trade_table.tag_configure("buy_odd",   background="#F0FDF4", foreground="#15803D")  # green-50 bg, green-700 fg
            self.trade_table.tag_configure("buy_even",  background="#DCFCE7", foreground="#15803D")  # green-100 bg
            self.trade_table.tag_configure("sell_odd",  background="#FFF1F2", foreground="#B91C1C")  # rose-50 bg, red-700 fg
            self.trade_table.tag_configure("sell_even", background="#FEE2E2", foreground="#B91C1C")  # red-100 bg
            # Date-group first-row accent (subtle left-border effect via slightly bolder bg)
            self.trade_table.tag_configure("date_start", font=ModernStyle.FONT_TABLE_BOLD)
        except Exception:
            pass

        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.trade_table.yview)
        self.trade_table.configure(yscroll=vsb.set)

        self.trade_table.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # Empty-state overlay frame (shown when the filter returns 0 rows)
        self._empty_frame = tk.Frame(table_frame, bg=ModernStyle.BG_SECONDARY)
        tk.Label(
            self._empty_frame,
            text="🪹",
            font=ModernStyle.FONT_EMPTY_STATE,
            bg=ModernStyle.BG_SECONDARY,
        ).pack(pady=(0, 4))
        tk.Label(
            self._empty_frame,
            text="No trades found for the selected filters",
            font=ModernStyle.FONT_HEADING,
            fg=ModernStyle.TEXT_SECONDARY,
            bg=ModernStyle.BG_SECONDARY,
        ).pack()
        tk.Label(
            self._empty_frame,
            text="Adjust your search criteria or add a new trade.",
            font=ModernStyle.FONT_BODY,
            fg=ModernStyle.TEXT_TERTIARY,
            bg=ModernStyle.BG_SECONDARY,
        ).pack()

        # Edit on double-click
        try:
            self.trade_table.bind("<Double-1>", self._on_double_click)
        except Exception:
            pass
        
        # Right-click context menu (Button-2 for macOS 3-button mouse, Button-3 for others)
        try:
            self.trade_table.bind("<Button-2>", self._show_trade_context_menu)
            self.trade_table.bind("<Button-3>", self._show_trade_context_menu)
        except Exception:
            pass

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
    def _parse_money(s: str) -> float:
        v = (s or "").strip().replace("₹", "").replace(",", "")
        if v in ("", "—"):
            return 0.0
        return float(v)

    @staticmethod
    def _parse_float(s: str) -> float:
        v = (s or "").strip().replace(",", "")
        if not v:
            return 0.0
        return float(v)

    def _on_double_click(self, event=None) -> None:
        try:
            if self.trade_table.identify_region(event.x, event.y) != "cell":
                return
        except Exception:
            pass

        iid = None
        try:
            iid = self.trade_table.focus()
        except Exception:
            iid = None
        if not iid:
            return

        broker, trade_id = self._split_trade_iid(iid)
        vals = self.trade_table.item(iid, "values") or ()
        if len(vals) < 15:
            return

        # Fetch ALL editable fields from the DB directly — never use display-formatted
        # treeview values (which may be stale, formatted with ₹/commas, or truncated)
        try:
            from model.database import db_session
            with db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT date, symbol, type, qty, price, fee, currency FROM trades WHERE broker=? AND trade_id=?", (broker, trade_id))
                row = cur.fetchone()
                if not row:
                    return
                date, symbol, t_type, qty, price, fee, currency = row[0], row[1], row[2], str(row[3]), str(row[4]), str(row[5]), str(row[6] or 'INR')
        except Exception:
            return

        self._open_edit_trade_dialog(
            broker=broker,
            trade_id=str(trade_id),
            date=date,
            symbol=symbol,
            trade_type=t_type,
            qty=qty,
            price=price,
            fee=fee,
            currency=currency,
        )

    def _open_edit_trade_dialog(
        self,
        *,
        broker: str,
        trade_id: str,
        date: str,
        symbol: str,
        trade_type: str,
        qty: str,
        price: str,
        fee: str,
        currency: str = "INR",
    ) -> None:
        if not broker or not trade_id:
            messagebox.showerror("Edit Trade", "Missing broker/trade id for this row.")
            return

        try:
            if self._th_edit_popup is not None and self._th_edit_popup.winfo_exists():
                self._th_edit_popup.destroy()
        except Exception:
            pass

        win = tk.Toplevel(self)
        self._th_edit_popup = win
        win.title("✏️ Edit Trade")
        ModernStyle.style_modal(win)
        win.configure(bg=ModernStyle.BG_PRIMARY)
        win.resizable(False, False)
        win.geometry("600x540")
        try:
            win.transient(self.winfo_toplevel())
            win.grab_set()
        except Exception:
            pass

        try:
            center_window(win, parent=self.winfo_toplevel())
        except Exception:
            pass

        # ── Header ─────────────────────────────────────────────────────────────
        # Accent top bar
        tk.Frame(win, bg=ModernStyle.ACCENT_PRIMARY, height=4).pack(fill="x")

        header = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
        header.pack(fill="x", padx=28, pady=(18, 0))

        # Big stock name
        tk.Label(
            header,
            text=symbol.upper() if symbol else "Edit Trade",
            bg=ModernStyle.BG_PRIMARY,
            fg=ModernStyle.ACCENT_PRIMARY,
            font=ModernStyle.FONT_SYMBOL_LARGE,
        ).pack(anchor="w")

        tk.Label(
            header,
            text=f"✏️  Editing Trade  ·  {trade_id}",
            bg=ModernStyle.BG_PRIMARY,
            fg=ModernStyle.TEXT_SECONDARY,
            font=ModernStyle.FONT_BODY,
        ).pack(anchor="w", pady=(2, 12))

        # Thin divider
        tk.Frame(win, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=20)

        # ── Form card ──────────────────────────────────────────────────────────
        card = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
        card.pack(fill="both", expand=True, padx=24, pady=16)

        form = tk.Frame(card, bg=ModernStyle.BG_PRIMARY)
        form.pack(fill="x")
        for i in range(2):
            form.grid_columnconfigure(i, weight=1)

        BG = ModernStyle.BG_PRIMARY
        BORDER = "#E2E8F0"
        FG = "#0F172A"

        def _label(text, r, c):
            tk.Label(form, text=text, bg=BG, fg=ModernStyle.TEXT_SECONDARY,
                     font=ModernStyle.FONT_BODY_BOLD).grid(
                row=r * 2, column=c, sticky="w",
                pady=(10 if r > 0 else 0, 4), padx=(0, 12 if c == 0 else 0))

        def _entry_widget(r, c, var, *, is_date=False):
            wrap = tk.Frame(form, bg=BORDER, padx=1, pady=1)
            wrap.grid(row=r * 2 + 1, column=c, sticky="ew",
                      pady=(0, 4), padx=(0, 12 if c == 0 else 0))
            if is_date:
                ent = _create_date_input(wrap, var)
                ent.pack(fill="both", expand=True)
            else:
                ent = tk.Entry(wrap, textvariable=var, bg="#F8FAFC", fg=FG,
                               font=ModernStyle.FONT_TABLE, relief=tk.FLAT,
                               insertbackground=ModernStyle.ACCENT_PRIMARY, highlightthickness=0)
                def _fi(e, w=wrap, i=ent): w.configure(bg=ModernStyle.ACCENT_PRIMARY); i.configure(bg="#FFFFFF")
                def _fo(e, w=wrap, i=ent): w.configure(bg=BORDER); i.configure(bg="#F8FAFC")
                ent.bind("<FocusIn>", _fi)
                ent.bind("<FocusOut>", _fo)
                ent.pack(fill="both", expand=True, ipady=6, padx=8)
            return ent

        self._edit_broker_var = tk.StringVar(value=(broker or "").strip())
        self._edit_date_var   = tk.StringVar(value=(date or "").strip())
        self._edit_symbol_var = tk.StringVar(value=(symbol or "").strip().upper())
        self._edit_type_var   = tk.StringVar(value=(trade_type or "BUY").strip().upper())
        self._edit_qty_var    = tk.StringVar(value=str(qty).replace(",", "").replace("₹", "").strip())
        self._edit_price_var  = tk.StringVar(value=str(price).replace(",", "").replace("₹", "").strip())
        self._edit_fee_var    = tk.StringVar(value=str(fee).replace(",", "").replace("₹", "").strip())
        self._edit_currency_var = tk.StringVar(value=(currency or "INR").strip().upper())

        # Row 0: Broker dropdown + Date
        _label("👑  Broker", 0, 0)
        # Broker dropdown — fetch distinct broker names from trade table
        broker_wrap = tk.Frame(form, bg=BORDER, padx=1, pady=1)
        broker_wrap.grid(row=1, column=0, sticky="ew", pady=(0, 4), padx=(0, 12))
        try:
            import model.crud as _crud
            known_brokers = sorted(set(_crud.get_all_brokers()))
        except Exception:
            known_brokers = []
        if broker and broker not in known_brokers:
            known_brokers.insert(0, broker)
        broker_cb = ttk.Combobox(broker_wrap, textvariable=self._edit_broker_var,
                                  values=known_brokers, font=ModernStyle.FONT_TABLE,
                                  state="normal")
        broker_cb.pack(fill="both", expand=True, ipady=4, padx=4)

        _label("📅  Trade Date", 0, 1)
        _entry_widget(0, 1, self._edit_date_var, is_date=True)

        # Row 1: Symbol + Quantity
        _label("💎  Symbol", 1, 0)
        _entry_widget(1, 0, self._edit_symbol_var)
        _label("📊  Quantity", 1, 1)
        _entry_widget(1, 1, self._edit_qty_var)

        # Row 2: Price + Fees
        _label("💰  Price (₹)", 2, 0)
        _entry_widget(2, 0, self._edit_price_var)
        _label("💸  Fees (₹)", 2, 1)
        _entry_widget(2, 1, self._edit_fee_var)

        lbl_frame = tk.Frame(form, bg=BG)
        lbl_frame.grid(row=8, column=0, columnspan=2, sticky="w", pady=(12, 4))
        tk.Label(lbl_frame, text="🌲  Trade Type", bg=BG, fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_BODY_BOLD).pack(side="left")
        tk.Frame(lbl_frame, width=16, bg=BG).pack(side="left")
        tk.Label(lbl_frame, text="💱  Currency", bg=BG, fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_BODY_BOLD).pack(side="left")

        btn_row = tk.Frame(form, bg=BG)
        btn_row.grid(row=9, column=0, columnspan=2, sticky="w", pady=(0, 10))

        for val, color in [("BUY", "#059669"), ("SELL", "#DC2626")]:
            tk.Radiobutton(btn_row, text=val, variable=self._edit_type_var, value=val,
                           bg=BG, fg=color, font=ModernStyle.FONT_TABLE_BOLD,
                           selectcolor=BG, activebackground=BG).pack(side="left", padx=(0, 24))

        tk.Frame(btn_row, bg=ModernStyle.DIVIDER_COLOR, width=2, height=20).pack(side="left", padx=16)

        for val in ["INR", "JPY"]:
            tk.Radiobutton(btn_row, text=val, variable=self._edit_currency_var, value=val,
                           bg=BG, fg=ModernStyle.ACCENT_PRIMARY, font=ModernStyle.FONT_TABLE_BOLD,
                           selectcolor=BG, activebackground=BG).pack(side="left", padx=(0, 24))

        # Row 3: Trade Type radio buttons


        # ── Status + actions ──────────────────────────────────────────────────
        tk.Frame(win, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=24, pady=(4, 0))

        status = tk.Label(win, text="", bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY,
                          font=ModernStyle.FONT_ITALIC, anchor="w")
        status.pack(anchor="w", padx=28, pady=(8, 4), fill="x")

        actions = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
        actions.pack(fill="x", padx=24, pady=(0, 20))

        def _close():
            try:
                win.destroy()
            except Exception:
                pass

        ModernButton(
            actions, text="✓ Update Trade",
            command=lambda: self._save_trade_edits(broker, trade_id, symbol, status, win),
            bg=ModernStyle.ACCENT_PRIMARY, fg="#ffffff", canvas_bg=ModernStyle.BG_PRIMARY,
            width=160, height=42, radius=8, font=ModernStyle.FONT_SUBHEADING
        ).pack(side="right")

        ModernButton(
            actions, text="✕ Cancel", command=_close,
            bg=ModernStyle.TEXT_TERTIARY, fg="#ffffff", canvas_bg=ModernStyle.BG_PRIMARY,
            width=120, height=42, radius=8, font=ModernStyle.FONT_SUBHEADING
        ).pack(side="right", padx=(0, 12))

    def _save_trade_edits(self, broker_old: str, trade_id: str, symbol_old: str, status_label: tk.Label, dialog: tk.Toplevel) -> None:
        # Validate inputs
        try:
            broker = (self._edit_broker_var.get() or "").strip()
            if not broker:
                raise ValueError("Broker is required")
            date = self._parse_date_or_none(self._edit_date_var.get() or "")
            if not date:
                raise ValueError("Date must be YYYY-MM-DD")
            symbol = (self._edit_symbol_var.get() or "").strip().upper()
            if not symbol:
                raise ValueError("Symbol is required")
            t_type = (self._edit_type_var.get() or "BUY").strip().upper()
            if t_type not in ("BUY", "SELL"):
                raise ValueError("Type must be BUY or SELL")
            qty = self._parse_float(self._edit_qty_var.get())
            price = self._parse_float(self._edit_price_var.get())
            fee = self._parse_float(self._edit_fee_var.get())
            cur = (self._edit_currency_var.get() or "INR").strip().upper()
            if qty <= 0:
                raise ValueError("Qty must be > 0")
            if price <= 0:
                raise ValueError("Price must be > 0")
        except Exception as e:
            status_label.configure(text=str(e), fg=ModernStyle.ERROR)
            return

        rename_all = False
        if symbol != symbol_old:
            rename_all = messagebox.askyesno(
                "Rename Symbol",
                f"You changed the symbol from '{symbol_old}' to '{symbol}'.\n\nDo you want to rename ALL trades for '{symbol_old}' under broker '{broker_old}'?",
                parent=dialog
            )

        status_label.configure(text="Updating…", fg=ModernStyle.TEXT_TERTIARY)

        def _bg():
            err = None
            try:
                import model.crud as crud
                from model.engine import rebuild_holdings
                from model.database import db_session

                if rename_all:
                    # Rename ALL matching trades for the old symbol under this broker
                    with db_session() as conn:
                        conn.execute("UPDATE trades SET symbol = ? WHERE broker = ? AND symbol = ?", (symbol, broker_old, symbol_old))

                # If broker changed, delete old trade and add new one
                if broker != broker_old:
                    crud.delete_trade(broker_old, trade_id)
                    crud.add_trade(broker, date, symbol, t_type, float(qty), float(price), float(fee), trade_id, currency=cur)
                else:
                    # Just update the specific trade being actively edited (overwrites any partial rename if necessary)
                    crud.update_trade(broker, trade_id, date, symbol, t_type, float(qty), float(price), float(fee), currency=cur)
                
                try:
                    rebuild_holdings()
                except Exception:
                    pass
                try:
                    if self.app_state and hasattr(self.app_state, "refresh_data_cache"):
                        self.app_state.refresh_data_cache()
                except Exception:
                    pass
            except Exception as e:
                err = str(e)

            def _done():
                if err:
                    status_label.configure(text=f"Update failed: {err}", fg=ModernStyle.ERROR)
                    return
                try:
                    dialog.destroy()
                except Exception:
                    pass
                self._apply_filters()

            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _open_add_trade_dialog(self) -> None:
        try:
            if self._th_edit_popup is not None and self._th_edit_popup.winfo_exists():
                self._th_edit_popup.destroy()
        except Exception:
            pass

        win = tk.Toplevel(self)
        self._th_edit_popup = win
        win.title("➕ New Trade")
        ModernStyle.style_modal(win)
        win.configure(bg=ModernStyle.BG_PRIMARY)
        win.resizable(False, False)
        win.geometry("600x540")
        try:
            win.transient(self.winfo_toplevel())
            win.grab_set()
        except Exception:
            pass

        try:
            center_window(win, parent=self.winfo_toplevel())
        except Exception:
            pass

        # ── Header ─────────────────────────────────────────────────────────────
        tk.Frame(win, bg=ModernStyle.SUCCESS, height=4).pack(fill="x")

        header = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
        header.pack(fill="x", padx=28, pady=(18, 0))

        tk.Label(
            header,
            text="➕  New Trade",
            bg=ModernStyle.BG_PRIMARY,
            fg=ModernStyle.SUCCESS,
            font=ModernStyle.FONT_SYMBOL_LARGE,
        ).pack(anchor="w")

        tk.Label(
            header,
            text="Add a new historical or manual trade entry",
            bg=ModernStyle.BG_PRIMARY,
            fg=ModernStyle.TEXT_SECONDARY,
            font=ModernStyle.FONT_BODY,
        ).pack(anchor="w", pady=(2, 12))

        tk.Frame(win, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=20)

        # ── Form ───────────────────────────────────────────────────────────────
        card = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
        card.pack(fill="both", expand=True, padx=24, pady=16)

        form = tk.Frame(card, bg=ModernStyle.BG_PRIMARY)
        form.pack(fill="x")
        for i in range(2):
            form.grid_columnconfigure(i, weight=1)

        BG = ModernStyle.BG_PRIMARY
        BORDER = "#E2E8F0"
        FG = "#0F172A"

        def _label(text, r, c):
            tk.Label(form, text=text, bg=BG, fg=ModernStyle.TEXT_SECONDARY,
                     font=ModernStyle.FONT_BODY_BOLD).grid(
                row=r * 2, column=c, sticky="w",
                pady=(10 if r > 0 else 0, 4), padx=(0, 12 if c == 0 else 0))

        def _entry_widget(r, c, var, *, is_date=False):
            wrap = tk.Frame(form, bg=BORDER, padx=1, pady=1)
            wrap.grid(row=r * 2 + 1, column=c, sticky="ew",
                      pady=(0, 4), padx=(0, 12 if c == 0 else 0))
            if is_date:
                ent = _create_date_input(wrap, var)
                ent.pack(fill="both", expand=True)
            else:
                ent = tk.Entry(wrap, textvariable=var, bg="#F8FAFC", fg=FG,
                               font=ModernStyle.FONT_TABLE, relief=tk.FLAT,
                               insertbackground=ModernStyle.SUCCESS, highlightthickness=0)
                def _fi(e, w=wrap, i=ent): w.configure(bg=ModernStyle.SUCCESS); i.configure(bg="#FFFFFF")
                def _fo(e, w=wrap, i=ent): w.configure(bg=BORDER); i.configure(bg="#F8FAFC")
                ent.bind("<FocusIn>", _fi)
                ent.bind("<FocusOut>", _fo)
                ent.pack(fill="both", expand=True, ipady=6, padx=8)
            return ent

        # Try to infer broker from current filter
        initial_broker = ""
        try:
            cur_broker = self.th_broker_var.get()
            if cur_broker and cur_broker != "All":
                initial_broker = cur_broker
        except Exception:
            pass

        self._add_broker_var = tk.StringVar(value=initial_broker)
        self._add_date_var   = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self._add_symbol_var = tk.StringVar(value="")
        self._add_type_var   = tk.StringVar(value="BUY")
        self._add_qty_var    = tk.StringVar(value="")
        self._add_price_var  = tk.StringVar(value="")
        self._add_fee_var    = tk.StringVar(value="0.0")

        # Broker dropdown
        _label("👑  Broker", 0, 0)
        broker_wrap = tk.Frame(form, bg=BORDER, padx=1, pady=1)
        broker_wrap.grid(row=1, column=0, sticky="ew", pady=(0, 4), padx=(0, 12))
        try:
            import model.crud as _crud
            known_brokers = sorted(set(_crud.get_all_brokers()))
        except Exception:
            known_brokers = []
        if initial_broker and initial_broker not in known_brokers:
            known_brokers.insert(0, initial_broker)
        broker_cb = ttk.Combobox(broker_wrap, textvariable=self._add_broker_var,
                                  values=known_brokers, font=ModernStyle.FONT_TABLE,
                                  state="normal")
        broker_cb.pack(fill="both", expand=True, ipady=4, padx=4)

        _label("📅  Trade Date", 0, 1)
        _entry_widget(0, 1, self._add_date_var, is_date=True)

        _label("💎  Symbol", 1, 0)
        sym_ent = _entry_widget(1, 0, self._add_symbol_var)
        _label("📊  Quantity", 1, 1)
        _entry_widget(1, 1, self._add_qty_var)

        # Stock name display: shown below the symbol entry, updated on focus-out
        stock_name_lbl = tk.Label(form, text="", bg=BG, fg=ModernStyle.ACCENT_PRIMARY,
                                  font=ModernStyle.FONT_BODY_BOLD, anchor="w")
        stock_name_lbl.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 4))

        def _on_symbol_focusout(e):
            sym = self._add_symbol_var.get().strip().upper()
            if not sym:
                stock_name_lbl.configure(text="")
                return
            stock_name_lbl.configure(text="⏳ Looking up stock name...")
            def _fetch():
                try:
                    import yfinance as yf
                    info = yf.Ticker(sym + ".NS").info
                    name = info.get("longName") or info.get("shortName") or ""
                    if not name:
                        info2 = yf.Ticker(sym).info
                        name = info2.get("longName") or info2.get("shortName") or sym
                except Exception:
                    name = ""
                def _update():
                    stock_name_lbl.configure(text=name if name else "")
                try:
                    win.after(0, _update)
                except Exception:
                    pass
            threading.Thread(target=_fetch, daemon=True).start()

        sym_ent.bind("<FocusOut>", _on_symbol_focusout)

        _label("💰  Price (₹)", 2, 0)
        _entry_widget(2, 0, self._add_price_var)
        _label("💸  Fees (₹)", 2, 1)
        _entry_widget(2, 1, self._add_fee_var)

        # Trade Type radio buttons
        type_lbl_frame = tk.Frame(form, bg=BG)
        type_lbl_frame.grid(row=6, column=0, columnspan=2, sticky="w", pady=(12, 4))
        tk.Label(type_lbl_frame, text="🌲  Trade Type", bg=BG, fg=ModernStyle.TEXT_SECONDARY,
                 font=ModernStyle.FONT_BODY_BOLD).pack(side="left")

        type_row = tk.Frame(form, bg=BG)
        type_row.grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 10))

        for val, color in [("BUY", "#059669"), ("SELL", "#DC2626")]:
            tk.Radiobutton(type_row, text=val, variable=self._add_type_var, value=val,
                           bg=BG, fg=color, font=ModernStyle.FONT_TABLE_BOLD,
                           selectcolor=BG, activebackground=BG).pack(side="left", padx=(0, 24))

        # ── Status + Actions ────────────────────────────────────────────────────
        tk.Frame(win, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=24, pady=(4, 0))

        status = tk.Label(win, text="", bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY,
                          font=ModernStyle.FONT_ITALIC, anchor="w")
        status.pack(anchor="w", padx=28, pady=(8, 4), fill="x")

        actions = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
        actions.pack(fill="x", padx=24, pady=(0, 20))

        def _close():
            try:
                win.destroy()
            except Exception:
                pass

        ModernButton(
            actions, text="✓ Add Trade",
            command=lambda: self._save_new_trade(status, win),
            bg=ModernStyle.SUCCESS, fg="#ffffff", canvas_bg=ModernStyle.BG_PRIMARY,
            width=160, height=42, radius=8, font=ModernStyle.FONT_SUBHEADING
        ).pack(side="right")

        ModernButton(
            actions, text="✕ Cancel", command=_close,
            bg=ModernStyle.TEXT_TERTIARY, fg="#ffffff", canvas_bg=ModernStyle.BG_PRIMARY,
            width=120, height=42, radius=8, font=ModernStyle.FONT_SUBHEADING
        ).pack(side="right", padx=(0, 12))

    def _save_new_trade(self, status_label: tk.Label, dialog: tk.Toplevel) -> None:
        # Validate inputs
        try:
            broker = (self._add_broker_var.get() or "").strip()
            if not broker:
                raise ValueError("Broker is required")
            date = self._parse_date_or_none(self._add_date_var.get() or "")
            if not date:
                raise ValueError("Date must be YYYY-MM-DD")
            symbol = (self._add_symbol_var.get() or "").strip().upper()
            if not symbol:
                raise ValueError("Symbol is required")
            t_type = (self._add_type_var.get() or "BUY").strip().upper()
            if t_type not in ("BUY", "SELL"):
                raise ValueError("Type must be BUY or SELL")
            qty = self._parse_float(self._add_qty_var.get())
            price = self._parse_float(self._add_price_var.get())
            fee = self._parse_float(self._add_fee_var.get())
            if qty <= 0:
                raise ValueError("Qty must be > 0")
            if price <= 0:
                raise ValueError("Price must be > 0")
        except Exception as e:
            status_label.configure(text=str(e), fg=ModernStyle.ERROR)
            return

        status_label.configure(text="Saving trade…", fg=ModernStyle.TEXT_TERTIARY)

        def _bg():
            err = None
            try:
                import model.crud as crud
                from model.engine import rebuild_holdings
                from model.database import db_session

                import uuid
                trade_id = str(uuid.uuid4())[:8] # Generate a temporary nice tight ID similar to the other ones
                
                crud.add_trade(broker, date, symbol, t_type, float(qty), float(price), float(fee), trade_id)
                
                try:
                    rebuild_holdings()
                except Exception:
                    pass
                try:
                    if self.app_state and hasattr(self.app_state, "refresh_data_cache"):
                        self.app_state.refresh_data_cache()
                except Exception:
                    pass
            except Exception as e:
                err = str(e)

            def _done():
                if err:
                    status_label.configure(text=f"Save failed: {err}", fg=ModernStyle.ERROR)
                    return
                try:
                    dialog.destroy()
                except Exception:
                    pass
                self._apply_filters()

            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _delete_selected(self) -> None:
        try:
            items = list(self.trade_table.selection() or [])
        except Exception:
            items = []
        if not items:
            messagebox.showinfo("Trade History", "Select one or more rows to delete (Cmd-click / Shift-click).")
            return

        count = len(items)
        if count == 1:
            vals = self.trade_table.item(items[0], "values")
            trade_id = str(vals[2]).strip() if len(vals) > 2 else "Unknown"
            msg = f"Are you sure you want to delete trade {trade_id}?\n\nThis action cannot be undone."
            title = "Delete Trade"
        else:
            msg = f"Are you sure you want to delete {count} selected trades?\n\nThis action cannot be undone."
            title = f"Delete {count} Trades"

        # Confirm
        if not messagebox.askyesno(title, msg, parent=self.winfo_toplevel()):
            return

        def _bg():
            err = None
            try:
                import model.crud as crud
                from model.engine import rebuild_holdings

                for iid in items:
                    broker, trade_id = self._split_trade_iid(iid)
                    if not broker or not trade_id:
                        continue
                    crud.delete_trade(broker, trade_id)

                try:
                    rebuild_holdings()
                except Exception:
                    pass
                try:
                    if self.app_state and hasattr(self.app_state, "refresh_data_cache"):
                        self.app_state.refresh_data_cache()
                except Exception:
                    pass
            except Exception as e:
                err = str(e)

            def _done():
                if err:
                    messagebox.showerror("Delete Trades", f"Delete failed: {err}")
                    return
                self._apply_filters()

            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _copy_selected(self) -> None:
        try:
            items = list(self.trade_table.selection() or [])
        except Exception:
            items = []
        if not items:
            messagebox.showinfo("Trade History", "No rows selected.")
            return
        self._copy_items(items)

    def _copy_all(self) -> None:
        items = list(self.trade_table.get_children() or [])
        if not items:
            messagebox.showinfo("Trade History", "No data to copy.")
            return
        self._copy_items(items)

    def _copy_items(self, items: list[str]) -> None:
        cols = list(self.trade_table["columns"])
        lines = ["\t".join(cols)]
        for iid in items:
            vals = self.trade_table.item(iid, "values")
            lines.append("\t".join(str(v).replace("₹", "").replace(",", "").replace("%", "").strip() for v in vals))
        text = "\n".join(lines)
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("Trade History", f"Copied {len(items)} row(s) to clipboard.")
        except Exception as e:
            messagebox.showerror("Trade History", f"Failed to copy: {e}")

    def _show_trade_context_menu(self, event) -> None:
        """Show right-click context menu for trade history table."""
        try:
            iid = self.trade_table.identify_row(event.y)
            if not iid:
                return
            
            # Select the clicked row if not already selected
            if iid not in self.trade_table.selection():
                self.trade_table.selection_set(iid)
            
            # Get trade data for edit
            vals = self.trade_table.item(iid, "values") or ()
            
            # Create context menu
            menu = tk.Menu(self.trade_table, tearoff=False)
            
            # Only enable Edit if we have enough values
            if len(vals) >= 15:
                menu.add_command(label="Edit", command=lambda: self._edit_from_context(iid))
            
            menu.add_command(label="Copy", command=self._copy_selected)
            menu.add_separator()
            menu.add_command(label="Delete", command=self._delete_selected)
            
            # Display menu
            menu.tk_popup(event.x_root, event.y_root)
        except Exception as e:
            pass

    def _edit_from_context(self, iid: str) -> None:
        """Edit a trade from context menu."""
        try:
            broker, trade_id = self._split_trade_iid(iid)
            vals = self.trade_table.item(iid, "values") or ()
            if len(vals) < 15:
                messagebox.showerror("Edit Trade", "Invalid row data.")
                return

            date = str(vals[1])
            symbol = str(vals[3])
            t_type_raw = str(vals[5]).upper()
            t_type = "BUY" if "BUY" in t_type_raw else "SELL"
            qty = str(vals[6])
            price = str(vals[7])
            fee = str(vals[13])

            self._open_edit_trade_dialog(
                broker=broker,
                trade_id=trade_id,
                date=date,
                symbol=symbol,
                trade_type=t_type,
                qty=qty,
                price=price,
                fee=fee,
            )
        except Exception as e:
            messagebox.showerror("Edit Trade", f"Error: {e}")

    def on_show(self):
        self._is_active = True
        self._load_brokers()
        if not getattr(self, "_data_loaded", False):
            self.load_data()

    def _load_brokers(self):
        """Load broker list in background to populate dropdown."""
        def _bg():
            try:
                import model.crud as crud
                brokers = ["All"] + list(crud.get_all_brokers())
                
                def _update_ui():
                    curr = self.th_broker_var.get()
                    self.th_broker_cb["values"] = brokers
                    # Restore selection if it still exists in the new list, otherwise default to All
                    if curr not in brokers:
                        self.th_broker_var.set("All")
                    else:
                        self.th_broker_var.set(curr)

                self.after(0, _update_ui)
            except Exception as e:
                # Fallback to at least "All" if database fails
                self.after(0, lambda: self.th_broker_cb.configure(values=["All"]))
                print(f"Error loading brokers in TradeHistoryView: {e}")

        import threading
        threading.Thread(target=_bg, daemon=True).start()

    def on_hide(self):
        self._is_active = False

    def _parse_date_or_none(self, s: str) -> str | None:
        val = (s or "").strip()
        if not val:
            return None
        try:
            # Validate format
            datetime.strptime(val, "%Y-%m-%d")
        except Exception:
            pass
            #raise ValueError("Date must be YYYY-MM-DD")
        return val

    def _update_date_range_info(self) -> None:
        """Update the date range info label to show selected range."""
        try:
            start_str = self.th_start_var.get().strip()
            end_str = self.th_end_var.get().strip()
            
            if start_str and end_str:
                start_dt = datetime.strptime(start_str, "%Y-%m-%d")
                end_dt = datetime.strptime(end_str, "%Y-%m-%d")
                days_diff = (end_dt - start_dt).days
                
                # Format: "Jan 1 - Jan 31 (31 days)"
                date_range = f"{start_dt.strftime('%b %d')} - {end_dt.strftime('%b %d')} ({days_diff + 1} days)"
                self.th_date_range_info.config(text=date_range)
            else:
                self.th_date_range_info.config(text="")
        except Exception:
            self.th_date_range_info.config(text="")

    def _debounced_symbol(self) -> None:
        """Debounced symbol search to avoid excessive filtering."""
        try:
            if self._th_search_timer is not None:
                self.after_cancel(self._th_search_timer)
        except Exception:
            pass
        self._th_search_timer = self.after(180, self._apply_filters)

    def _apply_filters(self) -> None:
        pass
        # Update date range info display
        self._update_date_range_info()
        # Re-run load with current UI filters
        self._data_loaded = False
        self.load_data()

    def load_data(self):
        if self.app_state and hasattr(self.app_state, "data_cache"):
            self._is_active = True
            self._data_loaded = True

            def _bg():
                try:
                    from model.database import _invalidate_thread_connection
                    from model.data_cache import TradeHistoryFilters
                    _invalidate_thread_connection()
                    
                    # Refresh cache from DB to pick up latest changes
                    try:
                        self.app_state.data_cache.refresh_from_db()
                    except Exception:
                        pass

                    broker = (getattr(self, "th_broker_var", None).get() if hasattr(self, "th_broker_var") else "All")
                    # Use get_value() from ModernEntry to ignore placeholder text
                    symbol_like = (self.th_symbol_entry.get_value() if hasattr(self, "th_symbol_entry") else "")
                    trade_type = (getattr(self, "th_type_var", None).get() if hasattr(self, "th_type_var") else "All")

                    start_raw = (getattr(self, "th_start_var", None).get() if hasattr(self, "th_start_var") else "")
                    end_raw = (getattr(self, "th_end_var", None).get() if hasattr(self, "th_end_var") else "")
                    start_date = self._parse_date_or_none(start_raw)
                    end_date = self._parse_date_or_none(end_raw)

                    filters = TradeHistoryFilters(
                        broker=broker or "All",
                        symbol_like=symbol_like or "",
                        trade_type=trade_type or "All",
                        start_date=start_date,
                        end_date=end_date,
                    )
                    df, summary = self.app_state.data_cache.get_tradehistory_filtered(filters)
                    self.after(0, lambda: self._update_trades(df, summary))
                except ValueError as ve:
                    err = str(ve)
                    self.after(0, lambda e=err: messagebox.showerror("Trade History", e))
                    self._data_loaded = False
                except Exception as e:
                    self._data_loaded = False

            threading.Thread(target=_bg, daemon=True).start()

    def _sync_th_type_buttons(self) -> None:
        t = (self.th_type_var.get() or "All").upper()
        try:
            if t == "BUY":
                self.th_type_buy_rb.configure(bg=ModernStyle.ACCENT_SECONDARY, fg=ModernStyle.TEXT_ON_ACCENT, activebackground=ModernStyle.ACCENT_SECONDARY, activeforeground=ModernStyle.TEXT_ON_ACCENT)
                self.th_type_sell_rb.configure(bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_PRIMARY, activebackground=ModernStyle.BG_PRIMARY, activeforeground=ModernStyle.TEXT_PRIMARY)
                self.th_type_all_rb.configure(bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_PRIMARY, activebackground=ModernStyle.BG_PRIMARY, activeforeground=ModernStyle.TEXT_PRIMARY)
            elif t == "SELL":
                self.th_type_sell_rb.configure(bg=ModernStyle.ERROR, fg=ModernStyle.TEXT_ON_ACCENT, activebackground=ModernStyle.ERROR, activeforeground=ModernStyle.TEXT_ON_ACCENT)
                self.th_type_buy_rb.configure(bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_PRIMARY, activebackground=ModernStyle.BG_PRIMARY, activeforeground=ModernStyle.TEXT_PRIMARY)
                self.th_type_all_rb.configure(bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_PRIMARY, activebackground=ModernStyle.BG_PRIMARY, activeforeground=ModernStyle.TEXT_PRIMARY)
            else:
                self.th_type_all_rb.configure(bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT, activebackground=ModernStyle.ACCENT_PRIMARY, activeforeground=ModernStyle.TEXT_ON_ACCENT)
                self.th_type_buy_rb.configure(bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_PRIMARY, activebackground=ModernStyle.BG_PRIMARY, activeforeground=ModernStyle.TEXT_PRIMARY)
                self.th_type_sell_rb.configure(bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_PRIMARY, activebackground=ModernStyle.BG_PRIMARY, activeforeground=ModernStyle.TEXT_PRIMARY)
        except Exception:
            pass

    def _update_trades(self, df, summary: dict):
        # clear
        for item in self.trade_table.get_children():
            self.trade_table.delete(item)

        # summary
        try:
            qty_buy = float(summary.get("qty_buy", 0.0) or 0.0)
            qty_sell = float(summary.get("qty_sell", 0.0) or 0.0)
            live_qty = qty_buy - qty_sell
            fee_buy = float(summary.get("fee_buy", 0.0) or 0.0)
            fee_sell = float(summary.get("fee_sell", 0.0) or 0.0)
            total_pnl = float(summary.get("total_pnl", 0.0) or 0.0)
            trades = int(getattr(df, "shape", [0])[0] or 0) if df is not None else 0
            self.sum_trades.config(text=f"{trades}")
            self.sum_buy_qty.config(text=f"{qty_buy:g}")
            self.sum_sell_qty.config(text=f"{qty_sell:g}")
            self.sum_live_qty.config(text=f"{live_qty:g}")
            self.sum_fees.config(text=f"₹{(fee_buy + fee_sell):,.2f}")
            self.sum_pnl.config(text=f"₹{total_pnl:,.2f}", fg=ModernStyle.SUCCESS if total_pnl >= 0 else ModernStyle.ERROR)
        except Exception:
            pass

        if df is None or getattr(df, "empty", True):
            # Show the empty-state overlay
            try:
                self._empty_frame.place(relx=0.5, rely=0.5, anchor="center")
            except Exception:
                pass
            return

        # Hide empty-state overlay
        try:
            self._empty_frame.place_forget()
        except Exception:
            pass

        current_date = None
        buy_count = 0
        sell_count = 0
        running_tpnl = 0.0
        cum_fees: dict[tuple[str, str], float] = {}  # (broker, symbol) → cumulative fees

        for idx, row in enumerate(df.itertuples(index=False)):
            row_date = str(getattr(row, "date", ""))
            try:
                from datetime import datetime
                disp_date = datetime.strptime(row_date, "%Y-%m-%d").strftime("%Y-%b-%d")
            except Exception:
                disp_date = row_date

            is_new_date = row_date != current_date
            if is_new_date:
                current_date = row_date
                buy_count = 0
                sell_count = 0

            row_type = str(getattr(row, "type", "")).upper()
            qty = float(getattr(row, "qty", 0.0) or 0.0)
            price = float(getattr(row, "price", 0.0) or 0.0)
            fee = float(getattr(row, "fee", 0.0) or 0.0)
            run_qty = float(getattr(row, "run_qty", 0.0) or 0.0)
            avg_cost = float(getattr(row, "avg_cost", 0.0) or 0.0)
            trade_pnl = float(getattr(row, "trade_pnl", 0.0) or 0.0)

            # Trade Value = Qty × Price
            trade_value = qty * price

            # Cumulative fees per (broker, symbol)
            broker = str(getattr(row, "broker", "") or "").strip()
            symbol_val = str(getattr(row, "symbol", "") or "").strip()
            fee_key = (broker, symbol_val)
            cum_fees[fee_key] = cum_fees.get(fee_key, 0.0) + fee
            cum_fee_disp = cum_fees[fee_key]

            from ui_utils import format_money
            currency = str(getattr(row, 'currency', 'INR')).strip().upper()

            # Running PnL (cumulative trade_pnl)
            running_tpnl += trade_pnl
            if row_type == "SELL":
                arrow = "🌲" if running_tpnl >= 0 else "🔻"
                pnl_disp = f"{arrow} {format_money(abs(running_tpnl), currency)}"
            else:
                pnl_disp = "—"

            # Per-trade P&L (only meaningful for SELL)
            if row_type == "SELL" and trade_pnl != 0.0:
                tp_arrow = "▲" if trade_pnl >= 0 else "▼"
                tp_disp = f"{tp_arrow} {format_money(abs(trade_pnl), currency)}"
            else:
                tp_disp = "—"

            trade_id = str(getattr(row, "trade_id", "") or "").strip()
            iid = self._make_trade_iid(broker, trade_id)

            type_disp = row_type
            if row_type == "BUY":
                type_disp = "🌲 Buy"
                buy_count += 1
                stripe = "buy_odd" if buy_count % 2 == 1 else "buy_even"
            elif row_type == "SELL":
                type_disp = "🔻 Sell"
                sell_count += 1
                stripe = "sell_odd" if sell_count % 2 == 1 else "sell_even"
            else:
                stripe = "buy_odd"

            # Build tag list — add date_start for first row of each date group
            tags = [stripe]
            if is_new_date:
                tags.append("date_start")

            values = (
                str(idx + 1),
                disp_date,
                trade_id,
                symbol_val,
                broker,
                type_disp,
                f"{qty:g}",
                format_money(price, currency),
                format_money(trade_value, currency),
                f"{run_qty:g}",
                format_money(avg_cost, currency),
                tp_disp,
                pnl_disp,
                format_money(fee, currency),
                format_money(cum_fee_disp, currency),
            )
            try:
                self.trade_table.insert("", "end", iid=iid, values=values, tags=tuple(tags))
            except Exception:
                # Fallback if iid collides (should be rare)
                self.trade_table.insert("", "end", values=values, tags=tuple(tags))

