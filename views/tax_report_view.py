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
        # Must initialize before super().__init__() since BaseView calls build() immediately.
        self._fy_options = ["FY 2023-2024", "FY 2024-2025", "All Time"]
        # Delay StringVar creation to after Tkinter root is available via super().__init__
        self._fy_options_list = ["FY 2023-2024", "FY 2024-2025", "All Time"]
        self._current_fy_val = "FY 2024-2025"
        self._current_fy = None  # Will be set in build()
        super().__init__(parent, app_state=app_state)

    def build(self):
        self._ui_built = False
        self._current_fy = tk.StringVar(value=self._current_fy_val)
        
        # No scroll — use self directly as the layout container
        self._content = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        self._content.pack(fill="both", expand=True)
        
        self._build_header()
        self._build_summary_bar()
        self._build_trades_table()
        
        self._ui_built = True

    def _build_header(self):
        hdr = tk.Frame(self._content, bg=ModernStyle.BG_PRIMARY)
        hdr.pack(fill="x", padx=30, pady=(30, 10))
        
        left_hdr = tk.Frame(hdr, bg=ModernStyle.BG_PRIMARY)
        left_hdr.pack(side="left")
        
        tk.Label(
            left_hdr, text="📜 Tax Report & Harvesting",
            font=ModernStyle.FONT_PAGE_TITLE,
            bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.ACCENT_PRIMARY
        ).pack(anchor="w")
        
        tk.Label(
            left_hdr, text="View Realized Capital Gains (STCG & LTCG) per Indian Tax Rules.",
            font=ModernStyle.FONT_SUBHEADING,
            bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY
        ).pack(anchor="w", pady=(4, 0))
        
        # FY Selector
        right_hdr = tk.Frame(hdr, bg=ModernStyle.BG_PRIMARY)
        right_hdr.pack(side="right", anchor="s")
        
        tk.Label(right_hdr, text="Financial Year:", bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_BODY).pack(side="left", padx=10)
        
        cb = ModernDropdown(
            right_hdr, textvariable=self._current_fy,
            values=self._fy_options_list, width=150,
            font=ModernStyle.FONT_BODY
        )
        cb.pack(side="left")
        try:
             self._current_fy.trace_add("write", lambda *args: self.load_data())
        except Exception:
             pass
        
        tk.Frame(self._content, bg="#D4AF37", height=1).pack(fill="x", padx=20, pady=(10, 0))

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
        
        if fy_str == "FY 2023-2024":
            start_date = "2023-04-01"
            end_date = "2024-03-31"
        elif fy_str == "FY 2024-2025":
            start_date = "2024-04-01"
            end_date = "2025-03-31"
            
        threading.Thread(target=self._calc_taxes, args=(start_date, end_date), daemon=True).start()

    def _calc_taxes(self, start_date, end_date):
        # We need a FIFO queue of ALL buys to match against ALL sells.
        # This gives us exact holding periods for each sell instance.
        
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT symbol, type, date, qty, price, fee FROM trades ORDER BY date ASC")
            trades = cur.fetchall()
            
        inventory_by_symbol = {}
        realized_events = []
        
        stcg_total = 0.0
        ltcg_total = 0.0
        
        for sym, ttype, date_str, qty, px, fee in trades:
            ttype = str(ttype).upper()
            qty = float(qty)
            px = float(px)
            fee = float(fee)
            
            if sym not in inventory_by_symbol:
                inventory_by_symbol[sym] = []
                
            q = inventory_by_symbol[sym]
            
            if ttype == 'BUY':
                q.append({'date': date_str, 'qty': qty, 'price': px, 'fee': fee})
            elif ttype == 'SELL':
                rem_qty = qty
                sell_pnl = 0.0
                capital_gain_type = ""
                days_held = 0
                buy_dates_str = []
                
                while rem_qty > 0 and q:
                    buy = q[0]
                    consume = min(rem_qty, buy['qty'])
                    
                    # Calculate dates
                    d_buy = datetime.strptime(buy['date'], '%Y-%m-%d')
                    d_sell = datetime.strptime(date_str, '%Y-%m-%d')
                    delta = (d_sell - d_buy).days
                    is_ltcg = delta > 365
                    
                    # Cost block
                    cost_basis = consume * buy['price']
                    sale_proceeds = consume * px
                    
                    # For simplicity, assign proportion of buy/sell fees to this chunk
                    chunk_pf = (consume / buy['qty']) * buy['fee']
                    chunk_sf = (consume / qty) * fee
                    
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
                            'px': px,
                            'days': delta,
                            'type': "LTCG" if is_ltcg else "STCG",
                            'pnl': net_pnl
                        })
                    
                    buy['qty'] -= consume
                    rem_qty -= consume
                    
                    if buy['qty'] <= 1e-6:
                        q.pop(0)

        # Update UI safely
        self.after(0, lambda: self._apply_data(realized_events, stcg_total, ltcg_total))

    def _apply_data(self, events, stcg, ltcg):
        for it in self.tv.get_children():
            self.tv.delete(it)
            
        # Update summary cards
        stcg_color = ModernStyle.SUCCESS if stcg >= 0 else ModernStyle.ERROR
        ltcg_color = ModernStyle.SUCCESS if ltcg >= 0 else ModernStyle.ERROR
        total = stcg + ltcg
        total_color = ModernStyle.SUCCESS if total >= 0 else ModernStyle.ERROR
        
        stcg_arrow = "▲" if stcg >= 0 else "▼"
        ltcg_arrow = "▲" if ltcg >= 0 else "▼"
        total_arrow = "▲" if total >= 0 else "▼"
        
        self._stcg_lbl.config(text=f"{stcg_arrow} ₹{abs(stcg):,.2f}", fg=stcg_color)
        self._ltcg_lbl.config(text=f"{ltcg_arrow} ₹{abs(ltcg):,.2f}", fg=ltcg_color)
        self._total_lbl.config(text=f"{total_arrow} ₹{abs(total):,.2f}", fg=total_color)
        
        # Insert table data
        events.sort(key=lambda x: x['date'], reverse=True)
        
        for idx, row in enumerate(events):
            stripe = 'odd' if idx % 2 else 'even'
            tag = 'ltcg' if row['type'] == 'LTCG' else 'stcg'
            
            pnl_arrow = "▲" if row['pnl'] >= 0 else "▼"
            vals = (
                idx + 1,
                row['sym'],
                row['buy_date'],
                row['date'],
                f"{row['qty']:g}",
                f"₹{row['buy_px']:,.2f}",
                f"₹{row['px']:,.2f}",
                f"{row['days']} days",
                row['type'],
                f"{pnl_arrow} ₹{abs(row['pnl']):,.2f}"
            )
            
            self.tv.insert("", "end", values=vals, tags=(stripe, tag))
