"""
Dashboard view for PTracker: a greeting header, ten KPI cards and four tables
(top / worst performers, actionable insights, watchlist alerts).

The Dashboard shows ONE currency at a time (INR or JPY, chosen in the header);
the sidebar and status bar add up all currencies in ₹, so the header subtitle
always says which holdings are shown.

How it works:
  * load_data() paints at once from dashboard_cache.json when that file holds
    the selected currency, then fetches fresh figures in background threads
    (ui.ui_utils.run_in_background). Results come back on the Tk thread. Every
    load has a generation number, so a slower, older result (for example INR
    after a quick switch to JPY) is ignored.
  * Widgets are built once and updated in place, and only when something
    changes: on a Retina Mac every visual change makes Tk redraw the whole
    window (about 0.1 s).
  * Colours and fonts come only from ModernStyle roles, so the light and the
    dark theme both work.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone, time as dtime
from functools import lru_cache
from tkinter import ttk, messagebox

from model.applog import log
from ui.ui_theme import ModernStyle
from ui.ui_utils import (
    HeadingTips,
    ToolTip,
    add_treeview_copy_menu,
    call_on_ui,
    format_money,
    run_in_background,
    show_toast,
    start_ui_dispatcher,
)
from ui.ui_widgets import ModernButton, ModernCard, PremiumModal
from views.base_view import BaseView

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - zoneinfo is in the standard library
    ZoneInfo = None


# ── Constants ──────────────────────────────────────────────────────────────────

_CURRENCY_SYMBOLS = {"INR": "₹", "JPY": "¥", "USD": "$", "GBP": "£", "CNY": "¥"}

_LOAD_TIMEOUT_S = 60       # show "taking too long" + Retry after this
_REFRESH_TIMEOUT_S = 60    # always give the Refresh button back after this
_TABLE_ROWS = 10           # rows visible in each dashboard table


def _roi_bar(v: float, biggest: float) -> str:
    """A 4-block bar showing how big this ROI is next to the table's biggest."""
    n = 0 if not v else max(1, min(4, round(4 * abs(v) / biggest)))
    return "▰" * n + "▱" * (4 - n)


def _pct_cell(v: float) -> str:
    """+12.3% normally; +10,077% for very large values so they fit the column."""
    return f"{v:+,.0f}%" if abs(v) >= 1000 else f"{v:+.1f}%"

# Exchange sessions in each market's OWN time zone (exchange holidays are not known).
# (name, IANA zone, fixed UTC offset used if the zone database is missing, sessions, tooltip)
_MARKETS = (
    ("NSE", "Asia/Kolkata", timedelta(hours=5, minutes=30),
     ((dtime(9, 15), dtime(15, 30)),),
     "NSE (India): 09:15–15:30 IST, Monday to Friday"),
    ("TSE", "Asia/Tokyo", timedelta(hours=9),
     ((dtime(9, 0), dtime(11, 30)), (dtime(12, 30), dtime(15, 30))),
     "TSE (Japan): 09:00–11:30 and 12:30–15:30 JST, Monday to Friday"),
)

# Per-broker symbol rows for the KPI breakdown pop-up (parameters: broker, currency)
_BREAKDOWN_SQL = {
    "total_value": "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)) AS val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)) > 0 ORDER BY val DESC",
    "total_invested": "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), (h.qty * h.avg_price) AS val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND (h.qty * h.avg_price) > 0 ORDER BY val DESC",
    "overall_pnl": "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), running_pnl AS val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND running_pnl != 0 ORDER BY val DESC",
    "unrealized_pnl": "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price) - h.qty*h.avg_price) AS val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price) - h.qty*h.avg_price) != 0 ORDER BY val DESC",
    "unrealized_loss": "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price) - h.qty*h.avg_price) AS val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price) - h.qty*h.avg_price) < 0 ORDER BY val ASC",
    "realized_pnl": "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), realized_pnl AS val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND realized_pnl != 0 ORDER BY val DESC",
    "realized_loss": "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), realized_pnl AS val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND realized_pnl < 0 ORDER BY val ASC",
}

# run_in_background() hands results back through call_on_ui(), which needs
# main.py to have called start_ui_dispatcher(); see _check_ui_dispatcher().
_dispatcher_probe = {"checked": False, "seen": False}


# ── Small utility helpers ──────────────────────────────────────────────────────

def _num(v) -> float:
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _sym(currency: str) -> str:
    return _CURRENCY_SYMBOLS.get((currency or "INR").upper(), "₹")


def _money(v, currency: str = "INR") -> str:
    """Format a float with the correct currency symbol (₹1,234.50, -¥99.00)."""
    return format_money(v, currency)


def _whole_money(v, currency: str = "INR") -> str:
    """Whole currency units with the minus before the symbol: -₹1,012,862."""
    f = _num(v)
    return f"{'-' if f < 0 else ''}{_sym(currency)}{abs(f):,.0f}"


def _pct(v) -> str:
    """Format a float as percentage."""
    try:
        return f"{float(v or 0.0):,.2f}%"
    except Exception:
        return "0.00%"


def _compact_money(v, currency: str = "INR") -> str:
    """Short money: ₹1.20Cr / ₹75.39L / ₹1.3K for INR; ¥1.23M / ¥12.3K for others."""
    code = (currency or "INR").upper()
    sym = _sym(code)
    f = _num(v)
    sign = "-" if f < 0 else ""
    a = abs(f)
    if code == "INR":
        if a >= 1_00_00_000:
            return f"{sign}{sym}{a / 1_00_00_000:.2f}Cr"
        if a >= 1_00_000:
            return f"{sign}{sym}{a / 1_00_000:.2f}L"
    elif a >= 1_000_000:
        return f"{sign}{sym}{a / 1_000_000:.2f}M"
    if a >= 1_000:
        return f"{sign}{sym}{a / 1_000:.1f}K"
    return f"{sign}{sym}{a:,.0f}"


def _fmt_ratio(v) -> str:
    """PE / EPS cell: two decimals, or '-' when missing."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    return f"{f:,.2f}" if f else "-"


def _wrapped_lines(font, text: str, width: int) -> int:
    """How many lines Tk's word wrap gives `text` at `width` pixels."""
    lines, current = 1, ""
    for word in str(text).split():
        trial = f"{current} {word}" if current else word
        if current and font.measure(trial) > width:
            lines += 1
            current = word
        else:
            current = trial
    return lines


def _rgb_hex(rgb) -> str:
    """(r, g, b) tuple from the theme -> Tk colour string."""
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb[:3])


def _mix(a, b, t: float) -> tuple:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _short_error(exc) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text if len(text) <= 80 else text[:77] + "…"


@lru_cache(maxsize=None)
def _market_tz(name: str, fallback: timedelta):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            log.warning("Time zone %s not available; using UTC%+.1f", name, fallback.total_seconds() / 3600)
    return timezone(fallback)


def _market_is_open(tz_name: str, fallback: timedelta, sessions, now_utc: datetime | None = None) -> bool:
    """True when the exchange is in a trading session, judged in its own time zone."""
    local = (now_utc or datetime.now(timezone.utc)).astimezone(_market_tz(tz_name, fallback))
    if local.weekday() >= 5:
        return False
    t = local.time()
    return any(start <= t < end for start, end in sessions)


def _kpi_families() -> dict:
    """Colour families for the KPI cards, from the active theme.

    tint = card body, pale = chips / card border (a little stronger),
    fill = accent bar (solid), text = coloured text readable on tint and pale.
    """
    S = ModernStyle
    return {
        "blue":   {"tint": S.KPI_TINT_BLUE,   "pale": S.ACCENT_PRIMARY_PALE, "fill": S.ACCENT_PRIMARY, "text": S.TEXT_ACCENT},
        "teal":   {"tint": S.KPI_TINT_TEAL,   "pale": S.INFO_PALE,           "fill": S.INFO_FILL,      "text": S.INFO},
        "green":  {"tint": S.KPI_TINT_GREEN,  "pale": S.SUCCESS_PALE,        "fill": S.SUCCESS_FILL,   "text": S.SUCCESS},
        "red":    {"tint": S.KPI_TINT_RED,    "pale": S.ERROR_PALE,          "fill": S.ERROR_FILL,     "text": S.ERROR},
        "amber":  {"tint": S.KPI_TINT_AMBER,  "pale": S.WARNING_PALE,        "fill": S.WARNING_FILL,   "text": S.WARNING},
        "purple": {"tint": S.KPI_TINT_PURPLE, "pale": S.ACCENT_PURPLE_PALE,  "fill": S.PURPLE_FILL,    "text": S.TEXT_PURPLE},
    }


def _query_extras(currency: str) -> dict:
    """Background thread: small facts for the chips and the header subtitle.

    Returns stocks / brokers held, stocks below cost, the newest price time,
    and (only when the view converts currencies) the currencies whose
    exchange rate is a built-in estimate. Never touches Tk.
    """
    from model.database import db_session

    code = (currency or "INR").upper()
    extras: dict = {}
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(DISTINCT symbol), COUNT(DISTINCT broker) FROM holdings "
                "WHERE qty > 0 AND currency = ?", (code,))
            stocks, brokers = cur.fetchone() or (0, 0)
            cur.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT h.symbol,
                           SUM(h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price))
                             - SUM(h.qty * h.avg_price) AS u
                    FROM holdings h LEFT JOIN marketdata m ON h.symbol = m.symbol
                    WHERE h.qty > 0 AND h.currency = ?
                    GROUP BY h.symbol
                ) WHERE u < 0
                """, (code,))
            losing = (cur.fetchone() or (0,))[0]
            cur.execute(
                "SELECT MAX(m.last_updated) FROM marketdata m JOIN holdings h ON h.symbol = m.symbol "
                "WHERE h.qty > 0 AND h.currency = ?", (code,))
            price_time = (cur.fetchone() or (None,))[0]
        extras.update(stocks=int(stocks or 0), brokers=int(brokers or 0),
                      losing=int(losing or 0), price_time=price_time)
    except Exception:
        log.exception("Dashboard: could not count holdings for %s", code)

    if code == "ALL":  # only a mixed-currency view converts with exchange rates
        try:
            import model.engine as engine
            get_estimates = getattr(engine, "get_fx_estimates", None)
            if get_estimates is not None:
                extras["fx_estimates"] = sorted(str(c) for c in (get_estimates() or ()))
        except Exception:
            log.exception("Dashboard: could not read exchange-rate estimates")
    return extras


def _refresh_market_data_work(app_state) -> int:
    """Background thread: fetch prices for every traded / watched symbol, rebuild holdings."""
    from model.database import db_session
    with DashboardView._import_lock:
        from model.engine import fetch_and_update_market_data, rebuild_holdings

    with db_session() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT symbol FROM trades
            UNION
            SELECT DISTINCT symbol FROM watchlist
        """)
        symbols = [r[0] for r in cur.fetchall() if r[0]]
    if symbols:
        fetch_and_update_market_data(symbols)
    rebuild_holdings()
    if app_state is not None and hasattr(app_state, "refresh_data_cache"):
        app_state.refresh_data_cache()
    return len(symbols)


