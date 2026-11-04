"""
Watchlist View — single-screen CRUD for tracked symbols.

Layout (top → bottom):
  • Gradient header with the "Refresh All" button
  • Inline Add / Edit form (symbol, notes, tags, your target price + Save / Clear /
    Edit Metrics / Delete)
  • Signal filter pills (All / Strong Buy / Accumulate / Wait / Watch / Avoid / No Data)
  • Treeview table showing all watchlist entries
  Clicking a row fills the form for editing; double-clicking opens the full analysis.

Saving never loses data: a form save sends only the fields you changed, and
Refresh All sends only the values Yahoo actually returned (see
model/watchlist_db.py). All network work (Yahoo Finance, Screener.in) runs in
background threads through run_in_background().
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from ui import dialogs

import pandas as pd

from model.applog import log
from views.base_view import BaseView
from ui.ui_theme import ModernStyle
from ui.ui_widgets import (EmptyState, RoundedBox, ModernButton, ModernEntry, ModernCard, PremiumModal, ScrollArea,
                           action_button, header_button, secondary_button)
from ui.ui_utils import (add_treeview_copy_menu, format_date, treeview_sort_column, run_in_background,
                         call_on_ui, color_gain_loss, color_signals, show_toast, ToolTip, HeadingTips)


# ── Signals ───────────────────────────────────────────────────────────────────
# One table for the badge text, the filter pills and the colours, so they
# always match.
SIGNAL_ORDER = ["strong_buy", "accumulate", "wait", "avoid", "nodata"]
SIGNAL_TEXT = {
    "strong_buy": ("🟢", "Strong Buy"),
    "accumulate": ("🌲", "Accumulate"),
    "wait":       ("🔸", "Wait / Watch"),
    "avoid":      ("🔻", "Avoid"),
    "nodata":     ("⚪", "No Data"),
}


def signal_badge(key: str) -> str:
    emoji, label = SIGNAL_TEXT[key]
    return f"{emoji}  {label}"


def signal_colours(key: str) -> tuple[str, str, str]:
    """(text colour, soft tint, solid fill) for a signal key or "all"."""
    S = ModernStyle
    return {
        "all":        (S.TEXT_ACCENT, S.ACCENT_PRIMARY_PALE, S.ACCENT_PRIMARY),
        "strong_buy": (S.SUCCESS, S.SUCCESS_PALE, S.SUCCESS_FILL),
        "accumulate": (S.INFO, S.INFO_PALE, S.INFO_FILL),
        "wait":       (S.WARNING, S.WARNING_PALE, S.WARNING_FILL),
        "avoid":      (S.ERROR, S.ERROR_PALE, S.ERROR_FILL),
        "nodata":     (S.TEXT_SECONDARY, S.BG_TERTIARY, S.NEUTRAL_FILL),
    }[key]


# ── Number helpers ────────────────────────────────────────────────────────────

def parse_num(val) -> float | None:
    """'₹1,234.5' / '12.3%' / '₹1,234 Cr' / '$1.2B' / 3.4 → float, or None."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return None if (isinstance(val, float) and math.isnan(val)) else float(val)
    s = str(val).strip()
    if s in ("", "None", "—", "-", "nan", "N/A", "n/a"):
        return None
    for ch in ",%₹¥$£€▲▼+":
        s = s.replace(ch, "")
    s = s.strip()
    mult = 1.0
    if s.lower().endswith("cr"):
        mult, s = 1e7, s[:-2]
    elif s[-1:] in ("T", "B", "M", "K"):
        mult, s = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}[s[-1]], s[:-1]
    try:
        return float(s.strip()) * mult
    except ValueError:
        return None


def graham_number(row: dict) -> float | None:
    """√(22.5 × EPS × book value per share), or None when either is missing/negative."""
    eps, bv = parse_num(row.get("eps")), parse_num(row.get("book_value"))
    if eps and bv and eps > 0 and bv > 0:
        return math.sqrt(22.5 * eps * bv)
    return None


def _week52(row: dict) -> tuple[float, float] | None:
    text = str(row.get("week52_range") or "")
    if "–" not in text:
        return None
    lo, _, hi = text.partition("–")
    lo_f, hi_f = parse_num(lo), parse_num(hi)
    if lo_f is None or hi_f is None:
        return None
    return lo_f, hi_f


def compute_signal(row: dict) -> tuple[str, str, str]:
    """Score a watchlist row. Returns (signal key, badge text, reason text).

    Only metrics that are present are scored and counted, so a stock with
    patchy data is judged on what is known instead of drifting to "Avoid".
    Pure function: safe to call from a background thread.
    """
    from model.engine import is_placeholder_eps
    if is_placeholder_eps(row.get("eps"), row.get("pe_ratio"), row.get("current_value")):
        # EPS 1.00 with P/E = price is missing data: don't score P/E, fair value or Graham on it
        row = {k: v for k, v in row.items() if k not in ("eps", "pe_ratio", "intrinsic_value")}
    score = 0
    max_score = 0
    reasons_pass: list[str] = []
    reasons_fail: list[str] = []

    def check(label, key, condition_fn, tip_pass, tip_fail):
        nonlocal score, max_score
        v = parse_num(row.get(key))
        if v is None:
            return  # no data: neither scored nor counted
        max_score += 1
        if condition_fn(v):
            score += 1
            reasons_pass.append(f"✅ {label}: {tip_pass}")
        else:
            score -= 1
            reasons_fail.append(f"❌ {label}: {tip_fail}")

    # === Valuation ===
    check("P/E", "pe_ratio", lambda v: 0 < v < 30, "Reasonable valuation", "Overvalued or negative earnings")
    check("PEG Ratio", "peg_ratio", lambda v: v < 2.0, "Growth at fair price", "Expensive relative to growth")
    check("P/B Ratio", "pb_ratio", lambda v: v < 3.0, "Reasonable price-to-book", "High price vs book value")
    check("Debt/Equity", "debt_to_equity", lambda v: v < 1.0, "Low financial leverage", "High debt is risky")
    check("Current Ratio", "current_ratio", lambda v: v >= 1.5,
          "Healthy short-term liquidity", "May struggle to meet short-term obligations")

    # === Profitability ===
    check("ROE", "roe", lambda v: v >= 12.0, "Strong return on equity", "Weak returns for shareholders")
    check("ROCE", "roce", lambda v: v >= 12.0, "Efficient capital allocation", "Capital not being used efficiently")
    check("OPM", "opm", lambda v: v >= 10.0, "Healthy operating margins", "Thin operating margins")
    check("Net Profit Margin", "net_profit_margin", lambda v: v >= 8.0, "Solid profitability", "Low net margins")
    check("Free Cash Flow", "free_cash_flow", lambda v: v > 0,
          "Positive FCF — company self-funds growth", "Negative FCF — cash burn risk")
    check("EBITDA Margin", "ebitda_margin", lambda v: v >= 15.0,
          "Good earnings before interest and taxes", "Low EBITDA margins")

    # === Growth ===
    check("Sales Gr", "sales_growth", lambda v: v >= 10.0, "Strong revenue growth", "Sluggish growth")
    check("Profit Gr", "profit_growth", lambda v: v >= 10.0, "Earnings expanding rapidly", "Profit growth lagging")
    check("3Y Rev CAGR", "revenue_cagr_3y", lambda v: v >= 10.0,
          "Consistent 3-year revenue compounding", "Inconsistent long-term revenue")
    check("3Y Profit CAGR", "profit_cagr_3y", lambda v: v >= 10.0,
          "Consistent 3-year profit compounding", "Inconsistent long-term profit")
    check("QoQ Op", "qoq_op_profit", lambda v: v > 0, "Sequential operating improvement", "Operating profit declined")

    # === Intrinsic value, Graham number, analyst target, 52-week range ===
    cp = parse_num(row.get("current_value"))
    iv = parse_num(row.get("intrinsic_value"))
    if cp and iv and cp > 0 and iv > 0:
        max_score += 2  # margin of safety counts double
        if cp < iv * 0.8:
            score += 2
            reasons_pass.append("✅ Intrinsic Value: Trading at >20% discount to DCF value (Safety Margin)")
        elif cp < iv:
            score += 1
            reasons_pass.append("✅ Intrinsic Value: Trading below DCF intrinsic value")
        else:
            score -= 1
            reasons_fail.append("❌ Intrinsic Value: Trading above DCF intrinsic value (Overvalued)")

    gn = graham_number(row)
    if gn and cp:
        max_score += 1
        if cp < gn:
            score += 1
            reasons_pass.append("✅ Graham Number: Price is below classic defensive valuation limit")
        else:
            score -= 1
            reasons_fail.append("❌ Graham Number: Price exceeds defensive valuation threshold")

    check("Dividend", "dividend_yield", lambda v: v >= 1.2, "Healthy dividend payout", "Low or no dividend yield")

    at = parse_num(row.get("analyst_target"))
    if cp and at:
        max_score += 1
        if cp < at * 0.9:
            score += 1
            reasons_pass.append("✅ Analyst Target: Price is >10% below average analyst target")
        elif cp > at * 1.1:
            score -= 1
            reasons_fail.append("❌ Analyst Target: Price exceeds analyst target by >10%")

    rng = _week52(row)
    if rng and cp and rng[0] < rng[1]:
        max_score += 1
        pos_pct = (cp - rng[0]) / (rng[1] - rng[0])
        if pos_pct < 0.25:
            score += 1
            reasons_pass.append("✅ 52W Range: Trading near 52-week lows (Potential value)")
        elif pos_pct > 0.85:
            score -= 1
            reasons_fail.append("❌ 52W Range: Trading near 52-week highs (Potential resistance zone)")

    # === Ownership & technical ===
    check("Promoters", "promoter_holding", lambda v: v >= 40.0, "Promoters have skin in the game", "Low promoter confidence")
    check("RSI", "rsi", lambda v: 30.0 <= v <= 65.0, "Good entry zone", "Overbought or deeply oversold")
    check("Beta", "beta", lambda v: v < 1.5, "Lower volatility vs market", "High beta — volatile stock")
    check("MACD", "macd", lambda v: v > 0, "Short-term momentum is bullish", "Short-term momentum is bearish")

    # ── Badge ──
    pct = score / max_score if max_score else 0
    if max_score == 0:
        key = "nodata"
    elif pct >= 0.65:
        key = "strong_buy"
    elif pct >= 0.4:
        key = "accumulate"
    elif pct >= 0.1:
        key = "wait"
    else:
        key = "avoid"
    badge = signal_badge(key)

    tip_lines = [f"Signal: {badge}  (Score: {score}/{max_score})"]
    if reasons_pass:
        tip_lines.append("\nStrengths:")
        tip_lines.extend(reasons_pass)
    if reasons_fail:
        tip_lines.append("\nWeaknesses:")
        tip_lines.extend(reasons_fail)
    if max_score == 0:
        tip_lines.append("No metrics fetched yet. Use Edit Metrics → Auto-Fill, or Refresh All, to fetch them.")
    return key, badge, "\n".join(tip_lines)


