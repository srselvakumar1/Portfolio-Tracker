"""
Help view for TKinter-based PTracker application.
"""

import tkinter as tk
from tkinter import ttk

from views.base_view import BaseView, _enable_canvas_mousewheel
from ui_theme import ModernStyle
from ui_widgets import ModernButton

class HelpView(BaseView):
    """Help and documentation view."""
    
    def build(self):
        """Build help documentation view (rich, sectioned like the Flet help page)."""

        self._help_font_scale = 2
        self._section_map = {}  # Tracks section_id -> widget for navigation

        header_frame = tk.Frame(self, bg=ModernStyle.BG_PRIMARY, height=60)
        header_frame.pack(fill="x", padx=15, pady=(15, 10))

        left = tk.Frame(header_frame, bg=ModernStyle.BG_PRIMARY)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text="❓ Help & Documentation", fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_PRIMARY, font=ModernStyle.FONT_TITLE).pack(anchor="w")
        tk.Label(left, text="Comprehensive documentation and formulas used in PTracker.", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_PRIMARY, font=ModernStyle.FONT_BODY).pack(anchor="w")

        right = tk.Frame(header_frame, bg=ModernStyle.BG_PRIMARY)
        right.pack(side="right")
        tk.Label(right, text="Text Size", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_PRIMARY, font=ModernStyle.FONT_SMALL).pack(side="left", padx=(0, 8))
        ModernButton(right, text="-", command=lambda: self._help_adjust_font(-1), bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY, canvas_bg=ModernStyle.BG_PRIMARY, width=42, height=34).pack(side="left", padx=(0, 6))
        ModernButton(right, text="+", command=lambda: self._help_adjust_font(1), bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY, canvas_bg=ModernStyle.BG_PRIMARY, width=42, height=34).pack(side="left")

        # Stationary navigation bar for quick links
        self._nav_bar = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        self._nav_bar.pack(fill="x", padx=15, pady=(0, 10))

        # Accent divider
        tk.Frame(self, bg="#D4AF37", height=1).pack(fill="x", padx=15, pady=(0, 10))

        # Scrollable container
        self.canvas = tk.Canvas(self, bg=ModernStyle.BG_PRIMARY, highlightthickness=0)
        vscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True, padx=15, pady=0)

        self._help_content = tk.Frame(self.canvas, bg=ModernStyle.BG_PRIMARY)
        cid = self.canvas.create_window((0, 0), window=self._help_content, anchor="nw")

        def _on_cfg(_e=None):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            self.canvas.itemconfigure(cid, width=self.canvas.winfo_width())

        self._help_content.bind("<Configure>", _on_cfg)
        self.canvas.bind("<Configure>", _on_cfg)

        # Mouse wheel scrolling over the help content
        _enable_canvas_mousewheel(self.canvas, include_widget=self._help_content)

        # Build content
        self._help_text_widgets: list[tk.Widget] = []
        self._help_title_widgets: list[tk.Widget] = []

        self._build_help_sections(self._help_content)
        self._build_quick_navigation()
        self._help_apply_font_scale()

    def _help_adjust_font(self, delta: int) -> None:
        self._help_font_scale = max(-3, min(6, int(self._help_font_scale) + int(delta)))
        self._help_apply_font_scale()

    def _help_apply_font_scale(self) -> None:
        # Scale base fonts by +/- a few points.
        try:
            base = int(ModernStyle.FONT_BODY[1])
            small = int(ModernStyle.FONT_SMALL[1])
            heading = int(ModernStyle.FONT_SUBHEADING[1])
        except Exception:
            base, small, heading = 11, 10, 12
        s = int(self._help_font_scale)
        f_body = (ModernStyle.FONT_FAMILY, max(9, base + s))
        f_small = (ModernStyle.FONT_FAMILY, max(8, small + s))
        f_head = (ModernStyle.FONT_FAMILY, max(10, heading + s), "bold")

        for w in getattr(self, "_help_text_widgets", []):
            try:
                w.configure(font=f_body)
            except Exception:
                pass
        for w in getattr(self, "_help_title_widgets", []):
            try:
                w.configure(font=f_head)
            except Exception:
                pass

    def _help_card(self, parent: tk.Misc, title: str, section_id: str | None = None) -> tk.Frame:
        card = tk.Frame(parent, bg=ModernStyle.BG_SECONDARY, highlightbackground=ModernStyle.BORDER_COLOR, highlightthickness=1)
        card.pack(fill="x", pady=(0, 12))
        
        if section_id:
            self._section_map[section_id] = card

        title_lbl = tk.Label(card, text=title, fg=ModernStyle.ACCENT_PRIMARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_HEADING)
        title_lbl.pack(anchor="w", padx=12, pady=(10, 6))
        self._help_title_widgets.append(title_lbl)
        inner = tk.Frame(card, bg=ModernStyle.BG_SECONDARY)
        inner.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        return inner

    def _help_paragraph(self, parent: tk.Misc, text: str) -> tk.Label:
        lbl = tk.Label(
            parent,
            text=text,
            fg=ModernStyle.TEXT_SECONDARY,
            bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_BODY,
            justify="left",
            wraplength=1100,
        )
        lbl.pack(anchor="w", pady=(0, 8))
        self._help_text_widgets.append(lbl)
        return lbl

    def _help_item(self, parent: tk.Misc, title: str, desc: str) -> None:
        t = tk.Label(parent, text=title, fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SUBHEADING)
        t.pack(anchor="w", pady=(8, 2))
        self._help_title_widgets.append(t)
        self._help_paragraph(parent, desc)

    def _help_table(self, parent: tk.Misc, cols: list[str], rows: list[list[str]]) -> None:
        wrap = tk.Frame(parent, bg=ModernStyle.BG_SECONDARY, highlightbackground=ModernStyle.BORDER_COLOR, highlightthickness=1)
        wrap.pack(fill="x", pady=(6, 0))

        grid = tk.Frame(wrap, bg=ModernStyle.BG_SECONDARY)
        grid.pack(fill="x", padx=10, pady=10)

        # Header
        for c, name in enumerate(cols):
            grid.grid_columnconfigure(c, weight=1, uniform="ht")
            h = tk.Label(grid, text=name, fg=ModernStyle.TEXT_ON_ACCENT, bg=ModernStyle.ACCENT_PRIMARY, font=ModernStyle.FONT_SMALL)
            h.grid(row=0, column=c, sticky="ew", padx=(0, 6 if c < len(cols) - 1 else 0))
            self._help_text_widgets.append(h)

        # Rows
        for r_i, r in enumerate(rows):
            bg = ModernStyle.BG_PRIMARY if (r_i % 2 == 0) else ModernStyle.BG_SECONDARY
            for c_i, val in enumerate(r):
                cell = tk.Label(grid, text=str(val), fg=ModernStyle.TEXT_SECONDARY, bg=bg, font=ModernStyle.FONT_SMALL, justify="left", wraplength=240)
                cell.grid(row=r_i + 1, column=c_i, sticky="ew", padx=(0, 6 if c_i < len(cols) - 1 else 0), pady=(4, 0))
                self._help_text_widgets.append(cell)

    def _scroll_to_section(self, section_id: str) -> None:
        """Scroll the canvas to the specified section widget."""
        widget = self._section_map.get(section_id)
        if not widget:
            return

        self.canvas.update_idletasks() # Ensure geometry is updated
        
        # Calculate Y relative to the content frame
        y = widget.winfo_y()
        total_h = self._help_content.winfo_height()
        
        if total_h > 0:
            # We want the widget at the top, but let's give a tiny bit of padding (e.g. 5px)
            fraction = max(0, (y - 5) / total_h)
            self.canvas.yview_moveto(fraction)

    def _build_quick_navigation(self) -> None:
        """Build the horizontal chip row for quick links."""
        links = [
            ("⌨️ Shortcuts", "shortcuts"),
            ("📥 Bulk Import", "import"),
            ("🧮 Formulas", "formulas"),
            ("💸 Trade Fees", "fees"),
            ("📄 Tax Report", "tax"),
            ("📊 Watchlist", "watchlist"),
        ]
        
        for text, sid in links:
            btn = ModernButton(
                self._nav_bar,
                text=text,
                command=lambda s=sid: self._scroll_to_section(s),
                bg=ModernStyle.BG_TERTIARY,
                fg=ModernStyle.TEXT_PRIMARY,
                canvas_bg=ModernStyle.BG_PRIMARY,
                height=32,
                radius=16, # Pill shape
                font=ModernStyle.FONT_SMALL,
            )
            btn.pack(side="left", padx=(0, 8))
            self._help_text_widgets.append(btn)

    def _build_help_sections(self, parent: tk.Misc) -> None:
        # Example data (mirrors the Flet help page)
        pnl_run_cols = ["Date", "Type", "Qty", "Price", "Current", "Running PnL"]
        pnl_run_rows = [
            ["2023-01-01", "BUY", "10", "₹100", "₹120", "+₹200"],
            ["2023-01-05", "BUY", "5", "₹110", "₹120", "+₹150"],
            ["Total", "-", "15", "₹103.33", "₹120", "+₹250"],
        ]

        pnl_real_cols = ["Date", "Action", "Qty", "Price", "Avg Cost", "Realized"]
        pnl_real_rows = [
            ["2023-01-01", "BUY", "10", "₹100", "-", "-"],
            ["2023-02-01", "SELL", "5", "₹150", "₹100", "+₹250"],
            ["Balance", "-", "5", "-", "₹100", "-"],
        ]

        cagr_cols = ["Year", "Investment", "Value", "Return", "CAGR"]
        cagr_rows = [
            ["Start", "₹10,000", "₹10,000", "-", "-"],
            ["Year 1", "₹10,000", "₹11,500", "15%", "15.0%"],
            ["Year 3", "₹10,000", "₹15,000", "50%", "14.47%"],
        ]

        iv_cols = ["Year", "Proj. EPS", "Disc. Factor", "Pres. Value"]
        iv_rows = [
            ["Base", "₹10.00", "1.000", "₹10.00"],
            ["Year 1", "₹11.20", "0.909", "₹10.18"],
            ["Year 5", "₹17.62", "0.621", "₹10.94"],
            ["TV", "₹264.30", "0.621", "₹164.13"],
            ["Total IV", "-", "-", "₹214.25"],
        ]

        fees_cols = ["Charge", "Rate / Logic", "BUY ₹1L sample", "SELL ₹1L sample"]
        fees_rows = [
            ["Brokerage",         "Flat ₹1 per order",               "₹1.00",    "₹1.00"],
            ["STT",               "0.1% of turnover (both sides)",   "₹100.00",  "₹100.00"],
            ["Transaction Chg",   "₹2.97/lakh = 0.00297% (NSE CM)", "₹2.97",    "₹2.97"],
            ["SEBI Charges",      "₹10 per crore (0.0001%)",         "₹0.10",    "₹0.10"],
            ["Stamp Duty",        "0.015% of turnover (BUY only)",   "₹15.00",   "-"],
            ["DP Charges",        "₹13 + 18% GST = ₹15.34 (SELL)",  "-",        "₹15.34"],
            ["GST",               "18% on (Brkg + Txn + SEBI)",      "₹0.73",    "₹0.73"],
            ["Total Fees",        "-",                               "₹119.80",  "₹120.14"],
        ]

        calc_levels_cols = ["Calculation", "Level", "Reason"]
        calc_levels_rows = [
            ["Running Quantity", "Transaction", "Evolves with each trade"],
            ["Cost Basis", "Transaction", "Accumulates through each trade"],
            ["Realized PnL", "Transaction", "Only occurs per SELL"],
            ["Fee Accumulation", "Transaction", "Sums stored fees per trade"],
            ["Cash Flows", "Transaction", "Collected per trade for XIRR"],
            ["Average Price", "Holding", "Computed from final totals"],
            ["Unrealized PnL", "Holding", "Uses current market price + final state"],
            ["Running PnL", "Holding", "Combines all realized + unrealized"],
            ["XIRR/CAGR", "Holding", "Uses complete cash flow history"],
            ["Total Fees", "Holding", "Sum of all trade fees"],
        ]

        shortcuts_cols = ["Shortcut", "Platform", "Action"]
        shortcuts_rows = [
            ["Ctrl+N", "Windows/Linux | Cmd+N on Mac", "Add new trade (Trade Entry)"],
            ["Esc", "All Platforms", "Close open dialogs"],
            ["Ctrl+K", "Windows/Linux | Cmd+K on Mac", "Focus symbol search (Holdings/Trade History)"],
        ]

        import_cols = ["CSV Header", "Required?", "Accepted Aliases", "Notes"]
        import_rows = [
            ["date",      "Yes", "trade_date",  "Supports YYYY-MM-DD and DD-MM-YYYY"],
            ["symbol",    "Yes", "-",           "Ticker symbol (e.g. RELIANCE.NS)"],
            ["type",      "Yes", "trade_type",  "Must be BUY or SELL (case-insensitive)"],
            ["qty",       "Yes", "quantity",    "Number of shares (must be > 0)"],
            ["price",     "Yes", "-",           "Smart cleaning: ₹, $ and commas are ignored"],
            ["trade_id",  "No",  "-",           "Prevents duplicates if same file is re-imported"],
            ["broker",    "No",  "-",           "If missing, uses default selected in UI"],
        ]

        # Sections
        s = self._help_card(parent, "Keyboard Shortcuts & Quick Navigation", "shortcuts")
        self._help_item(s, "Available Shortcuts", "Use these keyboard shortcuts to navigate faster and perform common actions without clicking.")
        self._help_table(s, shortcuts_cols, shortcuts_rows)

        s = self._help_card(parent, "Project Overview")
        self._help_item(
            s,
            "About PTracker",
            "PTracker is a portfolio management tool for tracking holdings and trades, computing performance metrics, and surfacing actionable insights.",
        )

        s = self._help_card(parent, "Application Views")
        self._help_item(s, "Dashboard", "High-level financial summary with key metrics, performers, actionable insights, and tax harvesting opportunities.")
        self._help_item(s, "Holdings", "Current portfolio holdings. Double-click a row to open drilldown and view the trade history for that holding.")
        self._help_item(s, "Trade Entry", "Add new trades manually or import a CSV. Case-insensitive symbols and types are handled automatically.")
        self._help_item(s, "Trade History", "Search and filter every transaction. Supports copy/export, edit on double-click, and bulk deletion.")

        s = self._help_card(parent, "📥 Bulk Import (CSV Format)", "import")
        self._help_item(
            s, "Smart CSV Importing",
            "PTracker supports flexible CSV imports from most brokers. Use the following column structure to ensure a successful upload."
        )
        self._help_table(s, import_cols, import_rows)
        self._help_item(
            s, "Key Features",
            "• Smart Normalization: Headers like 'Trade Date' or 'Quantity' are automatically mapped.\n"
            "• Currency Cleaning: Prices like '₹72.81' or '$150.00' have symbols and commas stripped automatically.\n"
            "• Date Freedom: Both '2024-03-25' and '25-03-2024' formats are recognized.\n"
            "• Duplicate Prevention: If you include a 'trade_id', the app will skip any rows that were already imported."
        )

        s = self._help_card(parent, "Metric Formulas & Tabular Examples", "formulas")
        self._help_item(s, "Avg Purchase Price", "Calculated as: Total Cost Basis / Current Quantity. Fees are included in the cost basis for BUY trades and deducted for SELL trades.")
        self._help_item(s, "Running (Unrealized) PnL", "(Current Price - Avg Purchase Price) × Current Quantity.")
        self._help_table(s, pnl_run_cols, pnl_run_rows)
        self._help_item(s, "Running PnL", "Combines realized gains (SELL) and unrealized gains/losses from open quantity.")
        self._help_table(s, pnl_real_cols, pnl_real_rows)
        self._help_item(s, "Overall CAGR", "(Ending Value / Beginning Value)^(1/Years) - 1")
        self._help_table(s, cagr_cols, cagr_rows)
        self._help_item(s, "Overall XIRR", "Annualized return using dated cashflows (IRR/XIRR).")

        s = self._help_card(parent, "Calculation Levels: Transaction vs Holding")
        self._help_item(s, "Understanding Where Calculations Happen", "Some values evolve per trade, while others are computed after aggregating a holding.")
        self._help_table(s, calc_levels_cols, calc_levels_rows)

        s = self._help_card(parent, "Intrinsic Value & Action Signals")
        self._help_item(s, "Intrinsic Value (DCF)", "Discounted Cash Flow style intrinsic value based on projected EPS and discount factors.")
        self._help_table(s, iv_cols, iv_rows)
        self._help_item(s, "ACCUMULATE", "Current Market Price < 70% of Intrinsic Value.")
        self._help_item(s, "REDUCE", "Current Market Price > 110% of Intrinsic Value.")
        self._help_item(s, "HOLD", "Price is between 70% and 110% of Intrinsic Value.")

        s = self._help_card(parent, "Trade Fees (Indian Equity — NSE Delivery)", "fees")
        self._help_item(
            s, "Charge Breakdown (verified April 2026)",
            "Fee table for equity delivery trades on NSE. "
            "All charges apply per order. Sample columns assume a ₹1,00,000 turnover trade."
        )
        self._help_table(s, fees_cols, fees_rows)
        self._help_item(
            s, "Key Notes",
            "• Brokerage: flat ₹1 per order (generic default; Zerodha = ₹0 for delivery).\n"
            "• STT: 0.1% on both BUY and SELL sides.\n"
            "• Exchange Txn Charges: ₹2.97/lakh (NSE Cash Market, revised Oct 2024).\n"
            "• Stamp Duty: 0.015% on BUY side only (uniform nationwide).\n"
            "• DP Charges: ₹13.00 + 18% GST = ₹15.34 on SELL delivery trades only.\n"
            "• GST: 18% on (Brokerage + Transaction Charges + SEBI Charges).\n"
            "• SEBI Turnover Fee: ₹10 per crore of turnover.\n"
            "• IPFT: ₹0.01 per crore — negligible, not included."
        )
        self._help_item(
            s, "BUY Formula",
            "Total = Brkg(₹1) + STT(0.1%) + TxnChg(0.00297%) + SEBI(0.0001%) + Stamp(0.015%) + GST(18% on Brkg+Txn+SEBI)"
        )
        self._help_item(
            s, "SELL Formula",
            "Total = Brkg(₹1) + STT(0.1%) + TxnChg(0.00297%) + SEBI(0.0001%) + DP(₹15.34) + GST(18% on Brkg+Txn+SEBI)"
        )

        s = self._help_card(parent, "Market Data & Sync")
        self._help_item(s, "Data Source", "Market data is fetched via yfinance. Indian symbols may be suffixed with .NS or .BO.")
        self._help_item(s, "Syncing", "Market data sync runs in the background to keep the UI responsive.")

        # ── Tax Report & Harvesting ────────────────────────────────────────────
        tax_cols = ["Term", "Holding Period", "Tax Rate (Indian Equity)", "FY Window"]
        tax_rows = [
            ["STCG", "≤ 1 year", "15% flat on gains", "Apr 1 – Mar 31"],
            ["LTCG", "> 1 year", "10% on gains above ₹1L exemption", "Apr 1 – Mar 31"],
        ]

        fifo_cols = ["Step", "Action", "Result"]
        fifo_rows = [
            ["1", "Sort all BUY lots for a symbol by date (oldest first)", "Establishes cost queue"],
            ["2", "Match each SELL against the oldest BUY lot first", "Consumes oldest shares first"],
            ["3", "Record (Sell Date − Buy Date) to classify STCG vs LTCG", "Determines holding period"],
            ["4", "Net PnL = Sale Proceeds − Cost − Proportional Fees", "Computes actual gain/loss"],
        ]

        harvest_cols = ["Scenario", "Action", "Benefit"]
        harvest_rows = [
            ["Unrealized loss > ₹10K", "Sell before Mar 31 to book loss", "Offset STCG/LTCG gains"],
            ["LTCG exemption headroom", "Book gains up to ₹1L", "Avoid 10% tax; re-enter position"],
            ["Mix of STCG & LTCG lots", "Sell LTCG lots first (hold >1yr)", "Lower effective tax rate"],
        ]

        s = self._help_card(parent, "📄 Tax Report & Harvesting", "tax")
        self._help_item(
            s, "What is the Tax Report?",
            "The Tax Report view computes your Short Term (STCG) and Long Term (LTCG) Capital Gains "
            "for any selected financial year using FIFO (First-In, First-Out) matching of buy/sell trades. "
            "It mimics the method used by Indian Income Tax rules."
        )
        self._help_table(s, tax_cols, tax_rows)

        self._help_item(
            s, "How FIFO Matching Works",
            "For every SELL trade, shares are matched against the earliest BUY lots first. "
            "The holding period (Buy Date → Sell Date) determines whether the gain is classified as STCG or LTCG."
        )
        self._help_table(s, fifo_cols, fifo_rows)

        self._help_item(
            s, "Steps to Generate Your Tax Report",
            "1. Navigate to Tax Report from the sidebar.\n"
            "2. Select the applicable Financial Year (FY 2024-2025 = April 1, 2024 – March 31, 2025).\n"
            "3. The summary cards show your total STCG, LTCG, and combined taxable gains.\n"
            "4. The table below lists every sale with its holding duration, gain type, and net PnL.\n"
            "5. Use this data when filing your ITR under Schedule CG (Capital Gains)."
        )

        self._help_item(
            s, "Tax Harvesting Strategies",
            "Tax-loss harvesting allows you to reduce your taxable gains by strategically selling "
            "positions before the financial year ends. Common strategies are listed below."
        )
        self._help_table(s, harvest_cols, harvest_rows)

        self._help_item(
            s, "Important Notes",
            "• This report is for reference only and does not constitute professional tax advice.\n"
            "• Fees are apportioned proportionally to each matched SELL chunk.\n"
            "• If a SELL consumes lots with different holding periods, the longest period is displayed.\n"
            "• Always verify the output with a CA or tax professional before filing.\n"
            "• LTCG exemption of ₹1 lakh per FY applies only to equity/equity mutual funds (Section 112A)."
        )


        # ── Watchlist Advanced Metrics ─────────────────────────────────────────

        s = self._help_card(parent, "📊 Advanced Watchlist Benchmarks", "watchlist")
        self._help_item(
            s, "Using Advanced Metrics",
            "The Watchlist allows you to track up to 20 fundamental and technical metrics for any symbol. "
            "Use the following benchmarks to evaluate if a stock matches your investing criteria."
        )

        val_cols = ["Metric / Ratio", "Ideal Benchmark / Target", "Description"]
        val_rows = [
            ["P/E Ratio", "Compare with Industry", "Price-to-Earnings; determines if the stock is cheap or expensive. Avoid 'Value Traps' with very low P/E."],
            ["PEG Ratio", "< 1.0 (Best) or < 2.0", "Price/Earnings to Growth; measures if the P/E is justified by the company's growth rate."],
            ["EPS", "Double Digits (>10)", "Earnings Per Share; the portion of a company's profit allocated to each outstanding share."],
            ["Debt to Equity", "< 1.0", "Total liabilities divided by shareholder equity; ensures the company is not over-leveraged."],
            ["Book Value", "Compare to Price", "The net asset value. Useful for understanding 'De-listing' or liquidation value."],
            ["Intrinsic Value", "Higher than Market Price", "The actual 'fair value' of the business based on its brand and assets."],
        ]
        self._help_table(s, val_cols, val_rows)

        prof_cols = ["Metric / Ratio", "Ideal Benchmark / Target", "Description"]
        prof_rows = [
            ["ROE", "Double Digits", "Return on Equity; measures how effectively the company uses investor money to generate profit."],
            ["ROCE", "Double Digits", "Return on Capital Employed; measures profit against total capital (Equity + Debt)."],
            ["OPM (%)", "> 10% - 15%", "Operating Profit Margin; the percentage of revenue left after paying for variable costs."],
            ["Free Cash Flow", "Must be Positive", "The actual cash remaining after all expenses and investments (CapEx)."],
            ["Inventory Days", "Lower is generally better", "The number of days it takes to turn stock into sales."],
        ]
        self._help_table(s, prof_cols, prof_rows)

        growth_cols = ["Metric", "Target", "Description"]
        growth_rows = [
            ["Sales Growth", "Double Digits", "Revenue growth on a Year-on-Year (YoY) and Quarter-on-Quarter (QoQ) basis."],
            ["Profit Growth", "Double Digits", "Net profit growth; must ideally grow faster than or equal to sales growth."],
        ]
        self._help_table(s, growth_cols, growth_rows)

        op_cols = ["Metric", "Observation", "Description"]
        op_rows = [
            ["Promoter Holding", "High & Stable", "The percentage of the company owned by the founders/owners."],
            ["Pledged Shares", "Zero (Ideal)", "Whether promoters have used their shares as collateral for loans."],
            ["FII / DII Holding", "Increasing / Stable", "Ownership by Foreign and Domestic Institutional Investors (Mutual Funds)."],
            ["Order Book", "High Visibility", "Total value of orders yet to be executed; provides a roadmap for future revenue."],
        ]
        self._help_table(s, op_cols, op_rows)

        tech_cols = ["Metric", "Observation", "Description"]
        tech_rows = [
            ["50 & 200 DMA", "Above the lines", "Moving Averages; used to see if the stock is in a long-term uptrend."],
            ["RSI", "30 (Oversold) / 70 (Overbought)", "Relative Strength Index; identifies if a stock is at a buying or selling extreme."],
            ["Volume", "Increasing", "Confirms if a price movement is backed by significant market interest."],
        ]
        self._help_table(s, tech_cols, tech_rows)
