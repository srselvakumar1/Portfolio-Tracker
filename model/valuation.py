"""Fair value and BUY / HOLD / REDUCE / SELL decisions: one set of rules for every page.

Holdings, Watchlist, Valuation and the Dashboard all call decide() with the same
company numbers (see model/fundamentals.py), so their signals can't contradict
each other. Everything here is a pure function: no database, no network.

The rules are written up in VALUATION_REVIEW.md (sections 6 and 7). In short:

* Fair value = the median of the methods that apply:
    a) an earnings model (EPS grows, then fades to long-run growth; only the part
       of the profit that needn't be reinvested counts),
    b) the stock's own median P/E of the last few years × normalised EPS,
    c) for lenders (banks, credit companies): a fair price-to-book from ROE.
  A reverse check shows what growth the current price implies.
* Confidence: High when two or more methods agree within 25% and EPS has been
  positive for 3 years; Medium for one method or agreement within 50%; Low otherwise.
* Zones: BUY below fair value × (1 − margin of safety), REDUCE above fair value
  × 1.2, HOLD in between. SELL only on bad news. NONE ("no signal") when the
  data is missing, old or the methods disagree.

The assumptions (required return, growth limits, margins) are settings. These
are choices, not facts, and every decision carries the ones it used.
"""
from __future__ import annotations

import json
import math
import os
import statistics
from dataclasses import dataclass, field
from datetime import datetime

# ── Assumptions ───────────────────────────────────────────────────────────────

DEFAULT_ASSUMPTIONS: dict = {
    "IN": {"required_return": 0.12, "long_run_growth": 0.05, "growth_cap": 0.15,
           "roe_min": 0.12, "roe_min_lender": 0.12},
    "JP": {"required_return": 0.075, "long_run_growth": 0.015, "growth_cap": 0.08,
           "roe_min": 0.08, "roe_min_lender": 0.07},
    "mos_high": 0.25,            # margin of safety needed for BUY at High confidence
    "mos_medium": 0.35,          # ... at Medium confidence
    "reduce_above": 0.20,        # REDUCE when the price is this far above fair value
    "strong_extra": 0.15,        # "Strong Buy": a further 15% below the buy price
    "fv_cut_sell": 0.25,         # SELL when fair value is cut by more than this ...
    "fv_cut_days": 30,           # ... within this many days
    "quality_fail_days": 90,     # SELL for this long after the quality check newly fails
    "price_max_age_days": 5,
    "fundamentals_max_age_days": 120,
    "terminal_pe_cap": 30.0,
    "history_pe_cap": 60.0,
    "default_roe": 0.15,         # used when Yahoo has no ROE (shown as an assumption)
}

COUNTRY_NAMES = {"IN": "India", "JP": "Japan"}
CURRENCY_SIGNS = {"INR": "₹", "JPY": "¥", "USD": "$", "GBP": "£", "EUR": "€", "CNY": "¥"}

# What each page shows for a zone
STORED_SIGNAL = {"BUY": "ACCUMULATE", "HOLD": "HOLD", "REDUCE": "REDUCE", "SELL": "SELL", "NONE": "N/A"}
ZONE_LABEL = {"BUY": "🟢 Accumulate", "HOLD": "⏸ Hold", "REDUCE": "🔻 Reduce",
              "SELL": "⛔ Sell", "NONE": "⚪ No signal"}

_assumption_cache: dict = {"mtime": None, "value": None}


def merge_assumptions(saved: dict | None) -> dict:
    """The defaults with any saved values laid over them (bad values are ignored)."""
    out = json.loads(json.dumps(DEFAULT_ASSUMPTIONS))
    if not isinstance(saved, dict):
        return out
    for key, value in saved.items():
        if key in ("IN", "JP") and isinstance(value, dict):
            for k2, v2 in value.items():
                if k2 in out[key] and isinstance(v2, (int, float)) and not isinstance(v2, bool):
                    out[key][k2] = float(v2)
        elif key in out and not isinstance(out[key], dict) and isinstance(value, (int, float)) \
                and not isinstance(value, bool):
            out[key] = float(value)
    for c in ("IN", "JP"):   # the long-run growth must stay below the required return
        a = out[c]
        if a["long_run_growth"] >= a["required_return"] - 0.01:
            a["long_run_growth"] = a["required_return"] - 0.01
    return out


