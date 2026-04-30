"""
Valuation View - Standalone Stock Analysis & Valuation view.
Allows users to enter a symbol, fetch metrics, compute intrinsic value, and see a buy/sell signal.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from views.base_view import BaseView, _enable_canvas_mousewheel
from ui_theme import ModernStyle
from ui_widgets import ModernButton, LoadingOverlay, ModernCard, ModernEntry
import pandas as pd


class ValuationView(BaseView):
    """View to analyze a single stock's valuation metrics."""

    def build(self):
        # ── Header ─────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        hdr.pack(fill="x", padx=20, pady=(20, 4))

        left = tk.Frame(hdr, bg=ModernStyle.BG_PRIMARY)
        left.pack(side="left")
        tk.Label(
            left,
            text="🔬 Valuation Analysis",
            fg=ModernStyle.ACCENT_PRIMARY,
            bg=ModernStyle.BG_PRIMARY,
            font=ModernStyle.FONT_PAGE_TITLE,
        ).pack(anchor="w")
        tk.Label(
            left,
            text="Enter a symbol to fetch parameters and determine if it is undervalued.",
            fg=ModernStyle.TEXT_TERTIARY,
            bg=ModernStyle.BG_PRIMARY,
            font=ModernStyle.FONT_BODY,
        ).pack(anchor="w", pady=(2, 0))

        # Accent divider
        tk.Frame(self, bg="#D4AF37", height=1).pack(fill="x", padx=20, pady=(10, 10))

        self.main_scroll_frame = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        self.main_scroll_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(
            self.main_scroll_frame,
            bg=ModernStyle.BG_PRIMARY,
            highlightthickness=0
        )
        scrollbar = ttk.Scrollbar(self.main_scroll_frame, orient="vertical", command=canvas.yview)
        self.scrollable_inner = tk.Frame(canvas, bg=ModernStyle.BG_PRIMARY)

        self.scrollable_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas_window = canvas.create_window((0, 0), window=self.scrollable_inner, anchor="nw")
        
        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
            
        canvas.bind("<Configure>", _on_canvas_configure)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)
        _enable_canvas_mousewheel(canvas)
        
        # ── Loading Overlay ───────────────────────────────────────────────────
        self.loading_overlay = LoadingOverlay(self.main_scroll_frame)


        # ── Input Row ─────────────────────────────────────────────────────────
        input_card = ModernCard(
            self.scrollable_inner,
            bg=ModernStyle.BG_SECONDARY,
            highlight_color=ModernStyle.BORDER_COLOR,
            highlight_thickness=1,
            radius=10,
            canvas_bg=ModernStyle.BG_PRIMARY
        )
        input_card.pack(fill="x", padx=20, pady=(10, 6))
        input_inner = tk.Frame(input_card.content, bg=ModernStyle.BG_SECONDARY)
        input_inner.pack(fill="x", padx=16, pady=10)

        tk.Label(
            input_inner, text="Stock Symbol:",
            fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_HEADING,
        ).pack(side="left", padx=(0, 10))

        self._v_symbol = tk.StringVar()
        self._e_symbol = ModernEntry(
            input_inner, textvariable=self._v_symbol, width=15,
            bg=ModernStyle.ENTRY_BG, fg=ModernStyle.ACCENT_PRIMARY,
            font=ModernStyle.FONT_INPUT,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightcolor=ModernStyle.ACCENT_PRIMARY,
            highlightbackground=ModernStyle.BORDER_COLOR,
            insertbackground=ModernStyle.ACCENT_PRIMARY,
        )
        def _fi(e_evt, w=input_inner, i=self._e_symbol): i.configure(bg="#FFFFFF")
        def _fo(e_evt, w=input_inner, i=self._e_symbol): i.configure(bg=ModernStyle.ENTRY_BG)
        self._e_symbol.bind("<FocusIn>", _fi, add="+")
        self._e_symbol.bind("<FocusOut>", _fo, add="+")
        self._e_symbol.pack(side="left", ipady=5, padx=(0, 15))
        
        # Allow hitting Enter to fetch
        self._e_symbol.bind("<Return>", lambda _: self._fetch_data())

        self._btn_fetch = ModernButton(
            input_inner, text="⚡ Analyze",
            command=self._fetch_data,
            bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.BG_SECONDARY,
            width=120, height=40, radius=8,
            font=ModernStyle.FONT_SUBHEADING,
        )
        self._btn_fetch.pack(side="left")

        self._lbl_status = tk.Label(
            input_inner,
            text="",
            fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_SMALL,
        )
        self._lbl_status.pack(side="left", padx=15)
        
        # Company Name Label (Right aligned)
        self._lbl_company_name = tk.Label(
            input_inner,
            text="",
            fg=ModernStyle.ACCENT_PRIMARY, bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_MODAL_TITLE,
        )
        self._lbl_company_name.pack(side="right", padx=(10, 0))

        # ── Summary Dashboard ─────────────────────────────────────────────────
        self.summary_card = ModernCard(
            self.scrollable_inner,
            bg=ModernStyle.BG_SECONDARY,
            highlight_color=ModernStyle.BORDER_COLOR,
            highlight_thickness=1,
            radius=10,
            canvas_bg=ModernStyle.BG_PRIMARY
        )
        self.summary_card.pack(fill="x", padx=20, pady=10)
        self.summary_card.pack_forget() # Hide initially

        tk.Frame(self.summary_card.content, bg=ModernStyle.ACCENT_SECONDARY, height=3).pack(fill="x")
        
        summary_inner = tk.Frame(self.summary_card.content, bg=ModernStyle.BG_SECONDARY)
        summary_inner.pack(fill="both", expand=True, padx=20, pady=16)
        
        # Left side: Signal and core value
        left_summary = tk.Frame(summary_inner, bg=ModernStyle.BG_SECONDARY)
        left_summary.pack(side="left", fill="y", padx=(0, 30))
        
        self.lbl_signal_badge = tk.Label(
            left_summary, text="---",
            font=ModernStyle.FONT_DRILLDOWN_SYM,
            bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY
        )
        self.lbl_signal_badge.pack(anchor="w", pady=(0, 10))
        
        prices_frame = tk.Frame(left_summary, bg=ModernStyle.BG_SECONDARY)
        prices_frame.pack(anchor="w")
        
        tk.Label(prices_frame, text="Current Price:", font=ModernStyle.FONT_SUBHEADING, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_SECONDARY).grid(row=0, column=0, sticky="w", pady=2)
        self.lbl_current_price = tk.Label(prices_frame, text="---", font=ModernStyle.FONT_HEADING, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY)
        self.lbl_current_price.grid(row=0, column=1, sticky="w", padx=10, pady=2)

        tk.Label(prices_frame, text="Intrinsic Value:", font=ModernStyle.FONT_SUBHEADING, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_SECONDARY).grid(row=1, column=0, sticky="w", pady=2)
        self.lbl_intrinsic_value = tk.Label(prices_frame, text="---", font=ModernStyle.FONT_HEADING, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY)
        self.lbl_intrinsic_value.grid(row=1, column=1, sticky="w", padx=10, pady=2)
        
        self.lbl_margin_safety = tk.Label(prices_frame, text="", font=ModernStyle.FONT_BODY_BOLD, bg=ModernStyle.BG_SECONDARY)
        self.lbl_margin_safety.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # Visual Gauge Bar
        self.gauge_frame = tk.Frame(prices_frame, bg=ModernStyle.BG_SECONDARY)
        self.gauge_frame.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self.gauge_canvas = tk.Canvas(self.gauge_frame, bg=ModernStyle.BG_TERTIARY, height=12, width=220, highlightthickness=0)
        self.gauge_canvas.pack(anchor="w")
        self.gauge_rect = self.gauge_canvas.create_rectangle(0, 0, 0, 12, fill=ModernStyle.SUCCESS, outline="")

        # Right side: Rationale text
        right_summary = tk.Frame(summary_inner, bg=ModernStyle.BG_SECONDARY)
        right_summary.pack(side="left", fill="both", expand=True)
        
        tk.Label(right_summary, text="Decision Rationale", font=ModernStyle.FONT_SUBHEADING, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        
        self.txt_rationale = tk.Text(
            right_summary, height=10, bg=ModernStyle.SLATE_800, fg=ModernStyle.SLATE_300,
            font=ModernStyle.FONT_HEADING, relief=tk.FLAT,
            wrap=tk.WORD, padx=12, pady=12
        )
        self.txt_rationale.pack(fill="both", expand=True)
        self.txt_rationale.configure(state="disabled")


        # ── Detailed Metrics Grid ─────────────────────────────────────────────
        self.metrics_frame = tk.Frame(self.scrollable_inner, bg=ModernStyle.BG_PRIMARY)
        self.metrics_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.metrics_frame.pack_forget()

        # Dictionary to store metric stringvars
        self._metrics_vars = {}
        self._metric_labels = {}
        
        # Define categories to group metrics nicely
        categories = {
            "Valuation": [
                ("P/E Ratio",        "pe_ratio"),
                ("Forward P/E",      "forward_pe"),
                ("PEG Ratio",        "peg_ratio"),
                ("P/B Ratio",        "pb_ratio"),
                ("Price/Sales",      "price_to_sales"),
                ("Enterprise Value", "enterprise_value"),
                ("Analyst Target",   "analyst_target"),
                ("Beta",             "beta"),
                ("Dividend Yield",   "dividend_yield"),
                ("Payout Ratio",     "payout_ratio"),
                ("Market Cap",       "market_cap"),
            ],
            "Profitability": [
                ("EPS",              "eps"),
                ("ROE",              "roe"),
                ("ROCE",             "roce"),
                ("ROA",              "roa"),
                ("OPM",              "opm"),
                ("Net Profit Margin","net_profit_margin"),
                ("EBITDA Margin",    "ebitda_margin"),
                ("QoQ Op. Profit",   "qoq_op_profit"),
                ("Free Cash Flow",   "free_cash_flow"),
            ],
            "Growth & Health": [
                ("3Y Rev CAGR",      "revenue_cagr_3y"),
                ("5Y Rev CAGR",      "revenue_cagr_5y"),
                ("3Y Profit CAGR",   "profit_cagr_3y"),
                ("5Y Profit CAGR",   "profit_cagr_5y"),
                ("Sales Growth",     "sales_growth"),
                ("Profit Growth",    "profit_growth"),
                ("Debt to Equity",   "debt_to_equity"),
                ("Current Ratio",    "current_ratio"),
                ("Quick Ratio",      "quick_ratio"),
            ],
            "Technical": [
                ("50-Day MA",        "dma_50"),
                ("200-Day MA",       "dma_200"),
                ("50/200 Cross",     "dma_50_200"),
                ("52-Week Range",    "week52_range"),
                ("RSI (14D)",        "rsi"),
                ("MACD Signal",      "macd"),
                ("Sharpe Ratio",     "sharpe_ratio"),
                ("Volume",           "volume"),
                ("Short Ratio",      "short_ratio"),
                ("Support/Resist.",  "support_resistance"),
            ],
            "Ownership": [
                ("Insider Held",     "promoter_holding"),
                ("Institution Held", "institution_holding"),
                ("Institution Count","institution_count"),
            ],
            "Alternate Valuations": [
                ("Graham Number",    "graham_number"),
                ("Intrinsic Value",  "intrinsic_value_display"),
            ],
        }
        
        # Create a grid layout for cards
        row_idx = 0
        col_idx = 0
        
        for cat_name, items in categories.items():
            card = ModernCard(
                self.metrics_frame, bg=ModernStyle.BG_SECONDARY,
                highlight_color=ModernStyle.BORDER_COLOR, highlight_thickness=1,
                radius=10, canvas_bg=ModernStyle.BG_PRIMARY
            )
            card.grid(row=row_idx, column=col_idx, sticky="nsew", padx=8, pady=8)
            self.metrics_frame.grid_columnconfigure(col_idx, weight=1)
            
            # Category Header
            tk.Label(
                card.content, text=cat_name.upper(),
                font=ModernStyle.FONT_SMALL_BOLD,
                fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY
            ).pack(anchor="w", padx=12, pady=(12, 6))
            
            # Thin separator
            tk.Frame(card.content, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=12, pady=(0, 6))
            
            content = tk.Frame(card.content, bg=ModernStyle.BG_SECONDARY)
            content.pack(fill="both", expand=True, padx=12, pady=(0, 12))
            
            for i, (label_text, key) in enumerate(items):
                row = tk.Frame(content, bg=ModernStyle.BG_SECONDARY)
                row.pack(fill="x", pady=4)
                
                tk.Label(
                    row, text=label_text,
                    font=ModernStyle.FONT_BODY,
                    fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY
                ).pack(side="left")
                
                var = tk.StringVar(value="---")
                self._metrics_vars[key] = var
                
                lbl_val = tk.Label(
                    row, textvariable=var,
                    font=ModernStyle.FONT_HEADING,
                    fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_SECONDARY
                )
                lbl_val.pack(side="right")
                self._metric_labels[key] = lbl_val
            
            # Wrap to next row after 2 columns
            col_idx += 1
            if col_idx > 1:
                col_idx = 0
                row_idx += 1

        # We also need these for logic processing
        self._raw_data = {}

    def on_show(self):
        self._is_active = True
        self._e_symbol.focus_set()

    def _flash_status(self, msg: str, *, error: bool = False):
        color = ModernStyle.ERROR if error else ModernStyle.SUCCESS
        self._lbl_status.config(text=msg, fg=color)

    # ── Fetching Data ─────────────────────────────────────────────────────────

    def _fetch_data(self):
        symbol = self._v_symbol.get().strip().upper()
        if not symbol:
            self._flash_status("⚠ Enter a symbol to analyze.", error=True)
            return
            
        # Optional NS suffix handling for Indian stocks
        yf_symbol = symbol
        if not yf_symbol.endswith('.NS') and not yf_symbol.endswith('.BO'):
            # If standard Indian symbol length and no dot, default to NSE
            if len(yf_symbol) < 10 and '.' not in yf_symbol:
                yf_symbol += '.NS'

        self._btn_fetch.set_text("🔄 Analyzing...")
        self._btn_fetch.set_disabled(True)
        self._flash_status(f"Fetching data for {yf_symbol}...")
        
        self.loading_overlay.show()
        self.loading_overlay.set_text(f"Fetching data for {yf_symbol}...")
        
        # Reset UI
        self.summary_card.pack_forget()
        self.metrics_frame.pack_forget()
        self._raw_data.clear()
        for var in self._metrics_vars.values():
            var.set("---")
        for lbl in self._metric_labels.values():
            lbl.config(fg=ModernStyle.TEXT_PRIMARY)

        def bg_fetch():
            try:
                import yfinance as yf
                ticker = yf.Ticker(yf_symbol)
                info = ticker.info

                if not info or ('regularMarketPrice' not in info and 'currentPrice' not in info and 'previousClose' not in info):
                    self.after(0, lambda: self._flash_status(f"⚠ Could not find data for {yf_symbol}.", error=True))
                    return

                # ── Detect currency symbol from exchange ──────────────────────
                currency = (info.get("currency") or "USD").upper()
                cy = "₹" if currency in ("INR",) else ("¥" if currency in ("JPY", "CNY") else ("£" if currency == "GBP" else "$"))
                extract_meta = {"cy": cy, "currency": currency}

                # ── Historical data (RSI, MACD, Sharpe, Support/Resistance) ──
                hist = ticker.history(period="3y")
                rsi_val = None
                sharpe_val = None
                macd_val = None
                supp_res = None
                recent_hist = pd.DataFrame()

                if not hist.empty and len(hist) >= 30:
                    recent_hist = hist.tail(252)

                    # RSI (14-period)
                    delta = recent_hist['Close'].diff()
                    gain = delta.where(delta > 0, 0.0).rolling(window=14).mean()
                    loss = (-delta.where(delta < 0, 0.0)).rolling(window=14).mean()
                    rs = gain / loss.replace(0, float('nan'))
                    rsi_series = 100 - (100 / (1 + rs))
                    rsi_last = rsi_series.iloc[-1]
                    if pd.notna(rsi_last):
                        rsi_val = float(rsi_last)

                    # MACD (12/26/9)
                    exp12 = recent_hist['Close'].ewm(span=12, adjust=False).mean()
                    exp26 = recent_hist['Close'].ewm(span=26, adjust=False).mean()
                    macd_line = exp12 - exp26
                    signal_line = macd_line.ewm(span=9, adjust=False).mean()
                    if pd.notna(macd_line.iloc[-1]) and pd.notna(signal_line.iloc[-1]):
                        macd_val = float(macd_line.iloc[-1] - signal_line.iloc[-1])

                    # Support / Resistance (60-day high/low)
                    recent_min = recent_hist['Low'].tail(60).min()
                    recent_max = recent_hist['High'].tail(60).max()
                    supp_res = (float(recent_min), float(recent_max))

                    # Sharpe Ratio (annualised, rf=4%)
                    returns = recent_hist['Close'].pct_change().dropna()
                    if len(returns) > 20:
                        rf = 0.04 / 252
                        excess_ret = returns - rf
                        if excess_ret.std() > 0:
                            sharpe_val = float((excess_ret.mean() / excess_ret.std()) * (252 ** 0.5))

                    # Compute actual 50-Day & 200-Day MA from history if info values missing
                    if not hist.empty and len(hist) >= 50:
                        ma50_hist = float(hist['Close'].tail(50).mean())
                        ma200_hist = float(hist['Close'].tail(200).mean()) if len(hist) >= 200 else None
                    else:
                        ma50_hist = None
                        ma200_hist = None

                scr_data = self._fetch_screener_fallback(yf_symbol) if yf_symbol.endswith('.NS') or yf_symbol.endswith('.BO') else {}

                def extract(key, val):
                    self._raw_data[key] = val
                    return val

                # ── Current price ─────────────────────────────────────────────
                cur_price = 0.0
                try:
                    import math
                    val = float(ticker.fast_info.last_price)
                    if not math.isnan(val):
                        cur_price = val
                except Exception:
                    pass
                if cur_price <= 0.0:
                    cur_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose") or 0.0
                extract("current_price", cur_price)
                extract("currency_symbol", cy)

                # ── Identity ──────────────────────────────────────────────────
                extract("company_name",  info.get("longName") or info.get("shortName"))

                # ── Valuation multiples ───────────────────────────────────────
                extract("pe_ratio",      info.get("trailingPE")       or scr_data.get("stock p/e"))
                extract("forward_pe",    info.get("forwardPE"))
                extract("peg_ratio",     info.get("pegRatio"))
                extract("pb_ratio",      info.get("priceToBook"))
                extract("price_to_sales",info.get("priceToSalesTrailing12Months"))
                extract("beta",          info.get("beta"))
                extract("market_cap",    info.get("marketCap"))
                extract("enterprise_value", info.get("enterpriseValue"))
                extract("analyst_target",info.get("targetMeanPrice"))

                dy = info.get("dividendYield")
                extract("dividend_yield", dy * 100 if dy is not None else None)
                payout = info.get("payoutRatio")
                extract("payout_ratio",  payout * 100 if payout is not None else None)

                # ── Profitability ─────────────────────────────────────────────
                eps_raw = info.get("trailingEps")
                extract("eps", eps_raw)

                roe = info.get("returnOnEquity")
                extract("roe", roe * 100 if roe is not None else scr_data.get("roe"))

                roa = info.get("returnOnAssets")
                extract("roa", roa * 100 if roa is not None else None)

                # ROCE: computed from financials (EBIT / Capital Employed)
                # Capital Employed = Total Assets - Current Liabilities
                roce_val = scr_data.get("roce")  # Indian screener fallback
                if roce_val is None:
                    try:
                        bs  = ticker.balance_sheet
                        fin = ticker.financials
                        if not bs.empty and not fin.empty:
                            # Try multiple label variants across exchanges
                            def _row(df, *labels):
                                for lbl in labels:
                                    if lbl in df.index:
                                        v = df.loc[lbl].dropna()
                                        return float(v.iloc[0]) if len(v) else None
                                return None

                            total_assets = _row(bs, "Total Assets", "TotalAssets")
                            curr_liab    = _row(bs, "Current Liabilities", "CurrentLiabilities",
                                                    "Total Current Liabilities", "TotalCurrentLiabilities")
                            ebit         = _row(fin, "EBIT", "Operating Income", "OperatingIncome")

                            if total_assets and curr_liab and ebit:
                                cap_employed = total_assets - curr_liab
                                if cap_employed > 0:
                                    roce_val = (ebit / cap_employed) * 100
                    except Exception:
                        pass
                extract("roce", roce_val)

                opm = info.get("operatingMargins")
                extract("opm", opm * 100 if opm is not None else None)

                eb_m = info.get("ebitdaMargins")
                extract("ebitda_margin", eb_m * 100 if eb_m is not None else None)

                np_m = info.get("profitMargins")
                extract("net_profit_margin", np_m * 100 if np_m is not None else None)

                extract("free_cash_flow", info.get("freeCashflow"))

                # ── Health ────────────────────────────────────────────────────
                debt_eq = info.get("debtToEquity")
                extract("debt_to_equity",  debt_eq / 100 if debt_eq is not None else None)
                extract("book_value",       info.get("bookValue"))
                extract("current_ratio",    info.get("currentRatio"))
                extract("quick_ratio",      info.get("quickRatio"))

                # ── Growth ────────────────────────────────────────────────────
                rev_gr = info.get("revenueGrowth")
                extract("sales_growth",  rev_gr * 100 if rev_gr is not None else None)
                ern_gr = info.get("earningsGrowth")
                extract("profit_growth", ern_gr * 100 if ern_gr is not None else None)

                # ── Ownership ─────────────────────────────────────────────────
                insiders = info.get("heldPercentInsiders")
                extract("promoter_holding",   insiders * 100 if insiders is not None else None)
                inst = info.get("heldPercentInstitutions")
                extract("institution_holding", inst * 100 if inst is not None else None)

                extract("institution_count", None)
                try:
                    maj_holders = ticker.major_holders
                    if maj_holders is not None and not maj_holders.empty and 1 in maj_holders.columns:
                        count_row = maj_holders[maj_holders[1].str.contains("Number of Institutions", na=False)]
                        if not count_row.empty:
                            extract("institution_count", int(count_row[0].values[0]))
                except Exception:
                    pass

                extract("short_ratio", info.get("shortRatio"))

                # ── Technical ─────────────────────────────────────────────────
                dma50  = info.get("fiftyDayAverage")  or (ma50_hist  if not recent_hist.empty else None)
                dma200 = info.get("twoHundredDayAverage") or (ma200_hist if not recent_hist.empty else None)
                extract("dma_50",   dma50)
                extract("dma_200",  dma200)
                extract("rsi",      rsi_val)
                extract("macd",     macd_val)
                extract("support_resistance", supp_res)
                extract("sharpe_ratio", sharpe_val)
                extract("volume", info.get("volume") or info.get("averageVolume"))

                h52 = info.get("fiftyTwoWeekHigh")
                l52 = info.get("fiftyTwoWeekLow")
                extract("h52", h52)
                extract("l52", l52)

                # ── Intrinsic Value (DCF) ─────────────────────────────────────
                iv_val = None
                try:
                    from model.engine import calculate_intrinsic_value as _calc_iv
                    if eps_raw and eps_raw > 0:
                        iv_val = _calc_iv(eps_raw)
                        extract("intrinsic_value", iv_val)
                except Exception:
                    pass

                # ── Graham Number ─────────────────────────────────────────────
                bvps = info.get("bookValue")
                if eps_raw and bvps and eps_raw > 0 and bvps > 0:
                    try:
                        import math
                        extract("graham_number", math.sqrt(22.5 * eps_raw * bvps))
                    except Exception:
                        pass

                # ── CAGR from income statement ────────────────────────────────
                try:
                    inc_stmt = ticker.financials
                    if not inc_stmt.empty and "Total Revenue" in inc_stmt.index:
                        revs = inc_stmt.loc["Total Revenue"].dropna()
                        if len(revs) >= 4:
                            y0, y3 = revs.iloc[0], revs.iloc[3]
                            if y3 and y3 > 0:
                                extract("revenue_cagr_3y", (((y0 / y3) ** (1/3)) - 1) * 100)
                        if len(revs) >= 5:
                            periods = min(5, len(revs) - 1)
                            y5 = revs.iloc[periods]
                            if y5 and y5 > 0 and periods >= 4:
                                extract("revenue_cagr_5y", (((y0 / y5) ** (1/periods)) - 1) * 100)

                    if not inc_stmt.empty and "Net Income" in inc_stmt.index:
                        incomes = inc_stmt.loc["Net Income"].dropna()
                        if len(incomes) >= 4:
                            y0, y3 = incomes.iloc[0], incomes.iloc[3]
                            if y3 and y3 > 0:
                                extract("profit_cagr_3y", (((y0 / y3) ** (1/3)) - 1) * 100)
                        if len(incomes) >= 5:
                            periods = min(5, len(incomes) - 1)
                            y_end = incomes.iloc[periods]
                            if y_end and y_end > 0 and periods >= 4:
                                extract("profit_cagr_5y", (((y0 / y_end) ** (1/periods)) - 1) * 100)
                except Exception:
                    pass

                # ── QoQ Operating Profit ──────────────────────────────────────
                try:
                    qf = ticker.quarterly_financials
                    if not qf.empty:
                        for lbl in ("Operating Income", "EBIT", "OperatingIncome"):
                            if lbl in qf.index:
                                op_profit = qf.loc[lbl].iloc[0]
                                if pd.notna(op_profit):
                                    extract("qoq_op_profit", op_profit)
                                break
                except Exception:
                    pass

                self.after(0, self._process_and_display)

            except Exception as e:
                import traceback
                print(f"[ValuationView] fetch error: {e}\n{traceback.format_exc()}")
                self.after(0, lambda: self._flash_status(f"⚠ Failed: {e}", error=True))
            finally:
                self.after(0, self.loading_overlay.hide)
                self.after(1000, lambda: getattr(self, "_btn_fetch").set_text("⚡ Analyze") if hasattr(self, "_btn_fetch") else None)
                self.after(1000, lambda: getattr(self, "_btn_fetch").set_disabled(False) if hasattr(self, "_btn_fetch") else None)

        threading.Thread(target=bg_fetch, daemon=True).start()


    def _process_and_display(self):
        """Format the raw data into UI elements and run the logic engine."""
        self._flash_status("Analysis complete.")

        cy = self._raw_data.get("currency_symbol", "$")

        # ── Helper: safely set a formatted StringVar ─────────────────────────
        def sv(key: str, text: str) -> None:
            """Set metric var if the key exists in the grid."""
            if key in self._metrics_vars:
                self._metrics_vars[key].set(text)

        def update_var(key, fmt="{}") -> None:
            val = self._raw_data.get(key)
            if val is not None and str(val).strip() not in ("", "None", "nan"):
                try:
                    sv(key, fmt.format(val))
                except Exception:
                    pass

        # ── Valuation ────────────────────────────────────────────────────────
        update_var("pe_ratio",   "{:.1f}x")
        update_var("forward_pe", "{:.1f}x")
        update_var("peg_ratio",  "{:.2f}")
        update_var("pb_ratio",   "{:.2f}x")
        update_var("price_to_sales", "{:.2f}x")
        update_var("beta",       "{:.2f}")
        update_var("dividend_yield", "{:.2f}%")
        update_var("payout_ratio",   "{:.1f}%")
        update_var("short_ratio",    "{:.2f}")

        analyst_t = self._raw_data.get("analyst_target")
        if analyst_t is not None:
            sv("analyst_target", f"{cy}{analyst_t:,.1f}")

        for big_key in ("market_cap", "enterprise_value"):
            mc = self._raw_data.get(big_key)
            if mc is not None:
                try:
                    mc = float(mc)
                    if abs(mc) >= 1e12:
                        sv(big_key, f"{cy}{mc/1e12:.2f}T")
                    elif abs(mc) >= 1e9:
                        sv(big_key, f"{cy}{mc/1e9:.1f}B")
                    elif abs(mc) >= 1e6:
                        sv(big_key, f"{cy}{mc/1e6:.1f}M")
                    else:
                        sv(big_key, f"{cy}{mc:,.0f}")
                except Exception:
                    pass

        # ── Profitability ────────────────────────────────────────────────────
        eps = self._raw_data.get("eps")
        if eps is not None:
            try:
                sv("eps", f"{cy}{float(eps):.2f}")
            except Exception:
                pass

        update_var("roe",              "{:.1f}%")
        update_var("roce",             "{:.1f}%")
        update_var("roa",              "{:.1f}%")
        update_var("opm",              "{:.1f}%")
        update_var("ebitda_margin",    "{:.1f}%")
        update_var("net_profit_margin","{:.1f}%")

        fcf = self._raw_data.get("free_cash_flow")
        if fcf is not None:
            try:
                fcf = float(fcf)
                if abs(fcf) >= 1e12:
                    sv("free_cash_flow", f"{cy}{fcf/1e12:.2f}T")
                elif abs(fcf) >= 1e9:
                    sv("free_cash_flow", f"{cy}{fcf/1e9:.1f}B")
                elif abs(fcf) >= 1e6:
                    sv("free_cash_flow", f"{cy}{fcf/1e6:.1f}M")
                else:
                    sv("free_cash_flow", f"{cy}{fcf:,.0f}")
            except Exception:
                pass

        op = self._raw_data.get("qoq_op_profit")
        if op is not None:
            try:
                op = float(op)
                if abs(op) >= 1e9:
                    sv("qoq_op_profit", f"{cy}{op/1e9:.1f}B")
                elif abs(op) >= 1e6:
                    sv("qoq_op_profit", f"{cy}{op/1e6:.1f}M")
                else:
                    sv("qoq_op_profit", f"{cy}{op:,.0f}")
            except Exception:
                pass

        # ── Growth & Health ───────────────────────────────────────────────────
        update_var("revenue_cagr_3y",  "{:.1f}%")
        update_var("revenue_cagr_5y",  "{:.1f}%")
        update_var("profit_cagr_3y",   "{:.1f}%")
        update_var("profit_cagr_5y",   "{:.1f}%")
        update_var("sales_growth",     "{:.1f}%")
        update_var("profit_growth",    "{:.1f}%")
        update_var("debt_to_equity",   "{:.2f}")
        update_var("current_ratio",    "{:.2f}")
        update_var("quick_ratio",      "{:.2f}")

        # ── Technical ────────────────────────────────────────────────────────
        dma50  = self._raw_data.get("dma_50")
        dma200 = self._raw_data.get("dma_200")
        if dma50 is not None:
            sv("dma_50",  f"{cy}{float(dma50):,.2f}")
        if dma200 is not None:
            sv("dma_200", f"{cy}{float(dma200):,.2f}")
        if dma50 and dma200:
            sv("dma_50_200", f"{cy}{float(dma50):,.0f} / {cy}{float(dma200):,.0f}")

        h52 = self._raw_data.get("h52")
        l52 = self._raw_data.get("l52")
        if h52 and l52:
            sv("week52_range", f"{cy}{float(l52):,.0f} – {cy}{float(h52):,.0f}")

        update_var("rsi",         "{:.1f}")
        update_var("macd",        "{:.2f}")
        update_var("sharpe_ratio","{:.2f}")

        vol = self._raw_data.get("volume")
        if vol is not None:
            try:
                vol = float(vol)
                if vol >= 1e9:
                    sv("volume", f"{vol/1e9:.1f}B")
                elif vol >= 1e6:
                    sv("volume", f"{vol/1e6:.1f}M")
                elif vol >= 1e3:
                    sv("volume", f"{vol/1e3:.0f}K")
                else:
                    sv("volume", f"{vol:,.0f}")
            except Exception:
                pass

        sr = self._raw_data.get("support_resistance")
        if sr is not None:
            sv("support_resistance", f"{cy}{sr[0]:,.0f} / {cy}{sr[1]:,.0f}")

        # ── Ownership ────────────────────────────────────────────────────────
        update_var("promoter_holding",   "{:.1f}%")
        update_var("institution_holding", "{:.1f}%")
        update_var("institution_count",   "{}")

        # ── Alternate Valuations ─────────────────────────────────────────────
        graham = self._raw_data.get("graham_number")
        if graham is not None:
            sv("graham_number", f"{cy}{float(graham):,.2f}")

        iv_val = self._raw_data.get("intrinsic_value")
        if iv_val is not None:
            sv("intrinsic_value_display", f"{cy}{float(iv_val):,.2f}")

        # ── Company name label ────────────────────────────────────────────────
        c_name = self._raw_data.get("company_name")
        if c_name:
            self._lbl_company_name.config(text=(c_name[:38] + "…") if len(c_name) > 38 else c_name)
        else:
            self._lbl_company_name.config(text="")

        # Summary Header
        cur_price = self._raw_data.get("current_price")
        iv_val = self._raw_data.get("intrinsic_value")

        self.lbl_current_price.config(text=f"{cy}{cur_price:,.2f}" if cur_price else "---")
        self.lbl_intrinsic_value.config(text=f"{cy}{iv_val:,.2f}" if iv_val else "---")

        if cur_price and iv_val and iv_val > 0:
            margin = ((iv_val - cur_price) / iv_val) * 100
            
            # Update Gauge
            # Let's say max gauge is 50% over/undervalue limit
            gauge_w = 220
            pct_fill = min((iv_val / cur_price) if cur_price > 0 else 1.0, 2.0) / 2.0
            
            if margin > 0:
                self.lbl_margin_safety.config(text=f"({margin:.1f}% Undervalued)", fg=ModernStyle.SUCCESS)
                self.gauge_canvas.itemconfig(self.gauge_rect, fill=ModernStyle.SUCCESS)
                fill_w = min(pct_fill * gauge_w, gauge_w)
            else:
                self.lbl_margin_safety.config(text=f"({abs(margin):.1f}% Overvalued)", fg=ModernStyle.ERROR)
                self.gauge_canvas.itemconfig(self.gauge_rect, fill=ModernStyle.ERROR)
                fill_w = gauge_w # Full red if overvalued, or just visual representations
                
            self.gauge_canvas.coords(self.gauge_rect, 0, 0, fill_w, 12)
            self.gauge_frame.grid()
        else:
            self.lbl_margin_safety.config(text="")
            self.gauge_frame.grid_remove()


        # 2. Logic Engine
        badge, tip = self._compute_signal()
        
        self.lbl_signal_badge.config(text=badge)
        if "Strong Buy" in badge or "Accumulate" in badge:
            self.lbl_signal_badge.config(fg=ModernStyle.SUCCESS)
        elif "Avoid" in badge:
            self.lbl_signal_badge.config(fg=ModernStyle.ERROR)
        else:
            self.lbl_signal_badge.config(fg=ModernStyle.WARNING) # Warning orange
            
        self.txt_rationale.configure(state="normal")
        self.txt_rationale.delete(1.0, tk.END)
        self.txt_rationale.insert(tk.END, tip)
        self.txt_rationale.configure(state="disabled")

        # Show panels
        self.summary_card.pack(fill="x", padx=20, pady=10)
        self.metrics_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))


    def _compute_signal(self) -> tuple[str, str]:
        """Compute buy/sell signal and reason tip based on self._raw_data"""
        score = 0
        max_score = 0
        reasons_pass = []
        reasons_fail = []

        def check(label, key, condition_fn, tip_pass, tip_fail, ui_key=None):
            nonlocal score, max_score
            max_score += 1
            v = self._raw_data.get(key)
            if v is None:
                return  # No data = no score
            
            # Use specific ui_key if different from data key
            target_key = ui_key if ui_key else key

            if condition_fn(v):
                score += 1
                reasons_pass.append(f"✅ {label}: {tip_pass}")
                if target_key in self._metric_labels:
                    self._metric_labels[target_key].config(fg=ModernStyle.SUCCESS)
            else:
                score -= 1
                reasons_fail.append(f"❌ {label}: {tip_fail}")
                if target_key in self._metric_labels:
                    self._metric_labels[target_key].config(fg=ModernStyle.ERROR)

        # === Valuation & Multiples ===
        pe = self._raw_data.get("pe_ratio")
        if pe:
            max_score += 1
            if 0 < pe < 15.0:
                score += 1
                reasons_pass.append("✅ P/E Ratio: Undervalued compared to historical market averages (< 15x)")
            elif pe > 30.0:
                score -= 1
                reasons_fail.append("❌ P/E Ratio: Overvalued based on earnings multiple (> 30x)")

        peg = self._raw_data.get("peg_ratio")
        if peg:
            max_score += 1
            if 0 < peg < 1.0:
                score += 1
                reasons_pass.append("✅ PEG Ratio: Highly undervalued against its growth rate")
            elif peg > 1.5:
                score -= 1
                reasons_fail.append("❌ PEG Ratio: Growth rate does not justify current earnings multiple")

        check("P/B", "pb_ratio", lambda v: v < 3.0, "Reasonable price-to-book", "High price vs book value")

        # === Health & Quality Piotroski Proxy ===
        fcf = self._raw_data.get("free_cash_flow", 0)
        debt_eq = self._raw_data.get("debt_to_equity", 0)
        npm = self._raw_data.get("net_profit_margin", 0)
        
        # Hard stop / Z-Score proxy combinations
        if fcf is not None and debt_eq is not None and npm is not None:
            max_score += 2
            if fcf < 0 and debt_eq > 1.5:
                score -= 2
                reasons_fail.append("🚨 HEALTH RISK: Burning cash with heavy debt load (Bankruptcy risk proxy)")
            elif fcf > 0 and debt_eq < 0.5 and npm > 10:
                score += 2
                reasons_pass.append("🛡️ FUNDAMENTAL STRENGTH: Fortress balance sheet with high margins + cash flow")
            elif fcf < 0:
                score -= 1
                reasons_fail.append("❌ Cash Flow: Negative Free Cash Flow limits self-funding")

        # Fallback individual checks if proxy combination doesn't fire strongly
        check("Curr Ratio", "current_ratio", lambda v: v >= 1.5, "Healthy short-term liquidity buffer", "May struggle to meet short-term obligations")
        check("ROE", "roe", lambda v: v >= 12.0, "Strong return on shareholder equity", "Weak returns for shareholders")
        check("ROCE", "roce", lambda v: v >= 12.0, "Efficient capital allocation", "Capital not being deployed efficiently")

        dy = self._raw_data.get("dividend_yield")
        payout = self._raw_data.get("payout_ratio")
        if dy and dy > 4.0:
            max_score += 1
            if payout and payout > 90.0:
                score -= 1
                reasons_fail.append(f"❌ Dividend Trap: High yield ({dy:.1f}%) is unsustainable given {payout:.0f}% payout architecture")
            else:
                score += 1
                reasons_pass.append(f"✅ Safe Yield: Generating strong {dy:.1f}% dividend yield with room to grow")

        check("OPM", "opm", lambda v: v >= 10.0, "Healthy operating margins", "Thin operating margins")
        check("EBITDA Mg", "ebitda_margin", lambda v: v >= 15.0, "Good operating earnings", "Low EBITDA margins")

        # === Growth ===
        check("Sales Gr", "sales_growth", lambda v: v >= 10.0, "Strong revenue growth", "Sluggish growth")
        check("Profit Gr", "profit_growth", lambda v: v >= 10.0, "Earnings expanding rapidly", "Profit growth lagging")
        check("3Y Rev CAGR", "revenue_cagr_3y", lambda v: v >= 10.0, "Consistent 3-year revenue compounding", "Inconsistent long-term revenue", "revenue_cagr_3y")
        check("5Y Rev CAGR", "revenue_cagr_5y", lambda v: v >= 10.0, "Excellent 5-year historical revenue tracking", "Weak 5-year cyclical revenue", "revenue_cagr_5y")
        check("3Y Profit CAGR", "profit_cagr_3y", lambda v: v >= 10.0, "Consistent 3-year profit compounding", "Inconsistent long-term profit", "profit_cagr_3y")
        check("5Y Profit CAGR", "profit_cagr_5y", lambda v: v >= 10.0, "Excellent 5-year historical earnings compounding", "Weak 5-year cyclical earnings", "profit_cagr_5y")
        check("QoQ Op", "qoq_op_profit", lambda v: v > 0, "Sequential operating improvement", "Operating profit declined")

        # === Intrinsic Value & Alternate ===
        # Special check comparing IV to Current Price
        iv = self._raw_data.get("intrinsic_value")
        cp = self._raw_data.get("current_price")
        if iv and cp and cp > 0:
            max_score += 2 # Give higher weight to intrinsic value margin of safety
            if cp < iv * 0.8: # >20% margin of safety
                score += 2
                reasons_pass.append("✅ Intrinsic Value: Trading at >20% discount to DCF value (Safety Margin)")
            elif cp < iv: 
                score += 1
                reasons_pass.append("✅ Intrinsic Value: Trading below DCF intrinsic value")
            else:
                score -= 1 # Not necessarily a double penalty
                reasons_fail.append("❌ Intrinsic Value: Trading above DCF intrinsic value (Overvalued)")

        gn = self._raw_data.get("graham_number")
        if gn and cp:
            max_score += 1
            if cp < gn:
                score += 1
                reasons_pass.append("✅ Graham Number: Price is below classic defensive valuation limit")
            else:
                score -= 1
                reasons_fail.append("❌ Graham Number: Price exceeds defensive valuation threshold")

        # === Growth ===
        check("Sales Gr", "sales_growth", lambda v: v >= 10.0, "Strong revenue growth metrics", "Sluggish top-line growth")
        check("Profit Gr", "profit_growth", lambda v: v >= 10.0, "Earnings are expanding rapidly", "Profit growth is lagging")
        check("3Y Rev CAGR", "revenue_cagr_3y", lambda v: v >= 10.0, "Consistent 3-year revenue compounding", "Inconsistent multi-year revenue trends")
        check("3Y Profit CAGR", "profit_cagr_3y", lambda v: v >= 10.0, "Consistent 3-year profit compounding", "Inconsistent multi-year profit trends")

        # === Ownership & Technicals ===
        check("Promoters", "promoter_holding", lambda v: v >= 40.0, "High insider ownership aligns with shareholder interests", "Low promoter confidence & skin-in-the-game")
        check("Institutions", "institution_holding", lambda v: v >= 10.0, "Strong institutional backing ('Smart Money')", "Low institutional support", "institution_holding")
        
        dma_50 = self._raw_data.get("dma_50")
        dma_200 = self._raw_data.get("dma_200")
        if dma_50 and dma_200:
            max_score += 1
            if dma_50 > dma_200:
                score += 1
                reasons_pass.append("📈 Golden Cross: 50-Day MA is actively crossing above the 200-Day MA macro-trend")
            elif dma_50 < dma_200:
                score -= 1
                reasons_fail.append("📉 Death Cross: 50-Day MA is trapped below the 200-Day MA indicating long-term bear control")

        check("RSI", "rsi", lambda v: 30.0 <= v <= 65.0, "Relative Strength Index shows accumulation/neutrality", "Overbought momentum or deeply oversold (Falling Knife)")
        check("Beta", "beta", lambda v: v < 1.5, "Lower portfolio volatility vs overall market trends", "High beta — susceptible to violent market swings")


        # ── Determine badge ──
        pct = score / max_score if max_score else 0
        if pct >= 0.65:
            badge = "🟢 Strong Buy"
        elif pct >= 0.4:
            badge = "🟡 Accumulate"
        elif pct >= 0.1:
            badge = "⏳ Wait / Watch"
        else:
            badge = "🔴 Avoid"

        # ── Build reason tip ──
        tip_lines = [f"Analysis Score: {score}/{max_score} ({pct*100:.0f}%)"]
        if reasons_pass:
            tip_lines.append("\nSTRENGTHS:")
            tip_lines.extend(reasons_pass)
        if reasons_fail:
            tip_lines.append("\nWEAKNESSES / RISKS:")
            tip_lines.extend(reasons_fail)
        if score == 0 and max_score == 0:
            tip_lines.append("Failed to fetch metric data.")
        
        tip = "\n".join(tip_lines)

        return badge, tip

    def _fetch_screener_fallback(self, symbol: str) -> dict:
        """Hit Screener.in to pull ROE, ROCE, and P/E since yfinance omits them for India."""
        base_sym = symbol.replace('.NS', '').replace('.BO', '')
        url = f"https://www.screener.in/company/{base_sym}/consolidated/"
        fallback = {}
        try:
            import requests
            from bs4 import BeautifulSoup
            
            headers = {'User-Agent': 'Mozilla/5.0'}
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code != 200:
                url = f"https://www.screener.in/company/{base_sym}/"
                r = requests.get(url, headers=headers, timeout=5)
                
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                ratios = soup.find('div', class_='company-ratios')
                if ratios:
                    for item in ratios.find_all('li'):
                        name = item.find('span', class_='name')
                        val = item.find('span', class_='number')
                        if name and val:
                            n = name.text.strip().lower()
                            v = val.text.strip().replace(',', '')
                            try:
                                fallback[n] = float(v)
                            except ValueError:
                                pass
        except Exception as e:
            print(f"Screener fallback failed for {base_sym}: {e}")
            
        return fallback
