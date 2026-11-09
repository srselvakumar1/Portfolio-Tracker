"""A readable "Decision" panel for a valuation decision (model/valuation.py).

Used by the Watchlist pop-up and the Valuation page, so both explain a signal the
same way:

    [ Price ] [ Fair value ] [ Buy below ] [ Target ]        key figures as tiles
    [ Reduce above ] [ Value gap ] [ Confidence ] [ Return ]
    Why                         the reasons, as bullets
    What would change this      the levels that would change the signal
    Quality check               ✅ / ❌ per check
    How the fair value was worked out   (secondary text)
    Assumptions · Data as of            (small print)
    Quality scorecard           information only: strengths | weaknesses
"""
from __future__ import annotations

import tkinter as tk

from ui.ui_theme import ModernStyle


class ScoreItem(str):
    """A quality-scorecard line ("✅ ROE: Strong return…") that also carries the value it
    was judged on and its benchmark. Everywhere else it is just the text."""

    def __new__(cls, text, value: str = "", benchmark: str = ""):
        obj = super().__new__(cls, text)
        obj.value, obj.benchmark = value, benchmark
        return obj


def check_name(text: str) -> str:
    """The check's name as written: '🛡️ FUNDAMENTAL STRENGTH: …' → 'FUNDAMENTAL STRENGTH'."""
    t = str(text).strip()
    while t and not (t[0].isalnum() or t[0] in "(-"):
        t = t[1:].lstrip()
    return t.partition(":")[0].strip()


def with_benchmarks(items, info: dict, value_of) -> list:
    """Scorecard lines as ScoreItems: info = {check name: (benchmark, value key)};
    value_of(key) gives the value as shown on the page."""
    out = []
    for text in items:
        bench, key = info.get(check_name(text), ("", None))
        try:
            value = value_of(key) if key else ""
        except Exception:
            value = ""
        out.append(ScoreItem(text, value or "", bench))
    return out