def load_assumptions() -> dict:
    """The assumptions from settings.json (key "valuation") over the defaults.
    Read again only when the settings file changes."""
    try:
        from model.app_settings import SETTINGS_PATH, load_settings
        mtime = os.path.getmtime(SETTINGS_PATH) if os.path.exists(SETTINGS_PATH) else 0
        if _assumption_cache["value"] is not None and _assumption_cache["mtime"] == mtime:
            return _assumption_cache["value"]
        value = merge_assumptions(load_settings().get("valuation"))
        _assumption_cache.update(mtime=mtime, value=value)
        return value
    except Exception:
        return merge_assumptions(None)


# ── Symbols ───────────────────────────────────────────────────────────────────

def canonical(symbol) -> str:
    """One name per company: "INFY", "INFY.NS" and "INFY.BO" are all "INFY"."""
    s = str(symbol or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s


def country_of(symbol, currency: str | None = None) -> str:
    """JP for Tokyo listings (".T", a 4-digit code or yen), otherwise IN."""
    s = str(symbol or "").strip().upper()
    if s.endswith(".T") or (len(s) == 4 and s.isdigit()) or str(currency or "").upper() == "JPY":
        return "JP"
    return "IN"


def money(value, currency: str = "INR") -> str:
    if value is None:
        return "—"
    sign = CURRENCY_SIGNS.get(str(currency or "").upper(), "₹")
    v = float(value)
    return f"{'-' if v < 0 else ''}{sign}{abs(v):,.0f}" if abs(v) >= 100 else f"{'-' if v < 0 else ''}{sign}{abs(v):,.2f}"


# ── Small helpers ─────────────────────────────────────────────────────────────

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _clean_list(values) -> list[float]:
    out = []
    for v in values or []:
        f = _num(v)
        if f is not None:
            out.append(f)
    return out


def _cagr(newest, oldest, years: int):
    if newest is not None and oldest is not None and newest > 0 and oldest > 0 and years > 0:
        return (newest / oldest) ** (1.0 / years) - 1.0
    return None


def _parse_date(text):
    if not text:
        return None
    if isinstance(text, datetime):
        return text
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(text)[:19], fmt)
        except ValueError:
            continue
    return None


def _age_days(text, now: datetime):
    d = _parse_date(text)
    return None if d is None else max(0.0, (now - d).total_seconds() / 86400.0)


def is_lender(inputs: dict) -> bool:
    """Banks and credit companies: valued on book value, not cash flow."""
    ind = str(inputs.get("industry") or "").lower()
    return any(w in ind for w in ("bank", "credit", "mortgage"))


# ── Methods ───────────────────────────────────────────────────────────────────

def normalised_eps(inputs: dict) -> tuple[float | None, str]:
    """The EPS the fair value is built on, and a note on how it was chosen."""
    ttm = _num(inputs.get("eps_ttm"))
    hist = _clean_list(inputs.get("eps_annual"))[:3]
    if len(hist) >= 3:
        lo, hi = min(hist), max(hist)
        if lo <= 0 or (hi / lo - 1.0) > 0.30:
            return sum(hist) / 3.0, "average of the last 3 years' EPS (earnings swing a lot)"
    if ttm is not None:
        return ttm, "last 12 months' EPS"
    if hist:
        return hist[0], "latest yearly EPS"
    return None, "no EPS"


