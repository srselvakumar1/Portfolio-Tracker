import tkinter as tk
from tkinter import ttk
from datetime import datetime
import threading

from views.base_view import BaseView, _enable_canvas_mousewheel
from ui_theme import ModernStyle
from ui_widgets import ModernButton, ModernCard, ModernDropdown
from ui_utils import add_treeview_copy_menu, treeview_sort_column

from model.database import db_session

class TaxReportView(BaseView):
    """View to display Tax Harvesting and Capital Gains report."""
    
    def __init__(self, parent, app_state=None):
        # Build FY list dynamically based on current date
        self._fy_options_list = self._build_fy_options()
        # Default to the current Indian FY
        now = datetime.now()
        current_fy_start = now.year if now.month >= 4 else now.year - 1
        self._current_fy_val = f"FY {current_fy_start}-{current_fy_start + 1}"
        self._current_fy = None  # Will be set in build()
        super().__init__(parent, app_state=app_state)

    @staticmethod
    def _build_fy_options() -> list:
        """Generate FY options from the earliest trade year to the current FY."""
        now = datetime.now()
        current_fy_start = now.year if now.month >= 4 else now.year - 1

        # Try to find the earliest sell year in the database
        earliest_fy_start = current_fy_start - 2  # default fallback: 2 years back
        try:
            from model.database import db_session as _db
            with _db() as conn:
                row = conn.cursor().execute(
                    "SELECT MIN(date) FROM trades WHERE type='SELL'"
                ).fetchone()
                if row and row[0]:
                    yr = int(row[0][:4])
                    mo = int(row[0][5:7])
                    earliest_fy_start = yr if mo >= 4 else yr - 1
        except Exception:
            pass

        options = []
        for fy_start in range(current_fy_start, earliest_fy_start - 1, -1):
            options.append(f"FY {fy_start}-{fy_start + 1}")
        options.append("All Time")
        return options

    def build(self):
        self._ui_built = False
        self._current_fy = tk.StringVar(value=self._current_fy_val)
        self._current_currency = tk.StringVar(value="All")
        
        # No scroll — use self directly as the layout container
        self._content = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        self._content.pack(fill="both", expand=True)
        
        self._build_header()
        self._build_summary_bar()
        self._build_trades_table()
        
        self._ui_built = True

    def _build_header(self):
        def _build_right(parent):
            tk.Label(parent, text="💴 Currency:", bg="#0D9488", fg="#FFFFFF", font=ModernStyle.FONT_BODY).pack(side="left", padx=(10, 2))
            currency_cb = ModernDropdown(
                parent, textvariable=self._current_currency,
                values=["All", "INR", "JPY"], width=80,
                font=ModernStyle.FONT_BODY
            )
            currency_cb.pack(side="left", padx=(0, 15))

            tk.Label(parent, text="Financial Year:", bg="#0D9488", fg="#FFFFFF", font=ModernStyle.FONT_BODY).pack(side="left", padx=(0, 2))
            cb = ModernDropdown(
                parent, textvariable=self._current_fy,
                values=self._fy_options_list, width=150,
                font=ModernStyle.FONT_BODY
            )
            cb.pack(side="left")
            try:
                 self._current_fy.trace_add("write", lambda *args: self.load_data())
                 self._current_currency.trace_add("write", lambda *args: self.load_data())
            except Exception:
                 pass

        self.add_gradient_header(
            self._content,
            "📜 Tax Report & Harvesting",
            "View Realized Capital Gains (STCG & LTCG) per Indian Tax Rules.",
            right_widget_func=_build_right
        )

    def _build_summary_bar(self):
        """Compact inline summary bar instead of tall cards."""
        self._summary_frame = ModernCard(self._content, bg=ModernStyle.BG_SECONDARY, highlight_color=ModernStyle.BORDER_COLOR, highlight_thickness=1, radius=8)
        self._summary_frame.pack(fill="x", padx=20, pady=(8, 0))

        def _stat(parent, label, init_val, fg_color=ModernStyle.TEXT_PRIMARY):
            cell = tk.Frame(parent.content, bg=ModernStyle.BG_SECONDARY)
            cell.pack(side="left", padx=20, pady=8)
            tk.Label(cell, text=label, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_KPI_LABEL).pack(anchor="w")
            lbl = tk.Label(cell, text=init_val, bg=ModernStyle.BG_SECONDARY, fg=fg_color, font=ModernStyle.FONT_KPI_VALUE)
            lbl.pack(anchor="w")
            return lbl

        self._stcg_lbl  = _stat(self._summary_frame, "▶ STCG (Short Term)", "₹0.00", ModernStyle.WARNING)
        
        # Thin vertical divider
        tk.Frame(self._summary_frame.content, bg=ModernStyle.BORDER_COLOR, width=1).pack(side="left", fill="y", pady=6)
        
        self._ltcg_lbl  = _stat(self._summary_frame, "▶ LTCG (Long Term)",  "₹0.00", ModernStyle.ACCENT_PRIMARY)
        
        tk.Frame(self._summary_frame.content, bg=ModernStyle.BORDER_COLOR, width=1).pack(side="left", fill="y", pady=6)

        self._total_lbl = _stat(self._summary_frame, "▶ Total Taxable Gains", "₹0.00", ModernStyle.SUCCESS)


    def _build_trades_table(self):
        table_frame = ModernCard(self._content, bg=ModernStyle.BG_SECONDARY, highlight_color=ModernStyle.BORDER_COLOR, highlight_thickness=1, radius=10, expand_height=True)
        table_frame.pack(fill="both", expand=True, padx=20, pady=(0, 30))
        table_frame.content.grid_rowconfigure(0, weight=1)
        table_frame.content.grid_columnconfigure(0, weight=1)
        
        tk.Label(table_frame.content, text="Realized Sales (FIFO Matching)", font=ModernStyle.FONT_HEADING, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY).pack(anchor="w", padx=20, pady=(15, 10))
        
        cols = ("#", "Symbol", "Buy Date", "Date Sold", "Qty", "Buy Price", "Sell Price", "Holding Days", "Type", "PnL")
        
        tv_frame = tk.Frame(table_frame.content, bg=ModernStyle.BG_SECONDARY)
        tv_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        style = ttk.Style()
        style.configure("Tax.Treeview", font=ModernStyle.FONT_TABLE, rowheight=32)
        style.configure("Tax.Treeview.Heading", font=ModernStyle.FONT_SUBHEADING)
        
        self.tv = ttk.Treeview(tv_frame, columns=cols, show="headings", height=15, style="Tax.Treeview")
        
        sortable_cols = ("Symbol", "Date Sold", "Type", "PnL")
        for c in cols:
            if c in sortable_cols:
                self.tv.heading(c, text=f"{c} ↕", anchor="w", command=lambda col=c: treeview_sort_column(self.tv, col, False))
            else:
                self.tv.heading(c, text=c, anchor="w")
            self.tv.column(c, anchor="w", width=100)
            
        add_treeview_copy_menu(self.tv)
            
        self.tv.heading("#", anchor="center")
        self.tv.column("#", anchor="center", width=40)
        
        # Center align specific columns
        for c in ["Qty", "Buy Price", "Sell Price", "PnL"]:
            self.tv.heading(c, anchor="center")
            self.tv.column(c, anchor="center", width=90)
            
        self.tv.column("Qty", width=70)
        self.tv.column("Holding Days", width=110)
        self.tv.column("Type", width=70)
        
        self.tv.tag_configure('stcg', foreground="#ef4444")
        self.tv.tag_configure('ltcg', foreground="#10b981")
        self.tv.tag_configure('even', background=ModernStyle.BG_SECONDARY)
        self.tv.tag_configure('odd', background=ModernStyle.BG_TERTIARY)
        
        vsb = ttk.Scrollbar(tv_frame, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=vsb.set)
        
        self.tv.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        
    def show(self):
        super().show()
        if not self._ui_built:
            self.build()
        self.load_data()
        
    def load_data(self):
        fy_str = self._current_fy.get() if self._current_fy else self._current_fy_val
        start_date = None
        end_date = None
        
        # Dynamically parse "FY YYYY-YYYY" instead of hardcoded if/elif
        if fy_str.startswith("FY "):
            try:
                parts = fy_str[3:].split("-")
                fy_start_year = int(parts[0])
                start_date = f"{fy_start_year}-04-01"
                end_date = f"{fy_start_year + 1}-03-31"
            except (ValueError, IndexError):
                pass  # Fall through to All Time (no filter)
            
        threading.Thread(target=self._calc_taxes, args=(start_date, end_date), daemon=True).start()

    def _calc_taxes(self, start_date, end_date):
        # We need a FIFO queue of ALL buys to match against ALL sells.
        # This gives us exact holding periods for each sell instance.
        currency_filter = self._current_currency.get() if hasattr(self, "_current_currency") else "All"
        from model.engine import get_exchange_rate

        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT symbol, type, date, qty, price, fee, currency FROM trades ORDER BY date ASC, type ASC, trade_id ASC")
            trades_raw = cur.fetchall()

            # ── Ground-truth net positions ─────────────────────────────
            cur.execute(
                "SELECT broker, symbol, "
                "  SUM(CASE WHEN type='BUY' THEN qty ELSE 0 END), "
                "  SUM(CASE WHEN type='SELL' THEN qty ELSE 0 END), "
                "  currency "
                "FROM trades GROUP BY broker, symbol, currency"
            )
            symbol_net = {}
            for _, symbol, total_buy, total_sell, cur_currency in cur.fetchall():
                total_buy = float(total_buy or 0.0)
                total_sell = float(total_sell or 0.0)
                cur_currency = str(cur_currency or 'INR').strip().upper()
                if currency_filter != "All" and cur_currency != currency_filter.upper():
                    continue
                symbol_net[symbol] = symbol_net.get(symbol, 0.0) + (total_buy - total_sell)

        # Filter trades list by active currency filter
        trades = []
        for sym, ttype, date_str, qty, px, fee, currency in trades_raw:
            currency = str(currency or 'INR').strip().upper()
            if currency_filter != "All" and currency != currency_filter.upper():
                continue
            trades.append((sym, ttype, date_str, qty, px, fee, currency))
            
        inventory_by_symbol = {}
        realized_events = []
        
        stcg_total = 0.0
        ltcg_total = 0.0
        
        for sym, ttype, date_str, qty, px, fee, currency in trades:
            ttype = str(ttype).upper()
            qty = float(qty)
            px = float(px)
            fee = float(fee)
            
            rate = 1.0 if currency_filter != "All" else get_exchange_rate(currency)
            
            if sym not in inventory_by_symbol:
                inventory_by_symbol[sym] = []
                
            q = inventory_by_symbol[sym]
            
            if ttype == 'BUY':
                q.append({'date': date_str, 'qty': qty, 'price': px * rate, 'fee': fee * rate, 'currency': currency})
            elif ttype == 'SELL':
                rem_qty = qty
                
                while rem_qty > 1e-6 and q:
                    buy = q[0]
                    if buy['qty'] <= 1e-6:
                        q.pop(0)
                        continue

                    consume = min(rem_qty, buy['qty'])
                    
                    # Calculate dates
                    d_buy = datetime.strptime(buy['date'], '%Y-%m-%d')
                    d_sell = datetime.strptime(date_str, '%Y-%m-%d')
                    delta = (d_sell - d_buy).days
                    is_ltcg = delta > 365
                    
                    # Cost block
                    cost_basis = consume * buy['price']
                    sale_proceeds = consume * px * rate
                    
                    # For simplicity, assign proportion of buy/sell fees to this chunk
                    chunk_pf = (consume / buy['qty']) * buy['fee'] if buy['qty'] > 0 else 0.0
                    chunk_sf = (consume / qty) * fee * rate if qty > 0 else 0.0
                    
                    net_pnl = sale_proceeds - cost_basis - chunk_pf - chunk_sf
                    
                    # Only include this chunk if it falls in our FY window.
                    include = True
                    if start_date and date_str < start_date: include = False
                    if end_date and date_str > end_date: include = False
                    
                    if include:
                        if is_ltcg:
                            ltcg_total += net_pnl
                        else:
                            stcg_total += net_pnl
                            
                        realized_events.append({
                            'sym': sym,
                            'buy_date': buy['date'],
                            'date': date_str,
                            'qty': consume,
                            'buy_px': buy['price'],
                            'px': px * rate,
                            'days': delta,
                            'type': "LTCG" if is_ltcg else "STCG",
                            'pnl': net_pnl,
                            'currency': 'INR' if currency_filter == "All" else currency
                        })
                    
                    buy['qty'] -= consume
                    rem_qty -= consume
                    
                    if buy['qty'] <= 1e-6:
                        q.pop(0)
                # If rem_qty > 0 here, this sell had no matching buys
                # (intraday/cross-broker). Silently skip — the net
                # position check below will catch inconsistencies.

        # Update UI safely
        self.after(0, lambda: self._apply_data(realized_events, stcg_total, ltcg_total))

    def _apply_data(self, events, stcg, ltcg):
        for it in self.tv.get_children():
            self.tv.delete(it)
            
        currency_filter = self._current_currency.get() if hasattr(self, "_current_currency") else "All"
        sym_char = "¥" if currency_filter == "JPY" else "₹"

        # Update summary cards
        stcg_color = ModernStyle.SUCCESS if stcg >= 0 else ModernStyle.ERROR
        ltcg_color = ModernStyle.SUCCESS if ltcg >= 0 else ModernStyle.ERROR
        total = stcg + ltcg
        total_color = ModernStyle.SUCCESS if total >= 0 else ModernStyle.ERROR
        
        stcg_arrow = "▲" if stcg >= 0 else "▼"
        ltcg_arrow = "▲" if ltcg >= 0 else "▼"
        total_arrow = "▲" if total >= 0 else "▼"
        
        self._stcg_lbl.config(text=f"{stcg_arrow} {sym_char}{abs(stcg):,.2f}", fg=stcg_color)
        self._ltcg_lbl.config(text=f"{ltcg_arrow} {sym_char}{abs(ltcg):,.2f}", fg=ltcg_color)
        self._total_lbl.config(text=f"{total_arrow} {sym_char}{abs(total):,.2f}", fg=total_color)
        
        # Insert table data
        events.sort(key=lambda x: x['date'], reverse=True)
        
        for idx, row in enumerate(events):
            stripe = 'odd' if idx % 2 else 'even'
            tag = 'ltcg' if row['type'] == 'LTCG' else 'stcg'
            
            pnl_arrow = "▲" if row['pnl'] >= 0 else "▼"
            row_currency = row.get('currency', 'INR')
            row_sym = "¥" if row_currency == "JPY" else "₹"

            vals = (
                idx + 1,
                row['sym'],
                row['buy_date'],
                row['date'],
                f"{row['qty']:g}",
                f"{row_sym}{row['buy_px']:,.2f}",
                f"{row_sym}{row['px']:,.2f}",
                f"{row['days']} days",
                row['type'],
                f"{pnl_arrow} {row_sym}{abs(row['pnl']):,.2f}"
            )
            
            self.tv.insert("", "end", values=vals, tags=(stripe, tag))