# ── Fetching metrics from Yahoo Finance (BACKGROUND THREAD ONLY) ──────────────

def _fmt_big(value: float, cy: str) -> str:
    """Large money amounts: ₹1,234.5 Cr for rupees, $1.2B / ¥3.4T otherwise."""
    v = float(value)
    if cy == "₹":
        return f"{cy}{v / 1e7:,.1f} Cr" if abs(v) >= 1e7 else f"{cy}{v:,.0f}"
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= div:
            return f"{cy}{v / div:,.2f}{suffix}"
    return f"{cy}{v:,.0f}"


def _price(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}"


def fetch_watchlist_metrics(symbol: str, columns: set[str]) -> tuple[str, dict[str, str]]:
    """Fetch and format every watchlist metric Yahoo has for `symbol`.

    Returns (yahoo symbol used, {column: text}). Only values that were really
    found are included, and only for columns this database has, so nothing
    gets blanked and nothing is computed only to be thrown away.
    Raises LookupError when Yahoo has no data for the symbol.
    """
    from views.valuation_view import (resolve_ticker, currency_symbol, dividend_yield_pct,
                                      fetch_screener_ratios)

    info, yf_symbol, ticker = resolve_ticker(symbol)
    cy = currency_symbol(info, yf_symbol)
    out: dict[str, str] = {}

    def put(key, val, fmt="{}"):
        if key not in columns or val is None:
            return
        try:
            if isinstance(val, float) and math.isnan(val):
                return
            text = fmt.format(val)
        except (TypeError, ValueError):
            return
        if text.strip() and text.lower() != "nan":
            out[key] = text

    def put_big(key, val):
        if val is not None and key in columns:
            try:
                out[key] = _fmt_big(val, cy)
            except (TypeError, ValueError):
                pass

    def pct(field):
        v = info.get(field)
        return v * 100 if isinstance(v, (int, float)) else None

    def safe(fn):
        try:
            return fn()
        except Exception as exc:
            log.debug("yfinance call for %s failed: %s", yf_symbol, exc)
            return None

    scr = fetch_screener_ratios(yf_symbol)

    put("stock_name", info.get("longName") or info.get("shortName"))
    put("sector", info.get("sector"))
    put("industry", info.get("industry"))
    cur_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    put("current_value", cur_price, f"{cy}{{:,.2f}}")

    put("pe_ratio", info.get("trailingPE") or scr.get("stock p/e"), "{:.1f}")
    put("peg_ratio", info.get("pegRatio") or info.get("trailingPegRatio"), "{:.2f}")
    put("pb_ratio", info.get("priceToBook"), "{:.2f}")
    eps = info.get("trailingEps")
    from model.engine import is_placeholder_eps
    if is_placeholder_eps(eps, info.get("trailingPE"), cur_price):
        # Earnings unknown (EPS 1.00, P/E = price): clear the old figures, not store fake ones
        eps = None
        for key in ("eps", "pe_ratio", "intrinsic_value"):
            if key in columns:
                out[key] = ""
    put("eps", eps, f"{cy}{{:,.2f}}")
    put("book_value", info.get("bookValue"), f"{cy}{{:,.2f}}")
    de = info.get("debtToEquity")
    put("debt_to_equity", de / 100 if isinstance(de, (int, float)) else None, "{:.2f}")
    put("current_ratio", info.get("currentRatio"), "{:.2f}")
    put("beta", info.get("beta"), "{:.2f}")

    roe = pct("returnOnEquity")
    put("roe", roe if roe is not None else scr.get("roe"), "{:.1f}%")
    put("roce", scr.get("roce"), "{:.1f}%")
    put("opm", pct("operatingMargins"), "{:.1f}%")
    put("ebitda_margin", pct("ebitdaMargins"), "{:.1f}%")
    put("net_profit_margin", pct("profitMargins"), "{:.1f}%")
    put_big("free_cash_flow", info.get("freeCashflow"))
    put("sales_growth", pct("revenueGrowth"), "{:.1f}%")
    put("profit_growth", pct("earningsGrowth"), "{:.1f}%")
    put("promoter_holding", pct("heldPercentInsiders"), "{:.1f}%")
    put("fii_dii_holding", pct("heldPercentInstitutions"), "{:.1f}%")
    put("dividend_yield", dividend_yield_pct(info), "{:.2f}%")
    put_big("market_cap", info.get("marketCap"))
    put("analyst_target", info.get("targetMeanPrice"), f"{cy}{{:,.1f}}")

    h52, l52 = info.get("fiftyTwoWeekHigh"), info.get("fiftyTwoWeekLow")
    if h52 and l52:
        put("week52_range", f"{_price(l52)} – {_price(h52)}")
    d50, d200 = info.get("fiftyDayAverage"), info.get("twoHundredDayAverage")
    if d50 and d200:
        put("dma_50_200", f"{_price(d50)} / {_price(d200)}")

    vol = info.get("volume") or info.get("averageVolume")
    if isinstance(vol, (int, float)):
        if vol >= 1e9:
            put("volume", f"{vol / 1e9:.1f}B")
        elif vol >= 1e6:
            put("volume", f"{vol / 1e6:.1f}M")
        else:
            put("volume", f"{vol:,.0f}")

    if eps and eps > 0 and "intrinsic_value" in columns:
        try:
            from model.engine import calculate_intrinsic_value as _calc_iv
            iv_val = _calc_iv(eps)
            if iv_val and iv_val > 0:
                put("intrinsic_value", iv_val, f"{cy}{{:,.2f}}")
        except Exception:
            log.debug("Intrinsic value for %s failed", yf_symbol, exc_info=True)

    # ── One year of prices: RSI, Sharpe ratio, MACD, support / resistance ──
    hist = safe(lambda: ticker.history(period="1y"))
    if hist is not None and not hist.empty and len(hist) >= 30:
        close = hist["Close"]
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=14).mean()
        rsi = (100 - 100 / (1 + gain / loss.replace(0, float("nan")))).iloc[-1]
        if pd.notna(rsi):
            put("rsi", float(rsi), "{:.1f}")
        returns = close.pct_change().dropna()
        if len(returns) > 20:
            excess = returns - 0.07 / 252  # 7 % risk-free rate
            if excess.std() > 0:
                put("sharpe_ratio", float(excess.mean() / excess.std() * 252 ** 0.5), "{:.2f}")
        if "macd" in columns:
            macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
            sig = macd.ewm(span=9, adjust=False).mean()
            if pd.notna(macd.iloc[-1]) and pd.notna(sig.iloc[-1]):
                put("macd", float(macd.iloc[-1] - sig.iloc[-1]), "{:.2f}")
        if "support_resistance" in columns:
            lo, hi = hist["Low"].tail(60).min(), hist["High"].tail(60).max()
            if pd.notna(lo) and pd.notna(hi):
                put("support_resistance", f"{_price(lo)} / {_price(hi)}")

    # ── Statements (each is a separate request, so only when needed) ──
    if "capex" in columns:
        cf = safe(lambda: ticker.cashflow)
        if cf is not None and not cf.empty and "Capital Expenditure" in cf.index:
            capex = cf.loc["Capital Expenditure"].dropna()
            if len(capex):
                put_big("capex", abs(float(capex.iloc[0])))
    if "qoq_op_profit" in columns:
        qf = safe(lambda: ticker.quarterly_financials)
        if qf is not None and not qf.empty:
            for lbl in ("Operating Income", "EBIT"):
                if lbl in qf.index:
                    op = qf.loc[lbl].dropna()
                    if len(op):
                        put_big("qoq_op_profit", float(op.iloc[0]))
                    break
    if {"revenue_cagr_3y", "profit_cagr_3y"} & columns:
        fin = safe(lambda: ticker.financials)
        if fin is not None and not fin.empty:
            for key, label in (("revenue_cagr_3y", "Total Revenue"), ("profit_cagr_3y", "Net Income")):
                if label in fin.index:
                    s = fin.loc[label].dropna()
                    if len(s) >= 4 and float(s.iloc[3]) > 0 and float(s.iloc[0]) > 0:
                        put(key, ((float(s.iloc[0]) / float(s.iloc[3])) ** (1 / 3) - 1) * 100, "{:.1f}%")

    return yf_symbol, out