class DecisionPanel(tk.Frame):
    """Lays out one Decision. `scorecard` = (score, checks counted, passes, fails) or None.
    Text re-wraps when the panel is resized."""

    ALL_SECTIONS = ("summary", "figures", "why", "changes", "quality", "notes", "footer", "scorecard")

    def __init__(self, parent, decision, *, bg: str, accent: str | None = None, tile_bg: str | None = None,
                 show_figures: bool = True, scorecard=None, wrap: int = 600, sections=ALL_SECTIONS):
        super().__init__(parent, bg=bg)
        S = ModernStyle
        self._bg, self._accent = bg, accent or S.TEXT_PRIMARY
        self._tile_bg = tile_bg or S.BG_SECONDARY
        self._wrapped: list[tuple[tk.Label, int]] = []     # (label, margin) re-wrapped on resize
        self._wrap = wrap
        d = decision
        money = lambda v: _money(v, d.currency)
        sections = set(sections) - (set() if show_figures else {"figures"})

        # In short: the decision in plain words, highlighted at the top
        summary = d.summary() if hasattr(d, "summary") and "summary" in sections else ""
        if summary:
            box = tk.Frame(self, bg=self._tile_bg, highlightthickness=1, highlightbackground=self._accent)
            box.pack(fill="x", pady=(2, 6))
            lbl = tk.Label(box, text=summary, bg=self._tile_bg, fg=S.TEXT_PRIMARY, font=S.FONT_BODY_BOLD,
                           justify="left", anchor="w", wraplength=wrap - 24)
            lbl.pack(fill="x", padx=10, pady=8)
            self._wrapped.append((lbl, 24))

        if "figures" in sections:
            if d.fair_value:
                rng = (f"{money(d.low)} – {money(d.high)}"
                       if d.low and d.high and d.high > d.low * 1.001 else "")
                up = d.upside
                tiles = [
                    ("Price", money(d.price), None, ""),
                    ("Fair value", money(d.fair_value), None, rng),
                    ("Buy below (practical)", money(d.buy_below), S.SUCCESS,
                     _level_note(d.buy_below, d.strict_buy_below, d.price, money)),
                    ("Target (2–3 yrs)", money(d.target), None, ""),
                    ("Reduce above (practical)", money(d.reduce_above), S.ERROR,
                     _level_note(d.reduce_above, d.strict_reduce_above, d.price, money)),
                    ("Value gap", f"{up:+.1f}%" if up is not None else "—",
                     S.SUCCESS if (up or 0) > 0 else S.ERROR if (up or 0) < 0 else None, "to fair value"),
                    ("Confidence", d.confidence, None, _confidence_note(d.confidence)),
                    ("Yearly return", f"{d.expected_return:+.1f}%" if d.expected_return is not None else "—",
                     None, "if the target is reached in 3 yrs"),
                ]
                self._tiles(tiles)
            else:
                self._section_title("No fair value")

        if "why" in sections:
            self._bullets("Why", d.reasons)
        if "changes" in sections:
            self._bullets("What would change this", d.changes)
        if d.quality and "quality" in sections:
            state = ("passed" if d.quality_pass else "failed" if d.quality_pass is False else "not enough data")
            colour = S.SUCCESS if d.quality_pass else S.ERROR if d.quality_pass is False else S.TEXT_SECONDARY
            self._section_title(f"Quality check: {state}", colour)
            for _label, passed, detail in d.quality:
                mark, fg = ("✅", S.SUCCESS) if passed else ("❌", S.ERROR) if passed is False else ("•", S.TEXT_SECONDARY)
                self._line(mark, detail, fg)
        if "notes" in sections:
            self._bullets("How the fair value was worked out", d.notes, fg=S.TEXT_SECONDARY)

        foot = [t for t in (d.assumptions_text(), d.dates_text()) if t] if "footer" in sections else []
        if foot:
            for t in foot:
                lbl = tk.Label(self, text=t, bg=bg, fg=S.TEXT_TERTIARY, font=S.FONT_SMALL,
                               justify="left", anchor="w", wraplength=wrap)
                lbl.pack(anchor="w", fill="x", pady=(6, 0))
                self._wrapped.append((lbl, 0))

        if "scorecard" in sections:
            groups = [("Buy / sell indicators (from the rules)", S.TEXT_ACCENT, _decision_rows(d))]
            if scorecard and scorecard[1]:
                score, max_score, passes, fails = scorecard
                as_rows = lambda items, ok: [(ok, *_split_check(t), getattr(t, "value", ""), getattr(t, "benchmark", ""))
                                             for t in items]
                groups.append((f"Strengths ({len(passes)})", S.SUCCESS, as_rows(passes, True)))
                groups.append((f"Weaknesses ({len(fails)})", S.ERROR, as_rows(fails, False)))
                note = (f"Quality scorecard {score}/{max_score}: information only, it doesn't decide the signal. "
                        f"Benchmarks are rules of thumb for a typical company.")
            else:
                note = "Benchmarks are rules of thumb for a typical company."
            self._section_title("Indicators and quality scorecard", S.TEXT_SECONDARY)
            tk.Label(self, text=note, bg=bg, fg=S.TEXT_TERTIARY, font=S.FONT_SMALL,
                     anchor="w", justify="left").pack(anchor="w", fill="x", pady=(0, 4))
            self._scorecard_table(groups)

        self.bind("<Configure>", self._rewrap, add="+")

    # ── building blocks ──
    def _scorecard_table(self, groups) -> None:
        """One numbered table: # | ✓ | Check | Value | What it means | Benchmark, in groups
        with a heading row each (indicators, strengths, weaknesses); striped rows."""
        S = ModernStyle
        table = tk.Frame(self, bg=S.BORDER_COLOR)          # the 1-px gaps between cells show this colour
        table.pack(fill="x", pady=(2, 0))
        table.grid_columnconfigure(4, weight=1)
        cell = dict(padx=(0, 1), pady=(0, 1), sticky="nsew")
        heads = ("#", "", "Check", "Value", "What it means", "Benchmark")
        for col, text in enumerate(heads):
            tk.Label(table, text=text, bg=S.BG_TERTIARY, fg=S.TEXT_SECONDARY, font=S.FONT_SMALL_BOLD,
                     anchor="w", padx=8, pady=4).grid(row=0, column=col, **cell)
        r, n = 1, 0
        for title, colour, rows in groups:
            if not rows:
                continue
            tk.Label(table, text=title, bg=S.BG_SECONDARY, fg=colour, font=S.FONT_BODY_BOLD, anchor="w",
                     padx=8, pady=5).grid(row=r, column=0, columnspan=len(heads), **cell)
            r += 1
            for status, check, meaning, value, bench in rows:
                n += 1
                row_bg = S.BG_PRIMARY if n % 2 else S.BG_SECONDARY
                mark, fg = (("✅", S.SUCCESS) if status is True else ("❌", S.ERROR) if status is False
                            else ("·", S.TEXT_TERTIARY))
                values = ((str(n), S.TEXT_TERTIARY, S.FONT_SMALL, "e"),
                          (mark, fg, S.FONT_SMALL, "center"),
                          (check, fg if status is not None else S.TEXT_PRIMARY, S.FONT_SMALL_BOLD, "w"),
                          (value or "—", S.TEXT_PRIMARY, S.FONT_SMALL_BOLD, "w"),
                          (meaning, S.TEXT_PRIMARY, S.FONT_SMALL, "w"),
                          (bench or "—", S.TEXT_SECONDARY, S.FONT_SMALL, "w"))
                for col, (text, tfg, font, anchor) in enumerate(values):
                    lbl = tk.Label(table, text=text, bg=row_bg, fg=tfg, font=font, anchor=anchor,
                                   justify="left", padx=8, pady=3)
                    lbl.grid(row=r, column=col, **cell)
                    if col == 4:
                        lbl.configure(wraplength=max(180, self._wrap - 600))
                        self._wrapped.append((lbl, 600))
                    elif col in (3, 5):
                        lbl.configure(wraplength=190)
                r += 1

    def _section_title(self, text: str, fg: str | None = None) -> None:
        tk.Label(self, text=text, bg=self._bg, fg=fg or self._accent,
                 font=ModernStyle.FONT_HEADING, anchor="w").pack(anchor="w", fill="x", pady=(12, 4))

    def _line(self, mark: str, text: str, fg: str, font=None) -> None:
        """A line with a hanging indent: the mark on the left, the text wrapping beside it."""
        row = tk.Frame(self, bg=self._bg)
        row.pack(anchor="w", fill="x", pady=1)
        tk.Label(row, text=mark, bg=self._bg, fg=fg, font=font or ModernStyle.FONT_BODY,
                 width=2, anchor="n").pack(side="left", anchor="n")
        lbl = tk.Label(row, text=text, bg=self._bg, fg=fg if mark in "✅❌" else ModernStyle.TEXT_PRIMARY,
                       font=font or ModernStyle.FONT_BODY, justify="left", anchor="w", wraplength=self._wrap - 30)
        lbl.pack(side="left", fill="x", expand=True)
        self._wrapped.append((lbl, 30))

    def _bullets(self, title: str, items, fg: str | None = None) -> None:
        items = [i for i in (items or []) if str(i).strip()]
        if not items:
            return
        self._section_title(title)
        for item in items:
            row = tk.Frame(self, bg=self._bg)
            row.pack(anchor="w", fill="x", pady=1)
            tk.Label(row, text="•", bg=self._bg, fg=self._accent, font=ModernStyle.FONT_BODY_BOLD,
                     width=2, anchor="n").pack(side="left", anchor="n")
            lbl = tk.Label(row, text=item, bg=self._bg, fg=fg or ModernStyle.TEXT_PRIMARY,
                           font=ModernStyle.FONT_BODY, justify="left", anchor="w", wraplength=self._wrap - 30)
            lbl.pack(side="left", fill="x", expand=True)
            self._wrapped.append((lbl, 30))

    def _tiles(self, tiles) -> None:
        S = ModernStyle
        grid = tk.Frame(self, bg=self._bg)
        grid.pack(fill="x", pady=(4, 0))
        per_row = 4
        for c in range(per_row):
            grid.grid_columnconfigure(c, weight=1, uniform="tiles")
        for i, (caption, value, colour, note) in enumerate(tiles):
            tile = tk.Frame(grid, bg=self._tile_bg, highlightthickness=1, highlightbackground=S.BORDER_COLOR)
            tile.grid(row=i // per_row, column=i % per_row, sticky="nsew", padx=3, pady=3)
            tk.Label(tile, text=caption, bg=self._tile_bg, fg=S.TEXT_SECONDARY,
                     font=S.FONT_SMALL).pack(anchor="w", padx=10, pady=(6, 0))
            tk.Label(tile, text=value, bg=self._tile_bg, fg=colour or S.TEXT_PRIMARY,
                     font=S.FONT_HEADING).pack(anchor="w", padx=10)
            tk.Label(tile, text=note or " ", bg=self._tile_bg, fg=S.TEXT_TERTIARY,
                     font=S.FONT_SMALL).pack(anchor="w", padx=10, pady=(0, 6))

    def _rewrap(self, event) -> None:
        width = max(300, int(event.width) - 8)
        if abs(width - self._wrap) < 12:
            return
        self._wrap = width
        for lbl, margin in self._wrapped:
            try:
                lbl.configure(wraplength=(width // 2 - 20) if margin == -2 else width - margin)
            except tk.TclError:
                pass


def _money(v, currency: str) -> str:
    if v is None:
        return "—"
    sign = {"INR": "₹", "JPY": "¥", "USD": "$", "GBP": "£", "EUR": "€", "CNY": "¥"}.get(str(currency).upper(), "₹")
    return f"{sign}{v:,.0f}" if abs(v) >= 100 else f"{sign}{v:,.2f}"


def _pct(level, price) -> str:
    if not level or not price:
        return ""
    return f"{(level / price - 1.0) * 100:+.0f}%"


def _confidence_note(confidence: str) -> str:
    return {"High": "methods agree", "Medium": "one method, or close",
            "Low": "methods disagree: levels capped by them"}.get(confidence, "")


def _split_check(text: str) -> tuple[str, str]:
    """'✅ ROE: Strong return…' → ('ROE', 'Strong return…'); leading marks and emoji dropped."""
    t = str(text).strip()
    while t and not (t[0].isalnum() or t[0] in "(-"):
        t = t[1:].lstrip()
    name, sep, rest = t.partition(":")
    if not sep:
        return t, ""
    name, rest = name.strip(), rest.strip()
    return (name.title() if name.isupper() and len(name) > 4 else name), rest[:1].upper() + rest[1:]



def _decision_rows(d) -> list:
    """Rows (status, check, what it means, value, benchmark) that matter for buying or selling,
    from the decision (model/valuation.py). status: True helps a buy, False points to sell /
    avoid, None neutral."""
    m = lambda v: _money(v, d.currency)
    rows = []
    zone_status = {"BUY": True, "REDUCE": False, "SELL": False}.get(d.zone)
    rows.append((zone_status, "Signal", d.reasons[0] if d.reasons else "", d.label,
                 "Strong Buy ≤ strict buy · Accumulate ≤ practical buy"))
    if not d.fair_value or not d.price:
        return rows
    a = d.assumptions or {}
    margin = d.margin or a.get("mos_medium", 0.35)
    in_buy = d.buy_below is not None and d.price <= d.buy_below
    in_reduce = d.reduce_above is not None and d.price > d.reduce_above
    price_status = True if in_buy else False if in_reduce else None
    rows.append((price_status, "Price vs buy price",
                 "At or below the buy price" if in_buy else
                 f"The price must fall {(1 - d.buy_below / d.price) * 100:.0f}% to reach the buy price",
                 f"{m(d.price)} vs {m(d.buy_below)}" + (f" (strict {m(d.strict_buy_below)})"
                                                         if _differs(d.strict_buy_below, d.buy_below) else ""),
                 "at or below = Accumulate"))
    # from the actual (practical) levels, which the lowest / highest method can move
    gap_buy = (d.fair_value / d.buy_below - 1) * 100 if d.buy_below else (1 / (1 - margin) - 1) * 100
    gap_reduce = ((d.fair_value / d.reduce_above - 1) * 100 if d.reduce_above
                  else (1 / (1 + a.get("reduce_above", 0.2)) - 1) * 100)
    rows.append((price_status, "Value gap", "How far fair value is above (+) or below (−) the price",
                 f"{d.upside:+.1f}%", f"≥ +{gap_buy:.0f}% buy zone · below −{abs(gap_reduce):.0f}% reduce"))
    conf_note = {"High": "The fair-value methods agree within 25%", "Medium": "One method, or they agree within 50%",
                 "Low": "The methods disagree: the buy price is at most the lowest method, the reduce "
                        "level at least the highest"}.get(d.confidence, "")
    rows.append(({"High": True, "Low": False}.get(d.confidence), "Confidence", conf_note, d.confidence,
                 "High = methods agree"))
    if d.quality_pass is not None:
        bad = "; ".join(det for _l, p, det in d.quality if p is False)
        rows.append((d.quality_pass, "Quality check", bad or "ROE, earnings, cash flow and debt look fine",
                     "passed" if d.quality_pass else "failed", "must pass for a buy"))
    if d.implied_growth is not None and d.growth_used is not None:
        rows.append((d.implied_growth <= d.growth_used + 0.01, "Growth the price assumes",
                     "EPS growth a year for 5 years that today's price needs",
                     f"{d.implied_growth * 100:.1f}% a year", f"≤ {d.growth_used * 100:.1f}% (growth used) = reasonable"))
    if d.expected_return is not None:
        req = a.get("required_return", 0.12) * 100
        er = d.expected_return
        rows.append((True if er >= req else False if er < 0 else None, "Yearly return to target",
                     "If the price reaches fair value in 3 years, with dividends", f"{er:+.1f}% a year",
                     f"≥ {req:.1f}% (required return)"))
    if d.analyst_target:
        up = (d.analyst_target / d.price - 1) * 100
        cnt = f", {d.analyst_count} analysts" if d.analyst_count else ""
        rows.append((up > 0, "Analyst target", f"Average analyst target (reference only{cnt})",
                     f"{m(d.analyst_target)} ({up:+.0f}%)", "above the price"))
    if d.dividend_yield:
        rows.append((True if d.dividend_yield >= 2 else None, "Dividend yield", "Paid to you while you hold",
                     f"{d.dividend_yield:.1f}%", "≥ 2% helpful"))
    return rows


def _differs(a, b) -> bool:
    return a is not None and b is not None and abs(a - b) > 0.005 * max(abs(b), 1.0)


def _level_note(practical, strict, price, money) -> str:
    """'−16% from today · strict ₹1,621' (the strict part only when it differs)."""
    note = f"{_pct(practical, price)} from today"
    return note + (f" · strict {money(strict)}" if _differs(strict, practical) else "")