def growth_rate(inputs: dict, a: dict, roe: float) -> tuple[float, str]:
    """Growth for years 1–5: the lowest of 3-year EPS growth, 3-year revenue
    growth + 2% and the cap; never below 0, and at most 0.8 × ROE."""
    eps = _clean_list(inputs.get("eps_annual"))
    rev = _clean_list(inputs.get("revenue_annual"))
    cands: list[tuple[float, str]] = []
    for series, extra, name in ((eps, 0.0, "EPS growth"), (rev, 0.02, "revenue growth + 2%")):
        years = min(3, len(series) - 1)
        if years >= 2:
            g = _cagr(series[0], series[years], years)
            if g is not None:
                cands.append((g + extra, f"{years}-year {name}"))
    if not cands:
        g, note = a["long_run_growth"], "no growth history, so long-run growth is used"
    else:
        cands.append((a["growth_cap"], "the growth cap"))
        g, note = min(cands)
    if g < 0:
        g, note = 0.0, f"{note} is negative, so 0% is used"
    if g > 0.8 * roe:
        g, note = 0.8 * roe, f"{note}, limited to 0.8 × ROE"
    return g, note


def earnings_model(eps: float, g1: float, roe: float, a: dict) -> float:
    """Present value of 10 years of the profit that needn't be reinvested
    (EPS × (1 − growth ÷ ROE)), plus a final value at year 10."""
    r, gl = a["required_return"], a["long_run_growth"]
    roe = max(roe, gl + 0.02)
    pv, e = 0.0, eps
    for t in range(1, 11):
        g = g1 if t <= 5 else g1 + (gl - g1) * (t - 5) / 5.0
        e *= 1.0 + g
        pv += e * max(0.0, 1.0 - g / roe) / (1.0 + r) ** t
    terminal_pe = min(a.get("terminal_pe_cap", DEFAULT_ASSUMPTIONS["terminal_pe_cap"]), (1.0 - gl / roe) / (r - gl))
    return pv + e * terminal_pe / (1.0 + r) ** 10


def implied_growth(price: float, eps: float, roe: float, a: dict) -> float | None:
    """The growth (years 1–5) that makes the earnings model equal today's price."""
    if not price or not eps or price <= 0 or eps <= 0:
        return None
    lo, hi = -0.30, 0.80
    f = lambda g: earnings_model(eps, g, max(roe, g / 0.8 if g > 0 else roe), a) - price
    if f(lo) > 0 or f(hi) < 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ── Decision ──────────────────────────────────────────────────────────────────