# ── Pop-up helpers ────────────────────────────────────────────────────────────

def _fit_to_screen(widget: tk.Misc, want_w: int, want_h: int) -> str:
    """A geometry string no bigger than the screen (13" MacBooks are ~800 pt tall)."""
    try:
        sw, sh = int(widget.winfo_screenwidth()), int(widget.winfo_screenheight())
    except Exception:
        sw, sh = 1440, 900
    w = max(560, min(want_w, sw - 80))
    h = max(420, min(want_h, sh - 150))  # menu bar, title bar and Dock
    return f"{w}x{h}"


def _bind_popup_scroll(top: tk.Toplevel, canvas: ScrollArea) -> None:
    """Scroll `canvas` (a ScrollArea, 20 px a step) with the wheel/trackpad anywhere inside `top`.

    The bindings live on the pop-up window itself (every child has it in its
    bindtags), so they never affect the rest of the app and vanish with the
    pop-up. Returning "break" stops a main-window bind_all handler running too.
    """
    pending = [0.0]

    def _wheel(event):
        d = event.delta
        if d:
            steps = -round(d / 120) * 3 if abs(d) >= 120 else -d
            canvas.yview_scroll(int(steps) or (-1 if d > 0 else 1), "units")
        return "break"

    def _touchpad(event):
        low = event.delta & 0xFFFF
        dy = low - 0x10000 if low >= 0x8000 else low
        pending[0] -= dy
        steps = int(pending[0] / 20)
        if steps:
            pending[0] -= steps * 20
            canvas.yview_scroll(steps, "units")
        return "break"

    top.bind("<MouseWheel>", _wheel)
    top.bind("<Button-4>", lambda _e: (canvas.yview_scroll(-3, "units"), "break")[1])
    top.bind("<Button-5>", lambda _e: (canvas.yview_scroll(3, "units"), "break")[1])
    try:
        top.bind("<TouchpadScroll>", _touchpad)  # Tk 9 trackpads
    except tk.TclError:
        pass


def _make_scroll_area(parent: tk.Misc, bg: str) -> tuple[ScrollArea, tk.Frame]:
    scrollbar = ttk.Scrollbar(parent, orient="vertical")
    area = ScrollArea(parent, bg, scrollbar=scrollbar)
    area.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    return area, area.inner


def _alive(widget) -> bool:
    try:
        return widget is not None and bool(widget.winfo_exists())
    except Exception:
        return False


