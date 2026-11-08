"""
Valuation View - Standalone Stock Analysis & Valuation view.
Allows users to enter a symbol, fetch metrics, compute intrinsic value, and see a buy/sell signal.

All network work (Yahoo Finance, Screener.in) runs in a background thread
through collect_valuation_data(); the Tk thread only formats and shows the
result. Only one analysis runs at a time.

The module-level helpers yf_symbol_candidates(), resolve_ticker(),
fetch_screener_ratios() and dividend_yield_pct() are shared with the
Watchlist view, so both pages find the same Yahoo symbol for what you type.
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

from model.applog import log
from views.base_view import BaseView, _enable_canvas_mousewheel
from ui.ui_theme import ModernStyle
from ui.ui_widgets import RoundedBox, LoadingOverlay, action_button, ModernCard, ModernEntry, ScrollArea
from ui.ui_utils import run_in_background
import pandas as pd


CURRENCY_SYMBOLS = {"INR": "₹", "JPY": "¥", "CNY": "¥", "GBP": "£", "USD": "$", "EUR": "€"}


# ── Shared Yahoo Finance helpers (used by the Watchlist view too) ─────────────

def yf_symbol_candidates(symbol: str) -> list[str]:
    """Yahoo symbols to try for what the user typed, best guess first.

        AAPL      -> AAPL, AAPL.NS, AAPL.BO   (as typed first: US and other listings)
        RELIANCE  -> RELIANCE, RELIANCE.NS, RELIANCE.BO
        7203      -> 7203.T                   (4-digit codes are Tokyo listings)
        TCS.NS, ^N225, USDINR=X -> as typed   (already a full Yahoo symbol)
    """
    s = (symbol or "").strip().upper()
    if not s:
        return []
    if any(ch in s for ch in ".^="):
        return [s]
    if len(s) == 4 and s.isdigit():
        return [s + ".T"]
    return [s, s + ".NS", s + ".BO"]


def _has_price(info) -> bool:
    if not isinstance(info, dict):
        return False
    return any(info.get(k) not in (None, 0, "") for k in ("regularMarketPrice", "currentPrice", "previousClose"))


def resolve_ticker(symbol: str):
    """Return (info, yf_symbol, ticker) for the first candidate Yahoo has prices for.

    Network calls: one .info request per candidate tried. Run in a background thread.
    Raises LookupError with a message for the user when nothing is found.
    """
    import yfinance as yf

    candidates = yf_symbol_candidates(symbol)
    errors = 0
    for cand in candidates:
        try:
            ticker = yf.Ticker(cand)
            info = ticker.info or {}
        except Exception as exc:
            errors += 1
            log.debug("Yahoo lookup of %s failed: %s", cand, exc)
            continue
        if _has_price(info):
            return info, cand, ticker
    if candidates and errors == len(candidates):
        raise LookupError(f"Couldn't reach Yahoo Finance for {symbol}. Check the internet connection and try again.")
    raise LookupError(f"No price data found for {symbol} (tried {', '.join(candidates) or symbol}).")


def currency_symbol(info: dict, yf_symbol: str = "") -> str:
    code = str((info or {}).get("currency") or "").upper()
    if code in CURRENCY_SYMBOLS:
        return CURRENCY_SYMBOLS[code]
    if yf_symbol.upper().endswith(".T"):
        return "¥"
    if yf_symbol.upper().endswith((".NS", ".BO")):
        return "₹"
    return "$"


def dividend_yield_pct(info: dict) -> float | None:
    """Dividend yield in percent (2.5 means 2.5 %).

    yfinance 1.x reports `dividendYield` already in percent (older versions
    used a fraction), so the yield is worked out from the dividend rate and
    the price when possible, and only then taken from the yield fields.
    """
    info = info or {}
    rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate")
    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    try:
        if rate and price and float(price) > 0:
            return float(rate) / float(price) * 100.0
    except (TypeError, ValueError):
        pass
    dy = info.get("dividendYield")
    if dy is not None:
        try:
            return float(dy)
        except (TypeError, ValueError):
            pass
    tdy = info.get("trailingAnnualDividendYield")
    try:
        return float(tdy) * 100.0 if tdy is not None else None
    except (TypeError, ValueError):
        return None


def fetch_screener_ratios(yf_symbol: str) -> dict:
    """ROE, ROCE and P/E from Screener.in for NSE/BSE symbols (yfinance often lacks them).

    Network call; run in a background thread. Returns {} on any failure.
    """
    if not yf_symbol.upper().endswith((".NS", ".BO")):
        return {}
    base_sym = yf_symbol.rsplit(".", 1)[0]
    fallback: dict = {}
    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(f"https://www.screener.in/company/{base_sym}/consolidated/", headers=headers, timeout=5)
        if r.status_code != 200:
            r = requests.get(f"https://www.screener.in/company/{base_sym}/", headers=headers, timeout=5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            ratios = soup.find("ul", id="top-ratios") or soup.find("div", class_="company-ratios")
            if ratios:
                for item in ratios.find_all("li"):
                    name = item.find("span", class_="name")
                    val = item.find("span", class_="number")
                    if name and val:
                        try:
                            fallback[name.text.strip().lower()] = float(val.text.strip().replace(",", ""))
                        except ValueError:
                            pass
    except Exception as exc:
        log.debug("Screener.in lookup for %s failed: %s", base_sym, exc)
    return fallback


def _safe(fn, default=None):
    """Run a yfinance property access, returning `default` when it fails."""
    try:
        return fn()
    except Exception as exc:
        log.debug("yfinance call failed: %s", exc)
        return default


def _cagr(series, periods: int):
    """Compound growth in percent between series[periods] (old) and series[0] (new)."""
    try:
        if len(series) <= periods:
            return None
        new, old = float(series.iloc[0]), float(series.iloc[periods])
        if old > 0 and new > 0:
            return ((new / old) ** (1 / periods) - 1) * 100
    except Exception:
        pass
    return None


def collect_valuation_data(symbol: str) -> dict:
    """Fetch everything the Valuation page shows. BACKGROUND THREAD ONLY.

    Returns a plain dict of raw numbers (no Tk objects). Raises LookupError
    when Yahoo has no data for the symbol.
    """
    info, yf_symbol, ticker = resolve_ticker(symbol)
    log.debug("Valuation: %s resolved to %s (%d info keys)", symbol, yf_symbol, len(info))

    cy = currency_symbol(info, yf_symbol)
    raw: dict = {"yf_symbol": yf_symbol, "currency_symbol": cy,
                 "currency": str(info.get("currency") or "").upper()}

    def extract(key, val):
        raw[key] = val
        return val

    # ── Historical data: 1 year is all the technicals use ─────────────────────
    hist = _safe(lambda: ticker.history(period="1y"), pd.DataFrame())
    rsi_val = sharpe_val = macd_val = supp_res = None
    ma50_hist = ma200_hist = None
    if hist is not None and not hist.empty and len(hist) >= 30:
        close = hist["Close"]
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, float("nan"))
        rsi_last = (100 - (100 / (1 + rs))).iloc[-1]
        if pd.notna(rsi_last):
            rsi_val = float(rsi_last)

        macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        if pd.notna(macd_line.iloc[-1]) and pd.notna(signal_line.iloc[-1]):
            macd_val = float(macd_line.iloc[-1] - signal_line.iloc[-1])

        lo, hi = hist["Low"].tail(60).min(), hist["High"].tail(60).max()
        if pd.notna(lo) and pd.notna(hi):
            supp_res = (float(lo), float(hi))

        returns = close.pct_change().dropna()
        if len(returns) > 20:
            excess = returns - 0.04 / 252
            if excess.std() > 0:
                sharpe_val = float((excess.mean() / excess.std()) * (252 ** 0.5))

        if len(hist) >= 50:
            ma50_hist = float(close.tail(50).mean())
        if len(hist) >= 200:
            ma200_hist = float(close.tail(200).mean())
    log.debug("Valuation %s technicals: RSI=%s MACD=%s Sharpe=%s", yf_symbol, rsi_val, macd_val, sharpe_val)

    scr_data = fetch_screener_ratios(yf_symbol)
    log.debug("Valuation %s: %d Screener.in ratios", yf_symbol, len(scr_data))

    # ── Current price ─────────────────────────────────────────────────────────
    cur_price = 0.0
    last = _safe(lambda: float(ticker.fast_info.last_price))
    if last is not None and not math.isnan(last):
        cur_price = last
    if cur_price <= 0.0:
        cur_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose") or 0.0
    extract("current_price", cur_price)

    extract("company_name", info.get("longName") or info.get("shortName"))

    # ── Valuation multiples ───────────────────────────────────────────────────
    extract("pe_ratio",       info.get("trailingPE") or scr_data.get("stock p/e"))
    extract("forward_pe",     info.get("forwardPE"))
    extract("peg_ratio",      info.get("pegRatio") or info.get("trailingPegRatio"))
    extract("pb_ratio",       info.get("priceToBook"))
    extract("price_to_sales", info.get("priceToSalesTrailing12Months"))
    extract("beta",           info.get("beta"))
    extract("market_cap",     info.get("marketCap"))
    extract("enterprise_value", info.get("enterpriseValue"))
    extract("analyst_target", info.get("targetMeanPrice"))
    extract("dividend_yield", dividend_yield_pct(info))
    payout = info.get("payoutRatio")
    extract("payout_ratio",   payout * 100 if payout is not None else None)

    # ── Profitability ─────────────────────────────────────────────────────────
    eps_raw = info.get("trailingEps")
    from model.engine import is_placeholder_eps
    if is_placeholder_eps(eps_raw, raw.get("pe_ratio"), cur_price):
        eps_raw = None              # EPS 1.00 with P/E = price: earnings unknown
        extract("pe_ratio", None)
    extract("eps", eps_raw)
    roe = info.get("returnOnEquity")
    extract("roe", roe * 100 if roe is not None else scr_data.get("roe"))
    roa = info.get("returnOnAssets")
    extract("roa", roa * 100 if roa is not None else None)

    # Annual income statement: fetched ONCE, used for ROCE and the CAGRs
    fin = _safe(lambda: ticker.financials, pd.DataFrame())
    if fin is None:
        fin = pd.DataFrame()

    def _row(df, *labels):
        for lbl in labels:
            if lbl in df.index:
                v = df.loc[lbl].dropna()
                return float(v.iloc[0]) if len(v) else None
        return None

    # ROCE = EBIT / (Total Assets - Current Liabilities)
    roce_val = scr_data.get("roce")
    if roce_val is None and not fin.empty:
        bs = _safe(lambda: ticker.balance_sheet, pd.DataFrame())
        if bs is not None and not bs.empty:
            total_assets = _row(bs, "Total Assets", "TotalAssets")
            curr_liab = _row(bs, "Current Liabilities", "CurrentLiabilities",
                             "Total Current Liabilities", "TotalCurrentLiabilities")
            ebit = _row(fin, "EBIT", "Operating Income", "OperatingIncome")
            if total_assets and curr_liab and ebit and total_assets - curr_liab > 0:
                roce_val = ebit / (total_assets - curr_liab) * 100
    extract("roce", roce_val)

    for key, field in (("opm", "operatingMargins"), ("ebitda_margin", "ebitdaMargins"),
                       ("net_profit_margin", "profitMargins")):
        v = info.get(field)
        extract(key, v * 100 if v is not None else None)
    extract("free_cash_flow", info.get("freeCashflow"))

    # ── Health ────────────────────────────────────────────────────────────────
    debt_eq = info.get("debtToEquity")
    extract("debt_to_equity", debt_eq / 100 if debt_eq is not None else None)
    extract("book_value",     info.get("bookValue"))
    extract("current_ratio",  info.get("currentRatio"))
    extract("quick_ratio",    info.get("quickRatio"))

    # ── Growth ────────────────────────────────────────────────────────────────
    rev_gr = info.get("revenueGrowth")
    extract("sales_growth",  rev_gr * 100 if rev_gr is not None else None)
    ern_gr = info.get("earningsGrowth")
    extract("profit_growth", ern_gr * 100 if ern_gr is not None else None)
    if not fin.empty:
        if "Total Revenue" in fin.index:
            revs = fin.loc["Total Revenue"].dropna()
            extract("revenue_cagr_3y", _cagr(revs, 3))
            extract("revenue_cagr_5y", _cagr(revs, 5))
        if "Net Income" in fin.index:
            incomes = fin.loc["Net Income"].dropna()
            extract("profit_cagr_3y", _cagr(incomes, 3))
            extract("profit_cagr_5y", _cagr(incomes, 5))

    # ── Ownership ─────────────────────────────────────────────────────────────
    insiders = info.get("heldPercentInsiders")
    extract("promoter_holding",    insiders * 100 if insiders is not None else None)
    inst = info.get("heldPercentInstitutions")
    extract("institution_holding", inst * 100 if inst is not None else None)
    extract("institution_count", None)
    holders = _safe(lambda: ticker.major_holders)
    try:
        if holders is not None and not holders.empty:
            if "Value" in holders.columns and "institutionsCount" in holders.index:
                extract("institution_count", int(holders.loc["institutionsCount", "Value"]))
            elif 1 in holders.columns:
                count_row = holders[holders[1].str.contains("Number of Institutions", na=False)]
                if not count_row.empty:
                    extract("institution_count", int(count_row[0].values[0]))
    except Exception:
        pass
    extract("short_ratio", info.get("shortRatio"))

    # ── Technical ─────────────────────────────────────────────────────────────
    extract("dma_50",  info.get("fiftyDayAverage") or ma50_hist)
    extract("dma_200", info.get("twoHundredDayAverage") or ma200_hist)
    extract("rsi", rsi_val)
    extract("macd", macd_val)
    extract("support_resistance", supp_res)
    extract("sharpe_ratio", sharpe_val)
    extract("volume", info.get("volume") or info.get("averageVolume"))
    extract("h52", info.get("fiftyTwoWeekHigh"))
    extract("l52", info.get("fiftyTwoWeekLow"))

    # ── Fair value and decision from the shared rules (model/valuation.py) ────
    # The same rules and company figures as Holdings, Watchlist and the Dashboard.
    # Indian and Tokyo listings are saved for those pages too.
    try:
        from model import fundamentals
        from model.valuation import canonical, decide, load_assumptions
        from datetime import datetime as _dt
        now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        inputs = fundamentals.extract_inputs(yf_symbol, info, ticker, fin=fin, now=now)
        state = {}
        if yf_symbol.upper().endswith((".NS", ".BO", ".T")):
            fundamentals.save_inputs(yf_symbol, dict(inputs, price=cur_price or None, price_at=now))
            rec = fundamentals.load_records([yf_symbol]).get(canonical(yf_symbol)) or {}
            inputs, state = rec.get("inputs") or inputs, rec.get("state") or {}
        decision = decide(inputs, cur_price, load_assumptions(), state, now)
        raw["decision"] = decision
        if decision.fair_value:
            extract("intrinsic_value", decision.fair_value)
    except Exception:
        log.warning("Valuing %s failed", yf_symbol, exc_info=True)
    bvps = info.get("bookValue")
    if eps_raw and bvps and eps_raw > 0 and bvps > 0:
        extract("graham_number", math.sqrt(22.5 * eps_raw * bvps))

    # ── Latest quarter operating profit ───────────────────────────────────────
    qf = _safe(lambda: ticker.quarterly_financials, pd.DataFrame())
    if qf is not None and not qf.empty:
        for lbl in ("Operating Income", "EBIT", "OperatingIncome"):
            if lbl in qf.index:
                op_profit = qf.loc[lbl].iloc[0]
                if pd.notna(op_profit):
                    extract("qoq_op_profit", float(op_profit))
                break

    log.debug("Valuation %s: %d values collected", yf_symbol, len(raw))
    return raw


class ValuationView(BaseView):
    """View to analyze a single stock's valuation metrics."""

    def build(self):
        self.add_gradient_header(
            self,
            "🔬 Valuation Analysis",
            "Type a symbol (AAPL, RELIANCE or 7203 for Tokyo) and press Enter or Analyze."
        )

        self.main_scroll_frame = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        self.main_scroll_frame.pack(fill="both", expand=True)

        # A ScrollArea, not a canvas window: Tk lays a canvas window out again on every
        # visit to the page (about 0.08 s here)
        scrollbar = ttk.Scrollbar(self.main_scroll_frame, orient="vertical")
        canvas = ScrollArea(self.main_scroll_frame, ModernStyle.BG_PRIMARY, scrollbar=scrollbar, unit=30)
        self.scrollable_inner = canvas.inner
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        _enable_canvas_mousewheel(canvas)
        
        # ── Loading Overlay ───────────────────────────────────────────────────
        self.loading_overlay = LoadingOverlay(self.main_scroll_frame)


        # ── Input Row ─────────────────────────────────────────────────────────
        input_card = ModernCard(
            self.scrollable_inner,
            bg=ModernStyle.BG_SECONDARY,
            highlight_color=ModernStyle.BG_SECONDARY, shadow=True,
            highlight_thickness=1,
            radius=ModernStyle.RADIUS_CARD,
            canvas_bg=ModernStyle.BG_PRIMARY
        )
        input_card.pack(fill="x", padx=20, pady=(10, 6))
        input_inner = tk.Frame(input_card.content, bg=ModernStyle.BG_SECONDARY)
        input_inner.pack(fill="x", padx=16, pady=10)

        tk.Label(
            input_inner, text="Stock Symbol:",
            fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_FIELD_LABEL,
        ).pack(side="left", padx=(0, 10))

        self._v_symbol = tk.StringVar()
        sym_box = RoundedBox(input_inner)
        self._e_symbol = ModernEntry(
            sym_box, textvariable=self._v_symbol, width=15,
            bg=ModernStyle.ENTRY_BG, fg=ModernStyle.ACCENT_PRIMARY,
            font=ModernStyle.FONT_INPUT,
            relief=tk.FLAT,
            highlightthickness=0,
            insertbackground=ModernStyle.ACCENT_PRIMARY,
        )
        self._e_symbol.pack(ipady=5, padx=8)
        sym_box.watch(self._e_symbol)
        sym_box.pack(side="left", padx=(0, 15))

        # Enter starts an analysis too (ignored while one is running)
        self._fetching = False
        self._fetch_gen = 0
        self._e_symbol.bind("<Return>", lambda _e: self._fetch_data())

        self._btn_fetch = action_button(input_inner, "▶ Analyze", self._fetch_data, width=140,
                                        canvas_bg=ModernStyle.BG_SECONDARY)
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
            highlight_color=ModernStyle.BG_SECONDARY, shadow=True,
            highlight_thickness=1,
            radius=ModernStyle.RADIUS_CARD,
            canvas_bg=ModernStyle.BG_PRIMARY
        )
        self.summary_card.pack(fill="x", padx=20, pady=10)
        self.summary_card.pack_forget() # Hide initially

        tk.Frame(self.summary_card.content, bg=ModernStyle.ACCENT_SECONDARY, height=ModernStyle.ACCENT_BAR).pack(fill="x")
        
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
        
        tk.Label(prices_frame, text="Current Price:", font=ModernStyle.FONT_FIELD_LABEL, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_SECONDARY).grid(row=0, column=0, sticky="w", pady=2)
        self.lbl_current_price = tk.Label(prices_frame, text="---", font=ModernStyle.FONT_HEADING, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY)
        self.lbl_current_price.grid(row=0, column=1, sticky="w", padx=10, pady=2)

        tk.Label(prices_frame, text="Fair Value:", font=ModernStyle.FONT_FIELD_LABEL, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_SECONDARY).grid(row=1, column=0, sticky="w", pady=2)
        self.lbl_intrinsic_value = tk.Label(prices_frame, text="---", font=ModernStyle.FONT_HEADING, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY)
        self.lbl_intrinsic_value.grid(row=1, column=1, sticky="w", padx=10, pady=2)
        
        self.lbl_margin_safety = tk.Label(prices_frame, text="", font=ModernStyle.FONT_BODY_BOLD, bg=ModernStyle.BG_SECONDARY)
        self.lbl_margin_safety.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # Visual Gauge Bar
        self.gauge_frame = tk.Frame(prices_frame, bg=ModernStyle.BG_SECONDARY)
        self.gauge_frame.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        # Centred gauge: the middle line is "price = fair value"; green grows right with the
        # upside, red grows left when the price is above fair value (both ends = ±100%)
        self.gauge_canvas = tk.Canvas(self.gauge_frame, bg=ModernStyle.BG_TERTIARY, height=12, width=220, highlightthickness=0)
        self.gauge_canvas.pack(anchor="w")
        self.gauge_rect = self.gauge_canvas.create_rectangle(0, 0, 0, 12, fill=ModernStyle.SUCCESS, outline="")
        self.gauge_canvas.create_line(110, 0, 110, 12, fill=ModernStyle.TEXT_SECONDARY, width=2)

        # Buy below / Target / Reduce above / Confidence, from the shared rules
        self._decision_labels = {}
        for i, (key, text) in enumerate((("buy_below", "Buy below:"), ("target", "Target (2–3 yrs):"),
                                         ("reduce_above", "Reduce above:"), ("confidence", "Confidence:")), start=4):
            tk.Label(prices_frame, text=text, font=ModernStyle.FONT_FIELD_LABEL, bg=ModernStyle.BG_SECONDARY,
                     fg=ModernStyle.TEXT_SECONDARY).grid(row=i, column=0, sticky="w", pady=(6 if i == 4 else 2, 2))
            lbl = tk.Label(prices_frame, text="---", font=ModernStyle.FONT_BODY_BOLD, bg=ModernStyle.BG_SECONDARY,
                           fg=ModernStyle.TEXT_PRIMARY)
            lbl.grid(row=i, column=1, sticky="w", padx=10, pady=(6 if i == 4 else 2, 2))
            self._decision_labels[key] = lbl

        # Right side: Rationale text
        right_summary = tk.Frame(summary_inner, bg=ModernStyle.BG_SECONDARY)
        right_summary.pack(side="left", fill="both", expand=True)
        
        tk.Label(right_summary, text="Decision Rationale", font=ModernStyle.FONT_CARD_TITLE, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY).pack(anchor="w", pady=(0, 4))
        
        self.txt_rationale = tk.Text(
            right_summary, height=18, bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY,
            font=ModernStyle.FONT_BODY, relief=tk.FLAT, highlightthickness=0,
            wrap=tk.WORD, padx=12, pady=10, cursor="arrow",
        )
        self.txt_rationale.tag_configure("head", font=ModernStyle.FONT_BODY_BOLD, foreground=ModernStyle.TEXT_PRIMARY,
                                         spacing1=6, spacing3=2)
        self.txt_rationale.tag_configure("pass", foreground=ModernStyle.SUCCESS)
        self.txt_rationale.tag_configure("fail", foreground=ModernStyle.ERROR)
        self.txt_rationale.tag_configure("body", foreground=ModernStyle.TEXT_PRIMARY)
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
                ("Latest Qtr Op.",   "qoq_op_profit"),
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
                ("Fair Value",       "intrinsic_value_display"),
            ],
        }
        
        # Create a grid layout for cards
        row_idx = 0
        col_idx = 0
        
        for cat_name, items in categories.items():
            card = ModernCard(
                self.metrics_frame, bg=ModernStyle.BG_SECONDARY,
                highlight_color=ModernStyle.BG_SECONDARY, shadow=True, highlight_thickness=1,
                radius=ModernStyle.RADIUS_CARD, canvas_bg=ModernStyle.BG_PRIMARY
            )
            card.grid(row=row_idx, column=col_idx, sticky="nsew", padx=8, pady=8)
            self.metrics_frame.grid_columnconfigure(col_idx, weight=1)
            
            # Category Header
            tk.Label(
                card.content, text=cat_name.upper(),
                font=ModernStyle.FONT_SMALL,
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
        """Start one analysis. Ignored while another one is still running
        (the Return key used to bypass the disabled Analyze button)."""
        if self._fetching:
            return
        symbol = self._v_symbol.get().strip().upper()
        if not symbol:
            self._flash_status("⚠ Enter a symbol to analyze.", error=True)
            return

        self._fetching = True
        self._fetch_gen += 1
        gen = self._fetch_gen

        # The button stays readable while busy; clicks are ignored via _fetching
        self._btn_fetch.set_text("⏳ Analyzing…")
        self._flash_status(f"Fetching data for {symbol}…")
        self.loading_overlay.show()
        self.loading_overlay.set_text(f"Fetching data for {symbol}…")

        # Reset UI
        self.summary_card.pack_forget()
        self.metrics_frame.pack_forget()
        self._raw_data = {}
        for var in self._metrics_vars.values():
            var.set("---")
        for lbl in self._metric_labels.values():
            lbl.config(fg=ModernStyle.TEXT_PRIMARY)

        run_in_background(
            lambda: collect_valuation_data(symbol),
            on_done=lambda raw: self._on_fetch_done(gen, raw),
            on_error=lambda err: self._on_fetch_failed(gen, symbol, err),
            widget=self, name="valuation-fetch",
        )

    def _end_fetch(self):
        self._fetching = False
        self.loading_overlay.hide()
        self._btn_fetch.set_text("▶ Analyze")

    def _on_fetch_done(self, gen: int, raw: dict):
        if gen != self._fetch_gen:
            return  # an older request; a newer one owns the page
        self._end_fetch()
        self._raw_data = raw
        self._process_and_display()

    def _on_fetch_failed(self, gen: int, symbol: str, err: Exception):
        if gen != self._fetch_gen:
            return
        self._end_fetch()
        msg = str(err) if isinstance(err, LookupError) else f"Couldn't analyse {symbol}: {err}"
        self._flash_status(f"⚠ {msg}", error=True)

    def _process_and_display(self):
        """Format the raw data into UI elements and run the logic engine."""
        yf_sym = self._raw_data.get("yf_symbol") or ""
        self._flash_status(f"✓ Analysis complete for {yf_sym}." if yf_sym else "✓ Analysis complete.")

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

        # Summary Header: the decision from the shared rules
        cur_price = self._raw_data.get("current_price")
        iv_val = self._raw_data.get("intrinsic_value")
        decision = self._raw_data.get("decision")
        fmt = lambda v: f"{cy}{v:,.2f}" if v else "---"
        for key, lbl in self._decision_labels.items():
            if decision is None:
                lbl.config(text="---")
            elif key == "confidence":
                lbl.config(text=decision.confidence if decision.fair_value else "---")
            else:
                lbl.config(text=fmt(getattr(decision, key)))

        self.lbl_current_price.config(text=f"{cy}{cur_price:,.2f}" if cur_price else "---")
        self.lbl_intrinsic_value.config(text=f"{cy}{iv_val:,.2f}" if iv_val else "---")

        if cur_price and iv_val and iv_val > 0:
            # Upside to fair value = fair value ÷ price − 1: the same figure as the
            # Watchlist and Dashboard. It can't go below −100%.
            upside = (iv_val / cur_price - 1.0) * 100.0
            half = 110   # the gauge is 220 wide; its middle is "price = fair value"
            reach = min(abs(upside), 100.0) / 100.0 * half
            if upside >= 0:
                self.lbl_margin_safety.config(text=f"Upside to fair value: {upside:+.1f}%", fg=ModernStyle.SUCCESS)
                self.gauge_canvas.itemconfig(self.gauge_rect, fill=ModernStyle.SUCCESS)
                self.gauge_canvas.coords(self.gauge_rect, half, 0, half + reach, 12)
            else:
                self.lbl_margin_safety.config(text=f"Upside to fair value: {upside:+.1f}% (price above fair value)",
                                              fg=ModernStyle.ERROR)
                self.gauge_canvas.itemconfig(self.gauge_rect, fill=ModernStyle.ERROR)
                self.gauge_canvas.coords(self.gauge_rect, half - reach, 0, half, 12)
            self.gauge_frame.grid()
        else:
            eps = self._raw_data.get("eps")
            no_fv = "No fair value: EPS is zero or negative" if eps is not None and eps <= 0 else \
                "No fair value" if decision is not None else ""
            self.lbl_margin_safety.config(text=no_fv, fg=ModernStyle.TEXT_SECONDARY)
            self.gauge_frame.grid_remove()


        # 2. The signal: the shared rules decide; the old checklist is information only
        scorecard = self._quality_scorecard()
        if decision is not None:
            badge = decision.label
            badge_fg = {"BUY": ModernStyle.SUCCESS, "REDUCE": ModernStyle.ERROR, "SELL": ModernStyle.ERROR,
                        "HOLD": ModernStyle.WARNING}.get(decision.zone, ModernStyle.TEXT_SECONDARY)
            explained = decision.text().split("\n", 1)[1:]      # its first line repeats the badge
            tip = "\n".join([f"Confidence: {decision.confidence}"] + explained + ["", scorecard])
        else:
            badge, badge_fg = "⚪ No signal", ModernStyle.TEXT_SECONDARY
            tip = "The fair value couldn't be worked out for this symbol.\n\n" + scorecard
        self.lbl_signal_badge.config(text=badge, fg=badge_fg)

        self.txt_rationale.configure(state="normal")
        self.txt_rationale.delete(1.0, tk.END)
        for line in tip.split("\n"):
            if not line.strip():
                continue
            if line.startswith(("✅", "🛡", "📈")):
                tag = "pass"
            elif line.startswith(("❌", "🚨", "📉")):
                tag = "fail"
            elif line.startswith(("•", "·")):
                tag = "body"
            else:
                tag = "head"
            self.txt_rationale.insert(tk.END, line + "\n", tag)
        self.txt_rationale.configure(state="disabled")

        # Show panels
        self.summary_card.pack(fill="x", padx=20, pady=10)
        self.metrics_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))


    def _quality_scorecard(self) -> str:
        """The old checklist (P/E, ROE, margins, growth, RSI…) as information only; the
        signal comes from the shared rules (model/valuation.py). Colours the metric values."""
        score = 0
        max_score = 0
        reasons_pass = []
        reasons_fail = []

        def check(label, key, condition_fn, tip_pass, tip_fail, ui_key=None):
            nonlocal score, max_score
            v = self._raw_data.get(key)
            if v is None:
                return  # No data: neither scored nor counted
            max_score += 1
            
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
        fcf = self._raw_data.get("free_cash_flow")
        debt_eq = self._raw_data.get("debt_to_equity")
        npm = self._raw_data.get("net_profit_margin")
        
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
        check("Latest Qtr Op", "qoq_op_profit", lambda v: v > 0,
              "Latest quarter's operating profit is positive", "Latest quarter had an operating loss")

        # === Graham number (the fair value itself is in the decision above) ===
        cp = self._raw_data.get("current_price")

        gn = self._raw_data.get("graham_number")
        if gn and cp:
            max_score += 1
            if cp < gn:
                score += 1
                reasons_pass.append("✅ Graham Number: Price is below classic defensive valuation limit")
            else:
                score -= 1
                reasons_fail.append("❌ Graham Number: Price exceeds defensive valuation threshold")

        # === Ownership & Technicals ===
        check("Promoters", "promoter_holding", lambda v: v >= 40.0, "High insider ownership aligns with shareholder interests", "Low promoter confidence & skin-in-the-game")
        check("Institutions", "institution_holding", lambda v: v >= 10.0, "Strong institutional backing ('Smart Money')", "Low institutional support", "institution_holding")
        
        dma_50 = self._raw_data.get("dma_50")
        dma_200 = self._raw_data.get("dma_200")
        if dma_50 and dma_200:
            max_score += 1
            if dma_50 > dma_200:
                score += 1
                reasons_pass.append("📈 Uptrend: the 50-day average is above the 200-day average")
            elif dma_50 < dma_200:
                score -= 1
                reasons_fail.append("📉 Downtrend: the 50-day average is below the 200-day average")

        check("RSI", "rsi", lambda v: 30.0 <= v <= 65.0, "Relative Strength Index shows accumulation/neutrality", "Overbought momentum or deeply oversold (Falling Knife)")
        check("Beta", "beta", lambda v: v < 1.5, "Lower portfolio volatility vs overall market trends", "High beta — susceptible to violent market swings")


        # ── The scorecard text (information only: it doesn't decide the signal) ──
        if max_score == 0:
            return "QUALITY SCORECARD: no ratios from Yahoo Finance for this symbol."
        tip_lines = [f"QUALITY SCORECARD (information only, it doesn't decide the signal): {score}/{max_score}"]
        if reasons_pass:
            tip_lines.append("STRENGTHS:")
            tip_lines.extend(reasons_pass)
        if reasons_fail:
            tip_lines.append("WEAKNESSES / RISKS:")
            tip_lines.extend(reasons_fail)
        return "\n".join(tip_lines)