@dataclass
class Decision:
    zone: str = "NONE"                    # BUY, HOLD, REDUCE, SELL or NONE
    strong: bool = False                  # BUY with a further 15% to spare
    price: float | None = None
    currency: str = "INR"
    country: str = "IN"
    fair_value: float | None = None
    low: float | None = None
    high: float | None = None
    methods: list = field(default_factory=list)          # [(name, value)]
    upside: float | None = None           # % : fair value ÷ price − 1
    buy_below: float | None = None
    target: float | None = None
    reduce_above: float | None = None
    expected_return: float | None = None  # % a year to reach the target in 3 years, plus dividends
    confidence: str = "Low"
    margin: float | None = None           # margin of safety used
    quality_pass: bool | None = None
    quality: list = field(default_factory=list)          # [(label, passed or None, detail)]
    reasons: list = field(default_factory=list)
    changes: list = field(default_factory=list)          # what would change this
    notes: list = field(default_factory=list)            # how the fair value was built
    implied_growth: float | None = None
    eps_used: float | None = None
    growth_used: float | None = None
    lender: bool = False
    price_date: str | None = None
    inputs_date: str | None = None
    info_date: str | None = None
    assumptions: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.zone == "BUY" and self.strong:
            return "🟢 Strong Buy"
        return ZONE_LABEL[self.zone]

    @property
    def stored_signal(self) -> str:
        return STORED_SIGNAL[self.zone]

    def text(self) -> str:
        """Everything a page needs to explain the decision, one item per line."""
        m = lambda v: money(v, self.currency)
        lines = [f"Decision: {self.label}  (confidence {self.confidence})"]
        if self.fair_value:
            rng = f"  (range {m(self.low)} – {m(self.high)})" if self.low and self.high and self.high > self.low else ""
            lines.append(f"Fair value: {m(self.fair_value)}{rng}")
            if self.upside is not None:
                lines.append(f"Upside to fair value: {self.upside:+.1f}%")
            lines.append(f"Buy below: {m(self.buy_below)}   ·   Target (2–3 years): {m(self.target)}"
                         f"   ·   Reduce above: {m(self.reduce_above)}")
            if self.expected_return is not None:
                lines.append(f"Yearly return if the target is reached in 3 years (with dividends): "
                             f"{self.expected_return:+.1f}%")
        lines += [f"• {r}" for r in self.reasons]
        if self.changes:
            lines.append("What would change this:")
            lines += [f"• {c}" for c in self.changes]
        if self.notes:
            lines.append("How the fair value was worked out:")
            lines += [f"• {n}" for n in self.notes]
        if self.quality:
            lines.append("Quality check: " + ("passed" if self.quality_pass else
                                              "failed" if self.quality_pass is False else "not enough data"))
            for label, passed, detail in self.quality:
                mark = "✅" if passed else "❌" if passed is False else "·"
                lines.append(f"{mark} {detail}")
        a = self.assumptions
        if a:
            lines.append(f"Assumptions ({COUNTRY_NAMES.get(self.country, self.country)}): required return "
                         f"{a['required_return']*100:.1f}%, long-run growth {a['long_run_growth']*100:.1f}%, "
                         f"growth cap {a['growth_cap']*100:.0f}%, margin of safety "
                         f"{a['mos_high']*100:.0f}% (High) / {a['mos_medium']*100:.0f}% (Medium), "
                         f"reduce above +{a['reduce_above']*100:.0f}%")
        dates = [f"price {self.price_date[:10]}" if self.price_date else "",
                 f"yearly figures {self.inputs_date[:10]}" if self.inputs_date else "",
                 f"latest figures {self.info_date[:10]}" if self.info_date else ""]
        dates = [d for d in dates if d]
        if dates:
            lines.append("Data as of: " + ", ".join(dates))
        return "\n".join(lines)


def check_quality(inputs: dict, a: dict, lender: bool) -> tuple[bool | None, list]:
    """Pass/fail quality test (not a score). Non-financials pass when at most one of
    the available checks fails; lenders must pass both of theirs."""
    checks = []
    roe = _num(inputs.get("roe"))
    roe_min = a["roe_min_lender"] if lender else a["roe_min"]
    if roe is not None:
        checks.append(("ROE", roe >= roe_min, f"ROE {roe*100:.1f}% (needs {roe_min*100:.0f}% or more)"))
    eps = _clean_list(inputs.get("eps_annual"))[:3]
    if len(eps) >= 3:
        checks.append(("EPS", all(e > 0 for e in eps), "EPS positive in each of the last 3 years"
                       if all(e > 0 for e in eps) else "EPS was zero or negative in one of the last 3 years"))
    if not lender:
        fcf = _num(inputs.get("fcf"))
        if fcf is not None:
            checks.append(("FCF", fcf > 0, "Free cash flow positive" if fcf > 0 else "Free cash flow negative"))
        de = _num(inputs.get("debt_to_equity"))
        if de is not None:
            checks.append(("D/E", de < 1.0, f"Debt to equity {de:.2f} (needs below 1.0)"))
    fails = sum(1 for c in checks if c[1] is False)
    if lender:
        result = None if not checks else fails == 0
    else:
        result = None if len(checks) < 2 else fails <= 1
    return result, checks