class WatchlistView(BaseView):
    """Watchlist view with inline CRUD form and a live Treeview table."""

    # Metric columns the form keeps values for (Edit Metrics dialog / Auto-Fill).
    # stock_name has no field; it is kept so Auto-Fill can store the company name.
    BASE_METRIC_KEYS = [
        "pe_ratio", "peg_ratio", "eps", "debt_to_equity", "book_value", "intrinsic_value",
        "roe", "roce", "opm", "free_cash_flow", "inventory_days",
        "sales_growth", "profit_growth",
        "promoter_holding", "pledged_shares", "fii_dii_holding", "order_book",
        "dma_50_200", "rsi", "volume",
        "ebitda_margin", "capex", "net_profit_margin", "sharpe_ratio", "qoq_op_profit",
        "beta", "week52_range", "current_ratio", "dividend_yield",
        "pb_ratio", "analyst_target", "market_cap", "action_signal",
        "sector", "industry", "current_value", "stock_name",
    ]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def build(self):
        from model.watchlist_db import OPTIONAL_METRIC_COLS

        self._selected_id: int | None = None   # id of row being edited
        self._loaded: dict = {}                 # form values of that row when it was selected
        self._loaded_metrics: dict = {}
        self._data: list[dict] = []
        self._db_columns: set[str] = set(self.BASE_METRIC_KEYS)
        self._optional_cols = list(OPTIONAL_METRIC_COLS)
        self._load_gen = 0
        self._refreshing = False
        self._autofill_running = False
        self._fetch_btn = None
        self._signal_filter = "all"
        self._filter_pills: dict[str, tk.Label] = {}
        self.wl_currency_var = tk.StringVar(value="INR")

        def _build_right(parent):
            # Currency pills (matching My Holdings: radius=14, green/purple/slate)
            self._wl_curr_btns = {}
            for code in ("INR", "JPY"):
                sym = {"INR": "₹", "JPY": "¥"}.get(code, "₹")
                btn = ModernButton(
                    parent, text=f"{sym} {code}",
                    command=lambda c=code: self.wl_currency_var.set(c),
                    bg=ModernStyle.NEUTRAL_FILL, fg=ModernStyle.TEXT_ON_ACCENT,
                    width=86, height=32, radius=14, font=ModernStyle.FONT_BODY_BOLD,
                )
                btn.pack(side="left", padx=(0, 6))
                self._wl_curr_btns[code] = btn
            self.wl_currency_var.trace_add("write", self._on_wl_currency_change)
            self._update_wl_currency_pills()

            self._btn_refresh_all = header_button(parent, "↻ Refresh All", self._bulk_refresh_metrics,
                                                  main=True, width=160)
            self._btn_refresh_all.pack(side="left", pady=(0, 4))
            ToolTip(self._btn_refresh_all, "Fetch the latest metrics from Yahoo Finance for every symbol")

        header = self.add_gradient_header(
            self,
            "👁  Watchlist",
            "Click a row to edit it · double-click for the full analysis.",
            right_widget_func=_build_right
        )
        header.pack_configure(pady=(6, 0))   # tight spacing: the table gets the room

        # ── Inline form ───────────────────────────────────────────────────────
        form_card = ModernCard(self,
            bg=ModernStyle.BG_SECONDARY,
            highlight_color=ModernStyle.BG_SECONDARY, shadow=True,
            highlight_thickness=1,
            radius=ModernStyle.RADIUS_CARD,
            canvas_bg=ModernStyle.BG_PRIMARY
        )
        form_card.pack(fill="x", padx=20, pady=(4, 2))

        form_inner = tk.Frame(form_card.content, bg=ModernStyle.BG_SECONDARY)
        form_inner.pack(fill="x", padx=16, pady=(8, 10))

        # Row 1: Symbol (+ Add) | Notes | Tags | My Target
        fields_row = tk.Frame(form_inner, bg=ModernStyle.BG_SECONDARY)
        fields_row.pack(fill="x")

        def _field(parent, label: str, var: tk.StringVar, width: int = 14, expand=False, placeholder: str = "") -> ModernEntry:
            col = tk.Frame(parent, bg=ModernStyle.BG_SECONDARY)
            col.pack(side="left", padx=(0, 16), fill="x" if expand else None, expand=expand)

            lbl_frame = tk.Frame(col, bg=ModernStyle.BG_SECONDARY)
            lbl_frame.pack(anchor="w", pady=(0, 4))
            if "*" in label:
                clean_lbl = label.replace("*", "").strip()
                tk.Label(
                    lbl_frame, text=clean_lbl, bg=ModernStyle.BG_SECONDARY,
                    fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_SMALL_BOLD
                ).pack(side="left")
                tk.Label(
                    lbl_frame, text=" *", bg=ModernStyle.BG_SECONDARY,
                    fg=ModernStyle.ERROR, font=ModernStyle.FONT_SMALL_BOLD
                ).pack(side="left")
            else:
                tk.Label(
                    lbl_frame, text=label, bg=ModernStyle.BG_SECONDARY,
                    fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_SMALL_BOLD
                ).pack(side="left")

            box = RoundedBox(col, padx=5, pady=5)
            inner = tk.Frame(box, bg=ModernStyle.ENTRY_BG)
            inner.pack(fill="both", expand=True)

            e = ModernEntry(
                inner, placeholder=placeholder,
                textvariable=var,
                bg=ModernStyle.ENTRY_BG,
                fg=ModernStyle.TEXT_PRIMARY,
                insertbackground=ModernStyle.ACCENT_PRIMARY,
                highlightthickness=0,
                relief=tk.FLAT,
                font=ModernStyle.FONT_INPUT,
                width=width
            )
            e.pack(side="left", fill="x", expand=True, padx=(10, 8), pady=3, ipady=4)

            # Enhanced hover & focus border effects
            is_focused = [False]
            def _on_focus_in(_evt):
                is_focused[0] = True
                if str(box.cget("bg")) != ModernStyle.ERROR:
                    box.configure(bg=ModernStyle.ACCENT_PRIMARY)

            def _on_focus_out(_evt):
                is_focused[0] = False
                if str(box.cget("bg")) != ModernStyle.ERROR:
                    box.configure(bg=ModernStyle.BORDER_COLOR)

            def _on_hover_in(_evt):
                if not is_focused[0] and str(box.cget("bg")) != ModernStyle.ERROR:
                    box.configure(bg=ModernStyle.TEXT_TERTIARY)

            def _on_hover_out(_evt):
                if not is_focused[0] and str(box.cget("bg")) != ModernStyle.ERROR:
                    box.configure(bg=ModernStyle.BORDER_COLOR)

            e.bind("<FocusIn>", _on_focus_in, add="+")
            e.bind("<FocusOut>", _on_focus_out, add="+")
            for w in (box, inner, e):
                w.bind("<Enter>", _on_hover_in, add="+")
                w.bind("<Leave>", _on_hover_out, add="+")

            box.pack(anchor="w", fill="x" if expand else None)
            e.bind("<Return>", lambda _e: self._on_save())
            e.bind("<Escape>", self._clear_form, add="+")
            return e

        self._v_symbol = tk.StringVar()
        self._v_notes  = tk.StringVar()
        self._v_tags   = tk.StringVar()
        self._v_target = tk.StringVar()

        self._metrics_keys = list(self.BASE_METRIC_KEYS)
        self._metrics_vars = {k: tk.StringVar() for k in self._metrics_keys}

        self._e_symbol = _field(fields_row, "Symbol *", self._v_symbol, width=12, placeholder="e.g. INFY")

        # Add-as-new button next to the symbol
        add_btn = action_button(fields_row, "+ Add", self._on_quick_add, kind="success",
                                canvas_bg=ModernStyle.BG_SECONDARY)
        add_btn.pack(side="left", padx=(0, 16), pady=(22, 0))
        ToolTip(add_btn, "Add this symbol as a new watchlist entry")

        self._e_notes = _field(fields_row, "Notes", self._v_notes, width=14, expand=True, placeholder="Investment thesis / key notes...")
        self._e_tags = _field(fields_row, "Tags", self._v_tags, width=12, placeholder="e.g. Bluechip, Tech")
        self._e_target = _field(fields_row, "My Target Price", self._v_target, width=11, placeholder="₹ Target")
        self._entries = (self._e_symbol, self._e_notes, self._e_tags, self._e_target)

        # Row 2: Buttons
        btn_row = tk.Frame(form_inner, bg=ModernStyle.BG_SECONDARY)
        btn_row.pack(fill="x", pady=(8, 0))

        action_button(btn_row, "✓ Save", self._on_save,
                      canvas_bg=ModernStyle.BG_SECONDARY).pack(side="left", padx=(0, 8))

        secondary_button(btn_row, "Clear", self._clear_form, icon="eraser",
                         canvas_bg=ModernStyle.BG_SECONDARY).pack(side="left", padx=(0, 8))

        action_button(btn_row, "Edit Metrics", self._open_metrics_dialog, soft=True, icon="gauge",
                      canvas_bg=ModernStyle.BG_SECONDARY).pack(side="left", padx=(0, 8))

        self._del_btn = action_button(btn_row, "Delete", self._on_delete, kind="danger", soft=True,
                                      icon="trash-2", canvas_bg=ModernStyle.BG_SECONDARY)
        self._del_btn.pack(side="left")
        self._set_delete_enabled(False)   # enabled only when a row is selected

        self._form_status = tk.Label(
            btn_row,
            text="",
            fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_SMALL_BOLD,
        )
        self._form_status.pack(side="right", padx=4)

        # ── Signal filter pills ───────────────────────────────────────────────
        filter_bar = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        filter_bar.pack(fill="x", padx=22, pady=(4, 0))
        tk.Label(
            filter_bar, text="Show:", bg=ModernStyle.BG_PRIMARY,
            fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_SMALL_BOLD,
        ).pack(side="left", padx=(0, 6))
        for key in ["all"] + SIGNAL_ORDER:
            pill = tk.Label(
                filter_bar, text=self._pill_text(key, None), font=ModernStyle.FONT_SMALL,
                padx=8, pady=4, cursor="hand2", bd=0,
            )
            pill.pack(side="left", padx=(0, 5))
            pill.bind("<Button-1>", lambda _e, k=key: self._set_signal_filter(k))
            self._filter_pills[key] = pill
        self._style_pills()

        # ── Treeview table ────────────────────────────────────────────────────
        table_frame = ModernCard(
            self,
            bg=ModernStyle.BG_SECONDARY,
            highlight_color=ModernStyle.BG_SECONDARY, shadow=True,
            highlight_thickness=1,
            radius=ModernStyle.RADIUS_CARD,
            canvas_bg=ModernStyle.BG_PRIMARY,
            expand_height=True,
        )
        table_frame.pack(fill="both", expand=True, padx=20, pady=(4, 12))
        table_frame.content.grid_rowconfigure(0, weight=1)
        table_frame.content.grid_columnconfigure(0, weight=1)
        self._empty = EmptyState(table_frame.content)

        cols = ("#", "Symbol", "Signal", "Sector / Industry", "Current Px", "IV (DCF)", "MoS %",
                "Graham No.", "Analyst Tgt", "My Target", "P/E", "PEG", "Div. Yield", "From 52W H",
                "Tags", "Notes / Name", "Added")

        style = ttk.Style()
        style.configure("Watchlist.Treeview", font=ModernStyle.FONT_TABLE, rowheight=ModernStyle.TABLE_ROW_HEIGHT)
        style.configure("Watchlist.Treeview.Heading", font=ModernStyle.FONT_SUBHEADING,
                        background=ModernStyle.TABLE_HEADER_BG, foreground=ModernStyle.TABLE_HEADER_FG,
                        relief="flat")
        style.map("Watchlist.Treeview.Heading",
                  background=[("active", ModernStyle.TABLE_HEADER_HOVER)],
                  foreground=[("active", ModernStyle.TABLE_HEADER_FG)])

        self._tv = ttk.Treeview(
            table_frame.content, columns=cols, show="headings",
            selectmode="browse", style="Watchlist.Treeview"
        )
        HeadingTips(self._tv, {
            "Signal": "Suggestion from the valuation checks",
            "Current Px": "Latest market price",
            "IV (DCF)": "Fair value from a discounted-cash-flow estimate",
            "MoS %": "Margin of safety: how far the price is below fair value",
            "Graham No.": "Benjamin Graham's fair price: √(22.5 × EPS × book value per share)",
            "Analyst Tgt": "Average analyst price target",
            "My Target": "Your own target price",
            "P/E": "Price ÷ earnings per share (lower can mean cheaper)",
            "PEG": "P/E ÷ earnings growth (under 1 can mean cheap for its growth)",
            "Div. Yield": "Yearly dividend as a % of the price",
            "From 52W H": "How far the price is below its 52-week high",
        })
        col_widths = [40, 120, 140, 250, 100, 100, 80, 100, 100, 100, 60, 60, 90, 100, 110, 220, 100]
        sortable_cols = ("Symbol", "Signal", "Current Px", "IV (DCF)", "MoS %", "P/E", "Div. Yield", "From 52W H", "Added")

        for c, w in zip(cols, col_widths):
            # numbers on the right so their digits line up; text and values with a ▲/▼ on the left
            anchor = ("center" if c in ("#", "Added") else
                      "e" if c in ("Current Px", "IV (DCF)", "Graham No.", "Analyst Tgt", "My Target",
                                   "P/E", "PEG", "Div. Yield") else "w")
            if c in sortable_cols:
                self._tv.heading(c, text=f"{c} ↕", anchor="center",
                                 command=lambda col=c: treeview_sort_column(self._tv, col, False))
            else:
                self._tv.heading(c, text=c, anchor="center")
            self._tv.column(c, width=w, minwidth=w, anchor=anchor)

        # Row colours by signal. Configured BEFORE the plain stripes so they win
        # if a sort adds "odd"/"even" tags; "odd"/"even" themselves carry no
        # colour (rows without a signal use the "plain_*" stripes).
        for key in SIGNAL_ORDER:
            if key == "nodata":
                continue
            _fg, pale, _fill = signal_colours(key)
            # a third of the signal's soft tint (as in Holdings): just a hint of colour. The text
            # stays plain; only the Signal and the indicator columns are coloured
            row_bg = ModernButton._blend(pale, ModernStyle.BG_SECONDARY, 0.35)
            self._tv.tag_configure(f"sig_{key}", background=row_bg, foreground=ModernStyle.TEXT_PRIMARY)
        self._tv.tag_configure("plain_odd", background=ModernStyle.BG_SECONDARY, foreground=ModernStyle.TEXT_PRIMARY)
        self._tv.tag_configure("plain_even", background=ModernStyle.TABLE_ROW_ALT, foreground=ModernStyle.TEXT_PRIMARY)

        vsb = ttk.Scrollbar(table_frame.content, orient="vertical",   command=self._tv.yview)
        hsb = ttk.Scrollbar(table_frame.content, orient="horizontal", command=self._tv.xview)
        self._tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        add_treeview_copy_menu(self._tv)

        # Row selection → fill form (mouse and arrow keys); double-click → analysis
        self._tv.bind("<ButtonRelease-1>", self._on_row_select)
        self._tv.bind("<KeyRelease-Up>",   self._on_row_select)
        self._tv.bind("<KeyRelease-Down>", self._on_row_select)
        self._tv.bind("<Double-1>",        self._on_double_click)
        self._tv.bind("<Return>",          self._on_double_click)
        # Escape clears the form from the table or any form field (they take focus)
        self._tv.bind("<Escape>", self._clear_form)

    # ── Data loading ──────────────────────────────────────────────────────────

    def on_show(self):
        self._is_active = True
        self._data_loaded = False   # always refresh on navigate
        self.load_data()

    def load_data(self):
        from model.watchlist_db import get_all_watchlist, watchlist_columns

        self._data_loaded = True
        self._load_gen += 1
        gen = self._load_gen
        run_in_background(
            lambda: (get_all_watchlist(), watchlist_columns()),
            on_done=lambda res: self._on_loaded(gen, res),
            on_error=lambda err: self._notify(f"Couldn't load the watchlist: {err}", "error"),
            widget=self, name="watchlist-load",
        )

    def _on_loaded(self, gen: int, result) -> None:
        if gen != self._load_gen:
            return  # a newer load is on its way
        rows, columns = result
        self._db_columns = set(columns)
        for key in self._optional_cols:
            if key in self._db_columns and key not in self._metrics_vars:
                self._metrics_vars[key] = tk.StringVar()
                self._metrics_keys.append(key)
        # Each visit reloads the list; the table is only rebuilt when something changed
        if rows != getattr(self, "_data", None) or not self._tv.get_children():
            self._populate_table(rows)
        if self._selected_id is not None and self._tv.exists(str(self._selected_id)):
            self._tv.selection_set(str(self._selected_id))

    # ── Filter pills ──────────────────────────────────────────────────────────

    @staticmethod
    def _pill_text(key: str, count: int | None) -> str:
        label = "All" if key == "all" else f"{SIGNAL_TEXT[key][0]} {SIGNAL_TEXT[key][1]}"
        return label if count is None else f"{label} {count}"

    def _style_pills(self) -> None:
        for key, pill in self._filter_pills.items():
            fg, pale, fill = signal_colours(key)
            if key == self._signal_filter:
                pill.config(bg=fill, fg=ModernStyle.TEXT_ON_ACCENT, font=ModernStyle.FONT_SMALL_BOLD)
            else:
                pill.config(bg=pale, fg=fg, font=ModernStyle.FONT_SMALL)

    def _set_signal_filter(self, key: str) -> None:
        if key == self._signal_filter:
            return
        self._signal_filter = key
        self._style_pills()
        self._populate_table()

    # ── Currency filter ──────────────────────────────────────────────────────

    def _update_wl_currency_pills(self, *_):
        S = ModernStyle
        active = self.wl_currency_var.get()
        fills = {"INR": S.SUCCESS_FILL, "JPY": S.PURPLE_FILL}
        for code, btn in self._wl_curr_btns.items():
            sym = {"INR": "₹", "JPY": "¥"}.get(code, "₹")
            if code == active:
                btn.set_palette(bg=fills.get(code, S.ACCENT_PRIMARY), fg=S.TEXT_ON_ACCENT)
                btn.set_text(f"✓ {sym} {code}")
            else:
                btn.set_palette(bg=S.NEUTRAL_FILL, fg=S.TEXT_ON_ACCENT)
                btn.set_text(f"{sym} {code}")

    def _on_wl_currency_change(self, *_):
        self._update_wl_currency_pills()
        if hasattr(self, '_tv'):
            self._populate_table()

    # ── Table rendering ───────────────────────────────────────────────────────

    def _populate_table(self, data: list[dict] | None = None) -> None:
        if data is not None:
            self._data = data
        self._tv.delete(*self._tv.get_children())

        active_cur = self.wl_currency_var.get()
        counts = {k: 0 for k in SIGNAL_ORDER}
        currency_total = 0
        shown = 0
        for row in self._data:
            sym = row.get("symbol", "")
            row_cur = "JPY" if str(sym).upper().endswith(".T") else "INR"
            if row_cur != active_cur:
                continue
            currency_total += 1

            key, signal_badge_text, _ = compute_signal(row)
            counts[key] += 1
            if self._signal_filter != "all" and key != self._signal_filter:
                continue

            cy = "¥" if active_cur == "JPY" else "₹"

            def money(text):
                text = str(text or "").strip()
                return text.replace("₹", cy) if text and text != "None" else "—"

            sector_cell = " / ".join(filter(None, [row.get("sector") or "", row.get("industry") or ""])) or "—"
            cv_f = parse_num(row.get("current_value"))
            iv_f = parse_num(row.get("intrinsic_value"))

            mos_str = graham_str = from_high_str = "—"
            if cv_f is not None:
                if iv_f is not None and iv_f > 0:
                    mos_pct = (iv_f - cv_f) / iv_f * 100
                    mos_str = f"{'▲ +' if mos_pct > 0 else '▼ '}{mos_pct:.1f}%"
                gn = graham_number(row)
                if gn:
                    graham_str = f"{cy}{gn:,.1f}"
                rng = _week52(row)
                if rng and rng[1] > 0:
                    drop_pct = (cv_f - rng[1]) / rng[1] * 100
                    from_high_str = f"{'▲ +' if drop_pct > 0 else '▼ '}{drop_pct:.1f}%"

            target = parse_num(row.get("target_price"))
            if target and target > 0:
                hit = cv_f is not None and cv_f <= target
                my_target = f"{'🎯 ' if hit else ''}{cy}{target:,.2f}"
            else:
                my_target = "—"

            if key == "nodata":
                row_tag = "plain_odd" if shown % 2 == 0 else "plain_even"
            else:
                row_tag = f"sig_{key}"

            self._tv.insert(
                "", "end",
                iid=str(row["id"]),
                values=(
                    shown + 1,
                    sym,
                    signal_badge_text,
                    sector_cell,
                    money(row.get("current_value")),
                    money(row.get("intrinsic_value")),
                    mos_str,
                    graham_str,
                    money(row.get("analyst_target")),
                    my_target,
                    row.get("pe_ratio") or "—",
                    row.get("peg_ratio") or "—",
                    row.get("dividend_yield") or "—",
                    from_high_str,
                    row.get("tags") or "",
                    row.get("notes") or row.get("stock_name") or "",
                    format_date(row.get("added_on", "")),
                ),
                tags=(row_tag,),
            )
            shown += 1
        color_gain_loss(self._tv, ("MoS %", "From 52W H"))
        color_signals(self._tv, "Signal")

        # A friendly empty screen when nothing is listed (once the data has loaded)
        if shown == 0 and (data is not None or self._data_loaded):
            if not self._data:
                self._empty.show("👀", "Your watchlist is empty",
                                 "Type a symbol in the form above and press Add to follow a stock.",
                                 "+ Add a stock", lambda: self._e_symbol.focus_set())
            elif currency_total == 0:
                other = "JPY" if active_cur == "INR" else "INR"
                self._empty.show("💱", f"No {active_cur} stocks in watchlist",
                                 f"Switch to {other} or add a stock.",
                                 f"↺ Show {other}", lambda o=other: self.wl_currency_var.set(o))
            else:
                self._empty.show("🔍", "No stocks with this signal",
                                 "Pick another signal above, or show them all.",
                                 "↺ Show all", lambda: self._set_signal_filter("all"))
        else:
            self._empty.hide()

        total = currency_total
        for key, pill in self._filter_pills.items():
            pill.config(text=self._pill_text(key, total if key == "all" else counts[key]))
        if total:   # in the header: the verdicts at a glance
            buy = counts["strong_buy"] + counts["accumulate"]
            self.set_header_summary(f"{total} {active_cur} {'stock' if total == 1 else 'stocks'}  ·  "
                                    f"{buy} worth buying  ·  {counts['wait']} to watch  ·  {counts['avoid']} to avoid")
        else:
            self.set_header_summary("")

    # ── Form helpers ──────────────────────────────────────────────────────────

    def _set_delete_enabled(self, enabled: bool) -> None:
        try:
            self._del_btn.set_disabled(not enabled)   # greyed out while off, its soft red while on
        except Exception:
            pass

    def _clear_form(self, _=None) -> None:
        self._selected_id = None
        self._loaded = {}
        self._loaded_metrics = {}
        self._v_symbol.set("")
        self._v_notes.set("")
        self._v_tags.set("")
        self._v_target.set("")
        for v in self._metrics_vars.values():
            v.set("")
        self._form_status.config(text="", fg=ModernStyle.TEXT_TERTIARY)
        self._set_delete_enabled(False)
        try:
            self._tv.selection_remove(*self._tv.selection())
        except Exception:
            pass

    def _row_by_iid(self, iid) -> dict | None:
        return next((r for r in self._data if str(r["id"]) == str(iid)), None)

    def _on_double_click(self, _=None):
        sel = self._tv.selection()
        row = self._row_by_iid(sel[0]) if sel else None
        if row:
            self._open_diagnostic_popup(row)

    def _on_row_select(self, _=None) -> None:
        sel = self._tv.selection()
        row = self._row_by_iid(sel[0]) if sel else None
        if row is None:
            return

        sym = row.get("symbol", "") or ""
        cy = "¥" if sym.upper().endswith(".T") else "₹"
        target = parse_num(row.get("target_price")) or 0.0

        self._selected_id = row["id"]
        self._loaded = {
            "symbol": sym.upper(),
            "notes": (row.get("notes") or "").strip(),
            "tags": (row.get("tags") or "").strip(),
            "target_price": target,
        }
        self._v_symbol.set(sym)
        self._v_notes.set(self._loaded["notes"])
        self._v_tags.set(self._loaded["tags"])
        self._v_target.set(f"{target:g}" if target else "")
        for e in self._entries:
            e.config(fg=e.normal_color)   # not the grey placeholder colour

        self._loaded_metrics = {}
        for k, v in self._metrics_vars.items():
            val = row.get(k)
            val = "" if val is None else str(val).replace("₹", cy)
            v.set(val)
            self._loaded_metrics[k] = val.strip()
        self._form_status.config(text=f"✏️ Editing {sym}", fg=ModernStyle.TEXT_ACCENT)
        self._set_delete_enabled(True)

    def _read_form(self) -> dict | None:
        """The form's values, or None (after telling the user) when invalid."""
        symbol = self._v_symbol.get().strip().upper()
        if not symbol:
            self._notify("Symbol is required.", "error")
            try:
                self._e_symbol.focus_set()
            except Exception:
                pass
            return None
        target_text = self._v_target.get().strip()
        target = parse_num(target_text) if target_text else 0.0
        if target is None or target < 0:
            self._notify("Target price must be a number, e.g. 1250 or 1250.50.", "error")
            return None
        return {"symbol": symbol, "notes": self._v_notes.get().strip(),
                "tags": self._v_tags.get().strip(), "target_price": target}

    def _metric_values(self) -> dict[str, str]:
        return {k: v.get().strip() for k, v in self._metrics_vars.items()}

    # ── CRUD event handlers ───────────────────────────────────────────────────

    def _on_save(self) -> bool:
        """Add a new entry, or save the CHANGED fields of the selected one.

        Returns True when a save was started.
        """
        from model.watchlist_db import add_watchlist, update_watchlist

        form = self._read_form()
        if form is None:
            return False

        if self._selected_id is None:
            metrics = {k: v for k, v in self._metric_values().items() if v}
            symbol = form["symbol"]
            self._run_db(lambda: add_watchlist(symbol, form["notes"], form["tags"], form["target_price"], **metrics),
                         f"'{symbol}' added to watchlist.")
            return True

        changes: dict = {}
        for key in ("symbol", "notes", "tags"):
            if form[key] != self._loaded.get(key, ""):
                changes[key] = form[key]
        if abs(form["target_price"] - self._loaded.get("target_price", 0.0)) > 1e-9:
            changes["target_price"] = form["target_price"]
        for k, val in self._metric_values().items():
            if val != self._loaded_metrics.get(k, ""):
                changes[k] = val
        if not changes:
            self._notify(f"No changes to save for {form['symbol']}.", "info")
            return True

        row_id = self._selected_id
        self._run_db(lambda: update_watchlist(row_id, **changes), f"'{form['symbol']}' updated.")
        return True

    def _on_quick_add(self) -> None:
        """Always add a NEW entry — never overwrite an existing one.

        When a row is selected and you type a different symbol, the selected
        row's metrics, notes, tags and target are NOT copied to the new entry
        (only what you changed in the form is used).
        """
        from model.watchlist_db import add_watchlist

        form = self._read_form()
        if form is None:
            return
        symbol = form["symbol"]
        if self._selected_id is None or symbol == self._loaded.get("symbol"):
            notes, tags, target = form["notes"], form["tags"], form["target_price"]
            metrics = {k: v for k, v in self._metric_values().items() if v} if self._selected_id is None else {}
        else:
            notes = form["notes"] if form["notes"] != self._loaded.get("notes") else ""
            tags = form["tags"] if form["tags"] != self._loaded.get("tags") else ""
            target = form["target_price"] if form["target_price"] != self._loaded.get("target_price") else 0.0
            metrics = {}
        self._run_db(lambda: add_watchlist(symbol, notes, tags, target, **metrics),
                     f"'{symbol}' added to watchlist.")

    def _on_delete(self) -> None:
        from model.watchlist_db import delete_watchlist

        if self._selected_id is None:
            return
        symbol = self._loaded.get("symbol") or self._v_symbol.get().strip().upper() or str(self._selected_id)
        if not dialogs.askyesno(
            "Delete from Watchlist",
            f"Remove '{symbol}' from your watchlist?",
            parent=self,
        ):
            return
        row_id = self._selected_id
        self._run_db(lambda: delete_watchlist(row_id), f"'{symbol}' removed.")

    def _run_db(self, work, success_msg: str) -> None:
        """Run a database write in the background; report success or the error."""
        run_in_background(
            work,
            on_done=lambda _res: self._post_save(success_msg),
            on_error=lambda err: self._notify(str(err) if isinstance(err, ValueError)
                                              else f"Couldn't save: {err}", "error"),
            widget=self, name="watchlist-save",
        )

    def _post_save(self, msg: str) -> None:
        """Refresh table, clear form, show success message."""
        self._clear_form()
        self._notify(msg, "success")
        self.load_data()

    def _notify(self, msg: str, kind: str = "success") -> None:
        """Show a toast (success / info / warning / error)."""
        try:
            show_toast(self.winfo_toplevel(), msg, type=kind)
        except Exception:
            color = ModernStyle.ERROR if kind == "error" else ModernStyle.SUCCESS
            self._form_status.config(text=msg, fg=color)

    # ── Auto-Fill one symbol (Edit Metrics dialog) ────────────────────────────

    def _set_fetch_btn(self, text: str) -> None:
        if _alive(self._fetch_btn):
            self._fetch_btn.set_text(text)

    def _auto_fetch_metrics(self):
        if self._autofill_running:
            return
        symbol = self._v_symbol.get().strip().upper()
        if not symbol:
            self._notify("Enter a symbol first to auto-fill.", "error")
            return
        self._autofill_running = True
        self._set_fetch_btn("🔄 Fetching…")
        columns = set(self._db_columns)
        run_in_background(
            lambda: fetch_watchlist_metrics(symbol, columns),
            on_done=lambda res: self._on_autofill_done(symbol, res),
            on_error=lambda err: self._on_autofill_failed(symbol, err),
            widget=self, name="watchlist-autofill",
        )

    def _reset_fetch_btn_later(self) -> None:
        self.after(2500, lambda: self._set_fetch_btn("✨ Auto-Fill (yfinance)"))

    def _on_autofill_done(self, symbol: str, result) -> None:
        self._autofill_running = False
        yf_symbol, values = result
        filled = 0
        for key, text in values.items():
            var = self._metrics_vars.get(key)
            if var is not None:
                var.set(text)
                filled += 1
        self._set_fetch_btn(f"✅ {filled} values filled")
        self._reset_fetch_btn_later()
        shown_as = f" ({yf_symbol})" if yf_symbol != symbol else ""
        self._notify(f"Auto-Fill: {filled} values for {symbol}{shown_as}. Press Save to keep them.", "success")

    def _on_autofill_failed(self, symbol: str, err: Exception) -> None:
        self._autofill_running = False
        self._set_fetch_btn("⚠ Failed")
        self._reset_fetch_btn_later()
        msg = str(err) if isinstance(err, LookupError) else f"Auto-Fill for {symbol} failed: {err}"
        self._notify(msg, "error")

    # ── Refresh All ───────────────────────────────────────────────────────────

    def _bulk_refresh_metrics(self):
        if self._refreshing:
            return
        if not self._data:
            self._notify("Watchlist is empty.", "error")
            return

        rows = [dict(r) for r in self._data]
        columns = set(self._db_columns)
        total = len(rows)
        self._refreshing = True
        self._btn_refresh_all.set_text(f"🔄 Updating 0/{total}")

        def work():
            import concurrent.futures
            from model.watchlist_db import update_watchlist

            updated, failed, done = 0, [], 0
            # A few symbols at a time; database writes stay in this one thread
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(fetch_watchlist_metrics, r.get("symbol") or "", columns): r for r in rows}
                for fut in concurrent.futures.as_completed(futures):
                    row = futures[fut]
                    sym = row.get("symbol") or "?"
                    done += 1
                    call_on_ui(self._show_refresh_progress, done, total)
                    try:
                        _yf, values = fut.result()
                    except Exception as exc:
                        log.warning("Watchlist refresh: %s failed: %s", sym, exc)
                        failed.append(sym)
                        continue
                    if not values:
                        failed.append(sym)
                        continue
                    merged = dict(row)
                    merged.update(values)
                    values["action_signal"] = compute_signal(merged)[1]
                    try:
                        update_watchlist(row["id"], **values)   # only the values found
                        updated += 1
                    except Exception:
                        log.exception("Watchlist refresh: saving %s failed", sym)
                        failed.append(sym)
            return updated, sorted(failed), total

        run_in_background(work, on_done=self._on_bulk_done, on_error=self._on_bulk_failed,
                          widget=self, name="watchlist-refresh-all")

    def _show_refresh_progress(self, done: int, total: int) -> None:
        if self._refreshing and _alive(self._btn_refresh_all):
            self._btn_refresh_all.set_text(f"🔄 Updating {done}/{total}")

    def _end_bulk(self) -> None:
        self._refreshing = False
        self._btn_refresh_all.set_text("↻ Refresh All")

    def _on_bulk_done(self, result) -> None:
        updated, failed, total = result
        self._end_bulk()
        msg = f"Updated {updated} of {total}"
        if failed:
            names = ", ".join(failed[:6]) + ("…" if len(failed) > 6 else "")
            msg += f" ({len(failed)} failed: {names})"
            kind = "warning" if updated else "error"
        else:
            msg += "."
            kind = "success"
        self._notify(msg, kind)
        self.load_data()

    def _on_bulk_failed(self, err: Exception) -> None:
        self._end_bulk()
        self._notify(f"Refresh All failed: {err}", "error")

    # ── Edit Metrics dialog ───────────────────────────────────────────────────

    def _open_metrics_dialog(self):
        sym = self._v_symbol.get().strip().upper() or "New Symbol"
        top = PremiumModal(self, title="Advanced Metrics", geometry=_fit_to_screen(self, 820, 850), icon="gauge",
                           icon_color="#0EA5E9")
        top.resizable(True, True)
        top.minsize(600, 420)
        top.add_chip("📈", sym, bg_color=ModernStyle.ACCENT_PRIMARY, fg_color=ModernStyle.TEXT_ON_ACCENT)

        main_frame = tk.Frame(top.content_frame, bg=ModernStyle.BG_SECONDARY)
        main_frame.pack(fill="both", expand=True)
        canvas, scrollable_frame = _make_scroll_area(main_frame, ModernStyle.BG_SECONDARY)
        _bind_popup_scroll(top, canvas)

        def present(fields):
            return [(lbl, key) for lbl, key in fields if key in self._metrics_vars]

        groups = [
            ("Financial Ratios & Valuation", ModernStyle.ACCENT_PRIMARY, [
                ("P/E Ratio", "pe_ratio"), ("PEG Ratio", "peg_ratio"), ("EPS", "eps"),
                ("Debt to Equity", "debt_to_equity"), ("Book Value", "book_value"), ("Intrinsic Value", "intrinsic_value"),
                ("P/B Ratio", "pb_ratio"), ("Current Ratio", "current_ratio"),
            ]),
            ("Profitability & Efficiency", ModernStyle.SUCCESS_FILL, [
                ("ROE", "roe"), ("ROCE", "roce"), ("OPM (%)", "opm"), ("EBITDA Margin (%)", "ebitda_margin"),
                ("Net Profit Margin (%)", "net_profit_margin"), ("Free Cash Flow", "free_cash_flow"),
                ("Inventory Days", "inventory_days"), ("Capex", "capex"), ("QoQ Op. Profit", "qoq_op_profit"),
            ]),
            ("Growth Metrics", ModernStyle.WARNING_FILL, [
                ("Sales Growth", "sales_growth"), ("Profit Growth", "profit_growth"),
                ("3Y Rev CAGR", "revenue_cagr_3y"), ("3Y Profit CAGR", "profit_cagr_3y"),
            ]),
            ("Operational & Ownership", ModernStyle.PURPLE_FILL, [
                ("Promoter Holding", "promoter_holding"), ("Pledged Shares", "pledged_shares"),
                ("FII / DII Holding", "fii_dii_holding"), ("Order Book", "order_book"),
                ("Dividend Yield", "dividend_yield"),
            ]),
            ("Technical Analysis (Entry/Exit)", ModernStyle.INFO_FILL, [
                ("50 & 200 DMA", "dma_50_200"), ("RSI", "rsi"), ("MACD", "macd"),
                ("Support/Resistance", "support_resistance"), ("Sharpe Ratio", "sharpe_ratio"),
                ("Volume", "volume"), ("Beta", "beta"), ("52-Week Range", "week52_range"),
            ]),
        ]

        for group_name, accent_color, fields in groups:
            fields = present(fields)
            if not fields:
                continue
            group_wrapper = tk.Frame(scrollable_frame, bg=ModernStyle.BG_SECONDARY)
            group_wrapper.pack(fill="x", pady=(0, 15))
            tk.Frame(group_wrapper, bg=accent_color, height=ModernStyle.ACCENT_BAR).pack(fill="x")

            group_frame = tk.Frame(group_wrapper, bg=ModernStyle.BG_TERTIARY, highlightthickness=1,
                                   highlightbackground=ModernStyle.BORDER_COLOR)
            group_frame.pack(fill="x", ipady=8)
            tk.Label(
                group_frame, text=group_name,
                fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_TERTIARY,
                font=ModernStyle.FONT_CARD_TITLE
            ).pack(anchor="w", padx=20, pady=(6, 8))

            grid = tk.Frame(group_frame, bg=ModernStyle.BG_TERTIARY)
            grid.pack(fill="x", padx=20)
            for i, (label_text, key) in enumerate(fields):
                f = tk.Frame(grid, bg=ModernStyle.BG_TERTIARY)
                f.grid(row=i // 2, column=i % 2, padx=12, pady=6, sticky="ew")
                grid.grid_columnconfigure(i % 2, weight=1)
                tk.Label(
                    f, text=label_text,
                    fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_TERTIARY,
                    font=ModernStyle.FONT_FIELD_LABEL, width=18, anchor="w"
                ).pack(side="left", padx=(0, 10))
                box = RoundedBox(f)
                box.pack(side="left", fill="x", expand=True)
                inner = tk.Frame(box, bg=ModernStyle.ENTRY_BG)
                inner.pack(fill="both", expand=True)
                ent = tk.Entry(
                    inner, textvariable=self._metrics_vars[key],
                    bg=ModernStyle.ENTRY_BG, fg=ModernStyle.TEXT_PRIMARY,
                    font=ModernStyle.FONT_INPUT, relief=tk.FLAT, bd=0, width=12,
                    highlightthickness=0, insertbackground=ModernStyle.ACCENT_PRIMARY)
                ent.pack(side="left", fill="x", expand=True, padx=(8, 8), pady=3, ipady=4)

                m_focused = [False]
                def _m_in(_e, b=box):
                    m_focused[0] = True
                    b.configure(bg=ModernStyle.ACCENT_PRIMARY)
                def _m_out(_e, b=box):
                    m_focused[0] = False
                    b.configure(bg=ModernStyle.BORDER_COLOR)
                def _m_hi(_e, b=box):
                    if not m_focused[0]:
                        b.configure(bg=ModernStyle.TEXT_TERTIARY)
                def _m_ho(_e, b=box):
                    if not m_focused[0]:
                        b.configure(bg=ModernStyle.BORDER_COLOR)

                ent.bind("<FocusIn>", _m_in, add="+")
                ent.bind("<FocusOut>", _m_out, add="+")
                for w in (box, inner, ent):
                    w.bind("<Enter>", _m_hi, add="+")
                    w.bind("<Leave>", _m_ho, add="+")

        top.set_status("Values are kept in the form; press Save & Close (or Save on the Watchlist page) to store them.")

        self._fetch_btn = action_button(top.actions_frame, "✨ Auto-Fill (yfinance)", self._auto_fetch_metrics,
                                        soft=True, width=210,
                                        canvas_bg=ModernStyle.BG_SECONDARY)
        self._fetch_btn.pack(side="left", padx=(0, 10))
        if self._autofill_running:
            self._fetch_btn.set_text("🔄 Fetching…")

        def _save_and_close():
            if self._on_save():
                top.destroy()

        secondary_button(top.actions_frame, "✕ Close", top.close,
                         canvas_bg=ModernStyle.BG_SECONDARY).pack(side="right")
        action_button(top.actions_frame, "✓ Save & Close", _save_and_close,
                      canvas_bg=ModernStyle.BG_SECONDARY).pack(side="right", padx=(0, 10))

        top.bind("<Escape>", lambda _e: top.close())
        # Enter saves and closes (not inside a multi-line box, where it starts a new line)
        top.bind("<Return>", lambda e: None if isinstance(e.widget, tk.Text) else _save_and_close())
        top.focus_set()

    # ── Double-click diagnostic pop-up ────────────────────────────────────────

    def _open_diagnostic_popup(self, row: dict):
        sym = row.get("symbol", "Symbol")
        stock_name = row.get("stock_name", "")
        popup_title = f"{stock_name} ({sym})" if stock_name else sym

        geometry = _fit_to_screen(self, 1000, 1100)
        popup_w = int(geometry.split("x")[0])
        top = PremiumModal(self, title=popup_title, geometry=geometry, icon="scan-search", icon_color="#EC4899")
        top.resizable(True, True)
        top.minsize(640, 420)
        top.add_chip("📈", sym, bg_color=ModernStyle.ACCENT_PRIMARY, fg_color=ModernStyle.TEXT_ON_ACCENT)

        canvas, scrollable_frame = _make_scroll_area(top.content_frame, ModernStyle.BG_SECONDARY)
        _bind_popup_scroll(top, canvas)

        secondary_button(top.actions_frame, "✕ Close", top.close,
                         canvas_bg=ModernStyle.BG_SECONDARY).pack(side="right")
        top.set_status("Esc closes this window.")

        # ── Signal banner ──────────────────────────────────────────────────
        key, badge, tip = compute_signal(row)
        badge_fg, badge_bg, _fill = signal_colours(key)
        wrap = max(360, popup_w - 200)

        sig_frame = tk.Frame(scrollable_frame, bg=badge_bg, highlightthickness=1, highlightbackground=badge_fg)
        sig_frame.pack(fill="x", padx=20, pady=(0, 20))
        sig_inner = tk.Frame(sig_frame, bg=badge_bg)
        sig_inner.pack(fill="both", padx=12, pady=8)

        tk.Label(sig_inner, text=badge, fg=badge_fg, bg=badge_bg,
                 font=ModernStyle.FONT_MODAL_TITLE).pack(anchor="w")
        tk.Label(sig_inner, text="ℹ️ Decision Rationale:", fg=badge_fg, bg=badge_bg,
                 font=ModernStyle.FONT_HEADING).pack(anchor="w", pady=(8, 4))
        for line in tip.split("\n"):
            if not line.strip():
                continue
            if line.startswith("✅"):
                line_fg = ModernStyle.SUCCESS if key != "strong_buy" else badge_fg
            elif line.startswith("❌"):
                line_fg = ModernStyle.ERROR if key != "avoid" else badge_fg
            else:
                line_fg = ModernStyle.TEXT_PRIMARY
            tk.Label(
                sig_inner, text=line, fg=line_fg, bg=badge_bg,
                font=ModernStyle.FONT_HEADING if line.startswith("Signal:") else ModernStyle.FONT_TABLE,
                justify="left", anchor="w", wraplength=wrap
            ).pack(anchor="w", padx=5)

        def evaluate_benchmark(key: str, val_str: str) -> bool | None:
            val = parse_num(val_str)
            if val is None:
                return None
            if key in ("eps", "roe", "roce", "opm", "sales_growth", "profit_growth", "ebitda_margin",
                       "net_profit_margin", "revenue_cagr_3y", "profit_cagr_3y"):
                return val >= 10.0
            if key in ("peg_ratio", "pb_ratio"):
                return val < 2.0
            if key == "debt_to_equity":
                return val < 1.0
            if key in ("free_cash_flow", "qoq_op_profit", "macd"):
                return val > 0.0
            if key == "sharpe_ratio":
                return val >= 1.0
            if key == "rsi":
                return 30.0 <= val <= 65.0
            if key == "beta":
                return val < 1.5
            if key == "current_ratio":
                return val >= 1.5
            return None  # P/E needs an industry comparison; others are context only

        cy = "¥" if str(sym).upper().endswith(".T") else "₹"
        gn = graham_number(row)
        values = dict(row)
        values["graham_number"] = f"{cy}{gn:,.2f}" if gn else ""
        values["target_price"] = (f"{cy}{parse_num(row.get('target_price')):,.2f}"
                                  if (parse_num(row.get("target_price")) or 0) > 0 else "")
        available = set(row.keys()) | {"graham_number"}

        groups = [
            ("Financial Ratios & Valuation Metrics", [
                ("P/E Ratio", "pe_ratio", "Compare with Industry"),
                ("PEG Ratio", "peg_ratio", "< 1.0 (Best) or < 2.0"),
                ("EPS", "eps", "Double Digits (>10)"),
                ("Debt to Equity", "debt_to_equity", "< 1.0"),
                ("Book Value", "book_value", "Compare to Price"),
                ("Intrinsic Value", "intrinsic_value", "Higher than Market Price"),
                ("Graham Number", "graham_number", "Higher than Market Price"),
                ("My Target Price", "target_price", "Your own buy target"),
            ]),
            ("Profitability & Efficiency Metrics", [
                ("ROE", "roe", "Double Digits"),
                ("ROCE", "roce", "Double Digits"),
                ("OPM (%)", "opm", "> 10% - 15%"),
                ("Free Cash Flow", "free_cash_flow", "Must be Positive"),
                ("Inventory Days", "inventory_days", "Lower is generally better"),
            ]),
            ("Growth Metrics", [
                ("3Y Rev CAGR", "revenue_cagr_3y", "Consistent > 10%"),
                ("3Y Profit CAGR", "profit_cagr_3y", "Consistent > 10%"),
                ("Sales Growth", "sales_growth", "Double Digits"),
                ("Profit Growth", "profit_growth", "Double Digits"),
                ("QoQ Op. Profit", "qoq_op_profit", "Positive / Growth"),
            ]),
            ("Operational & Ownership Metrics", [
                ("Promoter Holding", "promoter_holding", "High & Stable"),
                ("Pledged Shares", "pledged_shares", "Zero (Ideal)"),
                ("FII / DII Holding", "fii_dii_holding", "Increasing / Stable"),
                ("Order Book", "order_book", "High Visibility"),
            ]),
            ("Technical Analysis Metrics (Entry/Exit)", [
                ("50 & 200 DMA", "dma_50_200", "Above the lines"),
                ("RSI", "rsi", "30 (Oversold) / 70 (Overbought)"),
                ("MACD", "macd", "Positive Momentum"),
                ("Support/Resistance", "support_resistance", "Context Near Support"),
                ("Volume", "volume", "Increasing"),
            ]),
            ("Additional Valuation & Risk Metrics", [
                ("EBITDA Margin (%)", "ebitda_margin", "> 15%"),
                ("Net Profit Margin (%)", "net_profit_margin", "> 10%"),
                ("P/B Ratio", "pb_ratio", "< 2.0 (Fairly Valued)"),
                ("Current Ratio", "current_ratio", ">= 1.5 (Liquid)"),
                ("Beta", "beta", "< 1.5 (Lower Vol)"),
                ("Dividend Yield", "dividend_yield", "Stable / Growing"),
                ("Capex", "capex", "Expansion Indicator"),
            ]),
            ("Market Overview", [
                ("Market Cap", "market_cap", "Context Only"),
                ("52-Week Range", "week52_range", "Context Only"),
                ("Analyst Target", "analyst_target", "vs Current Price"),
                ("Sharpe Ratio", "sharpe_ratio", "> 1.0 (Good Risk-Return)"),
            ]),
        ]

        for group_name, fields in groups:
            fields = [f for f in fields if f[1] in available]   # no rows for metrics this database can't hold
            if not fields:
                continue
            card_outer = tk.Frame(scrollable_frame, bg=ModernStyle.BG_SECONDARY, highlightthickness=1,
                                  highlightbackground=ModernStyle.BORDER_COLOR)
            card_outer.pack(fill="x", pady=(0, 20), padx=25)
            tk.Frame(card_outer, bg=ModernStyle.ACCENT_PRIMARY, height=ModernStyle.ACCENT_BAR).pack(fill="x")

            card = tk.Frame(card_outer, bg=ModernStyle.BG_SECONDARY)
            card.pack(fill="both", expand=True, padx=20, pady=15)
            tk.Label(card, text=group_name, fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_SECONDARY,
                     font=ModernStyle.FONT_CARD_TITLE).pack(anchor="w", pady=(0, 15))

            hdr_row = tk.Frame(card, bg=ModernStyle.BG_SECONDARY)
            hdr_row.pack(fill="x", pady=(0, 10))
            target_hdr = "Observation" if "Technical" in group_name else "Ideal Benchmark / Target"
            tk.Label(hdr_row, text="Metric / Ratio", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
                     font=ModernStyle.FONT_TABLE_BOLD, width=22, anchor="w").pack(side="left")
            tk.Label(hdr_row, text="Actual Value", fg=ModernStyle.TEXT_ON_ACCENT, bg=ModernStyle.WARNING_FILL,
                     font=ModernStyle.FONT_SUBHEADING, width=16, anchor="w", padx=10).pack(side="left", padx=20)
            tk.Label(hdr_row, text=target_hdr, fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
                     font=ModernStyle.FONT_TABLE_BOLD, anchor="w").pack(side="left")
            tk.Frame(card, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", pady=(0, 12))

            for label_text, mkey, target_desc in fields:
                val_str = str(values.get(mkey) or "").replace("₹", cy).strip()
                is_pass = evaluate_benchmark(mkey, val_str)
                fg_col = (ModernStyle.SUCCESS if is_pass is True
                          else ModernStyle.ERROR if is_pass is False else ModernStyle.TEXT_PRIMARY)
                display_val = val_str if val_str and val_str != "None" else "—"

                row_fr = tk.Frame(card, bg=ModernStyle.BG_SECONDARY)
                row_fr.pack(fill="x", pady=6)
                tk.Label(row_fr, text=label_text, fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY,
                         font=ModernStyle.FONT_HEADING, width=22, anchor="w").pack(side="left")
                tk.Label(row_fr, text=display_val, fg=fg_col, bg=ModernStyle.BG_SECONDARY,
                         font=ModernStyle.FONT_INPUT, width=16, anchor="w").pack(side="left", padx=20)
                tk.Label(row_fr, text=target_desc, fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
                         font=ModernStyle.FONT_TABLE_BOLD, anchor="w").pack(side="left")

        top.bind("<Escape>", lambda _e: top.destroy())
        top.focus_set()
