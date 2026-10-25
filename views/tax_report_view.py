"""Tax Report: realised capital gains for a financial year (FIFO matching).

The calculation itself lives in model/tax.py (pure Python, unit-tested in
tests/test_tax.py). This view reads the trades, runs that calculation in the
background and shows the totals, any problems found, and one row per matched
piece of every sale.
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from datetime import datetime

from views.base_view import BaseView
from ui.ui_theme import ModernStyle
from ui.ui_utils import add_treeview_copy_menu, treeview_sort_column, run_in_background, format_money, format_date
from model.applog import log
from model.database import db_session
from model.tax import compute_realised_gains, LONG_TERM, SHORT_TERM

CURRENCIES = ("All", "INR", "JPY")
_SYMBOLS = {"INR": "₹", "JPY": "¥", "USD": "$", "GBP": "£", "CNY": "¥"}


# ── Small helpers (also used by the P&L Report) ──────────────────────────────
def currency_symbol(code: str) -> str:
    """₹ for INR, ¥ for JPY, $ for USD, £ for GBP; otherwise the code itself."""
    code = (code or "INR").upper()
    return _SYMBOLS.get(code, code + " ")


def signed_money(value: float, currency: str = "INR") -> str:
    """▲ ₹1,234.50 for a gain, ▼ ₹1,234.50 for a loss, ₹0.00 for nothing."""
    v = float(value or 0.0)
    if abs(v) < 0.005:
        return format_money(0.0, currency)
    return f"{'▲' if v > 0 else '▼'} {format_money(abs(v), currency)}"


def gain_colour(value) -> str:
    if value is None or abs(float(value)) < 0.005:
        return ModernStyle.TEXT_PRIMARY
    return ModernStyle.SUCCESS if value > 0 else ModernStyle.ERROR


_measure_fonts = {}


def fit_value_font(labels, avail: int) -> None:
    """Big KPI font for the value labels, or a smaller one when a value would not fit."""
    big, small = ModernStyle.FONT_KPI_VALUE, ModernStyle.FONT_SECTION_LABEL
    if big not in _measure_fonts:
        _measure_fonts[big] = tkfont.Font(font=big)
    need = max((_measure_fonts[big].measure(lbl.cget("text")) for lbl in labels), default=0)
    font = big if need <= avail else small
    for lbl in labels:
        if getattr(lbl, "_fit_font", None) != font:
            lbl._fit_font = font
            lbl.config(font=font)


def fit_columns(tree, prefs: dict, drop_order=(), min_scale: float = 0.86) -> None:
    """Keep a table's columns inside its width: scale them to fit, and hide the
    columns in drop_order (in that order) when the window is too narrow."""
    state = {"w": 0}

    def _on_configure(e):
        w = e.width - 4
        if w < 100 or abs(w - state["w"]) < 6:
            return
        state["w"] = w
        cols = list(prefs)
        for c in drop_order:
            if sum(prefs[x] for x in cols) * min_scale <= w:
                break
            cols.remove(c)
        scale = w / sum(prefs[x] for x in cols)
        tree.configure(displaycolumns=cols)
        for c in cols:
            tree.column(c, width=max(30, int(prefs[c] * scale)))

    tree.bind("<Configure>", _on_configure, add="+")


class CurrencyToggle(tk.Frame):
    """[All | INR | JPY] pill for the gradient header (keeps its own colours).

    Clicking only sets `variable`; whoever owns the variable reacts to it
    (one trace), so a click loads the data once.
    """

    def __init__(self, parent, variable: tk.StringVar, options=CURRENCIES):
        super().__init__(parent, bg=ModernStyle.BG_SECONDARY, padx=3, pady=3)
        self._ignore_sync_bg = True          # the header must not recolour it
        self._var = variable
        self._labels = {}
        for opt in options:
            lbl = tk.Label(self, text=opt, font=ModernStyle.FONT_BODY_BOLD,
                           padx=12, pady=3, cursor="hand2")
            lbl.pack(side="left", padx=(0, 2) if opt != options[-1] else 0)
            lbl.bind("<Button-1>", lambda _e, v=opt: self._pick(v))
            self._labels[opt] = lbl
        variable.trace_add("write", lambda *_: self._paint())
        self._paint()

    def _pick(self, value):
        if self._var.get() != value:
            self._var.set(value)

    def _paint(self):
        current = self._var.get()
        for opt, lbl in self._labels.items():
            if opt == current:
                lbl.config(bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT)
            else:
                lbl.config(bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY)


def build_table_rows(res, disp: str) -> list:
    """Table rows as (values, colour tag): problems first (amber), then sales newest first.
    Pure formatting, so it runs in the background thread."""
    sym = currency_symbol(disp)
    rows = []
    for u in res.unmatched_sells:
        rows.append(((u.broker, u.symbol, "—", format_date(u.date), f"{u.qty:g}", "—", f"{sym}{u.price:,.2f}",
                      "—", "No buy found", "not counted"), "problem"))
    for s in res.skipped:
        rows.append(((s.broker, s.symbol, "—", format_date(s.date) or "—", "—", "—", "—", "—", "Bad data",
                      "not counted"), "problem"))
    terms = {SHORT_TERM: "Short-term", LONG_TERM: "Long-term"}
    for r in sorted(res.rows, key=lambda x: (x.sell_date, x.buy_date), reverse=True):
        tag = "gain" if r.pnl > 0.005 else ("loss" if r.pnl < -0.005 else "flat")
        rows.append(((r.broker, r.symbol, format_date(r.buy_date), format_date(r.sell_date), f"{r.qty:g}",
                      f"{sym}{r.buy_price:,.2f}", f"{sym}{r.sell_price:,.2f}", f"{r.days:,}",
                      terms.get(r.term, f"n/a ({r.currency})"), signed_money(r.pnl, disp)), tag))
    return rows


class MenuPill(tk.Label):
    """A light pill for the gradient header that opens a native menu of choices.

    Much cheaper to show than a canvas dropdown (about 0.15 s less every time
    the page is shown). With `variable`, it shows and sets the chosen value;
    with `command`, it calls command(choice).
    """

    def __init__(self, parent, *, values, variable=None, text="", command=None):
        super().__init__(parent, font=ModernStyle.FONT_BODY_BOLD, bg=ModernStyle.BG_SECONDARY,
                         fg=ModernStyle.TEXT_PRIMARY, padx=14, pady=5, cursor="hand2")
        self._ignore_sync_bg = True          # the header must not recolour it
        self._var, self._command = variable, command
        self._menu = tk.Menu(self, tearoff=0)
        for v in values:
            self._menu.add_command(label=v, command=lambda v=v: self._choose(v))
        if variable is not None:
            variable.trace_add("write", lambda *_: self.config(text=f"{variable.get()}  ▾"))
            text = variable.get()
        self.config(text=f"{text}  ▾")
        self.bind("<Button-1>", self._open)

    def _open(self, _e=None):
        try:
            self._menu.tk_popup(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + 2)
        finally:
            self._menu.grab_release()

    def _choose(self, value):
        if self._var is not None and self._var.get() != value:
            self._var.set(value)
        if self._command:
            self._command(value)


# ── The view ─────────────────────────────────────────────────────────────────
class TaxReportView(BaseView):
    """Realised capital gains (short-term / long-term for INR) per financial year."""

    COLUMNS = ("#", "Broker", "Symbol", "Buy date", "Sell date", "Qty",
               "Buy price", "Sell price", "Days held", "Term", "Gain / loss")

    def __init__(self, parent, app_state=None):
        self._fy_options_list = self._build_fy_options()
        now = datetime.now()
        current_fy_start = now.year if now.month >= 4 else now.year - 1
        self._current_fy_val = f"FY {current_fy_start}-{current_fy_start + 1}"
        self._load_seq = 0
        super().__init__(parent, app_state=app_state)

    @staticmethod
    def _build_fy_options() -> list:
        """FY options from the year of the earliest sale to the current FY."""
        now = datetime.now()
        current_fy_start = now.year if now.month >= 4 else now.year - 1
        earliest_fy_start = current_fy_start - 2  # fallback: 2 years back
        try:
            with db_session() as conn:
                row = conn.cursor().execute("SELECT MIN(date) FROM trades WHERE type='SELL'").fetchone()
                if row and row[0]:
                    yr, mo = int(row[0][:4]), int(row[0][5:7])
                    earliest_fy_start = min(current_fy_start, yr if mo >= 4 else yr - 1)
        except Exception:
            log.exception("Tax Report: could not read the earliest sale date")
        options = [f"FY {y}-{y + 1}" for y in range(current_fy_start, earliest_fy_start - 1, -1)]
        options.append("All Time")
        return options

    # ── layout ───────────────────────────────────────────────────────────────
    def build(self):
        self._current_fy = tk.StringVar(value=self._current_fy_val)
        self._current_currency = tk.StringVar(value="All")

        self._content = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        self._content.pack(fill="both", expand=True)

        self._build_header()
        self._build_summary()
        self._build_notes()
        self._build_table()

        # One trace per choice: each change loads the report exactly once.
        self._current_fy.trace_add("write", lambda *_: self.load_data())
        self._current_currency.trace_add("write", lambda *_: self.load_data())

    def _build_header(self):
        def _build_right(parent):
            CurrencyToggle(parent, self._current_currency).pack(side="left", padx=(0, 14))
            tk.Label(parent, text="Year:", bg=parent.cget("bg"), fg=ModernStyle.HEADER_FG,
                     font=ModernStyle.FONT_BODY_BOLD).pack(side="left", padx=(0, 6))
            MenuPill(parent, values=self._fy_options_list, variable=self._current_fy).pack(side="left")

        self.add_gradient_header(
            self._content,
            "🧾 Tax Report",
            "Realised gains, matched first-in first-out per broker.",
            right_widget_func=_build_right,
        )

    def _build_summary(self):
        bar = tk.Frame(self._content, bg=ModernStyle.BG_PRIMARY)
        bar.pack(fill="x", padx=20, pady=(10, 0))
        specs = [
            ("short", "Short-term gains", "held 12 months or less", ModernStyle.WARNING_FILL, ModernStyle.WARNING),
            ("long", "Long-term gains", "held over 12 months", ModernStyle.INFO_FILL, ModernStyle.INFO),
            ("other", "Not split (JPY)", "one flat rate in Japan", ModernStyle.PURPLE_FILL, ModernStyle.TEXT_PURPLE),
            ("net", "Net realised gains", "before exemptions", ModernStyle.ACCENT_PRIMARY, ModernStyle.TEXT_ACCENT),
        ]
        self._stat = {}
        for col, (key, title, caption, bar_fill, title_fg) in enumerate(specs):
            bar.grid_columnconfigure(col, weight=1, uniform="taxstats")
            card = tk.Frame(bar, bg=ModernStyle.BG_SECONDARY, highlightthickness=1,
                            highlightbackground=ModernStyle.BORDER_COLOR)
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 5, 0 if col == 3 else 5))
            tk.Frame(card, bg=bar_fill, width=5).pack(side="left", fill="y")
            body = tk.Frame(card, bg=ModernStyle.BG_SECONDARY)
            body.pack(side="left", fill="both", expand=True, padx=14, pady=10)
            tk.Label(body, text=title, bg=ModernStyle.BG_SECONDARY, fg=title_fg,
                     font=ModernStyle.FONT_KPI_LABEL, anchor="w").pack(fill="x")
            value = tk.Label(body, text="…", bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY,
                             font=ModernStyle.FONT_KPI_VALUE, anchor="w")
            value.pack(fill="x", pady=(2, 0))
            tk.Label(body, text=caption, bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_SECONDARY,
                     font=ModernStyle.FONT_SMALL, anchor="w").pack(fill="x")
            self._stat[key] = value
        self._stat_bar = bar
        bar.bind("<Configure>", lambda e: self._fit_stats(e.width))

    def _fit_stats(self, width=None):
        width = width or self._stat_bar.winfo_width()
        if width > 100:
            fit_value_font(list(self._stat.values()), width // 4 - 50)

    def _build_notes(self):
        """Up to five one-paragraph messages (errors, problems found, how amounts were worked out)."""
        self._notes_frame = tk.Frame(self._content, bg=ModernStyle.BG_PRIMARY)
        self._notes_frame.pack(fill="x", padx=20, pady=(8, 0))
        self._note_labels = []
        for _ in range(5):
            lbl = tk.Label(self._notes_frame, font=ModernStyle.FONT_BODY, anchor="w",
                           justify="left", padx=12, pady=5, wraplength=900)
            self._note_labels.append(lbl)
        self._note_wrap = 900

        def _rewrap(e):
            w = max(300, e.width - 30)
            if abs(w - self._note_wrap) > 20:
                self._note_wrap = w
                for lbl in self._note_labels:
                    lbl.config(wraplength=w)
        self._notes_frame.bind("<Configure>", _rewrap)

    def _show_notes(self, notes):
        """notes: list of (kind, text) with kind in error / warning / info."""
        styles = {
            "error": (ModernStyle.ERROR_PALE, ModernStyle.ERROR),
            "warning": (ModernStyle.WARNING_PALE, ModernStyle.WARNING),
            "info": (ModernStyle.INFO_PALE, ModernStyle.INFO),
        }
        for i, lbl in enumerate(self._note_labels):
            if i < len(notes):
                kind, text = notes[i]
                bg, fg = styles[kind]
                lbl.config(text=text, bg=bg, fg=fg)
                if not lbl.winfo_ismapped():
                    lbl.pack(fill="x", pady=(0, 4))
            elif lbl.winfo_ismapped():
                lbl.pack_forget()

    def _build_table(self):
        card = tk.Frame(self._content, bg=ModernStyle.BG_SECONDARY, highlightthickness=1,
                        highlightbackground=ModernStyle.BORDER_COLOR)
        card.pack(fill="both", expand=True, padx=20, pady=(6, 16))

        head = tk.Frame(card, bg=ModernStyle.BG_SECONDARY)
        head.pack(fill="x", padx=16, pady=(10, 6))
        tk.Label(head, text="Realised sales", font=ModernStyle.FONT_HEADING,
                 bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_ACCENT).pack(side="left")
        self._caption = tk.Label(head, text="Calculating…", font=ModernStyle.FONT_BODY,
                                 bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_SECONDARY)
        self._caption.pack(side="left", padx=(12, 0))

        tv_frame = tk.Frame(card, bg=ModernStyle.BG_SECONDARY)
        tv_frame.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        style = ttk.Style()
        style.configure("Tax.Treeview", font=ModernStyle.FONT_TABLE, rowheight=ModernStyle.TABLE_ROW_HEIGHT)
        style.configure("Tax.Treeview.Heading", font=ModernStyle.FONT_TABLE_BOLD)

        self.tv = ttk.Treeview(tv_frame, columns=self.COLUMNS, show="headings", height=15, style="Tax.Treeview")
        widths = {"#": 46, "Broker": 110, "Symbol": 120, "Buy date": 100, "Sell date": 100, "Qty": 60,
                  "Buy price": 105, "Sell price": 105, "Days held": 85, "Term": 105, "Gain / loss": 130}
        right = {"Qty", "Buy price", "Sell price", "Days held", "Gain / loss"}
        for c in self.COLUMNS:
            anchor = "e" if c in right else ("center" if c == "#" else "w")
            self.tv.heading(c, text=c, anchor=anchor, command=lambda col=c: treeview_sort_column(self.tv, col, False))
            self.tv.column(c, anchor=anchor, width=widths[c], minwidth=30, stretch=False)
        # Narrow window: hide the price columns first (Copy All Rows still copies them)
        fit_columns(self.tv, widths, drop_order=("Buy price", "Sell price", "Days held", "#"))
        add_treeview_copy_menu(self.tv)

        self.tv.tag_configure("gain", foreground=ModernStyle.SUCCESS)
        self.tv.tag_configure("loss", foreground=ModernStyle.ERROR)
        self.tv.tag_configure("flat", foreground=ModernStyle.TEXT_PRIMARY)
        self.tv.tag_configure("problem", foreground=ModernStyle.WARNING)
        self.tv.tag_configure("even", background=ModernStyle.BG_SECONDARY)
        self.tv.tag_configure("odd", background=ModernStyle.BG_TERTIARY)

        vsb = ttk.Scrollbar(tv_frame, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=vsb.set)
        self.tv.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Shown over the table when the year has no sales
        self._empty = tk.Label(tv_frame, text="", font=ModernStyle.FONT_EMPTY_STATE, justify="center",
                               bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_SECONDARY)

    # ── data ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _fy_window(fy_str: str):
        """'FY 2024-2025' -> ('2024-04-01', '2025-03-31', nice label); All Time -> (None, None, label)."""
        if fy_str.startswith("FY "):
            try:
                y = int(fy_str[3:].split("-")[0])
                return f"{y}-04-01", f"{y + 1}-03-31", f"{fy_str} (1 Apr {y} – 31 Mar {y + 1})"
            except (ValueError, IndexError):
                pass
        return None, None, "All years"

    def load_data(self):
        # Read the Tk variables here, on the main thread, then work in the background.
        fy_str = self._current_fy.get()
        currency = self._current_currency.get()
        start, end, fy_label = self._fy_window(fy_str)
        self._load_seq += 1
        seq = self._load_seq
        self._caption.config(text="Calculating…")

        def work():
            with db_session() as conn:
                trades = conn.cursor().execute(
                    "SELECT broker, symbol, type, date, qty, price, fee, currency FROM trades "
                    "ORDER BY date ASC, type ASC, trade_id ASC"
                ).fetchall()
            if currency != "All":
                trades = [t for t in trades if str(t[7] or "INR").strip().upper() == currency]
            rates = {}

            def fx(cur):
                if currency == "All":
                    from model.engine import get_exchange_rate
                    rates[cur] = get_exchange_rate(cur)
                else:
                    rates[cur] = 1.0
                return rates[cur]

            result = compute_realised_gains(trades, start, end, fx_rate=fx)
            return result, rates, build_table_rows(result, "INR" if currency == "All" else currency)

        def done(payload):
            if seq == self._load_seq:
                result, rates, table_rows = payload
                self._apply_result(result, rates, table_rows, currency, fy_str, fy_label)

        def failed(err):
            if seq == self._load_seq:
                self._show_failure(err)

        run_in_background(work, done, failed, widget=self, name="tax-report")

    def _set_stat(self, key, value, currency):
        lbl = self._stat[key]
        if value is None:
            lbl.config(text="—", fg=ModernStyle.TEXT_TERTIARY)
        else:
            lbl.config(text=signed_money(value, currency), fg=gain_colour(value))

    def _show_failure(self, err):
        """Clear everything so last year's totals are never left on screen."""
        for key in self._stat:
            self._set_stat(key, None, "INR")
        self.tv.delete(*self.tv.get_children())
        self._empty.place_forget()
        self._caption.config(text="Not available")
        self._show_notes([("error", f"✖  The report could not be worked out: {err}. "
                                    "Nothing below is up to date. The details are in the app log.")])

    def _fill_table(self, table_rows, seq, start=0):
        if seq != self._load_seq:
            return  # a newer report replaced this one
        chunk = 1000 if start == 0 else 2500
        for i in range(start, min(start + chunk, len(table_rows))):
            values, tag = table_rows[i]
            self.tv.insert("", "end", values=(i + 1,) + values, tags=("odd" if i % 2 else "even", tag))
        if start + chunk < len(table_rows):
            self.after(1, lambda: self._fill_table(table_rows, seq, start + chunk))

    def _apply_result(self, res, rates, table_rows, currency, fy_str, fy_label):
        disp = "INR" if currency == "All" else currency
        non_inr = sorted(c for c in res.currencies if c != "INR")

        # Totals ("—" where a total does not apply to the chosen currency)
        self._set_stat("short", res.short_term if currency != "JPY" else None, disp)
        self._set_stat("long", res.long_term if currency != "JPY" else None, disp)
        self._set_stat("other", res.not_split if (non_inr or currency == "JPY") else None, disp)
        self._set_stat("net", res.net, disp)
        self._fit_stats()

        # Messages: problems first, then how the numbers were worked out
        notes = []
        if res.unmatched_sells:
            n = len(res.unmatched_sells)
            notes.append(("warning",
                f"⚠  {n} sale{'s' if n != 1 else ''} had no earlier buy at the same broker, so "
                f"{'they are' if n != 1 else 'it is'} not counted in the totals. "
                "They are listed first in the table (Term: No buy found). Check that the buy was "
                "entered for the same broker and currency."))
        if res.skipped:
            n = len(res.skipped)
            examples = "; ".join(f"{s.symbol or '?'} ({s.broker or '?'}): {s.reason}" for s in res.skipped[:3])
            more = f"; and {n - 3} more" if n > 3 else ""
            notes.append(("warning",
                f"⚠  {n} trade{'s' if n != 1 else ''} could not be read and {'were' if n != 1 else 'was'} "
                f"left out: {examples}{more}. Please correct {'them' if n != 1 else 'it'} in Trade History."))
        if currency == "All" and non_inr:
            parts = ", ".join(f"{currency_symbol(c)}1 = ₹{rates.get(c, 0.0):.4f}" for c in non_inr)
            notes.append(("info",
                f"ℹ  Amounts are in ₹. {', '.join(non_inr)} sales are converted at today's "
                f"exchange rate ({parts}), because past exchange rates are not stored."))
        if non_inr or currency == "JPY":
            text = "ℹ  " + " ".join(res.notes) if res.notes else (
                "ℹ  JPY gains are not split into short and long term: Japan taxes listed-share "
                "gains at one flat rate (about 20.315%).")
            if fy_str.startswith("FY ") and ("JPY" in non_inr or currency == "JPY"):
                text += " Japan's tax year is January to December; this year picker uses the Indian April to March year."
            notes.append(("info", text))
        self._show_notes(notes)

        # Table: filled in slices so a long "All Time" list never freezes the window
        self.tv.delete(*self.tv.get_children())
        self._fill_table(table_rows, self._load_seq)
        sym = currency_symbol(disp)

        n = len(res.rows)
        cur_label = "all currencies" if currency == "All" else currency
        self._caption.config(text=f"{fy_label} · {cur_label} · {n:,} sale row{'s' if n != 1 else ''}"
                                  f" · amounts in {sym.strip()}")

        if not table_rows:
            which = "" if currency == "All" else f" ({currency})"
            if fy_str.startswith("FY "):
                msg = f"No realised sales in {fy_str}{which}.\nShares you sell during this year will be listed here."
            else:
                msg = f"No realised sales yet{which}.\nShares you sell will be listed here."
            self._empty.config(text=msg)
            self._empty.place(relx=0.5, rely=0.45, anchor="center")
        else:
            self._empty.place_forget()