def fair_value(inputs: dict, a: dict, price: float | None = None):
    """(fair value, low, high, methods, notes, eps used, growth used, roe used, lender)."""
    lender = is_lender(inputs)
    notes: list[str] = []
    eps, eps_note = normalised_eps(inputs)
    roe = _num(inputs.get("roe"))
    if roe is None or roe <= 0:
        roe_used = a["default_roe"]
        notes.append(f"ROE unknown or negative, so {roe_used*100:.0f}% is assumed")
    else:
        roe_used = roe
    methods: list[tuple[str, float]] = []
    g = None
    if eps is not None and eps > 0:
        g, g_note = growth_rate(inputs, a, roe_used)
        v = earnings_model(eps, g, roe_used, a)
        methods.append(("Earnings model", v))
        notes.append(f"EPS {money(eps, inputs.get('currency'))}: {eps_note}")
        notes.append(f"Growth for years 1–5: {g*100:.1f}% ({g_note}), fading to "
                     f"{a['long_run_growth']*100:.1f}% by year 10")
        pes = [p for p in _clean_list(inputs.get("pe_history")) if p > 0]
        if len(pes) >= 2:
            med = min(statistics.median(pes), a["history_pe_cap"])
            methods.append(("Own P/E history", med * eps))
            notes.append(f"Own median P/E of the last {len(pes)} years: {med:.1f}")
    bvps = _num(inputs.get("bvps"))
    if lender and bvps and bvps > 0 and roe is not None and roe > 0:
        r, gl = a["required_return"], a["long_run_growth"]
        pb = (roe - gl) / (r - gl)
        if pb > 0:
            methods.append(("Price-to-book (lender)", bvps * pb))
            notes.append(f"Fair price-to-book {pb:.2f} = (ROE − long-run growth) ÷ (required return − long-run growth)")
    if not methods:
        return None, None, None, [], notes, eps, g, roe_used, lender
    values = [v for _n, v in methods]
    return statistics.median(values), min(values), max(values), methods, notes, eps, g, roe_used, lender


