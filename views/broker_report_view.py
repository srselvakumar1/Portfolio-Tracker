"""P&L Report: invested, current value and profit/loss per broker, with a chart
and a PDF export.

Everything slow (the broker metrics, XIRR, CAGR and the PDF) runs in the
background; the window only shows the results.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from collections import defaultdict
from datetime import datetime

from views.base_view import BaseView
from views.tax_report_view import (CurrencyToggle, currency_symbol, signed_money, gain_colour,
                                   fit_columns, fit_value_font)
from ui.ui_theme import ModernStyle
from ui.ui_widgets import ModernButton
from ui.ui_utils import add_treeview_copy_menu, treeview_sort_column, run_in_background, format_money


def _short_amount(val: float, currency: str) -> str:
    """Axis label: ₹26.6L / ₹1.2Cr for rupees, ¥26.4M / ¥950k for other currencies."""
    sym = currency_symbol(currency)
    if currency == "INR":
        for size, unit in ((1e7, "Cr"), (1e5, "L"), (1e3, "k")):
            if val >= size:
                return f"{sym}{val / size:.1f}{unit}"
    else:
        for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
            if val >= size:
                return f"{sym}{val / size:.1f}{unit}"
    return f"{sym}{val:.0f}"


class BrokerReportView(BaseView):
    """P&L per broker, grouped by currency, with KPI cards, chart and PDF export."""

    def __init__(self, parent, app_state=None):
        self._load_seq = 0
        self._cached_metrics = {}
        self._tip_data = {}          # canvas bar id -> (tooltip text, x, top y)
        self._tip_item = None
        self._chart_after = None
        self._chart_size = None
        super().__init__(parent, app_state=app_state)

    def build(self):
        self._current_currency = tk.StringVar(value="All")

        self._content = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        self._content.pack(fill="both", expand=True)

        self._build_header()
        self._build_kpis()
        self._status = tk.Label(self._content, text="", font=ModernStyle.FONT_BODY, anchor="w",
                                bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY)
        self._status.pack(fill="x", padx=22, pady=(2, 2))
        self._build_table()
        self._build_chart()

        self._current_currency.trace_add("write", lambda *_: self.load_data())

    # ── header ───────────────────────────────────────────────────────────────
    def _build_header(self):
        def _build_right(parent):
            CurrencyToggle(parent, self._current_currency).pack(side="left", padx=(0, 14))
            self._pdf_btn = ModernButton(
                parent, text="↓ Save PDF", command=self._export_pdf,
                bg=ModernStyle.WARNING_FILL, fg=ModernStyle.TEXT_ON_ACCENT,
                canvas_bg=parent.cget("bg"), width=120, height=34, font=ModernStyle.FONT_BODY_BOLD,
            )
            self._pdf_btn.pack(side="left")

        self.add_gradient_header(
            self._content,
            "📊 P&L Report",
            "Profit and loss, XIRR and CAGR for each broker.",
            right_widget_func=_build_right,
        )

    def _set_status(self, text: str, kind: str = "info") -> None:
        colour = {"info": ModernStyle.TEXT_SECONDARY, "success": ModernStyle.SUCCESS,
                  "warning": ModernStyle.WARNING, "error": ModernStyle.ERROR}.get(kind, ModernStyle.TEXT_SECONDARY)
        self._status.config(text=text, fg=colour)

    # ── KPI cards ────────────────────────────────────────────────────────────
    def _kpi_card(self, parent, title: str, bar_fill: str, value_fg: str, icon: str):
        card = tk.Frame(parent, bg=ModernStyle.BG_SECONDARY, highlightthickness=1,
                        highlightbackground=ModernStyle.BORDER_COLOR, height=ModernStyle.KPI_CARD_HEIGHT)
        card.pack_propagate(False)
        tk.Frame(card, bg=bar_fill, width=5).pack(side="left", fill="y")
        body = tk.Frame(card, bg=ModernStyle.BG_SECONDARY)
        body.pack(side="left", expand=True, fill="both", padx=14, pady=10)
        tk.Label(body, text=f"{icon}  {title}", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
                 font=ModernStyle.FONT_KPI_LABEL, anchor="w").pack(fill="x")
        val_lbl = tk.Label(body, text="…", fg=value_fg, bg=ModernStyle.BG_SECONDARY,
                           font=ModernStyle.FONT_KPI_VALUE, anchor="w")
        val_lbl.pack(fill="x", pady=(8, 0))
        return card, val_lbl

    def _build_kpis(self):
        self.kpi_frame = tk.Frame(self._content, bg=ModernStyle.BG_PRIMARY)
        self.kpi_frame.pack(fill="x", padx=20, pady=(12, 4))
        specs = [
            ("Total Invested", "inv", ModernStyle.INFO_FILL, ModernStyle.INFO, "📥"),
            ("Current Value", "val", ModernStyle.ACCENT_PRIMARY, ModernStyle.TEXT_ACCENT, "💼"),
            ("Overall P&L", "pnl", ModernStyle.PURPLE_FILL, ModernStyle.TEXT_PRIMARY, "📊"),
            ("Overall XIRR", "xirr", ModernStyle.WARNING_FILL, ModernStyle.TEXT_PRIMARY, "🎯"),
            ("Overall CAGR", "cagr", ModernStyle.SUCCESS_FILL, ModernStyle.TEXT_PRIMARY, "📐"),
        ]
        self.kpi_labels = {}
        for col, (title, key, bar_fill, value_fg, icon) in enumerate(specs):
            self.kpi_frame.grid_columnconfigure(col, weight=1, uniform="kpis")
            card, lbl = self._kpi_card(self.kpi_frame, title, bar_fill, value_fg, icon)
            card.grid(row=0, column=col, sticky="nsew", padx=4)
            self.kpi_labels[key] = lbl
        self.kpi_frame.bind("<Configure>", lambda e: self._fit_kpis(e.width))

    def _fit_kpis(self, width=None):
        width = width or self.kpi_frame.winfo_width()
        if width > 100:
            fit_value_font(list(self.kpi_labels.values()), width // 5 - 46)

    def _show_kpis(self, totals: dict, currency_filter: str):
        """Whole amounts on the cards (the table below has the paise/sen)."""
        cur = "INR" if currency_filter == "All" else currency_filter
        sym = currency_symbol(cur)
        pnl = float(totals["pnl"] or 0.0)
        arrow = "" if abs(pnl) < 0.5 else ("▲ " if pnl > 0 else "▼ ")
        self.kpi_labels["inv"].config(text=f"{sym}{totals['inv']:,.0f}")
        self.kpi_labels["val"].config(text=f"{sym}{totals['val']:,.0f}")
        self.kpi_labels["pnl"].config(text=f"{arrow}{sym}{abs(pnl):,.0f}", fg=gain_colour(pnl))
        for key in ("xirr", "cagr"):
            v = float(totals.get(key) or 0.0)
            arrow = "" if abs(v) < 0.005 else ("▲ " if v > 0 else "▼ ")
            self.kpi_labels[key].config(text=f"{arrow}{abs(v):.2f}%", fg=gain_colour(v))
        self._fit_kpis()

    # ── table ────────────────────────────────────────────────────────────────
    def _build_table(self):
        container = tk.Frame(self._content, bg=ModernStyle.BG_SECONDARY, highlightthickness=1,
                             highlightbackground=ModernStyle.BORDER_COLOR)
        container.pack(fill=tk.BOTH, expand=True, padx=20, pady=(4, 12))

        columns = ("broker", "invested", "current_val", "unrealized_pnl", "unrealized_loss",
                   "realized_pnl", "realized_loss", "total_pnl", "xirr")
        style = ttk.Style()
        style.configure("BrokerReport.Treeview", font=ModernStyle.FONT_REPORT_TABLE, rowheight=ModernStyle.TABLE_ROW_HEIGHT)
        style.configure("BrokerReport.Treeview.Heading", font=ModernStyle.FONT_REPORT_TABLE_BOLD)

        self.tree = ttk.Treeview(container, columns=columns, show="headings", style="BrokerReport.Treeview", height=5)
        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        headers = {
            "broker": ("Broker", 150), "invested": ("Invested", 120), "current_val": ("Current Value", 130),
            "unrealized_pnl": ("Unrealised P&L", 140), "unrealized_loss": ("Unrealised Loss", 135),
            "realized_pnl": ("Realised P&L", 135), "realized_loss": ("Realised Loss", 130),
            "total_pnl": ("Total P&L", 140), "xirr": ("XIRR", 95),
        }
        for col, (title, width) in headers.items():
            anchor = "w" if col == "broker" else "e"
            self.tree.heading(col, text=title, anchor=anchor, command=lambda c=col: treeview_sort_column(self.tree, c, False))
            self.tree.column(col, width=width, minwidth=30, anchor=anchor, stretch=False)
        # Narrow window: hide the two Loss columns first (Copy All Rows still copies them)
        fit_columns(self.tree, {c: w for c, (_t, w) in headers.items()},
                    drop_order=("unrealized_loss", "realized_loss"))
        add_treeview_copy_menu(self.tree)

        self.tree.tag_configure('profit', foreground=ModernStyle.SUCCESS)
        self.tree.tag_configure('loss', foreground=ModernStyle.ERROR)
        self.tree.tag_configure('even', background=ModernStyle.BG_SECONDARY)
        self.tree.tag_configure('odd', background=ModernStyle.BG_TERTIARY)
        self.tree.tag_configure('group', font=ModernStyle.FONT_REPORT_TABLE_BOLD,
                                background=ModernStyle.ACCENT_PRIMARY_PALE, foreground=ModernStyle.TEXT_ACCENT)
        self.tree.tag_configure('summary', font=ModernStyle.FONT_REPORT_TABLE_BOLD,
                                background=ModernStyle.BG_TERTIARY, foreground=ModernStyle.TEXT_PRIMARY)

    def _populate_table(self, metrics: dict, currency_filter: str):
        self.tree.delete(*self.tree.get_children())
        grouped = defaultdict(list)
        for broker, data in metrics.items():
            grouped[data.get("currency", "INR")].append((broker, data))
        shown = [c for c in sorted(grouped) if currency_filter == "All" or c == currency_filter]

        keys = ("total_invested", "total_value", "unrealized_pnl", "unrealized_loss",
                "realized_pnl", "realized_loss", "overall_pnl")
        for c in shown:
            if len(shown) > 1:
                self.tree.insert("", tk.END, values=(f"{c} brokers",) + ("",) * 8, tags=('group',))
            totals = dict.fromkeys(keys, 0.0)
            rows = sorted(grouped[c], key=lambda item: item[1].get("overall_pnl", 0.0), reverse=True)
            for idx, (broker, data) in enumerate(rows):
                v = {k: float(data.get(k, 0.0) or 0.0) for k in keys}
                for k in keys:
                    totals[k] += v[k]
                xirr = float(data.get("overall_xirr", 0.0) or 0.0)
                xirr_txt = "0.00%" if abs(xirr) < 0.005 else f"{'▲' if xirr > 0 else '▼'} {abs(xirr):.2f}%"
                self.tree.insert("", tk.END, values=(
                    broker,
                    format_money(v["total_invested"], c),
                    format_money(v["total_value"], c),
                    signed_money(v["unrealized_pnl"], c),
                    signed_money(v["unrealized_loss"], c),
                    signed_money(v["realized_pnl"], c),
                    signed_money(v["realized_loss"], c),
                    signed_money(v["overall_pnl"], c),
                    xirr_txt,
                ), tags=('odd' if idx % 2 else 'even', 'profit' if v["overall_pnl"] >= 0 else 'loss'))
            self.tree.insert("", tk.END, values=(
                f"TOTAL ({c})",
                format_money(totals["total_invested"], c),
                format_money(totals["total_value"], c),
                signed_money(totals["unrealized_pnl"], c),
                signed_money(totals["unrealized_loss"], c),
                signed_money(totals["realized_pnl"], c),
                signed_money(totals["realized_loss"], c),
                signed_money(totals["overall_pnl"], c),
                "",
            ), tags=('summary',))

    # ── chart ────────────────────────────────────────────────────────────────
    def _build_chart(self):
        frame = tk.Frame(self._content, bg=ModernStyle.BG_SECONDARY, highlightthickness=1,
                         highlightbackground=ModernStyle.BORDER_COLOR, height=230)
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 16))
        frame.pack_propagate(False)

        head = tk.Frame(frame, bg=ModernStyle.BG_SECONDARY)
        head.pack(fill="x", padx=16, pady=(10, 2))
        tk.Label(head, text="Investment vs current value by broker", font=ModernStyle.FONT_HEADING,
                 bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_ACCENT).pack(side="left")
        for colour, text in ((ModernStyle.ACCENT_PRIMARY, "Invested"),
                             (ModernStyle.SUCCESS_FILL, "Value (gain)"),
                             (ModernStyle.ERROR_FILL, "Value (loss)")):
            tk.Label(head, text=text, fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
                     font=ModernStyle.FONT_SMALL).pack(side="right", padx=(4, 12))
            tk.Frame(head, bg=colour, width=12, height=12).pack(side="right")

        self._chart_canvas = tk.Canvas(frame, bg=ModernStyle.BG_SECONDARY, highlightthickness=0)
        self._chart_canvas.pack(fill=tk.BOTH, expand=True)
        self._chart_canvas.bind("<Configure>", self._on_chart_resize)
        self._chart_canvas.bind("<Motion>", self._on_chart_motion)
        self._chart_canvas.bind("<Leave>", lambda _e: self._hide_tip())

    def _on_chart_resize(self, event):
        size = (event.width, event.height)
        if size == self._chart_size:
            return
        if self._chart_after:
            self.after_cancel(self._chart_after)
        self._chart_after = self.after(150, self._draw_chart)   # draw once, after the resize settles

    def _draw_chart(self):
        self._chart_after = None
        cv = self._chart_canvas
        cv.delete("all")
        self._tip_data = {}
        self._tip_item = None
        w, h = cv.winfo_width(), cv.winfo_height()
        self._chart_size = (w, h)
        if w < 50 or h < 50 or not self._cached_metrics:
            return

        currency_filter = self._current_currency.get()
        grouped = defaultdict(list)
        for broker, data in self._cached_metrics.items():
            grouped[data.get("currency", "INR")].append((broker, data))
        shown = [c for c in sorted(grouped) if currency_filter == "All" or c == currency_filter]
        if not shown:
            cv.create_text(w / 2, h / 2, text="No data for this currency yet",
                           fill=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_BODY)
            return

        section_w = w / len(shown)
        pad_l, pad_r, pad_t, pad_b = 70, 20, 26, 30
        for idx, c in enumerate(shown):
            brokers = sorted(grouped[c], key=lambda item: item[1].get("total_value", 0.0), reverse=True)
            x_off = idx * section_w
            max_val = max([max(d.get("total_invested", 0.0), d.get("total_value", 0.0)) for _, d in brokers] + [1.0])
            plot_w = section_w - pad_l - pad_r
            plot_h = h - pad_t - pad_b
            left, base = x_off + pad_l, h - pad_b

            if len(shown) > 1:
                cv.create_text(x_off + section_w / 2, 4, text=f"{c} brokers", anchor="n",
                               fill=ModernStyle.TEXT_PRIMARY, font=ModernStyle.FONT_SMALL_BOLD)
            for i in range(6):
                y = base - (i / 5) * plot_h
                cv.create_text(left - 6, y, text=_short_amount((i / 5) * max_val, c), anchor="e",
                               fill=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_SMALL)
                if i:
                    cv.create_line(left, y, left + plot_w, y, fill=ModernStyle.DIVIDER_COLOR, dash=(2, 2))
            cv.create_line(left, pad_t, left, base, fill=ModernStyle.TEXT_TERTIARY)
            cv.create_line(left, base, left + plot_w, base, fill=ModernStyle.TEXT_TERTIARY)

            group_w = plot_w / len(brokers)
            bar_w = min(40, group_w * 0.35)
            gap = bar_w * 0.1
            for i, (name, data) in enumerate(brokers):
                inv = float(data.get("total_invested", 0.0) or 0.0)
                cur = float(data.get("total_value", 0.0) or 0.0)
                xc = left + i * group_w + group_w / 2
                y_inv = base - (inv / max_val) * plot_h
                y_cur = base - (cur / max_val) * plot_h
                inv_id = cv.create_rectangle(xc - bar_w - gap / 2, y_inv, xc - gap / 2, base,
                                             fill=ModernStyle.ACCENT_PRIMARY, outline="")
                cur_id = cv.create_rectangle(xc + gap / 2, y_cur, xc + bar_w + gap / 2, base, outline="",
                                             fill=ModernStyle.SUCCESS_FILL if cur >= inv else ModernStyle.ERROR_FILL)
                self._tip_data[inv_id] = (f"{name}: invested {format_money(inv, c)}", xc - bar_w / 2, y_inv)
                self._tip_data[cur_id] = (f"{name}: now worth {format_money(cur, c)}  ({signed_money(cur - inv, c)})",
                                          xc + bar_w / 2, y_cur)
                label = name if len(name) <= 12 else name[:10] + "…"
                cv.create_text(xc, base + 6, text=label, anchor="n",
                               fill=ModernStyle.TEXT_PRIMARY, font=ModernStyle.FONT_SMALL)

    def _on_chart_motion(self, event):
        cv = self._chart_canvas
        hit = next((i for i in reversed(cv.find_overlapping(event.x, event.y, event.x, event.y))
                    if i in self._tip_data), None)
        if hit == self._tip_item:
            return                      # nothing changed: no redraw
        self._hide_tip()
        if hit is None:
            return
        self._tip_item = hit
        text, x, top = self._tip_data[hit]
        t = cv.create_text(x, max(top - 8, 18), text=text, anchor="s", tags="tip",
                           fill=ModernStyle.TEXT_PRIMARY, font=ModernStyle.FONT_SMALL_BOLD)
        x0, y0, x1, y1 = cv.bbox(t)
        shift = min(0, cv.winfo_width() - 4 - (x1 + 8)) or max(0, 4 - (x0 - 8))
        if shift:
            cv.move(t, shift, 0)
            x0, x1 = x0 + shift, x1 + shift
        cv.create_rectangle(x0 - 8, y0 - 4, x1 + 8, y1 + 4, fill=ModernStyle.BG_TERTIARY,
                            outline=ModernStyle.BORDER_COLOR, tags="tip")
        cv.tag_raise(t)

    def _hide_tip(self):
        if self._tip_item is not None:
            self._chart_canvas.delete("tip")
            self._tip_item = None

    # ── data ─────────────────────────────────────────────────────────────────
    def load_data(self):
        currency = self._current_currency.get()       # read on the main thread
        self._load_seq += 1
        seq = self._load_seq
        self._set_status("Loading…")

        def work():
            from model.engine import (get_metrics_by_broker, calculate_overall_xirr,
                                      get_dashboard_metrics, get_exchange_rate)
            metrics = get_metrics_by_broker(currency_filter=currency, force_refresh=True)
            totals = {"inv": 0.0, "val": 0.0, "pnl": 0.0}
            rates = {}
            for data in metrics.values():
                c = data.get("currency", "INR")
                if currency != "All" and c != currency:
                    continue
                if currency == "All" and c not in rates:
                    rates[c] = get_exchange_rate(c)
                rate = rates.get(c, 1.0)
                totals["inv"] += data.get("total_invested", 0.0) * rate
                totals["val"] += data.get("total_value", 0.0) * rate
                totals["pnl"] += data.get("overall_pnl", 0.0) * rate
            totals["xirr"] = calculate_overall_xirr(currency_filter=currency)
            totals["cagr"] = get_dashboard_metrics(currency_filter=currency).get("overall_cagr", 0.0)
            return metrics, totals, rates

        def done(payload):
            if seq != self._load_seq:
                return                  # a newer request is on its way
            metrics, totals, rates = payload
            self._cached_metrics = metrics
            self._populate_table(metrics, currency)
            self._show_kpis(totals, currency)
            others = sorted(c for c in rates if c != "INR")
            if others:
                parts = ", ".join(f"{currency_symbol(c)}1 = ₹{rates[c]:.4f}" for c in others)
                self._set_status(f"ℹ  The cards show all brokers in ₹: {', '.join(others)} amounts are "
                                 f"converted at today's exchange rate ({parts}).")
            elif not metrics:
                self._set_status("No holdings or sales yet for this currency.")
            else:
                self._set_status("")
            self._draw_chart()

        def failed(err):
            if seq != self._load_seq:
                return
            self._cached_metrics = {}
            self.tree.delete(*self.tree.get_children())
            for lbl in self.kpi_labels.values():
                lbl.config(text="—", fg=ModernStyle.TEXT_TERTIARY)
            self._draw_chart()
            self._set_status(f"✖  Could not load the broker figures: {err}", "error")

        run_in_background(work, done, failed, widget=self, name="broker-report")

    # ── PDF ──────────────────────────────────────────────────────────────────
    def _export_pdf(self):
        if not self._cached_metrics:
            messagebox.showwarning("No Data", "There is nothing to export yet. Please wait for the report to load.")
            return
        filepath = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            title="Save P&L Report As",
            initialfile=f"Broker_Report_{datetime.now().strftime('%Y%m%d')}.pdf",
        )
        if not filepath:
            return

        metrics = {b: dict(d) for b, d in self._cached_metrics.items()}   # a copy for the thread
        currency = self._current_currency.get()
        self._pdf_btn.set_disabled(True)
        self._set_status("Creating the PDF…")

        def work():
            from scripts.export_pdf import generate_broker_report_pdf
            generate_broker_report_pdf(filepath, metrics, currency)
            return filepath

        def done(path):
            self._pdf_btn.set_disabled(False)
            self._set_status(f"✓  PDF saved: {path}", "success")

        def failed(err):
            self._pdf_btn.set_disabled(False)
            self._set_status(f"✖  Could not create the PDF: {err}", "error")
            messagebox.showerror("Export Failed", f"Could not create the PDF:\n{err}")

        run_in_background(work, done, failed, widget=self, name="broker-pdf")