class DashboardView(BaseView):
    """Portfolio dashboard with summary metrics and overview."""

    # Engine imports from several threads at once raced inside PyInstaller builds.
    _import_lock = threading.Lock()

    # (title, key, colour family, icon, is_currency, coloured by gain/loss)
    _KPI_ROW1 = (
        ("Portfolio Value", "total_value",     "blue",   "◆", True,  False),
        ("Total Invested",  "total_invested",  "teal",   "⊕", True,  False),
        ("Today's P&L",     "day_pnl",         "amber",  "◷", True,  True),
        ("Overall P&L",     "overall_pnl",     "purple", "Σ", True,  True),
        ("Unrealised P&L",  "unrealized_pnl",  "blue",   "↗", True,  True),
    )
    _KPI_ROW2 = (
        ("Unrealised Loss", "unrealized_loss", "red",    "↘", True,  True),
        ("Realised P&L",    "realized_pnl",    "green",  "✓", True,  True),
        ("Realised Loss",   "realized_loss",   "red",    "✕", True,  True),
        ("XIRR",            "overall_xirr",    "amber",  "%", False, True),
        ("CAGR",            "overall_cagr",    "teal",   "↑", False, True),
    )

    # Table columns: (id, heading, width, anchor)
    _PERF_COLS = (("num", "#", 34, "center"), ("symbol", "Symbol", 110, "w"),
                  ("avg", "Avg Price", 86, "e"), ("ltp", "Last Price", 86, "e"),
                  ("pnl", "P&L", 96, "e"), ("roi", "ROI %", 118, "e"))
    _INSIGHT_COLS = (("num", "#", 34, "center"), ("symbol", "Symbol", 110, "w"),
                     ("signal", "Signal", 110, "w"), ("current", "Current", 90, "e"),
                     ("iv", "Fair Value", 90, "e"), ("diff", "Upside %", 80, "e"))
    _ALERT_COLS = (("num", "#", 34, "center"), ("symbol", "Symbol", 110, "w"),
                   ("target", "Target", 90, "e"), ("current", "Current", 90, "e"),
                   ("pe", "P/E", 56, "e"), ("eps", "EPS", 60, "e"), ("diff", "Upside %", 80, "e"))
    # What each column means, shown when the pointer rests on a heading
    _COL_TIPS = {
        "avg": "Average price you paid per share",
        "ltp": "Latest market price",
        "current": "Latest market price",
        "pnl": "Profit (▲) or loss (▼) on the shares you still hold",
        "roi": "Gain or loss as a % of what you paid",
        "signal": "▲ Accumulate: price is below fair value\n▼ Reduce: price is above fair value",
        "iv": "Fair value: what the share may really be worth (from the Watchlist valuation)",
        "target": "Your target price from the Watchlist",
        "pe": "Price ÷ earnings per share (lower can mean cheaper)",
        "eps": "Earnings per share over the last year",
        "diff": "How far the fair value or target is above (+) or below (−) today's price",
    }

    def build(self):
        self._ui_built = False
        self._data_loaded = False
        self._refresh_inflight = False
        self._load_gen = 0
        self._load_pending = False
        self._refresh_gen = 0
        self._refresh_active = None
        self._timeouts: dict = {}
        self._clock_after_id = None
        self._clock_ticking = False
        self._kpi_has_data = False
        self._shown_currency = None
        self._alerts_currency = None
        self._error_shown = False
        self._current_metrics: dict = {}
        self._current_performers: dict = {}
        self._current_insights: list = []
        self._current_alerts_data: list = []
        self._current_extras: dict = {}
        self._fonts: dict = {}
        self._families = _kpi_families()
        self._kpi: dict = {}
        self.kpi_labels: dict = {}
        self._kpi_cards: dict = {}
        self._wheel_tag = f"DashWheel{id(self)}"
        self._touch_acc = 0.0

        self.currency_var = tk.StringVar(value="INR")
        self.currency_var.trace_add("write", lambda *_: self.load_data(force=True))

        self._build_header()
        self._build_scroll_area()
        self._build_error_banner()
        self._build_kpi_rows()
        self._build_sections()
        self._install_wheel_scrolling()

        self._ui_built = True
        self._check_ui_dispatcher()
        self._start_clock()

    # ──────────────────────────────────────────────────────────────────────────
    # Header: greeting + subtitle on the gradient, controls in one right-hand frame
    # ──────────────────────────────────────────────────────────────────────────

    def _font(self, spec) -> tkfont.Font:
        f = self._fonts.get(spec)
        if f is None:
            f = self._fonts[spec] = tkfont.Font(root=self, font=spec)
        return f

    @staticmethod
    def _greeting(now: datetime | None = None) -> str:
        """The fixed banner title (the clock on the right shows the time)."""
        return "Portfolio Tracker  ·  Your wealth at a glance"

    def _build_header(self) -> None:
        S = ModernStyle
        self._grad_start = tuple(S.HEADER_GRAD_START)
        self._grad_mid = tuple(getattr(S, "HEADER_GRAD_MID", _mix(self._grad_start, S.HEADER_GRAD_END, 0.5)))
        self._grad_end = tuple(S.HEADER_GRAD_END)
        flat = self._header_flat_bg = _rgb_hex(self._grad_end)
        # "Frosted glass" controls: white let through the banner colour
        glass = self._header_glass = _rgb_hex(_mix(self._grad_end, (255, 255, 255), 0.18))
        glass_edge = _rgb_hex(_mix(self._grad_end, (255, 255, 255), 0.4))

        title_ls = self._font(S.FONT_SYMBOL_LARGE).metrics("linespace")
        body_ls = self._font(S.FONT_BODY).metrics("linespace")
        height = max(84, title_ls + 2 * body_ls + 18)

        c = self._header_canvas = tk.Canvas(self, bg=S.BG_PRIMARY, highlightthickness=0, height=height)
        c.pack(fill="x", padx=20, pady=(4, 0))
        self._header_layout_key = None
        self._grad_key = None
        # Largest greeting font first; smaller ones are used when the window is narrow.
        self._greeting_fonts = (S.FONT_SYMBOL_LARGE, S.FONT_TITLE, S.FONT_HEADING)
        self._greeting_text = self._greeting()
        self._subtitle_text = "Loading portfolio data…"

        self._greeting_id = c.create_text(
            20, 10, text=self._greeting_text, fill=S.HEADER_FG,
            font=S.FONT_SYMBOL_LARGE, anchor="nw", tags="header_content")
        self._header_subtitle = c.create_text(
            20, 54, text=self._subtitle_text, fill=S.HEADER_SUBTLE_FG,
            font=S.FONT_BODY, anchor="nw", tags="header_content")

        # Everything on the right lives in ONE frame anchored to the right edge.
        # The gradient ends just left of it and stays flat underneath, so the
        # frame's solid background matches the banner exactly.
        right = self._header_right = tk.Frame(c, bg=flat)
        top_row = tk.Frame(right, bg=flat)
        top_row.pack(side="top", anchor="e")
        bottom_row = tk.Frame(right, bg=flat)
        bottom_row.pack(side="top", anchor="e", pady=(6, 0))

        # One glass chip per market: green ● while open, hollow ○ while closed
        self._market_chips = {}
        for name, *_rest, tip in _MARKETS:
            chip = tk.Frame(top_row, bg=glass)
            chip.pack(side="left", padx=(0, 6))
            dot = tk.Label(chip, text="○", bg=glass, fg=S.HEADER_FG, font=S.FONT_SMALL_BOLD)
            dot.pack(side="left", padx=(8, 2))
            lbl = tk.Label(chip, text=f"{name} Closed", bg=glass, fg=S.HEADER_FG, font=S.FONT_SMALL_BOLD)
            lbl.pack(side="left", padx=(0, 9), pady=2)
            for w in (chip, dot, lbl):
                ToolTip(w, tip)
            self._market_chips[name] = (dot, lbl)
        self._clock_lbl = tk.Label(top_row, text="", bg=flat, fg=S.HEADER_FG,
                                   font=S.FONT_SUBHEADING, width=5, anchor="e")
        self._clock_lbl.pack(side="left", padx=(4, 0))

        self.top_movers_btn = ModernButton(
            bottom_row, text="★ Movers", command=self._show_gainers_losers_modal,
            bg=glass, fg=S.HEADER_FG, canvas_bg=flat,
            width=106, height=32, radius=8, font=S.FONT_SMALL_BOLD)
        self.top_movers_btn.pack(side="left", padx=(0, 8))

        # INR / JPY toggle: the active side is a white pill with banner-coloured text
        self._currency_frame = tk.Frame(bottom_row, bg=glass, highlightthickness=1,
                                        highlightbackground=glass_edge, highlightcolor=glass_edge)
        self._currency_frame.pack(side="left", padx=(0, 8))
        self.curr_buttons = {}
        for c_name in ("INR", "JPY"):
            btn = tk.Label(self._currency_frame, text=f"{_sym(c_name)} {c_name}", bg=glass,
                           fg=S.HEADER_SUBTLE_FG, font=S.FONT_SMALL_BOLD, padx=10, pady=5, cursor="hand2")
            btn.pack(side="left")
            btn.bind("<Button-1>", lambda _e, n=c_name: self._select_currency(n))
            btn.bind("<Enter>", lambda _e, n=c_name: self._hover_curr(n, True))
            btn.bind("<Leave>", lambda _e, n=c_name: self._hover_curr(n, False))
            self.curr_buttons[c_name] = btn
        self.currency_var.trace_add("write", self._update_curr_toggles)
        self._update_curr_toggles()

        self.refresh_btn = ModernButton(
            bottom_row, text="↻ Refresh", command=self._on_refresh_market_data,
            bg=S.HEADER_FG, fg=flat, canvas_bg=flat,   # the main action: solid white
            width=128, height=32, radius=8, font=S.FONT_SMALL_BOLD)
        self.refresh_btn.pack(side="left")

        self._header_right_win = c.create_window(0, 0, window=right, anchor="e", tags="header_content")
        c.bind("<Configure>", self._layout_header)
        right.bind("<Configure>", self._layout_header)
        self._update_market_status()

    def _select_currency(self, name: str) -> None:
        if self.currency_var.get() != name:
            self.currency_var.set(name)

    def _hover_curr(self, name: str, inside: bool) -> None:
        """Brighten the glass under the pointer so the switch looks clickable."""
        if name != self.currency_var.get():
            glass = _rgb_hex(_mix(self._grad_end, (255, 255, 255), 0.3)) if inside else self._header_glass
            self.curr_buttons[name].configure(bg=glass)

    def _update_curr_toggles(self, *_):
        S = ModernStyle
        active = self.currency_var.get()
        for name, btn in self.curr_buttons.items():
            if name == active:
                btn.configure(bg=S.HEADER_FG, fg=self._header_flat_bg)
            else:
                btn.configure(bg=self._header_glass, fg=S.HEADER_FG)

    def _layout_header(self, _event=None, force: bool = False) -> None:
        """Place the header texts and controls so nothing overlaps at any width."""
        c = self._header_canvas
        try:
            w, h = c.winfo_width(), c.winfo_height()
            rw = self._header_right.winfo_reqwidth()
        except tk.TclError:
            return
        if w < 50 or h < 20:
            return
        key = (w, h, rw, self._greeting_text, self._subtitle_text)
        if key == self._header_layout_key and not force:
            return
        self._header_layout_key = key

        right_x = w - 14
        cluster_left = right_x - rw
        avail = max(140, cluster_left - 24 - 20)

        # The biggest title that fits; drop the tagline as a last resort.
        text, font = self._greeting_text.split("  ·  ")[0], self._greeting_fonts[-1]
        for f in self._greeting_fonts:
            if self._font(f).measure(self._greeting_text) <= avail:
                text, font = self._greeting_text, f
                break
        c.itemconfigure(self._greeting_id, text=text, font=font)
        c.itemconfigure(self._header_subtitle, text=self._subtitle_text, width=avail)

        gb = c.bbox(self._greeting_id)
        sb = c.bbox(self._header_subtitle)
        gh = (gb[3] - gb[1]) if gb else 30
        sh = (sb[3] - sb[1]) if sb else 16
        top = max(2, (h - gh - sh - 2) // 2)
        c.coords(self._greeting_id, 20, top)
        c.coords(self._header_subtitle, 20, top + gh + 2)
        c.coords(self._header_right_win, right_x, h // 2)

        grad_key = (w, h, cluster_left)
        if grad_key != self._grad_key:
            self._grad_key = grad_key
            self._draw_header_gradient(w, h, cluster_left - 16)

    def _draw_header_gradient(self, w: int, h: int, flat_from: int) -> None:
        """Indigo → violet → pink across the text area, flat pink under the controls,
        two soft see-through bubbles and rounded corners."""
        c = self._header_canvas
        c.delete("gradient")
        flat_from = max(1, min(w, int(flat_from)))
        white = (255, 255, 255)
        # (centre x, centre y, radius, how much white shows through); kept clear of the controls
        bubbles = ((flat_from - 1.1 * h, -0.35 * h, 1.0 * h, 0.09),
                   (flat_from - 2.6 * h, 1.25 * h, 0.75 * h, 0.07))
        bands = 64
        for i in range(bands):
            t = i / (bands - 1)
            rgb = _mix(self._grad_start, self._grad_mid, t * 2) if t < 0.5 else \
                _mix(self._grad_mid, self._grad_end, t * 2 - 1)
            x0 = int(i * flat_from / bands)
            x1 = int((i + 1) * flat_from / bands) + 1
            c.create_rectangle(x0, 0, x1, h, fill=_rgb_hex(rgb), outline="", tags="gradient")
            for cx, cy, r, a in bubbles:
                lo, hi = max(x0, cx - r), min(x1, cx + r)
                if hi - lo < 1:
                    continue
                xs = [lo + (hi - lo) * k / 3 for k in range(4)]
                dy = [math.sqrt(max(0.0, r * r - (x - cx) ** 2)) for x in xs]
                top = [(x, max(0.0, cy - d)) for x, d in zip(xs, dy)]
                bot = [(x, min(float(h), cy + d)) for x, d in zip(xs, dy)][::-1]
                c.create_polygon(*top, *bot, fill=_rgb_hex(_mix(rgb, white, a)), outline="", tags="gradient")
        if flat_from < w:
            c.create_rectangle(flat_from, 0, w, h, fill=self._header_flat_bg, outline="", tags="gradient")
        # Rounded corners: paint the page colour outside a 14 px quarter circle
        r = 14
        bg = ModernStyle.BG_PRIMARY
        for (ox, oy, sx, sy) in ((0, 0, 1, 1), (w, 0, -1, 1), (0, h, 1, -1), (w, h, -1, -1)):
            pts = [(ox, oy)]
            pts += [(ox + sx * (r - r * math.cos(math.radians(d))), oy + sy * (r - r * math.sin(math.radians(d))))
                    for d in range(0, 91, 10)]
            c.create_polygon(*pts, fill=bg, outline="", tags="gradient")
        c.tag_lower("gradient")

    def _update_header_subtitle(self) -> None:
        """Say which holdings are shown (the sidebar adds all currencies in ₹)."""
        cur = (self.currency_var.get() or "INR").upper()
        parts = [f"Showing {cur} holdings only"]
        m = self._current_metrics or {}
        if self._kpi_has_data and m:
            total_v = _num(m.get("total_value"))
            total_inv = _num(m.get("total_invested"))
            pnl = _num(m.get("overall_pnl"))
            pct = (pnl / total_inv * 100.0) if total_inv else 0.0
            arrow = "▲" if pnl >= 0 else "▼"
            parts.append(f"Value {_compact_money(total_v, cur)}")
            parts.append(f"P&L {arrow} {_compact_money(abs(pnl), cur)} ({abs(pct):.2f}%)")  # arrow carries the sign
        price_time = self._fmt_price_time((self._current_extras or {}).get("price_time"))
        if price_time:
            parts.append(f"prices as of {price_time}")
        estimates = (self._current_extras or {}).get("fx_estimates") or []
        if cur == "ALL" and estimates:
            parts.append(f"≈ estimated exchange rate ({', '.join(estimates)})")
        text = "  ·  ".join(parts)
        if text != self._subtitle_text:
            self._subtitle_text = text
            self._layout_header()

    @staticmethod
    def _fmt_price_time(ts) -> str:
        if not ts:
            return ""
        try:
            dt = datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return str(ts)
        if dt.date() == datetime.now().date():
            return dt.strftime("%H:%M")
        return dt.strftime("%d %b %H:%M")

    # ──────────────────────────────────────────────────────────────────────────
    # Scrollable content area
    # ──────────────────────────────────────────────────────────────────────────

    def _build_scroll_area(self) -> None:
        S = ModernStyle
        self._vscroll = ttk.Scrollbar(self, orient="vertical")
        self._vscroll_shown = False
        self._main_canvas = tk.Canvas(self, bg=S.BG_PRIMARY, highlightthickness=0, yscrollincrement=4)
        self._main_canvas.pack(side="left", fill="both", expand=True)
        self._vscroll.configure(command=self._main_canvas.yview)
        self._main_canvas.configure(yscrollcommand=self._vscroll.set)

        self._content = tk.Frame(self._main_canvas, bg=S.BG_PRIMARY)
        self._content_id = self._main_canvas.create_window((0, 0), window=self._content, anchor="nw")
        self._content.bind("<Configure>", lambda _e: self._update_scrollregion())
        self._main_canvas.bind("<Configure>", lambda _e: self._sync_content_width())

    def _sync_content_width(self):
        """Give the scrollable content frame the canvas's current width."""
        try:
            w = self._main_canvas.winfo_width()
            if w <= 10:
                return
            current = self._main_canvas.itemcget(self._content_id, "width")
            if int(float(current or 0)) != w:
                self._main_canvas.itemconfigure(self._content_id, width=w)
            self._update_scrollregion()
        except tk.TclError:
            pass

    def _update_scrollregion(self) -> None:
        """Keep the scroll range in step with the content; show the scrollbar only when needed."""
        c = self._main_canvas
        try:
            content_h = self._content.winfo_reqheight()
            view_h = c.winfo_height()
            view_w = c.winfo_width()
        except tk.TclError:
            return
        if view_h <= 10:
            return
        # Fit the tables once the layout has settled (measuring mid-change is unreliable)
        if getattr(self, "_fit_after_id", None):
            self.after_cancel(self._fit_after_id)
        self._fit_after_id = self.after(150, self._run_fit)
        region = f"0 0 {max(1, view_w)} {max(content_h, view_h)}"
        if str(c.cget("scrollregion")) != region:
            c.configure(scrollregion=region)
        need = content_h > view_h + 1
        if need != self._vscroll_shown:
            self._vscroll_shown = need
            if need:
                self._vscroll.pack(side="right", fill="y", before=c)
            else:
                self._vscroll.pack_forget()
                c.yview_moveto(0)

    def _run_fit(self) -> None:
        self._fit_after_id = None
        try:
            content_h = self._content.winfo_reqheight()
            view_h = self._main_canvas.winfo_height()
        except tk.TclError:
            return
        if view_h > 10 and self._fit_tables(content_h, view_h):
            self.after(150, self._update_scrollregion)

    def _section_bodies(self):
        return (self.top_body, self.worst_body, self.insights_body, self.alerts_body)

    def _fit_tables(self, content_h: int, view_h: int) -> bool:
        """Fill the window with the tables exactly, so the Dashboard neither scrolls
        nor leaves an empty strip at the bottom.

        The two rows of tables share whatever height is left: as many rows as fit
        (5 to 10), then any spare height makes the rows a little taller (24-32 px).
        Tables with more rows than fit get their own small scrollbar.
        Returns True when anything changed.
        """
        bodies = self._section_bodies()
        style = ttk.Style(self)
        scale = ModernStyle.TEXT_SCALE
        lo, hi = round(24 * scale), round(34 * scale)
        try:
            rows = int(bodies[0]._tree.cget("height"))
            rh = int(float(style.lookup("Dashboard.Treeview", "rowheight") or ModernStyle.DASHBOARD_ROW_HEIGHT))
        except (tk.TclError, ValueError, TypeError, AttributeError):
            return False
        fixed = content_h - 2 * rows * rh           # everything except the table rows
        budget = view_h - 2 - fixed                 # height the rows of both table rows may use
        new_rows = max(5, min(_TABLE_ROWS, budget // (2 * lo)))
        new_rh = max(lo, min(hi, budget // (2 * new_rows)))
        if (new_rows, new_rh) == (rows, rh):
            return False
        # The cards follow the tables a moment later, so an early measurement can
        # be off; allow a few adjustments per window height, never an endless loop.
        if getattr(self, "_fit_for_height", None) != view_h:
            self._fit_for_height, self._fit_count = view_h, 0
        if self._fit_count >= 6:
            return False
        self._fit_count += 1
        if new_rh != rh:
            style.configure("Dashboard.Treeview", rowheight=new_rh)
        if new_rows != rows:
            for body in bodies:
                body._tree.configure(height=new_rows)
                self._update_table_bar(body)
        return True

    def _follow_content_height(self, card, event=None) -> None:
        """ModernCard only ever grows; the table cards must also shrink when their
        table shows fewer rows, or a blank strip is left under each table."""
        try:
            inset = getattr(card, "_inset", card.highlight_thickness)
            want = (event.height if event is not None else card.content.winfo_reqheight()) + 2 * inset \
                + getattr(card, "_shadow", 0)
            if int(float(card.cget("height"))) != want:
                card.configure(height=want)
                self.after_idle(self._update_scrollregion)
        except (tk.TclError, ValueError):
            pass

    def _install_wheel_scrolling(self) -> None:
        """Mouse wheel / trackpad scrolls the page anywhere over the content.

        A bind tag on every content widget (not bind_all, which the sidebar
        also uses) runs before the widget's class bindings, so tables that
        have nothing to scroll pass the wheel on to the page.
        """
        tag = self._wheel_tag
        self.bind_class(tag, "<MouseWheel>", self._on_mousewheel)
        try:
            self.bind_class(tag, "<TouchpadScroll>", self._on_touchpad_scroll)
        except tk.TclError:
            pass  # Tk 8.6 has no touchpad events
        self._add_wheel_tag(self._main_canvas)

    def _add_wheel_tag(self, widget) -> None:
        tags = widget.bindtags()
        if self._wheel_tag not in tags:
            widget.bindtags((tags[0], self._wheel_tag) + tuple(tags[1:]))
        for child in widget.winfo_children():
            self._add_wheel_tag(child)

    @staticmethod
    def _tree_wants_wheel(widget) -> bool:
        if isinstance(widget, ttk.Treeview):
            try:
                first, last = widget.yview()
                return float(first) > 0.0 or float(last) < 1.0
            except tk.TclError:
                return False
        return False

    def _scroll_page(self, units: int) -> None:
        c = self._main_canvas
        first, last = c.yview()
        if first <= 0.0 and last >= 1.0:
            return
        c.yview_scroll(units, "units")

    def _on_mousewheel(self, event):
        if self._tree_wants_wheel(event.widget):
            return None
        delta = getattr(event, "delta", 0) or 0
        if delta:
            self._scroll_page(-5 if delta > 0 else 5)
        return "break"

    def _on_touchpad_scroll(self, event):
        if self._tree_wants_wheel(event.widget):
            return None
        try:
            low = int(event.delta) & 0xFFFF
        except (TypeError, ValueError):
            return "break"
        dy = low - 0x10000 if low >= 0x8000 else low
        if dy:
            self._touch_acc -= dy
            units = int(self._touch_acc / 4)  # yscrollincrement is 4 px
            if units:
                self._touch_acc -= units * 4
                self._scroll_page(units)
        return "break"

    # ──────────────────────────────────────────────────────────────────────────
    # Error banner (load failed / too slow) with Retry
    # ──────────────────────────────────────────────────────────────────────────

    def _build_error_banner(self) -> None:
        S = ModernStyle
        self._error_banner = tk.Frame(self._content, bg=S.ERROR_PALE, highlightthickness=1,
                                      highlightbackground=S.ERROR, highlightcolor=S.ERROR)
        self._error_lbl = tk.Label(self._error_banner, text="", bg=S.ERROR_PALE, fg=S.ERROR,
                                   font=S.FONT_BODY_BOLD, anchor="w", justify="left", wraplength=640)
        self._error_lbl.pack(side="left", fill="x", expand=True, padx=12, pady=8)
        self._retry_btn = ModernButton(
            self._error_banner, text="↻ Retry", command=self._retry_load,
            bg=S.ERROR_FILL, fg=S.TEXT_ON_ACCENT, canvas_bg=S.ERROR_PALE,
            width=104, height=32, radius=8, font=S.FONT_BODY_BOLD)
        self._retry_btn.pack(side="right", padx=10, pady=6)

    def _show_load_error(self, message: str) -> None:
        S = ModernStyle
        if self._kpi_has_data:
            message += "  Showing the last figures."
        else:
            for key in self._kpi:
                self._tint_kpi_card(key, None)
                self._set_kpi_value(key, "—", fg=S.TEXT_TERTIARY)
                self._set_kpi_chip(key, "Not available")
            for body in (self.top_body, self.worst_body, self.insights_body, self.alerts_body):
                if not body._tree_shown:
                    body._empty_lbl.configure(text="⚠️  Couldn't load this list")
        self._error_lbl.configure(text=f"⚠️  {message}")
        if not self._error_shown:
            self._error_shown = True
            self._error_banner.pack(fill="x", padx=24, pady=(12, 0), before=self._kpi_row1)

    def _hide_error(self) -> None:
        if self._error_shown:
            self._error_shown = False
            self._error_banner.pack_forget()

    def _retry_load(self) -> None:
        self._hide_error()
        self._data_loaded = False
        self.load_data(force=True)

    # ──────────────────────────────────────────────────────────────────────────
    # KPI cards
    # ──────────────────────────────────────────────────────────────────────────

    def _build_kpi_rows(self) -> None:
        S = ModernStyle
        self._kpi_row1 = row1 = tk.Frame(self._content, bg=S.BG_PRIMARY)
        row1.pack(fill="x", padx=20, pady=(16, 6))
        self._kpi_row2 = row2 = tk.Frame(self._content, bg=S.BG_PRIMARY)
        row2.pack(fill="x", padx=20, pady=(6, 4))
        self._kpi_row_keys = (tuple(s[1] for s in self._KPI_ROW1), tuple(s[1] for s in self._KPI_ROW2))
        self._kpi_height_pending = False
        # KPI value fonts, largest first: all cards step down together when a figure won't fit
        self._kpi_value_fonts = (S.FONT_KPI_VALUE, S.FONT_SYMBOL_LARGE, S.FONT_DRILLDOWN_SYM)
        self._kpi_font_idx = 0
        for row, specs, group in ((row1, self._KPI_ROW1, "kpi1"), (row2, self._KPI_ROW2, "kpi2")):
            for i in range(len(specs)):
                row.grid_columnconfigure(i, weight=1, uniform=group)
            for col, (title, key, family, icon, is_cur, signed) in enumerate(specs):
                card = self._make_kpi_card(row, title, key, family, icon, is_cur, signed)
                card.grid(row=0, column=col, sticky="nsew", padx=4, pady=2)

    def _schedule_kpi_heights(self) -> None:
        if not self._kpi_height_pending:
            self._kpi_height_pending = True
            self.after_idle(self._fit_kpi_heights)

    def _fit_kpi_heights(self) -> None:
        """Fit the KPI cards to their width (runs once per idle, after resizes and updates).

        1. Pick the largest value font at which every card's figure fits
           (full figure, else the compact one), the same font for all cards.
        2. Make a row taller when a chip wraps onto more lines.
        """
        self._kpi_height_pending = False
        S = ModernStyle
        cards = [st for st in self._kpi.values() if st.get("avail", 0) > 20]
        idx = len(self._kpi_value_fonts) - 1
        for i, spec in enumerate(self._kpi_value_fonts):
            f = self._font(spec)
            if all(f.measure(self._kpi_text_for(st, f, st["avail"])) <= st["avail"] for st in cards):
                idx = i
                break
        if idx != self._kpi_font_idx:
            self._kpi_font_idx = idx
            for st in self._kpi.values():
                st["value"].configure(font=self._kpi_value_fonts[idx])
            for key in self._kpi:
                self._fit_kpi_value(key, schedule=False)

        font = self._font(S.FONT_TINY_BOLD)
        line = font.metrics("linespace")
        for keys in self._kpi_row_keys:
            extra = 0
            for k in keys:
                st = self._kpi[k]
                if st["chip_shown"] and st["wrap"]:
                    lines = _wrapped_lines(font, st["chip"].cget("text"), st["wrap"])
                    extra = max(extra, (lines - 1) * line)
            height = S.KPI_CARD_HEIGHT + 3 + extra   # +3 for the shadow
            for k in keys:
                card = self._kpi[k]["card"]
                try:
                    if int(card.cget("height")) != height:
                        card.configure(height=height)
                except tk.TclError:
                    pass

    def _make_kpi_card(self, parent, title: str, key: str, family: str, icon: str,
                       is_currency: bool, signed: bool) -> ModernCard:
        """One KPI card: tinted body, coloured accent bar, icon + title, value, chip."""
        S = ModernStyle
        fam = self._families[family]
        tint, pale = fam["tint"], fam["pale"]
        card = ModernCard(
            parent, bg=tint, highlight_color=tint, highlight_thickness=1,
            radius=10, canvas_bg=S.BG_PRIMARY, height=S.KPI_CARD_HEIGHT + 3, expand_height=True, shadow=True)
        # The content frame covers the card; the soft shadow below replaces a border.
        card.content.configure(height=S.KPI_CARD_HEIGHT - 2, highlightthickness=0)

        wrapper = tk.Frame(card.content, bg=tint)
        wrapper.pack(fill="both", expand=True)
        tk.Frame(wrapper, bg=fam["fill"], width=4).pack(side="left", fill="y")
        body = tk.Frame(wrapper, bg=tint)
        body.pack(side="left", fill="both", expand=True, padx=10, pady=6)

        title_row = tk.Frame(body, bg=tint)
        title_row.pack(fill="x")
        icon_lbl = tk.Label(title_row, text=icon, fg=fam["text"], bg=tint, font=S.FONT_ICON)
        icon_lbl.pack(side="left", padx=(0, 6))
        title_lbl = tk.Label(title_row, text=title, fg=S.TEXT_SECONDARY, bg=tint,
                             font=S.FONT_KPI_LABEL, anchor="w")
        title_lbl.pack(side="left", fill="x", expand=True)

        value_lbl = tk.Label(body, text="—", fg=fam["text"], bg=tint, font=S.FONT_KPI_VALUE, anchor="w",
                             bd=0, padx=0, highlightthickness=0)
        value_lbl.pack(fill="x", pady=(2, 2))

        # Small chip on a slightly stronger tint, outlined in the card's colour
        chip = tk.Label(body, text="", fg=fam["text"], bg=pale, font=S.FONT_TINY_BOLD, bd=0,
                        padx=6, pady=1, highlightthickness=1, highlightbackground=fam["text"],
                        highlightcolor=fam["text"], justify="left", anchor="w")
        setattr(value_lbl, "_trend_lbl", chip)  # older code looked the chip up here

        self.kpi_labels[key] = value_lbl
        self._kpi_cards[key] = card
        self._kpi[key] = {
            "card": card, "family": family, "signed": signed, "is_currency": is_currency,
            "tint": family, "hover": False, "body": body, "value": value_lbl, "chip": chip,
            "chip_shown": False, "wrap": None, "fg": fam["text"],
            "full": "—", "short": "—", "shown": "—",
            "tint_widgets": (wrapper, body, title_row, icon_lbl, title_lbl, value_lbl),
        }

        body.bind("<Configure>", lambda e, k=key: self._on_kpi_body_configure(k, e.width))

        # Hover outline + double-click breakdown, bound ONCE through a bind tag
        # shared by the card and everything inside it (no flicker between children).
        tag = f"KpiCard{key}{id(self)}"
        stack = [card]
        while stack:
            w = stack.pop()
            tags = w.bindtags()
            w.bindtags((tags[0], tag) + tuple(tags[1:]))
            try:
                w.configure(cursor="hand2")
            except tk.TclError:
                pass
            stack.extend(w.winfo_children())
        self.bind_class(tag, "<Enter>", lambda _e, k=key: self._kpi_hover(k, True))
        self.bind_class(tag, "<Leave>", lambda _e, k=key: self._on_kpi_leave(k))
        self.bind_class(tag, "<Double-1>",
                        lambda _e, t=title, k=key, cur=is_currency, col=fam["fill"]:
                        self._show_broker_breakdown(t, k, is_currency=cur, color=col))
        return card

    def _on_kpi_body_configure(self, key: str, width: int) -> None:
        st = self._kpi.get(key)
        if not st or width < 20:
            return
        wrap = max(60, width - 18)  # chip text width: body minus the chip's padding and outline
        if st["wrap"] != wrap:
            st["wrap"] = wrap
            st["chip"].configure(wraplength=wrap)
            self._schedule_kpi_heights()
        self._fit_kpi_value(key, width)

    def _kpi_hover(self, key: str, inside: bool) -> None:
        st = self._kpi.get(key)
        if not st or st["hover"] == inside:
            return
        st["hover"] = inside
        fam = self._families[st["tint"]]
        color = fam["fill"] if inside else fam["pale"]
        st["card"].content.configure(highlightbackground=color, highlightcolor=color)

    def _on_kpi_leave(self, key: str) -> None:
        """Only un-hover when the pointer really left the card (not just moved onto a child)."""
        st = self._kpi.get(key)
        if not st:
            return
        card = st["card"]
        inside = False
        try:
            x, y = card.winfo_pointerxy()
            under = card.winfo_containing(x, y)
            inside = under is not None and (under == card or str(under).startswith(str(card) + "."))
        except (tk.TclError, KeyError):
            pass
        if not inside:
            self._kpi_hover(key, False)

    def _tint_kpi_card(self, key: str, value=None, **_legacy) -> None:
        """Give a KPI card its soft background tint.

        Gain/loss cards are green when the value is >= 0 and red when it is
        negative; neutral cards (and cards with no value yet) use their own
        colour. Nothing is touched when the tint is already right, because
        every visual change costs a full-window redraw.
        """
        st = self._kpi.get(key)
        if st is None:
            return
        if st["signed"] and value is not None:
            family = "green" if value >= 0 else "red"
        else:
            family = st["family"]
        if family == st["tint"]:
            return
        st["tint"] = family
        fam = self._families[family]
        card = st["card"]
        set_fill = getattr(card, "set_fill", None)
        if set_fill is not None:
            set_fill(fam["tint"])  # rounded shape + content frame, in place
        else:
            card.bg_color = fam["tint"]
            card.content.configure(bg=fam["tint"])
        for w in st["tint_widgets"]:
            w.configure(bg=fam["tint"])
        border = fam["fill"] if st["hover"] else fam["pale"]
        card.content.configure(highlightbackground=border, highlightcolor=border)
        st["chip"].configure(bg=fam["pale"], fg=fam["text"],
                             highlightbackground=fam["text"], highlightcolor=fam["text"])

    def _set_kpi_value(self, key: str, full: str, short: str | None = None, fg: str | None = None) -> None:
        st = self._kpi.get(key)
        if st is None:
            return
        st["full"], st["short"] = full, (short or full)
        if fg and fg != st["fg"]:
            st["fg"] = fg
            st["value"].configure(fg=fg)
        self._fit_kpi_value(key)

    @staticmethod
    def _kpi_text_for(st: dict, font, avail: int) -> str:
        full = st["full"]
        if avail <= 20 or st["short"] == full or font.measure(full) <= avail:
            return full
        return st["short"]

    def _fit_kpi_value(self, key: str, width: int | None = None, schedule: bool = True) -> None:
        """Show the full figure, or the compact one (₹10.13L) when the card is too narrow."""
        st = self._kpi[key]
        if width is not None:
            st["avail"] = width
        avail = st.get("avail") or st["body"].winfo_width()
        font = self._font(self._kpi_value_fonts[self._kpi_font_idx])
        text = self._kpi_text_for(st, font, avail)
        if text != st["shown"]:
            st["shown"] = text
            st["value"].configure(text=text)
        if schedule and avail > 20 and (font.measure(text) > avail or self._kpi_font_idx > 0):
            self._schedule_kpi_heights()  # try another font size

    def _set_kpi_chip(self, key: str, text: str) -> None:
        st = self._kpi.get(key)
        if st is None:
            return
        chip = st["chip"]
        if text:
            if chip.cget("text") != text:
                chip.configure(text=text)
                self._schedule_kpi_heights()
            if not st["chip_shown"]:
                st["chip_shown"] = True
                chip.pack(anchor="w", pady=(2, 0))
        elif st["chip_shown"]:
            st["chip_shown"] = False
            chip.pack_forget()
            self._schedule_kpi_heights()

    def _show_loading_skeleton(self):
        """Placeholders while the first figures for this currency are fetched."""
        S = ModernStyle
        for key in self._kpi:
            self._tint_kpi_card(key, None)
            self._set_kpi_value(key, "—", fg=S.TEXT_TERTIARY)
            self._set_kpi_chip(key, "⏳ Loading…")
        for body in (self.top_body, self.worst_body, self.insights_body, self.alerts_body):
            self._fill_table(body, [], loading=True)

    # ──────────────────────────────────────────────────────────────────────────
    # Section cards with tables (built once; rows are replaced on each load)
    # ──────────────────────────────────────────────────────────────────────────

    def _build_sections(self) -> None:
        S = ModernStyle
        grid = tk.Frame(self._content, bg=S.BG_PRIMARY)
        grid.pack(fill="both", expand=True, padx=20, pady=(8, 4))
        grid.grid_columnconfigure(0, weight=1, uniform="p")
        grid.grid_columnconfigure(1, weight=1, uniform="p")

        self.top_card, self.top_body = self._section_card(
            grid, "Top Performers", "★", "green", self._PERF_COLS, "No holdings to rank yet",
            copy_command=lambda: self._copy_performers(is_top=True), hint="double-click a row for its trades")
        self.worst_card, self.worst_body = self._section_card(
            grid, "Worst Performers", "▼", "red", self._PERF_COLS, "No holdings to rank yet",
            copy_command=lambda: self._copy_performers(is_top=False), hint="double-click a row for its trades")
        self.insights_card, self.insights_body = self._section_card(
            grid, "Actionable Insights", "◎", "amber", self._INSIGHT_COLS, "No buy / sell signals right now",
            copy_command=self._copy_insights, hint="double-click a row for details")
        self.alerts_card, self.alerts_body = self._section_card(
            grid, "Watchlist Alerts", "◉", "purple", self._ALERT_COLS, "No watchlist alerts",
            copy_command=self._copy_alerts, hint="double-click to buy or sell · grey = watching")

        for card in (self.top_card, self.worst_card, self.insights_card, self.alerts_card):
            card.content.bind("<Configure>", lambda e, c=card: self._follow_content_height(c, e), add="+")
        self.top_card.grid(row=0, column=0, sticky="nsew", padx=6, pady=4)
        self.worst_card.grid(row=0, column=1, sticky="nsew", padx=6, pady=4)
        self.insights_card.grid(row=1, column=0, sticky="nsew", padx=6, pady=4)
        self.alerts_card.grid(row=1, column=1, sticky="nsew", padx=6, pady=4)

        # Double-click opens details / drilldown; Watchlist Alerts opens a trade form
        self.top_body._tree.bind("<Double-1>", lambda e: self._on_symbol_double_click(e, self._open_trade_drilldown))
        self.worst_body._tree.bind("<Double-1>", lambda e: self._on_symbol_double_click(e, self._open_trade_drilldown))
        self.insights_body._tree.bind("<Double-1>", lambda e: self._on_symbol_double_click(e, self._open_insight_drilldown))
        self.alerts_body._tree.bind("<Double-1>", self._on_alert_double_click)
        for body in (self.top_body, self.worst_body, self.insights_body, self.alerts_body):
            HeadingTips(body._tree, self._COL_TIPS)

    def _copy_icon(self, parent, fam: dict, command) -> tk.Canvas:
        """A small "copy" button drawn as two overlapping pages (crisp at any text size)."""
        u = max(1.0, self._font(ModernStyle.FONT_SMALL_BOLD).metrics("linespace") / 18)
        bg, ink = fam["pale"], fam["text"]
        c = tk.Canvas(parent, width=round(30 * u), height=round(24 * u), bg=bg, bd=0, cursor="hand2",
                      highlightthickness=1, highlightbackground=bg, highlightcolor=bg)

        def page(x0, y0, x1, y1, r=2.5 * u):
            pts = (x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
                   x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0)
            c.create_polygon(*pts, smooth=True, fill=bg,
                             outline=ink, width=max(1.5, 1.6 * u))

        page(9 * u, 4 * u, 19 * u, 16 * u)     # back page
        page(13 * u, 8 * u, 23 * u, 20 * u)    # front page, covering the back one's corner
        c.bind("<Enter>", lambda _e: c.configure(highlightbackground=ink))
        c.bind("<Leave>", lambda _e: c.configure(highlightbackground=bg))
        c.bind("<Button-1>", lambda _e: command())
        ToolTip(c, "Copy this table")
        return c

    def _section_card(self, parent, title: str, icon: str, family: str, columns, empty_msg: str,
                      copy_command=None, hint: str = "") -> tuple[ModernCard, tk.Frame]:
        """A card with a coloured header (title, count, Copy) and a fixed-height table."""
        S = ModernStyle
        fam = self._families[family]
        card = ModernCard(parent, bg=S.BG_SECONDARY, highlight_color=S.BG_SECONDARY,
                          highlight_thickness=1, radius=10, canvas_bg=S.BG_PRIMARY, shadow=True)
        tk.Frame(card.content, bg=fam["fill"], height=3).pack(fill="x")

        hdr = tk.Frame(card.content, bg=S.BG_SECONDARY)
        hdr.pack(fill="x", padx=12, pady=4)
        tk.Label(hdr, text=icon, fg=fam["text"], bg=S.BG_SECONDARY, font=S.FONT_HEADING).pack(side="left", padx=(0, 6))
        tk.Label(hdr, text=title, fg=S.TEXT_PRIMARY, bg=S.BG_SECONDARY, font=S.FONT_HEADING).pack(side="left")
        count_lbl = tk.Label(hdr, text="0", fg=fam["text"], bg=fam["pale"], font=S.FONT_SMALL_BOLD, padx=8)
        count_lbl.pack(side="left", padx=(8, 0))

        if copy_command:
            self._copy_icon(hdr, fam, copy_command).pack(side="right")
        if hint:  # packed last, so it is the first thing to give way when the card is narrow
            tk.Label(hdr, text=hint, fg=S.TEXT_SECONDARY, bg=S.BG_SECONDARY,
                     font=S.FONT_SMALL).pack(side="left", padx=(10, 0))

        tk.Frame(card.content, bg=S.DIVIDER_COLOR, height=1).pack(fill="x", padx=12)

        body = tk.Frame(card.content, bg=S.BG_SECONDARY)
        body.pack(fill="both", expand=True, pady=(2, 4))

        tree_frame = tk.Frame(body, bg=S.BG_SECONDARY)
        tv = ttk.Treeview(tree_frame, columns=[c[0] for c in columns], show="headings",
                          height=_TABLE_ROWS, style="Dashboard.Treeview")
        for cid, text, width, anchor in columns:
            tv.heading(cid, text=text)
            tv.column(cid, width=width, minwidth=min(width, 34 if cid == "num" else 56),
                      anchor=anchor, stretch=True)
        tv.tag_configure("evenrow", background=S.TABLE_ROW_ALT)
        tv.tag_configure("oddrow", background=S.BG_SECONDARY)
        tv.tag_configure("gain", foreground=S.SUCCESS)
        tv.tag_configure("loss", foreground=S.ERROR)
        tv.tag_configure("watch", foreground=S.TEXT_SECONDARY)
        tv.tag_configure("hover", background=S.BG_HOVER)   # configured last, so it wins

        def _hover(e, t=tv):
            iid = t.identify_row(e.y)
            prev = getattr(t, "_hover_iid", "")
            if iid == prev:
                return
            if prev and t.exists(prev):
                t.item(prev, tags=tuple(x for x in t.item(prev, "tags") if x != "hover"))
            if iid:
                t.item(iid, tags=tuple(t.item(iid, "tags")) + ("hover",))
            t._hover_iid = iid
        tv.bind("<Motion>", _hover, add="+")
        tv.bind("<Leave>", lambda e, t=tv: _hover(type("E", (), {"y": -1000})(), t), add="+")
        tv.pack(side="left", fill="both", expand=True, padx=(2, 0))
        base = tuple((cid, width) for cid, _t, width, _a in columns)
        tv.bind("<Configure>", lambda e, t=tv, b=base: self._fit_tree_columns(t, b, e.width))
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vsb.set)
        add_treeview_copy_menu(tv)

        empty = tk.Label(body, text="⏳  Loading…", fg=S.TEXT_TERTIARY, bg=S.BG_SECONDARY,
                         font=S.FONT_BODY, anchor="w")
        empty.pack(fill="x", padx=14, pady=10)

        body._tree = tv
        body._tree_frame = tree_frame
        body._vsb = vsb
        body._vsb_shown = False
        body._empty_lbl = empty
        body._empty_msg = empty_msg
        body._tree_shown = False
        body._count_lbl = count_lbl
        return card, body

    def _fill_table(self, body, rows: list, *, loading: bool = False, count: int | None = None) -> None:
        """Replace a table's rows in place. rows = [(values, tags), ...]."""
        tv = body._tree
        children = tv.get_children()
        if children:
            tv.delete(*children)
        for values, tags in rows:
            tv.insert("", "end", values=values, tags=tags)

        count = "…" if loading else str(len(rows) if count is None else count)
        if body._count_lbl.cget("text") != count:
            body._count_lbl.configure(text=count)

        has_rows = bool(rows)
        if has_rows != body._tree_shown:
            body._tree_shown = has_rows
            if has_rows:
                body._empty_lbl.pack_forget()
                body._tree_frame.pack(fill="both", expand=True)
            else:
                body._tree_frame.pack_forget()
                body._empty_lbl.pack(fill="x", padx=14, pady=10)
        if not has_rows:
            text = "⏳  Loading…" if loading else f"—  {body._empty_msg}"
            if body._empty_lbl.cget("text") != text:
                body._empty_lbl.configure(text=text)

        self._update_table_bar(body)

    @staticmethod
    def _update_table_bar(body) -> None:
        """A table's own scrollbar shows only when it has more rows than are visible."""
        tv = body._tree
        try:
            need_bar = len(tv.get_children()) > int(tv.cget("height"))
        except (tk.TclError, ValueError):
            return
        if need_bar != body._vsb_shown:
            body._vsb_shown = need_bar
            if need_bar:
                body._vsb.pack(side="right", fill="y")
            else:
                body._vsb.pack_forget()

    @staticmethod
    def _fit_tree_columns(tv: ttk.Treeview, base, width: int) -> None:
        """Scale the columns to the table's width.

        ttk.Treeview only ever widens columns; when the window is narrow the
        right-hand columns were cut off, so shrink them in proportion here.
        """
        avail = int(width) - 4
        if avail < 80:
            return
        total = sum(w for _c, w in base)
        widths = []
        for i, (cid, w) in enumerate(base):
            if i == len(base) - 1:
                widths.append((cid, max(30, avail - sum(x for _c, x in widths))))
            else:
                widths.append((cid, max(30, int(w * avail / total))))
        for cid, w in widths:
            try:
                if int(tv.column(cid, "width")) != w:
                    tv.column(cid, width=w, minwidth=min(w, 30))
            except tk.TclError:
                return

    @staticmethod
    def _tree_symbol(event) -> str:
        tv = event.widget
        try:
            if tv.identify_region(event.x, event.y) in ("heading", "nothing"):
                return ""
            iid = tv.identify_row(event.y) or tv.focus() or (tv.selection() or ("",))[0]
            values = tv.item(iid, "values") if iid else ()
        except tk.TclError:
            return ""
        return str(values[1]).strip() if values and len(values) > 1 else ""

    def _on_symbol_double_click(self, event, opener) -> None:
        symbol = self._tree_symbol(event)
        if symbol:
            opener(symbol)

    def _render_perf_table(self, frame: tk.Frame, data: list, *, is_top: bool) -> None:
        cur = self.currency_var.get()
        rows = []
        items = [it for it in (data or [])[:_TABLE_ROWS] if isinstance(it, dict)]
        biggest = max((abs(_num(it.get("pnl_pct"))) for it in items), default=0) or 1
        for item in items:
            pnl = _num(item.get("pnl"))
            i = len(rows)
            rows.append((
                (f"{i + 1}", str(item.get("symbol", "")),
                 _compact_money(_num(item.get("avg_price")), cur),
                 _compact_money(_num(item.get("current_price")), cur),
                 f"{'▲' if pnl >= 0 else '▼'} {_compact_money(abs(pnl), cur)}",
                 f"{_roi_bar(_num(item.get('pnl_pct')), biggest)}  {_pct_cell(_num(item.get('pnl_pct')))}"),
                ("evenrow" if i % 2 == 0 else "oddrow", "gain" if pnl >= 0 else "loss"),
            ))
        self._fill_table(frame, rows)

    def _render_insights_table(self, frame: tk.Frame, data: list) -> None:
        rows = []
        for item in data or []:
            i = len(rows)
            stripe = "evenrow" if i % 2 == 0 else "oddrow"
            if not isinstance(item, dict):  # older plain-text insights
                rows.append(((f"{i + 1}", str(item), "-", "-", "-", "-"), (stripe,)))
                continue
            signal = str(item.get("signal", "") or "").strip().upper()
            iv = _num(item.get("iv"))
            cp = _num(item.get("current_price"))
            currency = str(item.get("currency", "INR") or "INR").upper()
            diff_pct = ((iv - cp) / cp * 100.0) if cp else 0.0
            if signal == "ACCUMULATE":
                sig_text, tags = "▲ Accumulate", (stripe, "gain")
            elif signal == "REDUCE":
                sig_text, tags = "▼ Reduce", (stripe, "loss")
            else:
                sig_text, tags = signal.title() or "-", (stripe,)
            rows.append((
                (f"{i + 1}", str(item.get("symbol", "")).strip() or "—", sig_text,
                 format_money(cp, currency), format_money(iv, currency), _pct_cell(diff_pct)),
                tags,
            ))
        self._fill_table(frame, rows)

    def _render_alerts_table(self, frame: tk.Frame, data: list) -> None:
        rows = []
        for item in data or []:
            if not isinstance(item, dict):
                continue
            cp = _num(item.get("current_price"))
            tp = _num(item.get("target_price"))
            diff = _num(item.get("pct_below"))
            cur = item.get("currency", "INR")
            i = len(rows)
            stripe = "evenrow" if i % 2 == 0 else "oddrow"
            rows.append((
                (f"{i + 1}", str(item.get("symbol", "")).strip(),
                 format_money(tp, cur) if tp > 0 else "-",
                 format_money(cp, cur) if cp > 0 else "-",
                 _fmt_ratio(item.get("pe")), _fmt_ratio(item.get("eps")),
                 _pct_cell(diff) if tp > 0 and cp > 0 else "-"),
                (stripe, "watch") if item.get("watch") else (stripe,),
            ))
        # The badge counts real alerts; grey "watching" rows only fill the table
        self._fill_table(frame, rows, count=sum(1 for it in data or [] if isinstance(it, dict) and not it.get("watch")))

    def _on_alert_double_click(self, event):
        symbol = self._tree_symbol(event)
        if not symbol:
            return
        currency = next((str(a.get("currency") or "INR").upper() for a in self._current_alerts_data
                         if isinstance(a, dict) and str(a.get("symbol", "")).strip() == symbol),
                        self.currency_var.get())
        from views.shared_trade_edit import open_quick_add_trade_modal
        open_quick_add_trade_modal(
            parent=self,
            reload_cb=self._reload_after_trade,
            symbol=symbol,
            currency=currency,
            app_state=self.app_state,
        )

    def _reload_after_trade(self) -> None:
        """After a trade is saved from a Dashboard pop-up, fetch fresh figures."""
        self._data_loaded = False
        self.load_data(force=True)

    # ──────────────────────────────────────────────────────────────────────────
    # Live clock (HH:MM, updated once a minute) and market status
    # ──────────────────────────────────────────────────────────────────────────

    def _start_clock(self) -> None:
        if self._clock_ticking:
            return
        self._clock_ticking = True
        self._tick_clock()

    def _stop_clock(self) -> None:
        self._clock_ticking = False
        if self._clock_after_id:
            try:
                self.after_cancel(self._clock_after_id)
            except tk.TclError:
                pass
            self._clock_after_id = None

    def _tick_clock(self) -> None:
        """Update the clock, market badges and greeting, then wait for the next minute."""
        self._clock_after_id = None
        if not self._clock_ticking:
            return  # paused by on_hide
        try:
            if not self.winfo_exists():
                return
            now = datetime.now()
            text = now.strftime("%H:%M")
            if self._clock_lbl.cget("text") != text:
                self._clock_lbl.configure(text=text)
            self._update_market_status()
            greeting = self._greeting(now)
            if greeting != self._greeting_text:
                self._greeting_text = greeting
                self._layout_header()
        except tk.TclError:
            return
        except Exception:
            log.exception("Dashboard clock update failed")
        now = datetime.now()
        delay = (60 - now.second) * 1000 - now.microsecond // 1000 + 50
        self._clock_after_id = self.after(max(200, delay), self._tick_clock)

    def _update_market_status(self) -> None:
        """NSE / TSE open or closed, judged in each exchange's own time zone."""
        now_utc = datetime.now(timezone.utc)
        chips = getattr(self, "_market_chips", {})
        for name, tz_name, offset, sessions, _tip in _MARKETS:
            try:
                is_open = _market_is_open(tz_name, offset, sessions, now_utc)
            except Exception:
                log.exception("Market hours check failed for %s", name)
                is_open = False
            if name in chips:
                dot, lbl = chips[name]
                text = f"{name} {'Open' if is_open else 'Closed'}"
                if lbl.cget("text") != text:
                    lbl.configure(text=text)
                    dot.configure(text="●" if is_open else "○",
                                  fg="#4ADE80" if is_open else ModernStyle.HEADER_FG)

    # ──────────────────────────────────────────────────────────────────────────
    # One-shot timeouts that pause while the view is hidden
    # ──────────────────────────────────────────────────────────────────────────

    def _arm_timeout(self, name: str, seconds: float, callback) -> None:
        self._cancel_timeout(name)
        entry = [time.monotonic() + seconds, callback, None]
        self._timeouts[name] = entry
        if self._is_active or not self._ui_built:
            entry[2] = self.after(int(seconds * 1000), lambda n=name: self._fire_timeout(n))

    def _fire_timeout(self, name: str) -> None:
        entry = self._timeouts.pop(name, None)
        if entry:
            entry[1]()

    def _cancel_timeout(self, name: str) -> None:
        entry = self._timeouts.pop(name, None)
        if entry and entry[2]:
            try:
                self.after_cancel(entry[2])
            except tk.TclError:
                pass

    def _pause_timeouts(self) -> None:
        for entry in self._timeouts.values():
            if entry[2]:
                try:
                    self.after_cancel(entry[2])
                except tk.TclError:
                    pass
                entry[2] = None

    def _resume_timeouts(self) -> None:
        for name, entry in list(self._timeouts.items()):
            if entry[2] is None:
                remaining = max(0.0, entry[0] - time.monotonic())
                entry[2] = self.after(int(remaining * 1000), lambda n=name: self._fire_timeout(n))

    def _check_ui_dispatcher(self) -> None:
        """Results of background work arrive through call_on_ui(), which only
        runs once main.py has called start_ui_dispatcher(). If a probe has not
        come through after 3 s, start the dispatcher here so the Dashboard
        never waits forever."""
        if _dispatcher_probe["checked"]:
            return
        _dispatcher_probe["checked"] = True
        call_on_ui(_dispatcher_probe.__setitem__, "seen", True)

        def _verify():
            if not _dispatcher_probe["seen"]:
                log.warning("UI dispatcher was not running; starting it from the Dashboard")
                start_ui_dispatcher(self.winfo_toplevel())

        self.after(3000, _verify)

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle & Loading
    # ──────────────────────────────────────────────────────────────────────────

    def on_show(self):
        super().on_show()
        # Restart the clock if it was paused when navigating away
        self._start_clock()
        self._resume_timeouts()
        # MacOS Tkinter Bug: When a massive Scrollable Canvas is unmapped (pack_forget)
        # and re-mapped (pack), macOS puts its geometric <Configure> calculations on hold
        # until physical mouse motion wakes the runloop. Because the geometry isn't processed,
        # the inner frame width/height evaluate to 0 and the view looks frozen or empty.
        # So poke the canvas ourselves once the new layout has been computed. This used to
        # force update_idletasks() twice right here, which made every visit wait for two
        # full-window redraws (about 0.6 s); idle callbacks do the same job without the wait.
        self.after_idle(self._sync_content_width)
        self.after(150, self._sync_content_width)

    def on_hide(self):
        """Stop the clock and pause timeouts while the dashboard is not visible."""
        super().on_hide()
        self._stop_clock()
        self._pause_timeouts()

    @staticmethod
    def _cache_path() -> str:
        from model.database import DB_PATH
        return os.path.join(os.path.dirname(DB_PATH) if DB_PATH else os.getcwd(), "dashboard_cache.json")

    def load_data(self, force: bool = False):
        """Load dashboard data for the selected currency without blocking the UI.

        1. Paint at once from dashboard_cache.json when it holds this currency
           (skipped when force=True).
        2. Fetch metrics, performers and insights, and (separately, it is
           slower) watchlist alerts in background threads. Results are applied
           on the Tk thread; results of an older load are ignored.
        """
        if self._data_loaded and not force:
            return
        self._data_loaded = True
        currency = (self.currency_var.get() or "INR").upper()
        self._load_gen += 1
        gen = self._load_gen

        painted = False if force else self._paint_from_cache(currency)
        if not painted and (currency != self._shown_currency or not self._kpi_has_data):
            self._kpi_has_data = False
            self._show_loading_skeleton()
            self._update_header_subtitle()

        if painted and not self._engine_cache_invalid():
            # The saved figures are current: refresh only the small extras
            # (counts, price time), and the alerts if the cache had none.
            run_in_background(lambda: _query_extras(currency),
                              on_done=lambda ex, g=gen: self._on_extras_loaded(g, ex),
                              widget=self, name="dashboard-extras")
            if self._alerts_currency != currency:
                self._start_alerts_load(gen, currency)
            return

        self._load_pending = True
        self._arm_timeout("load", _LOAD_TIMEOUT_S, lambda g=gen: self._on_load_timeout(g))
        run_in_background(lambda: self._fetch_main(currency, force),
                          on_done=lambda res, g=gen: self._on_main_loaded(g, res),
                          on_error=lambda exc, g=gen: self._on_main_failed(g, exc),
                          widget=self, name="dashboard-load")
        self._start_alerts_load(gen, currency)

    def _start_alerts_load(self, gen: int, currency: str) -> None:
        run_in_background(lambda: self._fetch_alerts(currency),
                          on_done=lambda alerts, g=gen: self._on_alerts_loaded(g, alerts),
                          on_error=lambda exc, g=gen: self._on_alerts_failed(g, exc),
                          widget=self, name="dashboard-alerts")

    @staticmethod
    def _engine_cache_invalid() -> bool:
        """True when the engine dropped its cached metrics (e.g. after a background refresh)."""
        try:
            from model.engine import _metrics_cache, _cache_lock
            with _cache_lock:
                return _metrics_cache["data"] is None
        except Exception:
            log.exception("Dashboard: could not check the metrics cache")
            return True

    def _paint_from_cache(self, currency: str) -> bool:
        """Instant paint from the JSON cache saved last time (main thread, ~1 ms)."""
        path = self._cache_path()
        try:
            if not os.path.exists(path):
                return False
            with open(path, "r", encoding="utf-8") as f:
                cached = json.load(f)
        except Exception:
            log.warning("Dashboard cache %s could not be read", path, exc_info=True)
            return False
        if str(cached.get("currency", "")).upper() != currency:
            return False
        metrics = cached.get("metrics") or {}
        if _num(metrics.get("total_invested")) <= 0:
            return False
        self._current_extras = cached.get("extras") or {}
        self._apply_payload(metrics, cached.get("performers") or {}, cached.get("insights") or [],
                            save_cache=False)
        if cached.get("alerts_ok", True):
            self._apply_alerts(cached.get("alerts") or [], save_cache=False)
        else:
            self._alerts_currency = None
            self._fill_table(self.alerts_body, [], loading=True)
        return True

    def _fetch_main(self, currency: str, force: bool) -> dict:
        """Background thread: metrics, performers, insights and extras (no Tk calls)."""
        with DashboardView._import_lock:
            from model.engine import get_dashboard_metrics, get_top_worst_performers, get_actionable_insights
        with ThreadPoolExecutor(max_workers=4) as pool:
            f_metrics = pool.submit(get_dashboard_metrics, force_refresh=force, currency_filter=currency, _rebuild=False)
            f_perf = pool.submit(get_top_worst_performers, 10, currency_filter=currency)
            f_insights = pool.submit(get_actionable_insights, currency_filter=currency)
            f_extras = pool.submit(_query_extras, currency)
            return {
                "metrics": f_metrics.result(),
                "performers": f_perf.result(),
                "insights": f_insights.result(),
                "extras": f_extras.result(),
            }

    @staticmethod
    def _fetch_alerts(currency: str) -> list:
        """Background thread: watchlist alerts (no Tk calls)."""
        with DashboardView._import_lock:
            from model.engine import get_watchlist_alerts
        return get_watchlist_alerts(currency, fill_to=_TABLE_ROWS)

    def _on_main_loaded(self, gen: int, res: dict) -> None:
        if gen != self._load_gen:
            log.info("Dashboard: ignored an older load result")
            return
        self._load_pending = False
        self._cancel_timeout("load")
        self._hide_error()
        self._current_extras = res.get("extras") or {}
        self._apply_payload(res.get("metrics") or {}, res.get("performers") or {},
                            res.get("insights") or [], save_cache=True)

    def _on_main_failed(self, gen: int, exc: Exception) -> None:
        if gen != self._load_gen:
            return
        self._load_pending = False
        self._cancel_timeout("load")
        self._data_loaded = False  # the next visit (or Retry) tries again
        self._show_load_error(f"Couldn't load the dashboard ({_short_error(exc)}).")

    def _on_load_timeout(self, gen: int) -> None:
        if gen != self._load_gen or not self._load_pending:
            return
        log.warning("Dashboard load is taking more than %d s", _LOAD_TIMEOUT_S)
        self._data_loaded = False
        # A late result is still applied (same generation); Retry starts a new load.
        self._show_load_error("Loading is taking longer than usual.")

    def _on_extras_loaded(self, gen: int, extras: dict) -> None:
        if gen != self._load_gen or not extras:
            return
        self._current_extras = extras
        self._apply_kpis(self._current_metrics or {})
        self._update_header_subtitle()
        self._save_dashboard_cache()

    def _on_alerts_loaded(self, gen: int, alerts: list) -> None:
        if gen != self._load_gen:
            return
        self._apply_alerts(alerts)

    def _on_alerts_failed(self, gen: int, exc: Exception) -> None:
        if gen != self._load_gen:
            return
        if self._alerts_currency != self.currency_var.get():
            self._fill_table(self.alerts_body, [])
            self.alerts_body._empty_lbl.configure(text=f"⚠️  Couldn't load watchlist alerts ({_short_error(exc)})")

    def _apply_alerts(self, alerts: list, save_cache: bool = True):
        self._current_alerts_data = list(alerts or [])
        self._alerts_currency = self.currency_var.get()
        self._render_alerts_table(self.alerts_body, self._current_alerts_data)
        if save_cache:
            self._save_dashboard_cache()

    # ──────────────────────────────────────────────────────────────────────────
    # Payload application
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_payload(
        self,
        metrics: dict,
        performers: dict,
        insights: list,
        is_partial: bool = False,
        save_cache: bool = True
    ) -> None:
        metrics = metrics or {}
        performers = performers or {}
        insights = insights or []
        if not is_partial:
            self._current_metrics = metrics
            self._current_performers = performers
            self._current_insights = insights

        try:
            self._apply_kpis(metrics)
        except Exception:
            log.exception("Dashboard: could not show the KPI figures")
        self._update_header_subtitle()

        if not is_partial:
            try:
                self._render_perf_table(self.top_body, performers.get("top", []) or [], is_top=True)
                self._render_perf_table(self.worst_body, performers.get("worst", []) or [], is_top=False)
                self._render_insights_table(self.insights_body, insights)
            except Exception:
                log.exception("Dashboard: could not fill the tables")

        if not is_partial and save_cache:
            self._save_dashboard_cache()

    def _apply_kpis(self, metrics: dict) -> None:
        S = ModernStyle
        cur = self.currency_var.get()
        ex = self._current_extras or {}
        total_v = _num(metrics.get("total_value"))
        total_inv = _num(metrics.get("total_invested"))
        pnl = _num(metrics.get("overall_pnl"))
        upnl = _num(metrics.get("unrealized_pnl"))
        uloss = _num(metrics.get("unrealized_loss"))
        rpnl = _num(metrics.get("realized_pnl"))
        rloss = _num(metrics.get("realized_loss"))
        xirr = _num(metrics.get("overall_xirr"))
        cagr = _num(metrics.get("overall_cagr"))
        dpnl = _num(metrics.get("day_pnl"))
        # Money is shown in whole units: treat dust as zero, so it never reads "-₹0" on a red card
        pnl, upnl, uloss, rpnl, rloss, dpnl = (0.0 if abs(x) < 0.5 else x
                                               for x in (pnl, upnl, uloss, rpnl, rloss, dpnl))
        self._kpi_has_data = True
        self._shown_currency = cur

        def arrow(v):
            return "▲" if v >= 0 else "▼"

        def own_colour(key):
            return self._families[self._kpi[key]["family"]]["text"]

        # Neutral cards: their own colour
        for key, v in (("total_value", total_v), ("total_invested", total_inv)):
            self._tint_kpi_card(key, None)
            self._set_kpi_value(key, _compact_money(v, cur), _compact_money(v, cur), own_colour(key))

        # Gain / loss cards: green when >= 0, red when negative
        for key, v in (("day_pnl", dpnl), ("overall_pnl", pnl), ("unrealized_pnl", upnl),
                       ("unrealized_loss", uloss), ("realized_pnl", rpnl), ("realized_loss", rloss)):
            self._tint_kpi_card(key, v)
            self._set_kpi_value(key, _compact_money(v, cur), _compact_money(v, cur),
                                S.SUCCESS if v >= 0 else S.ERROR)

        # XIRR / CAGR: the engine returns 0.0 when it has nothing to compute from
        has_xirr = abs(xirr) > 1e-9
        has_cagr = total_inv > 0 and abs(cagr) > 1e-9
        for key, v, ok in (("overall_xirr", xirr, has_xirr), ("overall_cagr", cagr, has_cagr)):
            if ok:
                self._tint_kpi_card(key, v)
                self._set_kpi_value(key, f"{v:,.2f}%", fg=S.SUCCESS if v >= 0 else S.ERROR)
            else:
                self._tint_kpi_card(key, None)
                self._set_kpi_value(key, "—", fg=S.TEXT_TERTIARY)

        # Chips
        pnl_pct = (pnl / total_inv * 100.0) if total_inv else 0.0
        upnl_pct = (upnl / total_inv * 100.0) if total_inv else 0.0
        day_base = total_v - dpnl
        day_pct = (dpnl / day_base * 100.0) if day_base > 0 else 0.0
        stocks, brokers, losing = ex.get("stocks"), ex.get("brokers"), ex.get("losing")
        if stocks:
            held = f"{stocks} stock{'s' if stocks != 1 else ''} · {brokers} broker{'s' if brokers != 1 else ''}"
        else:
            held = "Cost of open positions"
        if losing:
            below = f"▼ {losing} below cost"
        elif losing == 0:
            below = "▲ No stock below cost"
        else:
            below = "Open positions in loss"
        chips = {
            "total_value": f"Invested {_compact_money(total_inv, cur)}",
            "total_invested": held,
            # one line each in a narrow card; the arrow carries the sign
            "day_pnl": f"{arrow(dpnl)} {abs(day_pct):.2f}% today",
            "overall_pnl": f"{arrow(pnl)} {abs(pnl_pct):.1f}% overall",
            "unrealized_pnl": f"{arrow(upnl)} {abs(upnl_pct):.1f}% on holdings",
            "unrealized_loss": below,
            "realized_pnl": f"{arrow(rpnl)} Closed trades",
            "realized_loss": "Closed-trade losses",
            "overall_xirr": "Yearly return" if has_xirr else "Not enough trades yet",
            "overall_cagr": "Yearly growth" if has_cagr else "Not enough data yet",
        }
        for key, text in chips.items():
            self._set_kpi_chip(key, text)

    def _save_dashboard_cache(self) -> None:
        """Persist current dashboard state to JSON cache for zero-latency startup."""
        currency = self.currency_var.get()
        alerts_ok = self._alerts_currency == currency
        data = {
            "currency": currency,
            "metrics": self._current_metrics or {},
            "performers": self._current_performers or {},
            "insights": self._current_insights or [],
            "alerts": self._current_alerts_data if alerts_ok else [],
            "alerts_ok": alerts_ok,
            "extras": self._current_extras or {},
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        path = self._cache_path()
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except Exception:
            log.exception("Could not save the dashboard cache to %s", path)

    # ──────────────────────────────────────────────────────────────────────────
    # Insight drilldown popup
    # ──────────────────────────────────────────────────────────────────────────

    def _open_insight_drilldown(self, symbol: str) -> None:
        symbol = str(symbol or "").strip()
        if not symbol:
            return

        try:
            from model.database import db_session
            with db_session() as conn:
                cur = conn.cursor()

                # Fetch Asset and Market data (two small look-ups by key: quick enough here)
                cur.execute('''
                    SELECT a.intrinsic_value, a.action_signal, a.promoter_holding, a.fii_holding, a.dii_holding,
                           m.current_price, m.pe_ratio, m.eps, m.high_52w, m.low_52w, m.stock_name,
                           m.pb_ratio, m.roe, m.roce, m.debt_to_equity, m.dividend_yield, m.sector, m.previous_close
                    FROM assets a
                    LEFT JOIN marketdata m ON a.symbol = m.symbol
                    WHERE a.symbol = ?
                ''', (symbol,))
                row = cur.fetchone()
                if not row:
                    messagebox.showinfo("Insight Drilldown", f"No asset data found for {symbol}.")
                    return

                (iv, signal, prom_hold, fii_hold, dii_hold, cp, pe, eps, high52, low52, name,
                 pb, roe, roce, d2e, div_yield, sector, prev_close) = row

                iv = _num(iv)
                cp = _num(cp)
                pe = _num(pe)
                eps = _num(eps)
                high52 = _num(high52)
                low52 = _num(low52)
                name = (name or symbol).strip()
                signal = (signal or "UNKNOWN").upper()
                prom_hold = _num(prom_hold)
                fii_hold = _num(fii_hold)
                dii_hold = _num(dii_hold)
                pb = _num(pb)
                roe = _num(roe)
                roce = _num(roce)
                d2e = _num(d2e)
                div_yield = _num(div_yield)
                prev_close = _num(prev_close)
                sector = (sector or "").strip()

                # Fetch Holdings data
                cur.execute('''
                    SELECT SUM(qty), SUM(qty * avg_price), SUM(running_pnl), MAX(currency)
                    FROM holdings WHERE symbol = ?
                ''', (symbol,))
                h_row = cur.fetchone()
                qty = _num(h_row[0])
                inv = _num(h_row[1])
                currency = str(h_row[3] or "INR").upper()

                avg_price = (inv / qty) if qty > 0 else 0.0
                cur_val = qty * cp
                upnl = cur_val - inv
                today_pnl = qty * (cp - prev_close) if prev_close > 0 else 0.0
        except Exception as e:
            log.exception("Insight drilldown for %s failed", symbol)
            messagebox.showerror("Error", f"Failed to load insight details: {e}")
            return

        S = ModernStyle
        modal = PremiumModal(self, title=f"Fundamental Insight — {name}", geometry="800x750", icon="💡")
        modal.add_chip("🏷️", symbol, bg_color=S.BG_TERTIARY, fg_color=S.TEXT_SECONDARY)
        if sector:
            modal.add_chip("🏢", sector, bg_color=S.BG_TERTIARY, fg_color=S.TEXT_SECONDARY)

        diff_pct = ((iv - cp) / cp * 100.0) if cp else 0.0

        if signal == "ACCUMULATE":
            sig_color, sig_bg, sig_fill = S.SUCCESS, S.SUCCESS_PALE, S.SUCCESS_FILL
        elif signal == "REDUCE":
            sig_color, sig_bg, sig_fill = S.ERROR, S.ERROR_PALE, S.ERROR_FILL
        else:
            sig_color, sig_bg, sig_fill = S.WARNING, S.WARNING_PALE, S.WARNING_FILL

        modal.add_chip("⚡", f"{signal} (Gap: {diff_pct:+.1f}%)", bg_color=sig_bg, fg_color=sig_color)

        # Grid layout for cards (2 columns, 2 rows)
        grid = tk.Frame(modal.content_frame, bg=S.BG_SECONDARY)
        grid.pack(fill="both", expand=True)
        grid.grid_columnconfigure(0, weight=1, uniform="ins")
        grid.grid_columnconfigure(1, weight=1, uniform="ins")

        def _card(row, col, heading, color):
            card = ModernCard(grid, bg=S.BG_TERTIARY, canvas_bg=S.BG_SECONDARY,
                              highlight_color=S.BORDER_COLOR, radius=10)
            card.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
            inner = tk.Frame(card.content, bg=S.BG_TERTIARY)
            inner.pack(fill="both", expand=True, padx=14, pady=10)
            tk.Label(inner, text=heading, bg=S.BG_TERTIARY, fg=color,
                     font=S.FONT_SUBHEADING).pack(anchor="w", pady=(0, 8))
            return inner

        def _kv(parent, k, v, v_color=None, font=None):
            f = tk.Frame(parent, bg=S.BG_TERTIARY)
            f.pack(fill="x", pady=2)
            tk.Label(f, text=k, bg=S.BG_TERTIARY, fg=S.TEXT_SECONDARY, font=S.FONT_BODY).pack(side="left")
            tk.Label(f, text=v, bg=S.BG_TERTIARY, fg=v_color or S.TEXT_PRIMARY,
                     font=font or S.FONT_BODY).pack(side="right")

        # Card 1: Valuation
        c1 = _card(0, 0, "🎯 Valuation", S.TEXT_ACCENT)
        _kv(c1, "Current Price:", format_money(cp, currency), font=S.FONT_SUBHEADING)
        _kv(c1, "Intrinsic Value:", format_money(iv, currency), font=S.FONT_SUBHEADING)
        _kv(c1, "52W High:", format_money(high52, currency))
        _kv(c1, "52W Low:", format_money(low52, currency))
        _kv(c1, "Deviation:", f"{diff_pct:+.2f}%", sig_color, font=S.FONT_BODY_BOLD)

        # Card 2: Extended Fundamentals
        c2 = _card(0, 1, "📈 Fundamentals", S.TEXT_PURPLE)
        _kv(c2, "P/E Ratio:", f"{pe:.2f}" if pe else "N/A")
        _kv(c2, "P/B Ratio:", f"{pb:.2f}" if pb else "N/A")
        _kv(c2, "EPS:", f"{eps:.2f}" if eps else "N/A")
        _kv(c2, "ROE:", f"{roe:.1f}%" if roe else "N/A")
        _kv(c2, "ROCE:", f"{roce:.1f}%" if roce else "N/A")
        _kv(c2, "Debt to Equity:", f"{d2e:.2f}" if d2e else "N/A")
        _kv(c2, "Dividend Yield:", f"{div_yield:.2f}%" if div_yield else "N/A")

        # Card 3: Ownership
        c3 = _card(1, 0, "👥 Ownership", S.INFO)
        _kv(c3, "Promoter Holding:", f"{prom_hold:.2f}%" if prom_hold else "N/A")
        _kv(c3, "FII Holding:", f"{fii_hold:.2f}%" if fii_hold else "N/A")
        _kv(c3, "DII Holding:", f"{dii_hold:.2f}%" if dii_hold else "N/A")

        # Card 4: Your Position
        c4 = _card(1, 1, "💼 Your Position", S.WARNING)
        _kv(c4, "Shares Held:", f"{qty:g}")
        _kv(c4, "Avg Price:", format_money(avg_price, currency))
        _kv(c4, "Current Value:", format_money(cur_val, currency))
        _kv(c4, "Unrealised P&L:", format_money(upnl, currency), S.SUCCESS if upnl >= 0 else S.ERROR)
        _kv(c4, "Today's P&L:", format_money(today_pnl, currency), S.SUCCESS if today_pnl >= 0 else S.ERROR)

        # Actions
        quick_type = "BUY" if signal == "ACCUMULATE" else "SELL"

        def _quick_trade():
            modal.destroy()
            from views.shared_trade_edit import open_quick_add_trade_modal
            open_quick_add_trade_modal(
                parent=self,
                reload_cb=self._reload_after_trade,
                symbol=symbol,
                stock_name=name,
                trade_type=quick_type,
                currency=currency,
                app_state=self.app_state,
            )

        btn_text = "▲ Quick Buy" if quick_type == "BUY" else "▼ Quick Sell"

        ModernButton(modal.actions_frame, text=btn_text, command=_quick_trade,
                     bg=sig_fill, fg=S.TEXT_ON_ACCENT, canvas_bg=S.BG_SECONDARY,
                     width=160, height=40, radius=8, font=S.FONT_SUBHEADING).pack(side="left")

        ModernButton(modal.actions_frame, text="✕  Close", command=modal.destroy,
                     bg=S.NEUTRAL_FILL, fg=S.TEXT_ON_ACCENT, canvas_bg=S.BG_SECONDARY,
                     width=110, height=40, radius=8, font=S.FONT_BODY_BOLD).pack(side="right")

    # ──────────────────────────────────────────────────────────────────────────
    # Trade Drilldown popup
    # ──────────────────────────────────────────────────────────────────────────

    def _open_trade_drilldown(self, symbol: str, *, broker: str | None = None) -> None:
        symbol = str(symbol or "").strip()
        if not symbol:
            return
        S = ModernStyle

        display_name = symbol
        try:
            from model.database import db_session
            with db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT stock_name FROM marketdata WHERE symbol = ?", (symbol,))
                row = cur.fetchone()
                if row and row[0] and row[0].strip():
                    display_name = f"{row[0].strip()} ({symbol})"
        except Exception:
            log.warning("Could not read the stock name of %s", symbol, exc_info=True)

        modal = PremiumModal(self, title=f"Trade Drilldown — {display_name}", geometry="1100x650", icon="📊")

        # Chips for context
        modal.add_chip("🏢", broker if broker else "All Brokers", bg_color=S.BG_TERTIARY, fg_color=S.TEXT_ACCENT)
        modal.add_chip("🏷️", symbol, bg_color=S.BG_TERTIARY, fg_color=S.TEXT_SECONDARY)

        # Summary chips (filled in after the trades load)
        modal.buy_chip = tk.Frame(modal.chips_row, bg=S.SUCCESS_PALE, highlightthickness=1, highlightbackground=S.SUCCESS)
        modal.buy_chip.pack(side="left", padx=(12, 6))
        modal.buy_lbl = tk.Label(modal.buy_chip, text="▲ Buy Volume: —", bg=S.SUCCESS_PALE, fg=S.SUCCESS,
                                 font=S.FONT_SMALL_BOLD, padx=8, pady=2)
        modal.buy_lbl.pack()

        modal.sell_chip = tk.Frame(modal.chips_row, bg=S.ERROR_PALE, highlightthickness=1, highlightbackground=S.ERROR)
        modal.sell_chip.pack(side="left", padx=(0, 6))
        modal.sell_lbl = tk.Label(modal.sell_chip, text="▼ Sell Volume: —", bg=S.ERROR_PALE, fg=S.ERROR,
                                  font=S.FONT_SMALL_BOLD, padx=8, pady=2)
        modal.sell_lbl.pack()

        close_btn = ModernButton(
            modal.inner_hdr, text="✕  Close", command=modal.destroy,
            bg=S.NEUTRAL_FILL, fg=S.TEXT_ON_ACCENT, canvas_bg=S.BG_PRIMARY,
            width=110, height=36, radius=8, font=S.FONT_BODY_BOLD)
        close_btn.pack(side="right", anchor="e")

        # Treeview Area
        table_frame = modal.content_frame
        table_frame.pack_configure(fill="both", expand=True)

        cols = ("#", "Date", "Trade ID", "Type", "Qty", "Price", "Fees", "Running Qty", "Avg Cost", "Running P&L", "Broker")
        tv = ttk.Treeview(table_frame, columns=cols, show="headings", height=16)

        style_name = "PremiumDrilldown.Treeview"
        ttk.Style().configure(style_name, rowheight=36, font=S.FONT_TABLE)
        tv.configure(style=style_name)

        widths = [40, 100, 100, 80, 80, 100, 80, 100, 100, 110, 110]
        for c, w in zip(cols, widths):
            tv.heading(c, text=c, anchor="center")
            tv.column(c, width=w, anchor="center")

        add_treeview_copy_menu(tv)

        tv.tag_configure("odd", background=S.BG_SECONDARY)
        tv.tag_configure("even", background=S.TABLE_ROW_ALT)
        tv.tag_configure("buy", foreground=S.SUCCESS, font=S.FONT_TABLE_BOLD)
        tv.tag_configure("sell", foreground=S.ERROR, font=S.FONT_TABLE_BOLD)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tv.yview)
        tv.configure(yscroll=vsb.set)
        tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        def _copy():
            try:
                lines = ["\t".join(cols)]
                for iid in tv.get_children():
                    vals = tv.item(iid, "values")
                    lines.append("\t".join(
                        str(v).replace("₹", "").replace("¥", "").replace(",", "").replace("%", "").strip()
                        for v in vals))
                self.clipboard_clear()
                self.clipboard_append("\n".join(lines))
                show_toast(modal, f"Copied {len(lines) - 1} trades to the clipboard.", type="success")
            except Exception as e:
                log.exception("Copying drilldown trades failed")
                show_toast(modal, f"Couldn't copy the trades: {e}", type="error")

        ModernButton(modal.actions_frame, text="⧉  Copy Trades", command=_copy, bg=S.ACCENT_PRIMARY,
                     fg=S.TEXT_ON_ACCENT, canvas_bg=S.BG_SECONDARY, width=150, height=40, radius=8,
                     font=S.FONT_SUBHEADING).pack(side="left")

        app_state = self.app_state

        def _work():
            from model.data_cache import TradeHistoryFilters
            if app_state is not None and hasattr(app_state, "data_cache"):
                cache = app_state.data_cache
            else:
                from model.data_cache import DataCache
                cache = DataCache()
                cache.refresh_from_db()
            f = TradeHistoryFilters(
                broker=(broker if broker else "All"),
                symbol_like=symbol,
                trade_type="All",
                start_date=None,
                end_date=None,
            )
            df, _ = cache.get_tradehistory_filtered(f)
            # symbol_like matches parts of names (ITC also finds ITCHOTELS): keep this symbol only
            if df is not None and not getattr(df, "empty", True) and "symbol" in df.columns:
                df = df[df["symbol"].astype(str).str.strip().str.upper() == symbol.upper()]
            return df

        def _apply(df):
            children = tv.get_children()
            if children:
                tv.delete(*children)
            if df is None or getattr(df, "empty", True):
                modal.set_status("No trades found for this filter.")
                return

            total_buy = 0.0
            total_sell = 0.0
            for idx, r in enumerate(df.itertuples(index=False)):
                rtype = str(getattr(r, "type", "")).upper()
                qty = _num(getattr(r, "qty", 0.0))
                price = _num(getattr(r, "price", 0.0))
                fee = _num(getattr(r, "fee", 0.0))
                run_qty = _num(getattr(r, "run_qty", 0.0))
                avg_cost = _num(getattr(r, "avg_cost", 0.0))
                rpnl = _num(getattr(r, "running_pnl", 0.0))
                row_currency = str(getattr(r, "currency", "INR") or "INR").upper()
                is_buy = rtype in {"BUY", "B"}
                is_sell = rtype in {"SELL", "S"}
                if is_buy:
                    total_buy += qty
                elif is_sell:
                    total_sell += qty
                type_disp = "▲ Buy" if is_buy else ("▼ Sell" if is_sell else rtype)

                raw_d = str(getattr(r, "date", ""))
                try:
                    disp_d = datetime.strptime(raw_d, "%Y-%m-%d").strftime("%d %b %Y")
                except ValueError:
                    disp_d = raw_d
                vals = (
                    str(idx + 1),
                    disp_d,
                    str(getattr(r, "trade_id", "")),
                    type_disp,
                    f"{qty:g}",
                    format_money(price, row_currency),
                    format_money(fee, row_currency),
                    f"{run_qty:g}",
                    format_money(avg_cost, row_currency),
                    format_money(rpnl, row_currency),
                    str(getattr(r, "broker", "")),
                )
                stripe = "odd" if idx % 2 else "even"
                tv.insert("", "end", values=vals, tags=(stripe, "buy" if is_buy else "sell"))

            modal.buy_lbl.configure(text=f"▲ Buy Volume: {total_buy:g}")
            modal.sell_lbl.configure(text=f"▼ Sell Volume: {total_sell:g}")
            modal.set_status(f"Loaded {len(df)} trades.")

        modal.set_status("Fetching trade history…")
        run_in_background(
            _work, on_done=_apply,
            on_error=lambda exc: modal.set_status(f"Couldn't load the trades: {_short_error(exc)}", is_error=True),
            widget=modal, name="dashboard-trade-drilldown")

    # ──────────────────────────────────────────────────────────────────────────
    # Broker breakdown popup
    # ──────────────────────────────────────────────────────────────────────────

    def _show_broker_breakdown(self, title: str, metric_key: str, *, is_currency: bool = True, color: str = ModernStyle.ACCENT_PRIMARY) -> None:
        S = ModernStyle
        c_val = self.currency_var.get()

        modal = PremiumModal(self, title=title, geometry="640x460", icon="📊")
        modal.add_chip("🏦", "Per broker", bg_color=S.BG_TERTIARY, fg_color=S.TEXT_SECONDARY)
        modal.add_chip("💱", f"{c_val} holdings", bg_color=S.ACCENT_PRIMARY_PALE, fg_color=S.TEXT_ACCENT)

        close_btn = ModernButton(
            modal.inner_hdr, text="✕  Close", command=modal.destroy,
            bg=S.NEUTRAL_FILL, fg=S.TEXT_ON_ACCENT, canvas_bg=S.BG_PRIMARY,
            width=110, height=36, radius=8, font=S.FONT_BODY_BOLD)
        close_btn.pack(side="right", anchor="e")

        # The thin accent line under the header takes the KPI card's colour
        for w in modal.body_card.winfo_children():
            if isinstance(w, tk.Frame) and str(w.cget("height")) == "2":
                w.configure(bg=color)

        table_frame = modal.content_frame
        table_frame.pack_configure(fill="both", expand=True)

        cols = ("#", "Broker", "Value", "% of Total") if is_currency else ("#", "Broker", "Performance Rate")
        tv = ttk.Treeview(table_frame, columns=cols, show="headings", height=16)
        style_name = "Breakdown.Treeview"
        ttk.Style().configure(style_name, rowheight=42, font=S.FONT_DASHBOARD_TABLE)
        tv.configure(style=style_name)
        for c in cols:
            tv.heading(c, text=c, anchor="center")
            width = 50 if c == "#" else (220 if (c == "Broker" or not is_currency) else 160)
            tv.column(c, width=width, stretch=c != "#", anchor="center")

        tv.tag_configure("odd", background=S.BG_SECONDARY)
        tv.tag_configure("even", background=S.TABLE_ROW_ALT)
        tv.tag_configure("sym", foreground=S.TEXT_SECONDARY, font=S.FONT_BODY)
        tv.tag_configure("profit", foreground=S.SUCCESS, font=S.FONT_DASHBOARD_TABLE_BOLD)
        tv.tag_configure("loss", foreground=S.ERROR, font=S.FONT_DASHBOARD_TABLE_BOLD)
        add_treeview_copy_menu(tv)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tv.yview)
        tv.configure(yscroll=vsb.set)
        tv.pack(side="left", fill="both", expand=True)
        modal.set_status("Loading the breakdown…")

        def _work():
            from model.database import db_session
            with DashboardView._import_lock:
                from model.engine import get_metrics_by_broker
            broker_metrics = get_metrics_by_broker(currency_filter=c_val)
            rows = sorted(((str(b), _num((m or {}).get(metric_key))) for b, m in (broker_metrics or {}).items()),
                          key=lambda x: x[1], reverse=True)
            children = {}
            sql = _BREAKDOWN_SQL.get(metric_key)
            if sql:
                try:
                    with db_session() as conn:
                        cur = conn.cursor()
                        for b, _v in rows:
                            cur.execute(sql, (b, c_val.upper()))
                            children[b] = [(s, n, _num(v)) for s, n, v in cur.fetchall()]
                except Exception:
                    log.exception("Failed to fetch the symbol breakdown for %s", metric_key)
            return rows, children

        def _populate(result):
            rows, children = result
            total = sum(v for _b, v in rows)
            if is_currency:
                modal.set_status(f"Total across brokers: {_money(total, c_val)}  ·  double-click a broker to see its stocks")
            else:
                modal.set_status(f"{title} calculated per broker.")
            if len(rows) > 8:
                vsb.pack(side="right", fill="y")
            for idx, (b, v) in enumerate(rows):
                tags = ["odd" if idx % 2 == 0 else "even"]
                if metric_key in {"overall_pnl", "unrealized_pnl", "realized_pnl", "overall_xirr", "overall_cagr", "day_pnl"}:
                    if v > 0:
                        tags.append("profit")
                    elif v < 0:
                        tags.append("loss")
                elif metric_key in {"unrealized_loss", "realized_loss"}:
                    tags.append("loss")
                disp = _money(v, c_val) if is_currency else _pct(v)
                if is_currency:
                    pct = (v / total * 100.0) if total != 0 else 0.0
                    tv.insert("", "end", iid=b, values=(idx + 1, b, disp, f"{pct:.1f}%"), tags=tuple(tags))
                else:
                    tv.insert("", "end", iid=b, values=(idx + 1, b, disp), tags=tuple(tags))
                for sym, name, val in children.get(b, []):
                    if abs(val) <= 0.01:
                        continue
                    share = f"{abs(val) / abs(v) * 100:.1f}%" if abs(v) > 0 else "0.0%"
                    label = f"   ↳ {name}" if name and name != sym else f"   ↳ {sym}"
                    sym_disp = _money(val, c_val) if is_currency else f"{val:.2f}"
                    tv.insert(b, "end", values=("", label, sym_disp, share), tags=("sym",))

        run_in_background(
            _work, on_done=_populate,
            on_error=lambda exc: modal.set_status(f"Couldn't load the breakdown: {_short_error(exc)}", is_error=True),
            widget=modal, name="dashboard-breakdown")

    # ──────────────────────────────────────────────────────────────────────────
    # Market Data Refresh
    # ──────────────────────────────────────────────────────────────────────────

    def _on_refresh_market_data(self) -> None:
        if self._refresh_inflight:
            return
        self._refresh_inflight = True
        self._refresh_gen += 1
        gen = self._refresh_active = self._refresh_gen
        try:
            self.refresh_btn.set_disabled(True)
            self.refresh_btn.set_text("↻ Updating…")
        except tk.TclError:
            pass
        self._arm_timeout("refresh", _REFRESH_TIMEOUT_S,
                          lambda g=gen: self._finish_refresh(f"no answer after {_REFRESH_TIMEOUT_S} s", gen=g))
        app_state = self.app_state
        run_in_background(
            lambda: _refresh_market_data_work(app_state),
            on_done=lambda count, g=gen: self._finish_refresh(gen=g, count=count),
            on_error=lambda exc, g=gen: self._finish_refresh(_short_error(exc), gen=g),
            widget=self, name="dashboard-refresh")

    def _finish_refresh(self, err: str | None = None, gen: int | None = None, count: int | None = None) -> None:
        if gen is not None and gen != self._refresh_active:
            return  # already finished (e.g. by the timeout)
        self._refresh_active = None
        self._refresh_inflight = False
        self._cancel_timeout("refresh")
        try:
            self.refresh_btn.set_text("↻ Refresh")
            self.refresh_btn.set_disabled(False)
        except tk.TclError:
            pass
        if err:
            log.warning("Dashboard price refresh failed: %s", err)
            show_toast(self, f"Couldn't refresh prices: {err}", type="error")
            return
        show_toast(self, f"Prices updated for {count} symbols." if count else "Prices updated.", type="success")
        self._data_loaded = False
        self.load_data(force=True)
        # Also refresh the sidebar's tickers and totals (on the Tk thread)
        sidebar = getattr(self.app_state, "sidebar", None) if self.app_state else None
        for method in ("refresh_tickers", "refresh_sidebar_data"):
            fn = getattr(sidebar, method, None)
            if fn is not None:
                try:
                    fn()
                except Exception:
                    log.exception("Sidebar %s failed after a refresh", method)

    # ──────────────────────────────────────────────────────────────────────────
    # Copy to clipboard
    # ──────────────────────────────────────────────────────────────────────────

    def _copy_text(self, text: str, message: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        show_toast(self, message, type="success")

    def _copy_performers(self, is_top: bool):
        try:
            cur = self.currency_var.get()
            data = (self._current_performers or {}).get("top" if is_top else "worst", []) or []
            data = data[:_TABLE_ROWS]
            if not data:
                show_toast(self, "No performers to copy.", type="info")
                return
            lines = ["Rank\tSymbol\tP&L\tROI%"]
            for i, item in enumerate(data):
                sym = str(item.get("symbol", ""))
                pnl = _num(item.get("pnl"))
                inv = _num(item.get("invested"))
                roi = (pnl / inv * 100.0) if inv > 0 else 0.0
                lines.append(f"#{i + 1}\t{sym}\t{format_money(pnl, cur)}\t{roi:+.1f}%")
            self._copy_text("\n".join(lines), f"Copied {len(data)} performers to the clipboard.")
        except Exception as e:
            log.exception("Copying performers failed")
            show_toast(self, f"Couldn't copy the performers: {e}", type="error")

    def _copy_insights(self):
        try:
            data = self._current_insights or []
            lines = ["Signal\tSymbol\tIV\tCurrent\tGap"]
            for item in data:
                if not isinstance(item, dict):
                    continue
                sym = str(item.get("symbol", "")).strip()
                signal = str(item.get("signal", "") or "").strip().upper()
                iv = _num(item.get("iv"))
                cp = _num(item.get("current_price"))
                cur = str(item.get("currency", "INR") or "INR").upper()
                diff = ((iv - cp) / cp * 100.0) if cp else 0.0
                lines.append(f"{signal}\t{sym}\t{format_money(iv, cur)}\t{format_money(cp, cur)}\t{diff:+.1f}%")
            if len(lines) == 1:
                show_toast(self, "No insights to copy.", type="info")
                return
            self._copy_text("\n".join(lines), f"Copied {len(lines) - 1} insights to the clipboard.")
        except Exception as e:
            log.exception("Copying insights failed")
            show_toast(self, f"Couldn't copy the insights: {e}", type="error")

    def _copy_alerts(self):
        try:
            lines = ["Symbol\tTarget\tCurrent\tPE\tEPS\t% Below"]
            for item in self._current_alerts_data or []:
                if not isinstance(item, dict):
                    continue
                sym = str(item.get("symbol", "")).strip()
                if sym:
                    lines.append(
                        f"{sym}\t{_num(item.get('target_price')):,.2f}\t{_num(item.get('current_price')):,.2f}"
                        f"\t{_fmt_ratio(item.get('pe'))}\t{_fmt_ratio(item.get('eps'))}\t{_num(item.get('pct_below')):,.1f}%")
            if len(lines) == 1:
                show_toast(self, "No alerts to copy.", type="info")
                return
            self._copy_text("\n".join(lines), f"Copied {len(lines) - 1} watchlist alerts to the clipboard.")
        except Exception as e:
            log.exception("Copying alerts failed")
            show_toast(self, f"Couldn't copy the alerts: {e}", type="error")

    # ──────────────────────────────────────────────────────────────────────────
    # Daily movers popup
    # ──────────────────────────────────────────────────────────────────────────

    def _show_gainers_losers_modal(self) -> None:
        S = ModernStyle
        currency = self.currency_var.get()  # read on the Tk thread, before the worker starts

        modal = PremiumModal(self, title="Daily Top 10 Portfolio Movers", geometry="1200x640", icon="🏆")
        modal.add_chip("💱", f"{currency} holdings", bg_color=S.ACCENT_PRIMARY_PALE, fg_color=S.TEXT_ACCENT)
        modal.add_chip("🕐", "Price vs previous close", bg_color=S.BG_TERTIARY, fg_color=S.TEXT_SECONDARY)

        body = modal.content_frame
        body.grid_columnconfigure(0, weight=1, uniform="movers")
        body.grid_columnconfigure(1, weight=1, uniform="movers")
        body.grid_rowconfigure(0, weight=1)

        cols = (("#", 40, "center"), ("Broker", 120, "w"), ("Symbol", 110, "w"), ("Prev Close", 90, "e"),
                ("Price", 90, "e"), ("Change", 100, "e"), ("% Change", 84, "e"))

        def _column(col, title, fill, row_tag, row_fg):
            frame = tk.Frame(body, bg=S.BG_SECONDARY, highlightthickness=1,
                             highlightbackground=fill, highlightcolor=fill)
            frame.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col == 0 else (8, 0))
            tk.Label(frame, text=title, bg=fill, fg=S.TEXT_ON_ACCENT, font=S.FONT_HEADING,
                     pady=8).pack(fill="x")
            tv = ttk.Treeview(frame, columns=[c[0] for c in cols], show="headings",
                              height=10, style="Drilldown.Treeview")
            for name, width, anchor in cols:
                tv.heading(name, text=name)
                tv.column(name, width=width, minwidth=60, anchor=anchor, stretch=True)
            tv.tag_configure("evenrow", background=S.TABLE_ROW_ALT)
            tv.tag_configure("oddrow", background=S.BG_SECONDARY)
            tv.tag_configure(row_tag, foreground=row_fg)
            tv.pack(fill="both", expand=True, padx=8, pady=8)
            base = tuple((name, width) for name, width, _a in cols)
            tv.bind("<Configure>", lambda e, t=tv, b=base: self._fit_tree_columns(t, b, e.width))
            add_treeview_copy_menu(tv)
            return tv

        gainers_tv = _column(0, "▲  Top 10 Gainers", S.SUCCESS_FILL, "gain", S.SUCCESS)
        losers_tv = _column(1, "▼  Top 10 Losers", S.ERROR_FILL, "loss", S.ERROR)

        ModernButton(modal.actions_frame, text="✕  Close", command=modal.destroy,
                     bg=S.NEUTRAL_FILL, fg=S.TEXT_ON_ACCENT, canvas_bg=S.BG_SECONDARY,
                     width=110, height=38, radius=8, font=S.FONT_BODY_BOLD).pack(side="right")
        modal.set_status("Loading today's movers…")

        def _work():
            with DashboardView._import_lock:
                from model.engine import get_daily_gainers_losers
            return get_daily_gainers_losers(limit=10, currency_filter=currency)

        def _populate(result):
            gainers, losers = result
            for tv, items, arrow, tag in ((gainers_tv, gainers, "▲", "gain"), (losers_tv, losers, "▼", "loss")):
                for i, g in enumerate(items or []):
                    cur = g.get("currency", currency)
                    tv.insert("", "end", values=(
                        i + 1,
                        g.get("broker", ""),
                        g.get("symbol", ""),
                        format_money(g.get("prev_close"), cur),
                        format_money(g.get("current_price"), cur),
                        f"{arrow} {format_money(abs(_num(g.get('price_change'))), cur)}",
                        f"{arrow} {abs(_num(g.get('pct_change'))):.2f}%",
                    ), tags=("evenrow" if i % 2 == 0 else "oddrow", tag))
            modal.set_status(f"{len(gainers or [])} gainers and {len(losers or [])} losers today "
                             f"among your {currency} holdings.")

        run_in_background(
            _work, on_done=_populate,
            on_error=lambda exc: modal.set_status(f"Couldn't load today's movers: {_short_error(exc)}", is_error=True),
            widget=modal, name="dashboard-movers")