def decide(inputs: dict | None, price, assumptions: dict | None = None, state: dict | None = None,
           price_date=None, now: datetime | None = None) -> Decision:
    """The decision for one stock at one price. `inputs` come from
    model/fundamentals.py, `state` remembers the last fair value and quality result."""
    now = now or datetime.now()
    inputs = inputs or {}
    state = state or {}
    A = assumptions or load_assumptions()
    currency = str(inputs.get("currency") or "").upper() or None
    country = country_of(inputs.get("symbol", ""), currency)
    if not currency:
        currency = "JPY" if country == "JP" else "INR"
    a = dict(A[country])
    for k in ("mos_high", "mos_medium", "reduce_above", "strong_extra", "terminal_pe_cap",
              "history_pe_cap", "default_roe"):
        a[k] = A[k]
    price = _num(price)
    d = Decision(price=price, currency=currency, country=country, assumptions=a,
                 price_date=str(price_date) if price_date else None,
                 inputs_date=inputs.get("inputs_updated_at") or None,
                 info_date=inputs.get("info_updated_at") or None)
    m = lambda v: money(v, currency)
    sell_rules = (f"SELL if 12-month EPS turns negative, fair value is cut by more than "
                  f"{A['fv_cut_sell']*100:.0f}% within {A['fv_cut_days']} days, or the quality check newly fails.")
    stale_rule = (f"No signal if the price is older than {A['price_max_age_days']} days or the company "
                  f"figures are older than {A['fundamentals_max_age_days']} days.")

    # ── Data gate ──
    if not inputs:
        d.reasons.append("No company figures yet: refresh prices (Holdings / Dashboard) or press Refresh All on the Watchlist.")
        return d
    if price is None or price <= 0:
        d.reasons.append("No current price.")
        return d
    age = _age_days(price_date, now)
    if age is not None and age > A["price_max_age_days"]:
        d.reasons.append(f"The price is {age:.0f} days old (limit {A['price_max_age_days']}).")
        return d
    f_age = _age_days(inputs.get("info_updated_at") or inputs.get("inputs_updated_at"), now)
    if f_age is not None and f_age > A["fundamentals_max_age_days"]:
        d.reasons.append(f"The company figures are {f_age:.0f} days old (limit {A['fundamentals_max_age_days']}).")
        return d

    fv, lo, hi, methods, notes, eps_used, g, roe_used, lender = fair_value(inputs, a, price)
    d.notes, d.eps_used, d.growth_used, d.lender, d.methods = notes, eps_used, g, lender, methods
    d.quality_pass, d.quality = check_quality(inputs, a, lender)

    # ── SELL: bad news only ──
    ttm = _num(inputs.get("eps_ttm"))
    if ttm is not None and ttm <= 0:
        d.zone = "SELL"
        d.reasons.append(f"Loss-making: EPS over the last 12 months is {m(ttm)}, so there is no fair value.")
        d.changes.append("Leaves SELL when 12-month EPS is positive again.")
        return d
    if fv:
        prev, changed = _num(state.get("fair_value_prev")), _parse_date(state.get("fv_changed_on"))
        if prev and changed and (now - changed).days <= A["fv_cut_days"] and fv < prev * (1 - A["fv_cut_sell"]):
            d.zone = "SELL"
            d.reasons.append(f"Fair value cut by {(1 - fv / prev)*100:.0f}% on {changed:%Y-%m-%d} "
                             f"(from {m(prev)} to {m(fv)}).")
            d.changes.append(f"Leaves SELL {A['fv_cut_days']} days after the cut, if nothing else is wrong.")
    failed_on = _parse_date(state.get("quality_failed_on"))
    if d.zone != "SELL" and d.quality_pass is False and failed_on and (now - failed_on).days <= A["quality_fail_days"]:
        d.zone = "SELL"
        bad = "; ".join(det for _l, p, det in d.quality if p is False)
        d.reasons.append(f"Quality check newly failed on {failed_on:%Y-%m-%d}: {bad}.")
        d.changes.append(f"Leaves SELL when the quality check passes again, or {A['quality_fail_days']} days after it failed.")

    if not fv:
        if d.zone != "SELL":
            d.reasons.append("No fair-value method applies (no positive EPS, and not a lender with book value).")
        return d

    d.fair_value, d.low, d.high = fv, lo, hi
    d.upside = (fv / price - 1.0) * 100.0
    d.implied_growth = implied_growth(price, eps_used, roe_used, a) if eps_used and eps_used > 0 else None
    if d.implied_growth is not None:
        d.notes.append(f"Today's price assumes about {d.implied_growth*100:.1f}% EPS growth a year for 5 years "
                       f"(then fading), at a {a['required_return']*100:.1f}% required return.")

    # ── Confidence ──
    eps3 = _clean_list(inputs.get("eps_annual"))[:3]
    eps_pos3 = len(eps3) >= 3 and all(e > 0 for e in eps3)
    spread = (hi / lo - 1.0) if len(methods) >= 2 and lo and lo > 0 else None
    if spread is not None and spread <= 0.25 and eps_pos3:
        d.confidence = "High"
    elif len(methods) == 1 or (spread is not None and spread <= 0.50):
        d.confidence = "Medium"
    else:
        d.confidence = "Low"
    if spread is not None:
        d.notes.append("Methods: " + ", ".join(f"{n} {m(v)}" for n, v in methods)
                       + f" (they differ by {spread*100:.0f}%)")

    margin = a["mos_high"] if d.confidence == "High" else a["mos_medium"]
    d.margin = margin
    d.buy_below = fv * (1.0 - margin)
    d.target = fv
    d.reduce_above = fv * (1.0 + a["reduce_above"])
    dy = _num(inputs.get("dividend_yield")) or 0.0
    d.expected_return = ((fv / price) ** (1.0 / 3.0) - 1.0) * 100.0 + dy

    if d.zone == "SELL":
        d.changes.append(sell_rules)
        return d
    if d.confidence == "Low":
        d.zone = "NONE"
        d.reasons.append(f"Not enough confidence: the methods disagree by {spread*100:.0f}% "
                         f"({', '.join(f'{n} {m(v)}' for n, v in methods)}).")
        d.changes.append("A signal appears when the methods agree within 50%.")
        return d

    # ── Zones ──
    pct = lambda level: (level / price - 1.0) * 100.0
    if price <= d.buy_below:
        if d.quality_pass:
            d.zone = "BUY"
            d.strong = price <= fv * (1.0 - margin - a["strong_extra"])
            d.reasons.append(f"Price {m(price)} is at or below the buy price {m(d.buy_below)} "
                             f"({margin*100:.0f}% below fair value, {d.confidence} confidence).")
            d.changes.append(f"Stops being a BUY above {m(d.buy_below)} ({pct(d.buy_below):+.1f}%).")
        else:
            d.zone = "HOLD"
            why = "the quality check failed" if d.quality_pass is False else "there isn't enough data for the quality check"
            d.reasons.append(f"Price is below the buy price {m(d.buy_below)}, but {why}, so not a BUY.")
            d.changes.append("Becomes a BUY when the quality check passes.")
    elif price > d.reduce_above:
        d.zone = "REDUCE"
        d.reasons.append(f"Price {m(price)} is more than {a['reduce_above']*100:.0f}% above fair value "
                         f"({m(d.reduce_above)}).")
        d.changes.append(f"Back to HOLD at or below {m(d.reduce_above)} ({pct(d.reduce_above):+.1f}%).")
    else:
        d.zone = "HOLD"
        d.reasons.append(f"Price {m(price)} is between the buy price {m(d.buy_below)} and the reduce level "
                         f"{m(d.reduce_above)}.")
        if d.quality_pass:
            d.changes.append(f"Becomes a BUY at or below {m(d.buy_below)} ({pct(d.buy_below):+.1f}%).")
        else:
            d.changes.append(f"A BUY needs the price at or below {m(d.buy_below)} and the quality check to pass.")
        d.changes.append(f"Becomes REDUCE above {m(d.reduce_above)} ({pct(d.reduce_above):+.1f}%).")
    d.changes.append(sell_rules)
    d.changes.append(stale_rule)
    return d


