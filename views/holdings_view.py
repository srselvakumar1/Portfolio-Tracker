"""
Holdings View - Tkinter Implementation
Modern, premium aesthetic with real-time data display
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import pandas as pd
from typing import Optional
from model.data_cache import DataCache, HoldingsFilters, TradeHistoryFilters
from model.database import db_session
import model.crud as crud

from ui_theme import ModernStyle
from ui_widgets import ModernButton, ModernEntry, PremiumModal, ModernDropdown, ModernCard, ClearableEntry
from ui_utils import center_window, add_treeview_copy_menu, treeview_sort_column, fade_color_transition
from views.base_view import BaseView

class HoldingsView(BaseView):
    def build(self):
        self._search_timer = None
        self.current_df: Optional[pd.DataFrame] = None
        self._row_meta: dict[str, dict] = {}
        
        # Initialize data cache
        self.data_cache = DataCache()
        try:
            self.data_cache.refresh_from_db()
        except Exception as e:
            print(f"Error loading data cache: {e}")
            
        self._build_header()
        self._build_filter_panel()
        self._build_stats_card()
        self._build_table()
        self.load_data()
    
    def _build_header(self):
        self.add_gradient_header(
            self,
            "💹 Holdings",
            "Manage and monitor your stock portfolio",
            show_divider=False
        )
    
    def _build_filter_panel(self):
        """Build filters grouped into two visual zones, separated by a colored divider."""
        from ui_widgets import ModernSegmentedControl

        CTRL_HEIGHT = 32  # unified control height for the whole bar
        FONT = ModernStyle.FONT_HEADING

        filter_frame = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        filter_frame.pack(fill=tk.X, padx=20, pady=(4, 2))

        # ── GROUP 1: Search ────────────────────────────────────────────────────
        grp1 = tk.Frame(filter_frame, bg=ModernStyle.BG_SECONDARY)
        grp1.pack(side=tk.LEFT, padx=(0, 0), pady=4, anchor=tk.CENTER)

        # Broker
        tk.Label(
            grp1, text="🏦 Broker:", bg=ModernStyle.BG_SECONDARY,
            fg=ModernStyle.TEXT_PRIMARY, font=FONT
        ).pack(side=tk.LEFT, padx=(10, 4), pady=4, anchor=tk.CENTER)
        self.broker_var = tk.StringVar(value="All")
        self.broker_combo = ttk.Combobox(
            grp1, textvariable=self.broker_var,
            values=["All"], state="readonly", width=12, font=ModernStyle.FONT_TABLE
        )
        self.broker_combo.pack(side=tk.LEFT, padx=(0, 6), pady=6, anchor=tk.CENTER)
        try:
            self.broker_var.trace_add("write", lambda *args: self._on_broker_selected())
        except Exception:
            pass

        # Currency variable (no UI toggle — auto-detected from broker/data)
        self.currency_var = tk.StringVar(value="INR")

        # Thin inner divider
        tk.Frame(grp1, bg=ModernStyle.ACCENT_PRIMARY, width=1).pack(
            side=tk.LEFT, fill=tk.Y, pady=6
        )

        # Symbol search
        tk.Label(
            grp1, text="🔍 Symbol:", bg=ModernStyle.BG_SECONDARY,
            fg=ModernStyle.TEXT_PRIMARY, font=FONT
        ).pack(side=tk.LEFT, padx=(8, 4), pady=4, anchor=tk.CENTER)
        self._symbol_bar = ClearableEntry(
            grp1,
            placeholder="Search...",
            on_change=self._on_symbol_search,
            bg=ModernStyle.ENTRY_BG,
            fg=ModernStyle.ACCENT_PRIMARY,
            font=ModernStyle.FONT_INPUT,
            width=15,
        )
        self._symbol_bar.pack(side=tk.LEFT, padx=(0, 10), pady=6, anchor=tk.CENTER)
        self.symbol_entry = self._symbol_bar.entry

        # ── COLORED VERTICAL DIVIDER ─────────────────────────────────────────
        tk.Frame(filter_frame, bg=ModernStyle.ACCENT_PRIMARY, width=3).pack(
            side=tk.LEFT, fill=tk.Y, padx=8, pady=6
        )

        # ── GROUP 2: Filters ──────────────────────────────────────────────────
        grp2 = tk.Frame(filter_frame, bg=ModernStyle.BG_SECONDARY)
        grp2.pack(side=tk.LEFT, padx=(0, 0), pady=4, anchor=tk.CENTER)

        # Signal segmented control
        tk.Label(
            grp2, text="📊 Signal:", bg=ModernStyle.BG_SECONDARY,
            fg=ModernStyle.TEXT_PRIMARY, font=FONT
        ).pack(side=tk.LEFT, padx=(10, 4), pady=4, anchor=tk.CENTER)
        self.signal_var = tk.StringVar(value="All")
        signal_seg = ModernSegmentedControl(
            grp2,
            options=["All", "Accumulate", "Reduce", "None"],
            variable=self.signal_var,
            command=self.on_filter_change,
            bg=ModernStyle.BG_TERTIARY,
            fg=ModernStyle.TEXT_SECONDARY,
            container_bg=ModernStyle.BG_SECONDARY,
            font=FONT,
            height=CTRL_HEIGHT,
            per_option_colors={
                "Accumulate": (ModernStyle.SUCCESS,        ModernStyle.TEXT_ON_ACCENT),
                "Reduce":     (ModernStyle.ERROR,          ModernStyle.TEXT_ON_ACCENT),
                "All":        (ModernStyle.ACCENT_PRIMARY, ModernStyle.TEXT_ON_ACCENT),
                "None":       (ModernStyle.TEXT_SECONDARY, ModernStyle.TEXT_ON_ACCENT),
            },
        )
        signal_seg.pack(side=tk.LEFT, padx=(0, 6), pady=4, anchor=tk.CENTER)

        # Thin inner divider
        tk.Frame(grp2, bg=ModernStyle.SUCCESS, width=1).pack(
            side=tk.LEFT, fill=tk.Y, pady=6
        )

        # Position / state segmented control
        tk.Label(
            grp2, text="🛡️ Filter:", bg=ModernStyle.BG_SECONDARY,
            fg=ModernStyle.TEXT_PRIMARY, font=FONT
        ).pack(side=tk.LEFT, padx=(8, 4), pady=4, anchor=tk.CENTER)
        self.holding_state_var = tk.StringVar(value="Active")
        state_seg = ModernSegmentedControl(
            grp2,
            options=["All", "Active", "Closed"],
            variable=self.holding_state_var,
            command=self.on_filter_change,
            bg=ModernStyle.BG_TERTIARY,
            fg=ModernStyle.TEXT_SECONDARY,
            container_bg=ModernStyle.BG_SECONDARY,
            active_bg=ModernStyle.SUCCESS,
            font=FONT,
            height=CTRL_HEIGHT,
        )
        state_seg.pack(side=tk.LEFT, padx=(0, 10), pady=4, anchor=tk.CENTER)

        # ── SPACER + REFRESH ─────────────────────────────────────────────────
        tk.Frame(filter_frame, bg=ModernStyle.BG_PRIMARY).pack(side=tk.LEFT, expand=True, fill=tk.X)

        refresh_btn = ModernButton(
            filter_frame,
            text="⟳ Refresh",
            command=self.refresh,
            bg=ModernStyle.ACCENT_TERTIARY,
            fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.BG_PRIMARY,
            width=100,
            height=CTRL_HEIGHT,
        )
        refresh_btn.pack(side=tk.LEFT, padx=(4, 0), pady=4, anchor=tk.CENTER)

        # Load brokers in the background
        threading.Thread(target=self._load_brokers, daemon=True).start()


    def _sort_and_remember(self, col: str):
        """Sort the treeview by the given column and remember the state for re-apply after refresh."""
        # Toggle direction if clicking the same column again
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = False
        treeview_sort_column(self.tree, col, self._sort_reverse)
        # Re-bind heading command: treeview_sort_column replaces it with its own
        # internal lambda which would bypass our state tracking on subsequent clicks
        self.tree.heading(col, command=lambda c=col: self._sort_and_remember(c))

    def _build_stats_card(self):
        stats_frame = tk.Frame(
            self,
            bg=ModernStyle.BG_PRIMARY,
            highlightbackground=ModernStyle.BORDER_COLOR,
            highlightthickness=0,
        )
        stats_frame.pack(fill=tk.X, padx=20, pady=2)
        
        self.stats_labels = {}
        self.stats_sublabels = {}
        
        # Define colored pills for each stat
        stat_configs = [
            ("Holdings", "count", ModernStyle.ACCENT_PRIMARY, ModernStyle.ACCENT_PRIMARY_PALE),
            ("Invested Value", "invested", ModernStyle.ACCENT_SECONDARY, ModernStyle.ACCENT_SECONDARY_PALE),
            ("Current Value", "current", ModernStyle.INFO, ModernStyle.INFO_PALE),
            ("Real P&L", "realized_pnl", ModernStyle.SUCCESS, ModernStyle.SUCCESS_PALE),
            ("Unreal P&L", "unrealized_pnl", ModernStyle.WARNING, ModernStyle.WARNING_PALE),
            ("Total Fees", "fees", ModernStyle.ERROR, ModernStyle.ERROR_PALE),
        ]
        
        for label, key, color, pill_bg in stat_configs:
            # Fallbacks for styles that might be missing locally
            try: pill_bg_color = pill_bg if getattr(ModernStyle, pill_bg.split(".")[-1] if "." in pill_bg else pill_bg, None) else ModernStyle.BG_SECONDARY
            except Exception: pill_bg_color = ModernStyle.BG_SECONDARY
            
            stat_pill = ModernCard(stats_frame, bg=ModernStyle.BG_SECONDARY, highlight_color=pill_bg_color, highlight_thickness=2, radius=8)
            stat_pill.pack(side=tk.LEFT, padx=3, pady=3, expand=True, fill=tk.BOTH)
            
            tk.Label(stat_pill.content, text=label, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_KPI_LABEL).pack(pady=(4, 0))
            
            val_label = tk.Label(stat_pill.content, text="—", bg=ModernStyle.BG_SECONDARY, fg=color, font=ModernStyle.FONT_KPI_VALUE)
            val_label.pack(pady=(2, 4))
            
            self.stats_labels[key] = val_label

        # Right-side actions (requested: at right end of Summary section)
        tk.Frame(stats_frame, bg=ModernStyle.BG_PRIMARY).pack(side=tk.LEFT, expand=True, fill=tk.X)
        actions = tk.Frame(stats_frame, bg=ModernStyle.BG_PRIMARY)
        actions.pack(side=tk.RIGHT, padx=4, pady=3)

        ModernButton(
            actions,
            text="Delete",
            command=self._delete_selected_holding,
            bg=ModernStyle.ERROR,
            fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.BG_PRIMARY,
            width=100,
            height=32,
        ).pack(side=tk.LEFT)
    
    def _build_table(self):
        """Build holdings table."""
        table_frame = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=4)

        # Inner frame for the table grid (tree + scrollbars)
        inner = tk.Frame(table_frame, bg=ModernStyle.BG_PRIMARY)
        inner.pack(fill=tk.BOTH, expand=True)
        
        # Create treeview (match Flet column set)
        columns = (
            "#",
            "Symbol",
            "Name",
            "Qty",
            "Avg Price",
            "Mkt Price",
            "PE Ratio",
            "Daily Chg %",
            "Unreal PnL",
            "Weight %",
            "XIRR %",
            "CAGR %",
            "Real PnL",
            "Net PnL",
            "Fees",
            "IV Signal",
        )
        self.tree = ttk.Treeview(inner, columns=columns, height=20, show="headings")
        
        # Define headings and column widths
        widths = [40, 100, 160, 60, 90, 90, 70, 90, 100, 150, 70, 70, 100, 100, 80, 100]
        # Track current sort state so we can re-apply after data refresh
        self._sort_col = None
        self._sort_reverse = False
        
        sortable_cols = ("Symbol", "PE Ratio", "Fees", "Real PnL", "Net PnL", "XIRR %", "CAGR %", "IV Signal")
        for col, w in zip(columns, widths):
            if col in sortable_cols:
                self.tree.heading(col, text=f"{col} ↕", command=lambda c=col: self._sort_and_remember(c))
            else:
                self.tree.heading(col, text=col)
            self.tree.column(col, width=w)

        # Alternating rows - clean zebra stripe, no per-row color overrides
        try:
            style = ttk.Style()
            style.configure("Holdings.Treeview", font=ModernStyle.FONT_TABLE, rowheight=30)
            # Header: dark slate — clearly distinct from the blue row-selection colour
            style.configure(
                "Holdings.Treeview.Heading",
                font=ModernStyle.FONT_TABLE_BOLD,
                background=ModernStyle.SLATE_800,
                foreground=ModernStyle.TEXT_ON_ACCENT,
                relief="flat",
            )
            style.map(
                "Holdings.Treeview.Heading",
                background=[("active", ModernStyle.SLATE_700)],
                foreground=[("active", ModernStyle.TEXT_ON_ACCENT)],
            )
            self.tree.configure(style="Holdings.Treeview")
            
            # Add right-click copy menu
            add_treeview_copy_menu(self.tree)

            # Only background zebra stripes — no foreground color tags on rows
            self.tree.tag_configure("odd",  background=ModernStyle.BG_SECONDARY)
            self.tree.tag_configure("even", background=ModernStyle.SLATE_50)
            # Signal highlighting tags - using a more saturated green for visibility
            self.tree.tag_configure("sig_accumulate", background="#d2fee2") 
            self.tree.tag_configure("low_unrealized_pnl", background="#FEE2E2") 
        except Exception:
            pass
        
        # Scrollbars
        vsb = ttk.Scrollbar(inner, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(inner, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscroll=vsb.set, xscroll=hsb.set)
        
        # Grid
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        
        inner.grid_rowconfigure(0, weight=1)
        inner.grid_columnconfigure(0, weight=1)

        # Empty-state overlay frame
        self._empty_frame = tk.Frame(inner, bg=ModernStyle.BG_SECONDARY)
        tk.Label(
            self._empty_frame,
            text="🪹",
            font=ModernStyle.FONT_EMPTY_STATE,
            bg=ModernStyle.BG_SECONDARY,
        ).pack(pady=(0, 4))
        tk.Label(
            self._empty_frame,
            text="No holdings match the current filter",
            font=ModernStyle.FONT_HEADING,
            fg=ModernStyle.TEXT_SECONDARY,
            bg=ModernStyle.BG_SECONDARY,
        ).pack()
        tk.Label(
            self._empty_frame,
            text="Clear your search or add a new trade.",
            font=ModernStyle.FONT_BODY,
            fg=ModernStyle.TEXT_TERTIARY,
            bg=ModernStyle.BG_SECONDARY,
        ).pack()        # Open drilldown on double-click
        try:
            self.tree.bind("<Double-1>", lambda _e=None: self._open_drilldown_selected())
        except Exception:
            pass
        
        # Right-click context menu (Button-2 for macOS 3-button mouse, Button-3 for others)
        try:
            self.tree.bind("<Button-2>", self._show_holdings_context_menu)
            self.tree.bind("<Button-3>", self._show_holdings_context_menu)
        except Exception:
            pass

    def _copy_selected(self) -> None:
        try:
            items = list(self.tree.selection() or [])
        except Exception:
            items = []
        if not items:
            messagebox.showinfo("Holdings", "No rows selected.")
            return
        self._copy_items(items)

    def _copy_all(self) -> None:
        items = list(self.tree.get_children() or [])
        if not items:
            messagebox.showinfo("Holdings", "No data to copy.")
            return
        self._copy_items(items)

    def _copy_items(self, items: list[str]) -> None:
        cols = list(self.tree["columns"])
        lines = ["\t".join(cols)]
        for iid in items:
            vals = self.tree.item(iid, "values")
            lines.append("\t".join(str(v).replace("₹", "").replace("¥", "").replace("$", "").replace(",", "").replace("%", "").strip() for v in vals))
        text = "\n".join(lines)
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("Holdings", f"Copied {len(items)} row(s) to clipboard.")
        except Exception as e:
            messagebox.showerror("Holdings", f"Failed to copy: {e}")

    def _show_holdings_context_menu(self, event) -> None:
        """Show right-click context menu for holdings table."""
        try:
            iid = self.tree.identify_row(event.y)
            if not iid:
                return
            
            # Select the clicked row if not already selected
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            
            # Create context menu
            menu = tk.Menu(self.tree, tearoff=False)
            menu.add_command(label="Edit", command=lambda: self._edit_holding_properties(iid))
            menu.add_command(label="View Trades", command=self._open_drilldown_selected)
            menu.add_command(label="➕ Add Trade", command=lambda: self._open_add_trade_from_holding(iid))
            menu.add_separator()
            menu.add_command(label="Copy Selected", command=self._copy_selected)
            menu.add_command(label="Copy All (Visible)", command=self._copy_all)
            menu.add_separator()
            menu.add_command(label="Delete", command=self._delete_selected_holding)
            
            # Display menu
            menu.tk_popup(event.x_root, event.y_root)
        except Exception as e:
            print(f"Context menu error: {e}")

    def _open_add_trade_from_holding(self, iid: str, *, keep_open: bool = False,
                                      symbol: str = "", broker: str = "",
                                      stock_name: str = "",
                                      on_success=None) -> None:
        """Open a quick Add Trade popup pre-filled with the holding's symbol and broker.

        Args:
            iid: Treeview row id (used to look up meta when symbol/broker not supplied).
            keep_open: If True the window stays open after each save so the user
                       can add multiple trades consecutively ("Add Trade & Continue").
            symbol / broker / stock_name: Override values; if empty the row meta is used.
            on_success: Optional callable invoked on the main thread after each
                        successful save (e.g. to reload a drilldown table).
        """
        import threading
        from ui_utils import center_window

        # Resolve symbol / broker from the row if not overridden
        if not symbol or not broker:
            meta = self._row_meta.get(iid, {})
            try:
                values = self.tree.item(iid, "values") or ()
                symbol = symbol or str(meta.get("symbol") or (values[1] if len(values) > 1 else "")).strip()
            except Exception:
                symbol = symbol or ""
            broker = broker or str(meta.get("broker") or "").strip()
            stock_name = stock_name or str(meta.get("stock_name") or "").strip()

        win = tk.Toplevel(self)
        win.title("➕ Add Trade & Continue" if keep_open else "➕ Add Trade")
        ModernStyle.style_modal(win)
        win.configure(bg=ModernStyle.BG_PRIMARY)
        win.resizable(False, False)
        win.geometry("600x520" if keep_open else "600x500")
        try:
            win.transient(self.winfo_toplevel())
            win.grab_set()
        except Exception:
            pass
        try:
            center_window(win, parent=self.winfo_toplevel())
        except Exception:
            pass

        # ── Header ──────────────────────────────────────────────────────────────
        hdr_color = ModernStyle.ACCENT_PRIMARY if keep_open else ModernStyle.SUCCESS
        tk.Frame(win, bg=hdr_color, height=4).pack(fill="x")

        header = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
        header.pack(fill="x", padx=28, pady=(16, 0))

        tk.Label(
            header, text=symbol,
            bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.ACCENT_PRIMARY,
            font=ModernStyle.FONT_SYMBOL_LARGE,
        ).pack(anchor="w")

        self._add_h_stock_name_lbl = tk.Label(
            header, text=stock_name if stock_name else "",
            bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY,
            font=ModernStyle.FONT_SUBHEADING,
        )
        self._add_h_stock_name_lbl.pack(anchor="w", pady=(0, 8))

        mode_text = "➕  Quick Add Trade • Continue Mode" if keep_open else "➕  Quick Add Trade"
        tk.Label(
            header, text=mode_text,
            bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY,
            font=ModernStyle.FONT_BODY,
        ).pack(anchor="w", pady=(0, 10))

        tk.Frame(win, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=20)

        # ── Form ────────────────────────────────────────────────────────────────
        card = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
        card.pack(fill="both", expand=True, padx=24, pady=12)

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
                pady=(8 if r > 0 else 0, 4), padx=(0, 12 if c == 0 else 0))

        _qty_entry_ref = [None]

        def _entry(r, c, var, *, is_date=False):
            from views.base_view import _create_date_input
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

        from datetime import datetime as _DT
        _add_broker_var  = tk.StringVar(value=broker)
        _add_date_var    = tk.StringVar(value=_DT.now().strftime("%Y-%m-%d"))
        _add_symbol_var  = tk.StringVar(value=symbol)
        _add_type_var    = tk.StringVar(value="BUY")
        _add_qty_var     = tk.StringVar(value="")
        _add_price_var   = tk.StringVar(value="")
        _add_fee_var     = tk.StringVar(value="0.0")
        _add_currency_var = tk.StringVar(value="INR")

        # Broker dropdown
        _label("👑  Broker", 0, 0)
        broker_wrap = tk.Frame(form, bg=BORDER, padx=1, pady=1)
        broker_wrap.grid(row=1, column=0, sticky="ew", pady=(0, 4), padx=(0, 12))
        try:
            import model.crud as _crud
            known_brokers = sorted(set(_crud.get_all_brokers()))
        except Exception:
            known_brokers = []
        if broker and broker not in known_brokers:
            known_brokers.insert(0, broker)
        ttk.Combobox(broker_wrap, textvariable=_add_broker_var,
                     values=known_brokers, font=ModernStyle.FONT_TABLE,
                     state="normal").pack(fill="both", expand=True, ipady=4, padx=4)

        _label("📅  Date", 0, 1)
        _entry(0, 1, _add_date_var, is_date=True)

        _label("📊  Quantity", 1, 0)
        _qty_entry = _entry(1, 0, _add_qty_var)
        _qty_entry_ref[0] = _qty_entry
        _label("💰  Price", 1, 1)
        _entry(1, 1, _add_price_var)

        _label("💸  Fees", 2, 0)
        _entry(2, 0, _add_fee_var)

        # Trade type + Currency on same row
        tc_lbl_row = tk.Frame(form, bg=BG)
        tc_lbl_row.grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 4))
        tk.Label(tc_lbl_row, text="🌲 Trade Type", bg=BG, fg=ModernStyle.TEXT_SECONDARY,
                 font=ModernStyle.FONT_BODY_BOLD).pack(side="left")
        tk.Frame(tc_lbl_row, width=16, bg=BG).pack(side="left")
        tk.Label(tc_lbl_row, text="💱 Currency", bg=BG, fg=ModernStyle.TEXT_SECONDARY,
                 font=ModernStyle.FONT_BODY_BOLD).pack(side="left")

        tc_row = tk.Frame(form, bg=BG)
        tc_row.grid(row=7, column=0, columnspan=2, sticky="w")
        for val, color in [("BUY", "#059669"), ("SELL", "#DC2626")]:
            tk.Radiobutton(tc_row, text=val, variable=_add_type_var, value=val,
                           bg=BG, fg=color, font=ModernStyle.FONT_TABLE_BOLD,
                           selectcolor=BG, activebackground=BG).pack(side="left", padx=(0, 24))
        tk.Frame(tc_row, bg=ModernStyle.DIVIDER_COLOR, width=2, height=20).pack(side="left", padx=16)
        for val in ["INR", "JPY"]:
            tk.Radiobutton(tc_row, text=val, variable=_add_currency_var, value=val,
                           bg=BG, fg=ModernStyle.ACCENT_PRIMARY, font=ModernStyle.FONT_TABLE_BOLD,
                           selectcolor=BG, activebackground=BG).pack(side="left", padx=(0, 24))

        # ── Actions ─────────────────────────────────────────────────────────────
        tk.Frame(win, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=24, pady=(4, 0))

        status_lbl = tk.Label(win, text="", bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY,
                              font=ModernStyle.FONT_ITALIC, anchor="w")
        status_lbl.pack(anchor="w", padx=28, pady=(6, 4), fill="x")

        act = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
        act.pack(fill="x", padx=24, pady=(0, 16))

        # Counter label — always shown, updates after each "Add & Continue" save
        _save_count = [0]
        count_lbl = tk.Label(act, text="", bg=ModernStyle.BG_PRIMARY,
                             fg=ModernStyle.ACCENT_PRIMARY, font=ModernStyle.FONT_BODY_BOLD)
        count_lbl.pack(side="left")

        def _do_save(close_after: bool):
            """Validate, persist, and either close or reset the form."""
            try:
                b = _add_broker_var.get().strip()
                if not b: raise ValueError("Broker is required")
                d_str = _add_date_var.get().strip()
                import datetime as _dt
                _dt.datetime.strptime(d_str, "%Y-%m-%d")  # validates format
                sym = _add_symbol_var.get().strip().upper()
                if not sym: raise ValueError("Symbol is required")
                t = _add_type_var.get().strip().upper()
                qty = float(_add_qty_var.get().replace(",", "") or 0)
                price = float(_add_price_var.get().replace(",", "").replace("₹", "").replace("¥", "").replace("$", "") or 0)
                fee = float(_add_fee_var.get().replace(",", "").replace("₹", "").replace("¥", "").replace("$", "") or 0)
                if qty <= 0: raise ValueError("Qty must be > 0")
                if price <= 0: raise ValueError("Price must be > 0")
            except Exception as ex:
                status_lbl.configure(text=str(ex), fg=ModernStyle.ERROR)
                return

            status_lbl.configure(text="Saving…", fg=ModernStyle.TEXT_SECONDARY)

            def _bg():
                err = None
                try:
                    import model.crud as _crud2
                    import uuid
                    trade_id = str(uuid.uuid4())[:8]
                    cur = _add_currency_var.get() or "INR"
                    _crud2.add_trade(b, d_str, sym, t, qty, price, fee, trade_id, currency=cur)
                    try:
                        from model.engine import rebuild_holdings
                        rebuild_holdings()
                    except Exception:
                        pass
                    try:
                        if self.app_state and hasattr(self.app_state, "refresh_data_cache"):
                            self.app_state.refresh_data_cache()
                    except Exception:
                        pass
                except Exception as ex2:
                    err = str(ex2)

                def _done():
                    if err:
                        status_lbl.configure(text=f"Error: {err}", fg=ModernStyle.ERROR)
                        return
                    # Always refresh the main holdings table in background
                    try:
                        self.load_data()
                    except Exception:
                        pass
                    # Run the optional caller-supplied callback (e.g. reload drilldown)
                    try:
                        if on_success:
                            on_success()
                    except Exception:
                        pass
                    if close_after:
                        try:
                            win.destroy()
                        except Exception:
                            pass
                    else:
                        # Keep-open mode: reset transient fields, show success flash
                        _save_count[0] += 1
                        status_lbl.configure(
                            text=f"✅ Trade saved!  ({_save_count[0]} trade{'s' if _save_count[0] != 1 else ''} added this session)",
                            fg=ModernStyle.SUCCESS,
                        )
                        count_lbl.configure(text=f"📌 {_save_count[0]} added")
                        _add_qty_var.set("")
                        _add_price_var.set("")
                        _add_fee_var.set("0.0")
                        # Focus back to Qty for quick re-entry
                        try:
                            if _qty_entry_ref[0]:
                                _qty_entry_ref[0].focus_set()
                        except Exception:
                            pass

                self.after(0, _done)

            threading.Thread(target=_bg, daemon=True).start()

        from ui_widgets import ModernButton as _MB
        # ✓ Add Trade — closes after save (rightmost)
        _MB(act, text="✓ Add Trade", command=lambda: _do_save(close_after=True),
            bg=ModernStyle.SUCCESS, fg="#ffffff", canvas_bg=BG,
            width=150, height=40, radius=8, font=ModernStyle.FONT_SUBHEADING
        ).pack(side="right")
        # ⟳ Add & Continue — keeps window open, resets fields
        _MB(act, text="⟳ Add & Continue", command=lambda: _do_save(close_after=False),
            bg=ModernStyle.ACCENT_PRIMARY, fg="#ffffff", canvas_bg=BG,
            width=165, height=40, radius=8, font=ModernStyle.FONT_SUBHEADING
        ).pack(side="right", padx=(0, 10))
        _MB(act, text="✕ Cancel", command=win.destroy,
            bg=ModernStyle.TEXT_TERTIARY, fg="#ffffff", canvas_bg=BG,
            width=110, height=40, radius=8, font=ModernStyle.FONT_SUBHEADING
        ).pack(side="right", padx=(0, 10))

    def _edit_holding_properties(self, iid: str) -> None:
        """Edit holding properties: stock name, avg cost, and total fees."""
        try:
            meta = self._row_meta.get(iid, {})
            values = self.tree.item(iid, "values") or ()
            
            symbol = str(meta.get("symbol") or (values[1] if len(values) > 1 else "")).strip()
            broker = str(meta.get("broker") or "").strip()
            stock_name = str(values[2] if len(values) > 2 else "—").replace("—", "").strip()
            avg_cost = str(values[4] if len(values) > 4 else "0").replace("₹", "").replace("¥", "").replace("$", "").replace("£", "").replace(",", "").strip()
            total_fees = str(meta.get("total_fees") or "0").replace("₹", "").replace("¥", "").replace("$", "").replace("£", "").replace(",", "").strip()
            row_currency = str(meta.get("currency") or "INR").upper()
            cur_sym = {"JPY": "¥", "USD": "$"}.get(row_currency, "₹")
            
            if not symbol or not broker:
                messagebox.showerror("Edit Holding", "Could not determine symbol/broker for selected row.")
                return
            
            # Create edit dialog using PremiumModal base class
            win = PremiumModal(self, title="Edit Holding", geometry="500x500", icon="✏️")
            
            # Add chips for context
            win.add_chip("📈", symbol, bg_color=ModernStyle.ACCENT_PRIMARY, fg_color=ModernStyle.SLATE_300)
            win.add_chip("🏦", broker, bg_color=ModernStyle.SLATE_800, fg_color=ModernStyle.SLATE_300)
            
            # Add top right close button manually to the top header
            tk.Button(
                win.inner_hdr, 
                text="✕", 
                command=win.destroy, 
                bg=ModernStyle.BG_PRIMARY, 
                fg=ModernStyle.ERROR, 
                font=ModernStyle.FONT_SECTION_LABEL,
                bd=0,
                activebackground=ModernStyle.BG_PRIMARY,
                activeforeground=ModernStyle.SALMON,
                cursor="hand2"
            ).pack(side="right", anchor="ne", padx=(0, 10))
            
            form = win.content_frame
            form.grid_columnconfigure(0, weight=1)
            
            def _field(label: str, emoji: str, row: int, var: tk.StringVar, hint: str = ""):
                # Label row
                lrow = tk.Frame(form, bg=ModernStyle.SLATE_50)
                lrow.grid(row=row, column=0, sticky="w", pady=(0, 4))
                tk.Label(
                    lrow, text=emoji,
                    bg=ModernStyle.SLATE_50, fg=ModernStyle.ACCENT_PRIMARY,
                    font=ModernStyle.FONT_HEADING
                ).pack(side="left", padx=(0, 6))
                tk.Label(
                    lrow, text=label,
                    bg=ModernStyle.SLATE_50, fg=ModernStyle.SLATE_900,
                    font=ModernStyle.FONT_SUBHEADING
                ).pack(side="left")
                if hint:
                    tk.Label(
                        lrow, text=hint,
                        bg=ModernStyle.SLATE_50, fg=ModernStyle.SLATE_400,
                        font=ModernStyle.FONT_SMALL
                    ).pack(side="left", padx=(6, 0))

                # Entry wrap with focus ring effect
                ent_wrap = tk.Frame(form, bg=ModernStyle.SLATE_300, padx=1, pady=1)
                ent_wrap.grid(row=row + 1, column=0, sticky="ew", pady=(0, 18))
                
                ent = tk.Entry(
                    ent_wrap,
                    textvariable=var,
                    bg=ModernStyle.BG_SECONDARY,
                    fg=ModernStyle.SLATE_900,
                    font=ModernStyle.FONT_HEADING,
                    relief=tk.FLAT,
                    insertbackground=ModernStyle.ACCENT_PRIMARY,
                    highlightthickness=0
                )
                
                def _on_focus_in(e, wrap=ent_wrap, inner=ent):
                    wrap.configure(bg=ModernStyle.ACCENT_PRIMARY)
                    inner.configure(bg=ModernStyle.BG_SECONDARY)
                def _on_focus_out(e, wrap=ent_wrap, inner=ent):
                    wrap.configure(bg=ModernStyle.SLATE_300)
                    inner.configure(bg=ModernStyle.BG_SECONDARY)
                
                ent.bind("<FocusIn>", _on_focus_in)
                ent.bind("<FocusOut>", _on_focus_out)
                ent.pack(fill="both", expand=True, ipady=8, padx=12)
                return ent
            
            stock_name_var = tk.StringVar(value=stock_name)
            avg_cost_var = tk.StringVar(value=avg_cost)
            total_fees_var = tk.StringVar(value=total_fees)
            
            _field("Stock Name", "💠", 0, stock_name_var, "(optional)")
            _field("Avg Cost", "💎", 2, avg_cost_var, f"({cur_sym})")
            _field("Total Fees", "💙", 4, total_fees_var, f"({cur_sym})")
            
            # We use PremiumModal's actions_frame
            actions = win.actions_frame
            
            def _close():
                try:
                    win.destroy()
                except Exception:
                    pass
            
            def _save():
                try:
                    new_stock_name = (stock_name_var.get() or "").strip()
                    new_avg_cost = float(avg_cost_var.get() or "0")
                    new_total_fees = float(total_fees_var.get() or "0")
                    
                    if new_avg_cost < 0:
                        raise ValueError("Avg Cost cannot be negative")
                    if new_total_fees < 0:
                        raise ValueError("Total Fees cannot be negative")
                    
                    win.set_status("⏳ Saving…")
                    
                    def _bg():
                        err = None
                        try:
                            from model.engine import rebuild_holdings
                            from model.database import db_session
                            
                            # Update stock name via crud
                            crud.update_holding_properties(broker, symbol, new_stock_name, new_avg_cost, new_total_fees)
                            
                            # If total_fees changed, proportionally scale individual trade fees
                            # so that rebuild_holdings() will recalculate the same total.
                            old_total = float(total_fees or 0)
                            if abs(new_total_fees - old_total) > 0.001 and old_total > 0:
                                ratio = new_total_fees / old_total
                                with db_session() as conn:
                                    cur = conn.cursor()
                                    cur.execute(
                                        "UPDATE trades SET fee = ROUND(fee * ?, 2) WHERE broker = ? AND symbol = ?",
                                        (ratio, broker, symbol)
                                    )
                            elif abs(new_total_fees - old_total) > 0.001 and old_total == 0:
                                # Old total was 0 but new isn't — distribute evenly
                                with db_session() as conn:
                                    cur = conn.cursor()
                                    cur.execute("SELECT COUNT(*) FROM trades WHERE broker = ? AND symbol = ?", (broker, symbol))
                                    trade_count = cur.fetchone()[0]
                                    if trade_count > 0:
                                        per_trade = round(new_total_fees / trade_count, 2)
                                        cur.execute(
                                            "UPDATE trades SET fee = ? WHERE broker = ? AND symbol = ?",
                                            (per_trade, broker, symbol)
                                        )
                            
                            # Now rebuild holdings from the updated trades — this ensures
                            # total_fees, avg_price, and PnL are all consistent
                            rebuild_holdings()
                            
                            try:
                                if self.app_state is not None and hasattr(self.app_state, "refresh_data_cache"):
                                    self.app_state.refresh_data_cache()
                            except Exception:
                                pass
                        except Exception as e:
                            err = str(e)
                        
                        def _done():
                            if err:
                                win.set_status(f"❌ Save failed: {err}", is_error=True)
                                return
                            try:
                                win.destroy()
                            except Exception:
                                pass
                            self.load_data()
                        
                        self.after(0, _done)
                    
                    threading.Thread(target=_bg, daemon=True).start()
                except Exception as e:
                    win.set_status(str(e), is_error=True)
            
            ModernButton(actions, text="✕  Cancel", command=_close, bg=ModernStyle.SALMON, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.SLATE_50, width=130, height=38).pack(side="right")
            ModernButton(actions, text="✔  Update", command=_save, bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.SLATE_50, width=130, height=38).pack(side="right", padx=(0, 10))
        except Exception as e:
            messagebox.showerror("Edit Holding", f"Error: {e}")

    def _open_drilldown_selected(self) -> None:
        try:
            sel = list(self.tree.selection() or [])
        except Exception:
            sel = []
        if not sel:
            messagebox.showinfo("Drilldown", "Select a holding row first.")
            return

        iid = sel[0]
        meta = self._row_meta.get(iid, {})
        # Fallback: read symbol from displayed table
        try:
            values = self.tree.item(iid, "values")
            symbol = str(values[1]) if len(values) > 1 else ""
        except Exception:
            symbol = ""

        symbol = (meta.get("symbol") or symbol or "").strip()
        if not symbol or symbol == "—":
            messagebox.showerror("Drilldown", "Could not determine symbol for selected row.")
            return

        broker = (meta.get("broker") or "").strip()
        stock_name_val = meta.get("stock_name")
        stock_name = stock_name_val.strip() if isinstance(stock_name_val, str) else ""

        top = PremiumModal(self, title="Trade Drilldown", geometry="980x640", icon="📊")

        if stock_name:
            top.title_lbl.config(text=f"{stock_name}", fg=ModernStyle.BRAND_GOLD, font=ModernStyle.FONT_DRILLDOWN_SYM)
        else:
            top.title_lbl.config(text=f"{symbol} Drilldown")

        # Summary line displayed inline as chips
        def _update_chips_ui(c_qty, c_avg, c_mkt, c_fees, c_pnl, c_currency):
            for w in top.chips_row.winfo_children():
                w.destroy()
            
            f_bold = ModernStyle.FONT_BODY_BOLD
            
            from ui_utils import format_money
            
            top.add_chip("📈", symbol, bg_color=ModernStyle.ACCENT_PRIMARY, fg_color=ModernStyle.SLATE_300, font=f_bold)
            top.add_chip("🏦", broker if broker else "All brokers", bg_color=ModernStyle.SLATE_800, fg_color=ModernStyle.SLATE_300, font=f_bold)
            
            pnl_color = ModernStyle.SUCCESS if c_pnl >= 0 else ModernStyle.ERROR
            
            # Format nicely. Added alongside chips to stay inline top
            top.add_chip("📊", f"Qty: {c_qty:g}", bg_color=ModernStyle.BG_PRIMARY, fg_color=ModernStyle.TEXT_PRIMARY, font=f_bold)
            top.add_chip("💵", f"Avg: {format_money(c_avg, c_currency)}", bg_color=ModernStyle.BG_PRIMARY, fg_color=ModernStyle.TEXT_PRIMARY, font=f_bold)
            top.add_chip("💰", f"Mkt: {format_money(c_mkt, c_currency)}", bg_color=ModernStyle.BG_PRIMARY, fg_color=ModernStyle.TEXT_PRIMARY, font=f_bold)
            top.add_chip("📉", f"Fees: {format_money(c_fees, c_currency)}", bg_color=ModernStyle.BG_PRIMARY, fg_color=ModernStyle.WARNING, font=f_bold)
            top.add_chip("🏆", f"P&L: {format_money(c_pnl, c_currency)}", bg_color=ModernStyle.BG_PRIMARY, fg_color=pnl_color, font=f_bold)

        try:
            qty = float(meta.get("qty", 0.0) or 0.0)
            avg = float(meta.get("avg_price", 0.0) or 0.0)
            mkt = float(meta.get("market_price", 0.0) or 0.0)
            pnl = float(meta.get("running_pnl", 0.0) or 0.0)
            fees = float(meta.get("total_fees", 0.0) or 0.0)
            currency = str(meta.get("currency") or "INR")
            _update_chips_ui(qty, avg, mkt, fees, pnl, currency)
        except Exception:
            pass

        # ── Drilldown: mutable TV ref for reload callback ──────────────────────────
        _dd_trade_tv_ref = [None]

        def _reload_drilldown():
            """Reload the drilldown trade table after a trade has been added."""
            tv = _dd_trade_tv_ref[0]
            if tv is None:
                return
            def _load_bg():
                # fetch fresh holdings stats for chips
                c_qty, c_avg, c_mkt, c_fees, c_pnl = 0.0, 0.0, 0.0, 0.0, 0.0
                cur_currency = str(meta.get("currency") or "INR")
                try:
                    from model.database import _invalidate_thread_connection, db_session
                    _invalidate_thread_connection()
                    with db_session() as conn:
                        cur = conn.cursor()
                        if broker:
                            cur.execute("SELECT h.qty, h.avg_price, m.current_price, h.total_fees, h.running_pnl, h.currency FROM holdings h LEFT JOIN marketdata m ON h.symbol = m.symbol WHERE h.symbol=? AND h.broker=?", (symbol, broker))
                            row = cur.fetchone()
                            if row:
                                c_qty, c_avg, c_mkt, c_fees, c_pnl = map(lambda x: float(x or 0.0), row[:5])
                                cur_currency = row[5] or "INR"
                        else:
                            cur.execute("SELECT SUM(h.qty), SUM(h.qty*h.avg_price), MAX(m.current_price), SUM(h.total_fees), SUM(h.running_pnl), MAX(h.currency) FROM holdings h LEFT JOIN marketdata m ON h.symbol = m.symbol WHERE h.symbol=?", (symbol,))
                            row = cur.fetchone()
                            if row and row[0] is not None:
                                c_qty = float(row[0])
                                sum_cost = float(row[1] or 0.0)
                                c_avg = sum_cost / c_qty if c_qty > 0 else 0.0
                                c_mkt = float(row[2] or 0.0)
                                c_fees = float(row[3] or 0.0)
                                c_pnl = float(row[4] or 0.0)
                                cur_currency = row[5] or "INR"
                    self.after(0, lambda: _update_chips_ui(c_qty, c_avg, c_mkt, c_fees, c_pnl, cur_currency))
                except Exception as e:
                    pass

                try:
                    cache = None
                    if self.app_state is not None and hasattr(self.app_state, "data_cache"):
                        cache = self.app_state.data_cache
                    else:
                        cache = self.data_cache
                    try:
                        cache.refresh_from_db()
                    except Exception:
                        pass
                    f = TradeHistoryFilters(
                        broker=(broker if broker else "All"),
                        symbol_like=symbol,
                        trade_type="All",
                        start_date=None,
                        end_date=None,
                    )
                    df, _sum = cache.get_tradehistory_filtered(f)
                except Exception:
                    df = pd.DataFrame()

                def _apply():
                    try:
                        if not tv.winfo_exists():
                            return
                    except Exception:
                        return
                    _update_chips_ui(c_qty, c_avg, c_mkt, c_fees, c_pnl, cur_currency)
                    for it in tv.get_children():
                        tv.delete(it)
                    if df is None or df.empty:
                        return
                    from ui_utils import format_money
                    for i, r in enumerate(df.itertuples(index=False)):
                        rtype = str(getattr(r, "type", "")).upper()
                        qty_v = float(getattr(r, "qty", 0.0) or 0.0)
                        price_v = float(getattr(r, "price", 0.0) or 0.0)
                        fee_v = float(getattr(r, "fee", 0.0) or 0.0)
                        run_qty_v = float(getattr(r, "run_qty", 0.0) or 0.0)
                        avg_cost_v = float(getattr(r, "avg_cost", 0.0) or 0.0)
                        rpnl_v = float(getattr(r, "running_pnl", 0.0) or 0.0)
                        row_currency = str(getattr(r, "currency", cur_currency) or cur_currency)
                        rpnl_disp = format_money(rpnl_v, row_currency) if rtype in {"SELL", "S"} else "—"
                        type_disp = rtype
                        type_tag = ""
                        if rtype in {"BUY", "B"}:
                            type_disp = "🌲 BUY"
                            type_tag = "🌲 buy"
                        elif rtype in {"SELL", "S"}:
                            type_disp = "🔻 SELL"
                            type_tag = "🔻 sell"
                        raw_d = str(getattr(r, "date", ""))
                        try:
                            from datetime import datetime
                            disp_d = datetime.strptime(raw_d, "%Y-%m-%d").strftime("%Y-%b-%d")
                        except Exception:
                            disp_d = raw_d
                        vals = (
                            str(i + 1),
                            disp_d,
                            str(getattr(r, "trade_id", "")),
                            type_disp,
                            f"{qty_v:g}",
                            format_money(price_v, row_currency),
                            format_money(fee_v, row_currency),
                            f"{run_qty_v:g}",
                            format_money(avg_cost_v, row_currency),
                            rpnl_disp,
                            str(getattr(r, "broker", "")),
                        )
                        tv.insert("", "end", values=vals, tags=(type_tag,))

                self.after(0, _apply)

            threading.Thread(target=_load_bg, daemon=True).start()

        # ── Top-right action panel (floated with place, immune to chip crowding) ──
        # Using place() on the Toplevel itself ensures the buttons always appear
        # in the top-right corner regardless of how many chips are in inner_hdr.
        _dd_iid = ""  # drilldown always uses explicit symbol/broker overrides
        from ui_widgets import ModernButton as _DDBtn

        # Floating panel — rendered on top of everything, anchored to top-right
        _action_panel = tk.Frame(top, bg=ModernStyle.BG_PRIMARY)
        _action_panel.place(relx=1.0, rely=0.0, anchor="ne", x=-12, y=14)

        # ➕ Add Trade (green) — left button in the panel
        _DDBtn(
            _action_panel,
            text="➕ Add Trade",
            command=lambda: self._open_add_trade_from_holding(
                _dd_iid, keep_open=False,
                symbol=symbol, broker=broker, stock_name=stock_name,
                on_success=_reload_drilldown,
            ),
            bg=ModernStyle.SUCCESS, fg="#ffffff",
            canvas_bg=ModernStyle.BG_PRIMARY,
            width=130, height=30,
        ).pack(side="left", padx=(0, 6))

        # ✕ Close (vivid red) — right button in the panel
        _DDBtn(
            _action_panel,
            text="✕ Close",
            command=top.destroy,
            bg=ModernStyle.ERROR, fg="#ffffff",
            canvas_bg=ModernStyle.BG_PRIMARY,
            width=90, height=30,
        ).pack(side="left")

        body = top.content_frame

        act = top.actions_frame
        # Clear and hide the bottom actions bar — buttons are in the floating panel
        for widget in act.winfo_children():
            widget.destroy()
        act.pack_forget()
        table = tk.Frame(body, bg=ModernStyle.BG_SECONDARY)
        table.pack(fill="both", expand=True)
        table.grid_rowconfigure(0, weight=1)
        table.grid_columnconfigure(0, weight=1)

        # Configure style for the drilldown table (matching Trade History view font size)
        style = ttk.Style()
        style.configure("Drilldown.Treeview", font=ModernStyle.FONT_TABLE, rowheight=32)
        style.configure("Drilldown.Treeview.Heading", font=ModernStyle.FONT_TABLE_BOLD)
        
        # Determine symbol for headers
        _sym_map = {"INR": "₹", "JPY": "¥", "USD": "$", "GBP": "£", "CNY": "¥"}
        sym_disp = _sym_map.get(str(meta.get("currency", "INR")).upper(), "₹")

        cols = ("#", "Date", "Trade ID", "Type", "Qty", f"Price {sym_disp}", f"Fees {sym_disp}", "Running Qty", f"AvgCost {sym_disp}", f"Running PnL {sym_disp}", "Broker")
        trade_tv = ttk.Treeview(table, columns=cols, show="headings", height=16, style="Drilldown.Treeview")
        _dd_trade_tv_ref[0] = trade_tv  # expose to reload callback
        widths = [40, 90, 90, 60, 70, 90, 80, 80, 95, 100, 100]
        for c, w in zip(cols, widths):
            trade_tv.heading(c, text=c)
            trade_tv.column(c, width=w, anchor="w", stretch=True)
        
        # Configure coloring tags
        trade_tv.tag_configure("🌲 buy", foreground=ModernStyle.SUCCESS, font=ModernStyle.FONT_TABLE)
        trade_tv.tag_configure("🔻 sell", foreground=ModernStyle.ERROR, font=ModernStyle.FONT_TABLE)

        vsb = ttk.Scrollbar(table, orient="vertical", command=trade_tv.yview)
        trade_tv.configure(yscrollcommand=vsb.set)

        trade_tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        
        # Add right click copy menu to the popup table
        add_treeview_copy_menu(trade_tv)

        # Context Menus and Double click for Edit / Delete
        trade_tv.bind("<Button-2>", lambda e: self._show_drilldown_context_menu(e, trade_tv, _reload_drilldown))
        trade_tv.bind("<Button-3>", lambda e: self._show_drilldown_context_menu(e, trade_tv, _reload_drilldown))
        trade_tv.bind("<Double-1>", lambda e: self._edit_trade_focus_handler(trade_tv, _reload_drilldown))

        # Load trades from cache (in background)
        def _load():
            try:
                # Prefer app_state cache if present to stay consistent with other views
                cache = None
                if self.app_state is not None and hasattr(self.app_state, "data_cache"):
                    cache = self.app_state.data_cache
                else:
                    cache = self.data_cache

                f = TradeHistoryFilters(
                    broker=(broker if broker else "All"),
                    symbol_like=symbol,
                    trade_type="All",
                    start_date=None,
                    end_date=None,
                )
                df, _sum = cache.get_tradehistory_filtered(f)
            except Exception:
                df = pd.DataFrame()

            def _apply():
                for it in trade_tv.get_children():
                    trade_tv.delete(it)
                if df is None or df.empty:
                    return
                running_tpnl = 0.0
                from ui_utils import format_money
                for i, r in enumerate(df.itertuples(index=False)):
                    rtype = str(getattr(r, "type", "")).upper()
                    qty = float(getattr(r, "qty", 0.0) or 0.0)
                    price = float(getattr(r, "price", 0.0) or 0.0)
                    fee = float(getattr(r, "fee", 0.0) or 0.0)
                    run_qty = float(getattr(r, "run_qty", 0.0) or 0.0)
                    avg_cost = float(getattr(r, "avg_cost", 0.0) or 0.0)
                    tpnl = float(getattr(r, "trade_pnl", 0.0) or 0.0)
                    running_tpnl += tpnl
                    row_cur = str(getattr(r, "currency", meta.get("currency", "INR")) or "INR")
                    rpnl_disp = format_money(running_tpnl, row_cur) if rtype in {"SELL", "S"} else "—"
                    type_disp = rtype
                    type_tag = ""
                    if rtype in {"BUY", "B"}:
                        type_disp = "🌲 BUY"
                        type_tag = "🌲 buy"
                    elif rtype in {"SELL", "S"}:
                        type_disp = "🔻 SELL"
                        type_tag = "🔻 sell"

                    raw_d = str(getattr(r, "date", ""))
                    try:
                        from datetime import datetime
                        disp_d = datetime.strptime(raw_d, "%Y-%m-%d").strftime("%Y-%b-%d")
                    except Exception:
                        disp_d = raw_d
                    vals = (
                        str(i + 1),
                        disp_d,
                        str(getattr(r, "trade_id", "")),
                        type_disp,
                        f"{qty:g}",
                        format_money(price, row_cur),
                        format_money(fee, row_cur),
                        f"{run_qty:g}",
                        format_money(avg_cost, row_cur),
                        rpnl_disp,
                        str(getattr(r, "broker", "")),
                    )
                    trade_tv.insert("", "end", values=vals, tags=(type_tag,))

            self.after(0, _apply)

        threading.Thread(target=_load, daemon=True).start()

    def _delete_selected_holding(self) -> None:
        try:
            sel = list(self.tree.selection() or [])
        except Exception:
            sel = []
        if not sel:
            messagebox.showinfo("Delete Holding", "Select a holding row first.")
            return

        iid = sel[0]
        meta = self._row_meta.get(iid, {})
        symbol = str(meta.get("symbol") or "").strip()
        broker = str(meta.get("broker") or "").strip()

        if not symbol:
            try:
                values = self.tree.item(iid, "values")
                symbol = str(values[1]) if len(values) > 1 else ""
            except Exception:
                symbol = ""

        if not symbol:
            messagebox.showerror("Delete Holding", "Could not determine selected symbol.")
            return
        if not broker:
            messagebox.showerror("Delete Holding", "Could not determine broker for selected holding.")
            return

        if not messagebox.askyesno(
            "Delete Holding",
            f"Delete holding {symbol} ({broker}) and ALL its underlying trades?\n\nThis cannot be undone.",
        ):
            return

        def _bg():
            try:
                crud.delete_holding_and_trades(broker, symbol)
            except Exception as e:
                err = str(e)
                self.after(0, lambda e=err: messagebox.showerror("Delete Holding", f"Failed to delete: {e}"))
                return

            try:
                from model.engine import rebuild_holdings
                rebuild_holdings()
            except Exception:
                pass

            try:
                self.data_cache.refresh_from_db()
            except Exception:
                pass
            try:
                if self.app_state is not None and hasattr(self.app_state, "data_cache"):
                    self.app_state.data_cache.refresh_from_db()
            except Exception:
                pass

            self.after(0, self.load_data)

        threading.Thread(target=_bg, daemon=True).start()
    
    def _on_broker_selected(self):
        """Auto-select currency based on selected broker."""
        broker = self.broker_var.get()
        if broker != "All":
            try:
                df = self.data_cache._holdings_df
                if df is not None and not df.empty and "currency" in df.columns:
                    b_df = df[df["broker"] == broker]
                    if not b_df.empty:
                        currency = str(b_df["currency"].iloc[0]).strip().upper()
                        if currency in ["INR", "JPY"]:
                            self.currency_var.set(currency)
            except Exception as e:
                print(f"Error auto-selecting currency: {e}")
        self.on_filter_change()

    def _load_brokers(self):
        """Load broker list in background."""
        try:
            brokers = ["All"]
            import model.crud as crud
            brokers.extend(crud.get_all_brokers())
            
            # Update combo box
            if hasattr(self, 'broker_combo'):
                self.after(0, lambda: self.broker_combo.configure(values=brokers))
        except Exception as e:
            print(f"Error loading brokers: {e}")
    
    def _on_symbol_search(self, event=None):
        """Handle symbol search with debouncing."""
        if self._search_timer:
            self.after_cancel(self._search_timer)
        
        # Debounce: wait 200ms before searching
        self._search_timer = self.after(200, self.on_filter_change)
    
    def _edit_trade_focus_handler(self, trade_tv, reload_cb):
        iid = trade_tv.focus()
        if not iid: return
        vals = trade_tv.item(iid, 'values')
        if not vals or len(vals) < 11: return
        
        broker = str(vals[10]).strip()
        trade_id = str(vals[2]).strip()
        
        # Fetch ALL editable fields from the DB directly — never use display-formatted
        # treeview values (which may be stale, formatted with ₹/commas, or truncated)
        from model.database import db_session
        try:
            with db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT symbol, date, type, qty, price, fee, currency FROM trades WHERE broker=? AND trade_id=?", (broker, trade_id))
                row = cur.fetchone()
                if not row:
                    return
                symbol, date, ttype, qty, price, fee = row[0], row[1], row[2], str(row[3]), str(row[4]), str(row[5])
                currency = str(row[6] or 'INR').strip().upper()
        except Exception:
            return

        from views.shared_trade_edit import open_edit_trade_modal
        
        def _on_edit_complete():
            if reload_cb: reload_cb()
            # Use on_filter_change() which runs load_data in a background thread
            # with a fresh DB connection, avoiding stale WAL reads on the main thread
            self.on_filter_change()
            
        open_edit_trade_modal(self, _on_edit_complete, broker, trade_id, date, symbol, ttype, qty, price, fee, currency, getattr(self, "app_state", None))

    def _show_drilldown_context_menu(self, event, trade_tv, reload_cb) -> None:
        try:
            iid = trade_tv.identify_row(event.y)
            if not iid: return
            if iid not in trade_tv.selection():
                trade_tv.selection_set(iid)
                
            def _copy_row():
                try:
                    vals = trade_tv.item(iid, "values")
                    text = "\t".join(str(v).replace("₹", "").replace("¥", "").replace("$", "").replace(",", "").replace("%", "").strip() for v in vals)
                    self.clipboard_clear()
                    self.clipboard_append(text)
                except Exception: pass

            def _copy_all():
                try:
                    cols = [trade_tv.heading(c, "text") for c in trade_tv["columns"]]
                    lines = ["\t".join(cols)]
                    for it in trade_tv.get_children():
                        vals = trade_tv.item(it, "values")
                        lines.append("\t".join(str(v).replace("₹", "").replace("¥", "").replace("$", "").replace(",", "").replace("%", "").strip() for v in vals))
                    self.clipboard_clear()
                    self.clipboard_append("\n".join(lines))
                except Exception: pass
                    
            menu = tk.Menu(trade_tv, tearoff=False)
            menu.add_command(label="📋 Copy Selected Row", command=_copy_row)
            menu.add_command(label="📝 Copy All Rows", command=_copy_all)
            menu.add_separator()
            menu.add_command(label="✏️ Update Trade", command=lambda: self._edit_trade_focus_handler(trade_tv, reload_cb))
            menu.add_separator()
            menu.add_command(label="🗑  Delete Trade", command=lambda: self._delete_trade_from_drilldown(trade_tv, iid, reload_cb))
            menu.tk_popup(event.x_root, event.y_root)
        except Exception as e:
            print(f"Drilldown Context menu error: {e}")

    def _delete_trade_from_drilldown(self, trade_tv, iid, reload_cb):
        from tkinter import messagebox
        
        selected = list(trade_tv.selection())
        if not selected:
            if iid:
                selected = [iid]
            else:
                return
                
        count = len(selected)
        if count == 1:
            vals = trade_tv.item(selected[0], "values")
            trade_id = str(vals[2]).strip() if len(vals) > 2 else "Unknown"
            msg = f"Are you sure you want to delete trade {trade_id}?\n\nThis action cannot be undone."
            title = "Delete Trade"
        else:
            msg = f"Are you sure you want to delete {count} selected trades?\n\nThis action cannot be undone."
            title = f"Delete {count} Trades"
            
        if not messagebox.askyesno(title, msg, parent=trade_tv.winfo_toplevel()):
            return
        
        try:
            import model.crud as crud
            from model.engine import rebuild_holdings
            
            for item in selected:
                vals = trade_tv.item(item, "values")
                if not vals or len(vals) < 11:
                    continue
                trade_id = str(vals[2]).strip()
                broker = str(vals[10]).strip()
                crud.delete_trade(broker, trade_id)
                
            rebuild_holdings()
            if self.app_state and hasattr(self.app_state, "refresh_data_cache"):
                self.app_state.refresh_data_cache()
            
            if reload_cb: reload_cb()
            self.load_data()
        except Exception as e:
            messagebox.showerror("Delete Trade", f"Failed to delete trade: {e}", parent=trade_tv.winfo_toplevel())

    def on_filter_change(self):
        """Handle filter changes."""
        threading.Thread(target=self.load_data, daemon=True).start()
    
    def load_data(self):
        """Load and display holdings data."""
        try:
            # Always refresh the cache from DB so we pick up any changes from
            # rebuild_holdings() that ran in a background thread (e.g. after bulk import).
            try:
                from model.database import _invalidate_thread_connection
                _invalidate_thread_connection()
                
                cache = None
                if self.app_state is not None and hasattr(self.app_state, "data_cache"):
                    cache = self.app_state.data_cache
                else:
                    cache = self.data_cache
                cache.refresh_from_db()
                # Keep both caches in sync
                self.data_cache = cache
            except Exception:
                pass

            # Get filter values
            broker = self.broker_var.get() if hasattr(self, 'broker_var') else "All"
            symbol = self.symbol_entry.get_value() if hasattr(self, 'symbol_entry') else ""
            signal_label = self.signal_var.get() if hasattr(self, 'signal_var') else "All"
            # Map display labels → actual DB values
            _signal_map = {
                "Accumulate": "ACCUMULATE",
                "Reduce":     "REDUCE",
                "None":       "N/A",
                "All":        "All",
            }
            signal = _signal_map.get(signal_label, signal_label)
            # Parse Segmented Control
            h_state = self.holding_state_var.get() if hasattr(self, 'holding_state_var') else "Active"
            exclude_zero = (h_state == "Active")
            zero_only = (h_state == "Closed")
            
            # Query cache
            filters = HoldingsFilters(
                broker=broker or "All",
                symbol_like=symbol.upper(),
                iv_signal=signal or "All",
                exclude_zero_qty=exclude_zero,
                zero_qty_only=zero_only
            )
            
            df, summary = self.data_cache.get_holdings_filtered(filters)
            
            # Get real portfolio total (ignoring symbol/signal filters) to keep Weight% accurate
            base_filters = HoldingsFilters(broker=broker or "All", exclude_zero_qty=exclude_zero, zero_qty_only=zero_only)
            _, base_summary = self.data_cache.get_holdings_filtered(base_filters)
            total_portfolio_val = float(base_summary.get('current', 0))
            
            self.current_df = df
            
            # Update UI in main thread
            self.after(0, lambda: self._update_display(df, summary, total_portfolio_val))
        
        except Exception as e:
            print(f"Error loading data: {e}")
    
    def _update_display(self, df: pd.DataFrame, summary: dict, total_portfolio_val: float = 0.0):
        """Update table and stats display."""
        self._row_meta = {}
        # Clear table
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        if df is None or getattr(df, "empty", True):
            try:
                self._empty_frame.place(relx=0.5, rely=0.5, anchor="center")
            except Exception:
                pass
        else:
            try:
                self._empty_frame.place_forget()
            except Exception:
                pass
        
        # Update stats — these are cross-currency aggregates, so label as "Value"
        self.stats_labels["count"].config(text=f"{len(df)}")
        
        currency_val = getattr(self, "currency_var", None)
        c_val = currency_val.get() if currency_val else "All"
        sym = {"JPY": "¥", "USD": "$"}.get(c_val, "₹")
        
        # Invested and current values are the aggregates stored in the summary
        from ui_utils import format_money
        self.stats_labels["invested"].config(text=f"{sym} {float(summary.get('invested', 0)):,.0f}")
        self.stats_labels["current"].config(text=f"{sym} {float(summary.get('current', 0)):,.0f}")
        
        pnl = float(summary.get('pnl', 0))
        
        from model.engine import get_exchange_rate
        if not df.empty:
            unique_currencies = [str(c).strip().upper() for c in df["currency"].dropna().unique()] if "currency" in df.columns else []
            rates = {c: get_exchange_rate(c) for c in unique_currencies}
            
            def _get_rate(c):
                if pd.isna(c):
                    return 1.0
                if c_val != "All":
                    return 1.0
                return rates.get(str(c).strip().upper(), 1.0)
            
            rates_series = df["currency"].apply(_get_rate) if "currency" in df.columns else pd.Series(1.0, index=df.index)
        else:
            rates_series = pd.Series(dtype=float)
        
        try:
            if not df.empty and "realized_pnl" in df.columns:
                total_real = float((df["realized_pnl"] * rates_series).sum())
            else:
                total_real = 0.0
                
            total_unreal = pnl - total_real
            
            real_color = ModernStyle.SUCCESS if total_real >= 0 else ModernStyle.ERROR
            unreal_color = ModernStyle.SUCCESS if total_unreal >= 0 else ModernStyle.ERROR
            
            if "realized_pnl" in self.stats_labels:
                self.stats_labels["realized_pnl"].config(text=f"{sym} {total_real:,.0f}", fg=real_color)
            if "unrealized_pnl" in self.stats_labels:
                self.stats_labels["unrealized_pnl"].config(text=f"{sym} {total_unreal:,.0f}", fg=unreal_color)
        except Exception:
            pass
        
        try:
            if not df.empty and "total_fees" in df.columns:
                total_fees = float((df["total_fees"] * rates_series).sum())
            else:
                total_fees = 0.0
            self.stats_labels["fees"].config(text=f"{sym} {total_fees:,.0f}")
        except Exception:
            self.stats_labels["fees"].config(text=f"{sym} 0")
        
        # Precompute total current value for Weight% 
        # (Use total_portfolio_val passed from load_data to keep weight accurate during filtering)
        if total_portfolio_val > 0:
            total_val = total_portfolio_val
        else:
            if not df.empty:
                total_val = float((df["current_value"] * rates_series).sum())
            else:
                total_val = 0.0

        # Sort DataFrame alphabetically by symbol
        if not df.empty and 'symbol' in df.columns:
            df = df.sort_values(by='symbol', ascending=True)

        # Populate table (match Flet computations)
        for idx, row in enumerate(df.itertuples(index=False)):
            qty = float(getattr(row, 'qty', 0) or 0)
            avg_price = float(getattr(row, 'avg_price', 0) or 0)
            mkt_price = float(getattr(row, 'market_price', 0) or 0)
            prev_close = float(getattr(row, 'previous_close', 0) or 0)
            running_pnl = float(getattr(row, 'running_pnl', 0) or 0)
            realized_pnl = float(getattr(row, 'realized_pnl', 0) or 0)
            total_fees = float(getattr(row, 'total_fees', 0) or 0)
            pe_ratio = float(getattr(row, 'pe_ratio', 0) or 0)
            xirr = float(getattr(row, 'xirr', 0) or 0)
            cagr = float(getattr(row, 'cagr', 0) or 0)
            current_value = float(getattr(row, 'current_value', 0) or 0)
            signal = getattr(row, 'action_signal', None) or getattr(row, 'iv_signal', None) or "N/A"

            # PE Ratio formatting
            pe_disp = f"{pe_ratio:.2f}" if pe_ratio > 0 else "—"

            # Daily change % — arrow prefix for sign clarity (no row color tag)
            if prev_close > 0 and mkt_price > 0:
                daily_pct = ((mkt_price - prev_close) / prev_close) * 100.0
                arrow = "🌲" if daily_pct >= 0 else "🔻"
                daily_disp = f"{arrow} {daily_pct:+.2f}%"
            else:
                daily_disp = "—"

            from ui_utils import format_money
            currency = str(getattr(row, 'currency', 'INR')).strip().upper()
            
            # Flash PnL — arrow prefix for sign clarity
            if mkt_price > 0:
                flash_pnl = (mkt_price - avg_price) * qty
                arrow = "🌲" if flash_pnl >= 0 else "🔻"
                flash_disp = f"{arrow} {format_money(flash_pnl, currency).split('.')[0]}" # no decimals for PnL
            else:
                flash_disp = "—"

            # Real PnL — arrow prefix
            rpnl_arrow = "🌲" if running_pnl >= 0 else "🔻"
            rpnl_disp = f"{rpnl_arrow} {format_money(running_pnl, currency).split('.')[0]}"
            
            # Realized PnL
            if realized_pnl == 0:
                realized_disp = "—"
            else:
                realized_arrow = "🌲" if realized_pnl > 0 else "🔻"
                realized_disp = f"{realized_arrow} {format_money(realized_pnl, currency).split('.')[0]}"

            # Weight% with Pro-Gradient 5-Block Scale (4% per block, 20% max)
            if total_val > 0:
                rate = get_exchange_rate(currency)
                current_value_inr = current_value * rate
                weight_pct = (current_value_inr / total_val) * 100.0
                # Scale: each block is 4% (5 blocks = 20% max)
                num_blocks = 5
                filled = min(num_blocks, int(max(1, weight_pct / 4.0)) if weight_pct > 0.5 else 0)
                empty = num_blocks - filled
                
                # Pro-Gradient: different colors per block as it builds up
                bar_chars = ["🟩", "🟦", "🟨", "🟧", "🟥"]
                bar = "".join(bar_chars[:filled]) + ("⬜" * empty)
                weight_disp = f"{bar}  {weight_pct:.1f}%"
            else:
                weight_disp = "⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜ 0.0%"

            xirr_disp = "—" if float(xirr) == -100 else (f"{xirr:.2f}%" if qty > 0 else "—")
            cagr_disp = f"{cagr:.2f}%" if qty > 0 else "—"

            # stock_name can be NaN (float) from pandas; normalize before slicing.
            stock_name = getattr(row, 'stock_name', '—')
            try:
                if stock_name is None or (isinstance(stock_name, float) and pd.isna(stock_name)):
                    stock_name = '—'
            except Exception:
                pass
            try:
                stock_name = str(stock_name)
            except Exception:
                stock_name = '—'
            stock_name = (stock_name or '—').strip() or '—'

            # Signal display — rich emoji badge per signal type
            sig_norm = str(signal).strip().upper()
            if sig_norm in {"ACCUMULATE", "BUY", "ADD"}:
                signal_disp = f"🌲 ACCUMULATE"
            elif sig_norm in {"REDUCE", "SELL", "TRIM"}:
                signal_disp = f"♦️ REDUCE"
            elif sig_norm in {"HOLD", "WAIT"}:
                signal_disp = f"🔸 HOLD"
            elif sig_norm in {"N/A", "NA", ""}:
                signal_disp = "🔘 N/A"
            else:
                signal_disp = f"🔹 {signal}"

            values = (
                str(idx + 1),
                getattr(row, 'symbol', '—'),
                stock_name[:28],
                f"{qty:,.0f}",
                format_money(avg_price, currency),
                format_money(mkt_price, currency) if mkt_price > 0 else "—",
                pe_disp,
                daily_disp,
                flash_disp,
                weight_disp,
                xirr_disp,
                cagr_disp,
                realized_disp,
                rpnl_disp,
                format_money(total_fees, currency),
                signal_disp,
            )

            # Tags: signal and highlight overrides take priority over zebra stripe
            stripe_tag = "even" if (idx % 2 == 0) else "odd"
            if running_pnl < -10000:
                row_tags = ("low_unrealized_pnl",)
            elif sig_norm in {"ACCUMULATE", "BUY", "ADD"}:
                row_tags = ("sig_accumulate",)
            else:
                row_tags = (stripe_tag,)
                
            iid = self.tree.insert("", "end", values=values, tags=row_tags)
            try:
                self._row_meta[str(iid)] = {
                    "broker": getattr(row, "broker", ""),
                    "symbol": getattr(row, "symbol", ""),
                    "stock_name": getattr(row, "stock_name", ""),
                    "qty": qty,
                    "avg_price": avg_price,
                    "market_price": mkt_price,
                    "running_pnl": running_pnl,
                    "total_fees": total_fees,
                }
            except Exception:
                pass
        
        # Re-apply the remembered sort after repopulating
        if self._sort_col:
            try:
                treeview_sort_column(self.tree, self._sort_col, self._sort_reverse)
            except Exception:
                pass
    
    def refresh(self):
        self._data_loaded = False
        def _force_rebuild():
            try:
                from model.engine import rebuild_holdings, fetch_and_update_market_data
                from model.database import db_session
                try:
                    with db_session() as conn:
                        c = conn.cursor()
                        # Manual refresh: fetch all historical trades + all watchlist symbols
                        c.execute("""
                            SELECT DISTINCT symbol FROM trades
                            UNION
                            SELECT DISTINCT symbol FROM watchlist
                        """)
                        symbols = [r[0] for r in c.fetchall() if r[0]]
                    if symbols:
                        fetch_and_update_market_data(symbols)
                except Exception as e:
                    print(f"Market fetch failed: {e}")

                rebuild_holdings()
            except Exception as e:
                print(f"Force rebuild failed: {e}")
            self.load_data()
        threading.Thread(target=_force_rebuild, daemon=True).start()

    def _clear_filters(self):
        try:
            self.broker_var.set("All")
        except Exception:
            pass
        try:
            self.signal_var.set("All")
        except Exception:
            pass
        try:
            if hasattr(self, "symbol_entry"):
                self.symbol_entry.delete(0, tk.END)
        except Exception:
            pass
        try:
            if hasattr(self, "holding_state_var"):
                self.holding_state_var.set("All")
        except Exception:
            pass
        self.on_filter_change()