def next_state(state: dict | None, d: Decision, assumptions: dict | None = None,
               now: datetime | None = None) -> dict:
    """What to remember after a refresh: the fair value (and the one before it,
    with the date it changed) and when the quality check last went from pass to fail.
    A change of assumptions or of the methods used doesn't count as a cut."""
    now = now or datetime.now()
    st = dict(state or {})
    key = json.dumps([d.assumptions, sorted(n for n, _v in d.methods)], sort_keys=True)
    fv = d.fair_value
    old = _num(st.get("fair_value"))
    if st.get("basis") != key:
        st["fair_value_prev"], st["fv_changed_on"] = None, None
    elif fv and old and abs(fv / old - 1.0) > 0.01:
        st["fair_value_prev"], st["fv_changed_on"] = old, now.strftime("%Y-%m-%d")
    st["basis"] = key
    if fv:
        st["fair_value"] = round(fv, 4)
    if d.quality_pass is False and st.get("quality_pass") is True:
        st["quality_failed_on"] = now.strftime("%Y-%m-%d")
    elif d.quality_pass is True:
        st["quality_failed_on"] = None
    if d.quality_pass is not None:
        st["quality_pass"] = d.quality_pass
    return st


def watchlist_key(d: Decision) -> str:
    """The Watchlist's signal key for a decision."""
    if d.zone == "BUY":
        return "strong_buy" if d.strong else "accumulate"
    return {"HOLD": "wait", "REDUCE": "avoid", "SELL": "avoid"}.get(d.zone, "nodata")
