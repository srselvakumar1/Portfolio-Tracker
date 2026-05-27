"""
Watchlist View — single-screen CRUD for tracked symbols.

Layout (top → bottom):
  • Header row with title and quick-add shortcut hint
  • Inline Add / Edit form (symbol, notes, tags, target price + Save / Clear / Delete)
  • Treeview table showing all watchlist entries
  Clicking a row pre-fills the form for editing.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox

from views.base_view import BaseView, _enable_canvas_mousewheel
from ui_theme import ModernStyle
from ui_widgets import ModernButton, PremiumModal, ModernEntry, ModernCard
from ui_utils import add_treeview_copy_menu, treeview_sort_column, fade_color_transition
import pandas as pd
import yfinance as yf

class WatchlistView(BaseView):
    """Watchlist view with inline CRUD form and a live Treeview table."""

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def build(self):
        self._selected_id: int | None = None   # id of row being edited
        self._data: list[dict] = []

        def _build_right(parent):
            self._btn_refresh_all = ModernButton(
                parent, text="🔄 Refresh All",
                command=self._bulk_refresh_metrics,
                bg=ModernStyle.ACCENT_SECONDARY, fg=ModernStyle.TEXT_ON_ACCENT,
                canvas_bg="#0D9488", width=140, height=36, radius=8,
                font=ModernStyle.FONT_BODY_BOLD
            )
            self._btn_refresh_all.pack(anchor="e", pady=(0, 4))

        self.add_gradient_header(
            self,
            "👁  Watchlist",
            "Track symbols you're watching — double-click a row to pre-fill the form.",
            right_widget_func=_build_right
        )

        # ── Inline form ───────────────────────────────────────────────────────
        form_card = ModernCard(self,
            bg=ModernStyle.BG_SECONDARY,
            highlight_color=ModernStyle.BORDER_COLOR,
            highlight_thickness=1,
            radius=10,
            canvas_bg=ModernStyle.BG_PRIMARY
        )
        form_card.pack(fill="x", padx=20, pady=(14, 6))

        # Thin top accent
        # tk.Frame(form_card, bg=ModernStyle.ACCENT_PRIMARY, height=3).pack(fill="x")

        form_inner = tk.Frame(form_card.content, bg=ModernStyle.BG_SECONDARY)
        form_inner.pack(fill="x", padx=16, pady=14)

        # Row 1: Symbol | Notes | Tags | Target Price
        fields_row = tk.Frame(form_inner, bg=ModernStyle.BG_SECONDARY)
        fields_row.pack(fill="x")

        def _field(parent, label: str, var: tk.StringVar, width: int = 14, numeric=False) -> tk.Entry:
            col = tk.Frame(parent, bg=ModernStyle.BG_SECONDARY)
            col.pack(side="left", padx=(0, 16))
            tk.Label(
                col, text=label, bg=ModernStyle.BG_SECONDARY,
                fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_SMALL_BOLD
            ).pack(anchor="w", pady=(0, 2))
            
            e = ModernEntry(
                col, placeholder=label,
                textvariable=var,
                bg=ModernStyle.ENTRY_BG,
                fg=ModernStyle.TEXT_PRIMARY,
                insertbackground=ModernStyle.TEXT_PRIMARY,
                highlightthickness=1,
                highlightcolor=ModernStyle.ACCENT_PRIMARY,
                highlightbackground=ModernStyle.BORDER_COLOR,
                relief=tk.FLAT,
                font=ModernStyle.FONT_INPUT,
                width=width
            )
            e.pack(anchor="w")
            return e

        self._v_symbol = tk.StringVar()
        self._v_notes  = tk.StringVar()
        self._v_tags   = tk.StringVar()
        self._v_target = tk.StringVar()

        self._metrics_keys = [
            "pe_ratio", "peg_ratio", "eps", "debt_to_equity", "book_value", "intrinsic_value",
            "roe", "roce", "opm", "free_cash_flow", "inventory_days",
            "sales_growth", "profit_growth",
            "promoter_holding", "pledged_shares", "fii_dii_holding", "order_book",
            "dma_50_200", "rsi", "volume",
            "ebitda_margin", "capex", "net_profit_margin", "sharpe_ratio", "qoq_op_profit",
            "beta", "week52_range", "current_ratio", "dividend_yield",
            "pb_ratio", "analyst_target", "market_cap", "action_signal",
            "sector", "industry", "current_value",
        ]
        self._metrics_vars = {k: tk.StringVar() for k in self._metrics_keys}

        self._e_symbol = _field(fields_row, "Symbol *",      self._v_symbol, width=20)
        
        # Quick Add Button inside the symbol row aligned with the entries
        ModernButton(
            fields_row, text="➕",
            command=self._on_quick_add,
            bg=ModernStyle.BRAND_GOLD, fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.BG_SECONDARY,
            width=36, height=36, radius=8,
            font=ModernStyle.FONT_HEADING,
        ).pack(side="left", padx=(0, 16), pady=(4, 0))
        
        _field(fields_row, "Notes",         self._v_notes,  width=60)

        # Row 2: Buttons (right-aligned)
        btn_row = tk.Frame(form_inner, bg=ModernStyle.BG_SECONDARY)
        btn_row.pack(fill="x", pady=(10, 0))

        ModernButton(
            btn_row, text="💾  Save",
            command=self._on_save,
            bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.BG_SECONDARY,
            width=110, height=36, radius=8,
            font=ModernStyle.FONT_SUBHEADING,
        ).pack(side="left", padx=(0, 8))

        ModernButton(
            btn_row, text="✕  Clear",
            command=self._clear_form,
            bg=ModernStyle.TEXT_SECONDARY, fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.BG_SECONDARY,
            width=100, height=36, radius=8,
            font=ModernStyle.FONT_SUBHEADING,
        ).pack(side="left", padx=(0, 8))

        ModernButton(
            btn_row, text="📋  Edit Metrics",
            command=self._open_metrics_dialog,
            bg=ModernStyle.ACCENT_TERTIARY, fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.BG_SECONDARY,
            width=140, height=36, radius=8,
            font=ModernStyle.FONT_BODY_BOLD,
        ).pack(side="left", padx=(0, 8))

        self._del_btn = ModernButton(
            btn_row, text="🗑  Delete",
            command=self._on_delete,
            bg=ModernStyle.ERROR, fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.BG_SECONDARY,
            width=110, height=36, radius=8,
            font=ModernStyle.FONT_SUBHEADING,
        )
        self._del_btn.pack(side="left")
        self._del_btn.set_disabled(True)   # enabled only when a row is selected

        self._form_status = tk.Label(
            btn_row,
            text="",
            fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_SMALL,
        )
        self._form_status.pack(side="right", padx=4)

        # ── Treeview table ────────────────────────────────────────────────────
        table_frame = ModernCard(
            self,
            bg=ModernStyle.BG_SECONDARY,
            highlight_color=ModernStyle.BORDER_COLOR,
            highlight_thickness=1,
            radius=10,
            canvas_bg=ModernStyle.BG_PRIMARY,
            expand_height=True,
        )
        table_frame.pack(fill="both", expand=True, padx=20, pady=(6, 20))
        table_frame.content.grid_rowconfigure(0, weight=1)
        table_frame.content.grid_columnconfigure(0, weight=1)

        cols = ("#", "Symbol", "Signal", "Sector / Industry", "Current ₹", "IV (DCF)", "MoS %", "Graham No.", "Target ₹", "P/E", "PEG", "Yield(%)", "From 52W H", "Notes", "Added")
        
        style = ttk.Style()
        style.configure("Watchlist.Treeview", font=ModernStyle.FONT_TABLE, rowheight=32)
        style.configure("Watchlist.Treeview.Heading", font=ModernStyle.FONT_SUBHEADING)
        
        self._tv = ttk.Treeview(
            table_frame.content, columns=cols, show="headings",
            selectmode="browse", style="Watchlist.Treeview"
        )
        col_widths = [36, 100, 130, 140, 90, 80, 70, 90, 80, 50, 50, 60, 90, 200, 80]
        sortable_cols = ("Symbol", "Signal", "P/E", "IV (DCF)")
        
        for c, w in zip(cols, col_widths):
            if c in sortable_cols:
                self._tv.heading(c, text=f"{c} ↕", command=lambda col=c: treeview_sort_column(self._tv, col, False), anchor="w" if c != "#" else "center")
            else:
                self._tv.heading(c, text=c, anchor="w" if c != "#" else "center")
            self._tv.column(c, width=w, minwidth=w, anchor="w" if c != "#" else "center")
        self._tv.heading("Added", text="Added", anchor="center")
        self._tv.column("Added", anchor="center")

        # Tag styles
        self._tv.tag_configure("odd",  background=ModernStyle.BG_SECONDARY)
        self._tv.tag_configure("even", background=ModernStyle.BG_PRIMARY)
        # Signal-based full row background colouring
        self._tv.tag_configure("sig_strong_buy", background="#DCFCE7", foreground="#15803D")  # pastel green
        self._tv.tag_configure("sig_accumulate", background="#d2fee2", foreground="#065F46")  # much more visible green
        self._tv.tag_configure("sig_wait",        background="#FFF7ED", foreground="#C2410C")  # pastel orange
        self._tv.tag_configure("sig_avoid",       background="#FEF2F2", foreground="#B91C1C")  # pastel red
        self._tv.tag_configure("undervalued",     background="#D1FAE5", foreground="#065F46", font=ModernStyle.FONT_SMALL_BOLD)
        self._tv.tag_configure("overvalued",      background="#FEE2E2", foreground="#991B1B", font=ModernStyle.FONT_SMALL_BOLD)

        vsb = ttk.Scrollbar(table_frame.content, orient="vertical",   command=self._tv.yview)
        hsb = ttk.Scrollbar(table_frame.content, orient="horizontal", command=self._tv.xview)
        self._tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.content.grid_rowconfigure(0, weight=1)
        table_frame.content.grid_columnconfigure(0, weight=1)
        
        # Add right click copy menu
        add_treeview_copy_menu(self._tv)

        # Row selection → fill form
        self._tv.bind("<ButtonRelease-1>", self._on_row_select)
        self._tv.bind("<Double-1>",        self._on_double_click)

        # Allow Escape to deselect
        self.bind("<Escape>", lambda _: self._clear_form())

    # ── Data loading ──────────────────────────────────────────────────────────

    def on_show(self):
        self._is_active = True
        self._data_loaded = False   # always refresh on navigate
        self.load_data()

    def load_data(self):
        self._data_loaded = True
        threading.Thread(target=self._bg_load, daemon=True).start()

    def _bg_load(self):
        try:
            from model.watchlist_db import get_all_watchlist
            data = get_all_watchlist()
            self.after(0, lambda: self._populate_table(data))
        except Exception as exc:
            print(f"[Watchlist] load error: {exc}")

    # ── Table rendering ───────────────────────────────────────────────────────

    def _populate_table(self, data: list[dict]) -> None:
        self._data = data
        self._tv.delete(*self._tv.get_children())
        for i, row in enumerate(data):
            analyst_target = str(row.get("analyst_target") or "—").strip()
            target_str = analyst_target if analyst_target and analyst_target != "None" else "—"
            tag = "odd" if i % 2 == 0 else "even"
            signal_badge, _ = self._compute_signal(row)
            # Build Sector / Industry combined cell
            sector = row.get("sector", "") or ""
            industry = row.get("industry", "") or ""
            sector_cell = " / ".join(filter(None, [sector, industry])) or "—"
            
            # Determine conditional styling tag for the current value cell
            curr_val = row.get("current_value")
            intr_val = row.get("intrinsic_value")
            cv_str = curr_val if curr_val else "—"
            iv_str = intr_val if intr_val else "—"
            
            cv_f = self._parse_num(curr_val)
            iv_f = self._parse_num(intr_val)
            
            mos_str = "—"
            graham_str = "—"
            from_high_str = "—"
            
            # Additional UI Context Computations
            if cv_f is not None:
                # 1. Margin of Safety
                if iv_f is not None and iv_f > 0:
                    mos_pct = ((iv_f - cv_f) / iv_f) * 100
                    prefix = "▲ +" if mos_pct > 0 else "▼ "
                    mos_str = f"{prefix}{mos_pct:.1f}%"
                    
                # 2. Graham Number
                eps_f = self._parse_num(str(row.get("eps")))
                bv_f = self._parse_num(str(row.get("book_value")))
                if eps_f and bv_f and eps_f > 0 and bv_f > 0:
                    import math
                    graham_val = math.sqrt(22.5 * eps_f * bv_f)
                    graham_str = f"₹{graham_val:.1f}"
                    
                # 3. Distance from 52-Week High
                range_52 = str(row.get("week52_range") or "")
                if range_52 and "–" in range_52:
                    parts = range_52.split("–")
                    if len(parts) == 2:
                        high_f = self._parse_num(parts[1])
                        if high_f and high_f > 0:
                            drop_pct = ((cv_f - high_f) / high_f) * 100
                            prefix = "▲ +" if drop_pct > 0 else "▼ "
                            from_high_str = f"{prefix}{drop_pct:.1f}%"
            
            price_tag = tag # Default to normal row color
            if cv_f and iv_f:
                if iv_f > 0: # Avoid division by zero
                    if cv_f < iv_f * 0.85: # Strong undervaluation
                        price_tag = "undervalued"
                    elif cv_f > iv_f * 1.15: # Strong overvaluation
                        price_tag = "overvalued"
                
            # Determine signal tag for full-row background coloring
            sig_tag = "odd"
            sig_lower = signal_badge.lower()
            if "strong buy" in sig_lower:
                sig_tag = "sig_strong_buy"
            elif "accumulate" in sig_lower:
                sig_tag = "sig_accumulate"
            elif "wait" in sig_lower or "watch" in sig_lower:
                sig_tag = "sig_wait"
            elif "avoid" in sig_lower:
                sig_tag = "sig_avoid"
            else:
                sig_tag = tag  # fallback to odd/even default
            
            # Use valuation override when signal is neutral/unavailable
            row_tags = (sig_tag,) if sig_tag not in ("odd", "even") else (tag,)
            if price_tag in ("undervalued", "overvalued") and sig_tag in ("odd", "even"):
                row_tags = (price_tag,)  # Only apply valuation color if no signal color

            self._tv.insert(
                "", "end",
                iid=str(row["id"]),
                values=(
                    i + 1,
                    row.get("symbol", ""),
                    signal_badge,
                    sector_cell,
                    cv_str,
                    iv_str,
                    mos_str,
                    graham_str,
                    target_str,
                    row.get("pe_ratio", "") or "—",
                    row.get("peg_ratio", "") or "—",
                    row.get("dividend_yield", "") or "—",
                    from_high_str,
                    row.get("notes", "") or row.get("stock_name", "") or "",
                    row.get("added_on", ""),
                ),
                tags=row_tags,
            )

    # ── Signal Engine ─────────────────────────────────────────────────────────

    @staticmethod
    def _parse_num(val_str: str) -> float | None:
        """Strip common formatting and return float or None."""
        if not val_str or str(val_str).strip() in ("", "None", "—"):
            return None
        clean = str(val_str).replace(",", "").replace("%", "").replace("₹","").replace(" Cr","e7").strip()
        # Handle '1.4e7' style if Cr suffix was converted
        clean = clean.replace("Cre7", "e7")
        try:
            return float(clean)
        except ValueError:
            return None

    def _compute_signal(self, row: dict) -> tuple[str, str]:
        """Compute buy/sell signal and reason tip from row metrics.
        Returns (badge_text, reason_tip_text).
        """
        score = 0
        max_score = 0
        reasons_pass = []
        reasons_fail = []

        def check(label, key, condition_fn, tip_pass, tip_fail):
            nonlocal score, max_score
            max_score += 1
            v = self._parse_num(str(row.get(key, "")))
            if v is None:
                return  # No data = no score
            if condition_fn(v):
                score += 1
                reasons_pass.append(f"✅ {label}: {tip_pass}")
            else:
                score -= 1
                reasons_fail.append(f"❌ {label}: {tip_fail}")

        # === Valuation ===
        check("P/E", "pe_ratio",
              lambda v: 0 < v < 30,
              "Reasonable valuation", "Overvalued or negative earnings")
        check("PEG Ratio", "peg_ratio",
              lambda v: v < 2.0,
              "Growth at fair price", "Expensive relative to growth")
        check("P/B Ratio", "pb_ratio",
              lambda v: v < 3.0,
              "Reasonable price-to-book", "High price vs book value")
        check("Debt/Equity", "debt_to_equity",
              lambda v: v < 1.0,
              "Low financial leverage", "High debt is risky")
        check("Current Ratio", "current_ratio",
              lambda v: v >= 1.5,
              "Healthy short-term liquidity", "May struggle to meet short-term obligations")

        # === Profitability ===
        check("ROE", "roe",
              lambda v: v >= 12.0,
              "Strong return on equity", "Weak returns for shareholders")
        check("ROCE", "roce",
              lambda v: v >= 12.0,
              "Efficient capital allocation", "Capital not being used efficiently")
        check("OPM", "opm",
              lambda v: v >= 10.0,
              "Healthy operating margins", "Thin operating margins")
        check("Net Profit Margin", "net_profit_margin",
              lambda v: v >= 8.0,
              "Solid profitability", "Low net margins")
        check("Free Cash Flow", "free_cash_flow",
              lambda v: v > 0,
              "Positive FCF — company self-funds growth", "Negative FCF — cash burn risk")
        check("EBITDA Margin", "ebitda_margin",
              lambda v: v >= 15.0,
              "Good earnings before interest and taxes", "Low EBITDA margins")

        # === Growth ===
        check("Sales Gr", "sales_growth", lambda v: v >= 10.0, "Strong revenue growth", "Sluggish growth")
        check("Profit Gr", "profit_growth", lambda v: v >= 10.0, "Earnings expanding rapidly", "Profit growth lagging")
        check("3Y Rev CAGR", "revenue_cagr_3y", lambda v: v >= 10.0, "Consistent 3-year revenue compounding", "Inconsistent long-term revenue")
        check("3Y Profit CAGR", "profit_cagr_3y", lambda v: v >= 10.0, "Consistent 3-year profit compounding", "Inconsistent long-term profit")
        check("QoQ Op", "qoq_op_profit", lambda v: v > 0, "Sequential operating improvement", "Operating profit declined")

        # === Intrinsic Value ===
        # Special check comparing IV to Current Price
        # In Watchlist, these are mostly strings formatted with currency, so we need to parse them
        try:
            cp_str = str(row.get("current_value", ""))
            iv_str = str(row.get("intrinsic_value", ""))
            if cp_str and iv_str and cp_str != "—" and iv_str != "—":
                cp = float(cp_str.replace("₹", "").replace(",", ""))
                iv = float(iv_str.replace("₹", "").replace(",", ""))
                
                if cp > 0 and iv > 0:
                    max_score += 2 # Give higher weight to margin of safety
                    if cp < iv * 0.8: # >20% margin of safety
                        score += 2
                        reasons_pass.append("✅ Intrinsic Value: Trading at >20% discount to DCF value (Safety Margin)")
                    elif cp < iv: 
                        score += 1
                        reasons_pass.append("✅ Intrinsic Value: Trading below DCF intrinsic value")
                    else:
                        score -= 1 # Not necessarily a double penalty
                        reasons_fail.append("❌ Intrinsic Value: Trading above DCF intrinsic value (Overvalued)")
        except: pass

        gn_str = str(row.get("graham_number", ""))
        try:
            if gn_str and gn_str != "—" and gn_str != "None":
                cp = float(str(row.get("current_value", "")).replace("₹", "").replace(",", ""))
                gn = float(gn_str.replace("₹", "").replace(",", ""))
                if gn and cp:
                    max_score += 1
                    if cp < gn:
                        score += 1
                        reasons_pass.append("✅ Graham Number: Price is below classic defensive valuation limit")
                    else:
                        score -= 1
                        reasons_fail.append("❌ Graham Number: Price exceeds defensive valuation threshold")
        except: pass

        # === Additional Technical / Valuation ===
        check("Dividend", "dividend_yield", lambda v: v >= 1.2, "Healthy dividend payout", "Low or no dividend yield")
        
        atpt_str = str(row.get("analyst_target", ""))
        try:
            if atpt_str and atpt_str != "—" and atpt_str != "None":
                cp = float(str(row.get("current_value", "")).replace("₹", "").replace(",", ""))
                at = float(atpt_str.replace("₹", "").replace(",", ""))
                if cp and at:
                    max_score += 1
                    if cp < at * 0.9:
                        score += 1
                        reasons_pass.append("✅ Analyst Target: Price is >10% below average analyst target")
                    elif cp > at * 1.1:
                        score -= 1
                        reasons_fail.append("❌ Analyst Target: Price exceeds analyst target by >10%")
        except: pass

        range52_str = str(row.get("week52_range", ""))
        try:
            if range52_str and "–" in range52_str:
                parts = range52_str.split("–")
                if len(parts) == 2:
                    l52 = float(parts[0].replace(",", "").strip())
                    h52 = float(parts[1].replace(",", "").strip())
                    cp = float(str(row.get("current_value", "")).replace("₹", "").replace(",", ""))
                    if l52 < h52 and cp:
                        max_score += 1
                        pos_pct = (cp - l52) / (h52 - l52)
                        if pos_pct < 0.25:
                            score += 1
                            reasons_pass.append("✅ 52W Range: Trading near 52-week lows (Potential value)")
                        elif pos_pct > 0.85:
                            score -= 1
                            reasons_fail.append("❌ 52W Range: Trading near 52-week highs (Potential resistance zone)")
        except: pass

        # === Ownership ===
        check("Promoters", "promoter_holding", lambda v: v >= 40.0, "Promoters have skin in the game", "Low promoter confidence")

        # === Technical ===
        check("RSI", "rsi", lambda v: 30.0 <= v <= 65.0, "Good entry zone", "Overbought or deeply oversold")
        check("Beta", "beta", lambda v: v < 1.5, "Lower volatility vs market", "High beta — volatile stock")
        check("MACD", "macd", lambda v: v > 0, "Short-term momentum is bullish", "Short-term momentum is bearish")

        # ── Determine badge ──
        pct = score / max_score if max_score else 0
        if pct >= 0.65:
            badge = " 🟢  Strong Buy "
        elif pct >= 0.4:
            badge = " 🌲  Accumulate "
        elif pct >= 0.1:
            badge = " 🔸  Wait / Watch "
        else:
            badge = " 🔻  Avoid "

        # ── Build reason tip ──
        tip_lines = [f"Signal: {badge}  (Score: {score}/{max_score})"]
        if reasons_pass:
            tip_lines.append("\nStrengths:")
            tip_lines.extend(reasons_pass)
        if reasons_fail:
            tip_lines.append("\nWeaknesses:")
            tip_lines.extend(reasons_fail)
        if score == 0 and max_score == 0:
            tip_lines.append("No metrics fetched yet. Use Auto-Fill to populate.")
        tip = "\n".join(tip_lines)

        return badge, tip

    # ── Form helpers ──────────────────────────────────────────────────────────

    def _clear_form(self, _=None) -> None:
        self._selected_id = None
        self._v_symbol.set("")
        self._v_notes.set("")
        self._v_tags.set("")
        self._v_target.set("")
        for v in self._metrics_vars.values():
            v.set("")
        self._form_status.config(text="", fg=ModernStyle.TEXT_TERTIARY)
        try:
            self._del_btn.set_disabled(True)
        except Exception:
            pass
        try:
            for sel in self._tv.selection():
                self._tv.selection_remove(sel)
        except Exception:
            pass


    def _on_double_click(self, _=None):
        sel = self._tv.selection()
        if not sel: return
        iid = sel[0]
        try:
            row = next(r for r in self._data if str(r["id"]) == str(iid))
        except StopIteration: return
        self._open_diagnostic_popup(row)

    def _on_row_select(self, _=None) -> None:
        sel = self._tv.selection()
        if not sel:
            return
        iid = sel[0]
        # Find row dict by id
        try:
            row = next(r for r in self._data if str(r["id"]) == str(iid))
        except StopIteration:
            return

        self._selected_id = row["id"]
        self._v_symbol.set(row.get("symbol", ""))
        self._v_notes.set(row.get("notes", ""))
        self._v_tags.set(row.get("tags", ""))
        target = row.get("target_price") or 0.0
        self._v_target.set(str(target) if target else "")
        for k, v in self._metrics_vars.items():
            v.set(row.get(k, ""))
        self._form_status.config(
            text=f"Editing: {row.get('symbol', '')}",
            fg=ModernStyle.ACCENT_TERTIARY,
        )
        try:
            self._del_btn.set_disabled(False)
        except Exception:
            pass

    # ── CRUD event handlers ───────────────────────────────────────────────────

    def _on_save(self) -> None:
        from model.watchlist_db import add_watchlist, update_watchlist

        symbol = self._v_symbol.get().strip().upper()
        if not symbol:
            self._flash_status("⚠  Symbol is required.", error=True)
            return

        notes  = self._v_notes.get().strip()
        tags   = self._v_tags.get().strip()
        target = 0.0


        def _bg():
            try:
                metrics = {k: v.get().strip() for k, v in self._metrics_vars.items()}
                if self._selected_id is None:
                    add_watchlist(symbol, notes, tags, target, **metrics)
                    msg = f"✅  '{symbol}' added to watchlist."
                else:
                    update_watchlist(self._selected_id, symbol, notes, tags, target, **metrics)
                    msg = f"✅  '{symbol}' updated."
                self.after(0, lambda: self._post_save(msg))
            except ValueError as exc:
                self.after(0, lambda: self._flash_status(f"⚠  {exc}", error=True))
            except Exception as exc:
                self.after(0, lambda: self._flash_status(f"⚠  {exc}", error=True))

        threading.Thread(target=_bg, daemon=True).start()

    def _on_quick_add(self) -> None:
        """Always add to the watchlist — never overwrite an existing entry."""
        from model.watchlist_db import add_watchlist

        symbol = self._v_symbol.get().strip().upper()
        if not symbol:
            self._flash_status("⚠  Symbol is required.", error=True)
            return

        notes  = self._v_notes.get().strip()
        tags   = self._v_tags.get().strip()
        target = 0.0

        def _bg():
            try:
                metrics = {k: v.get().strip() for k, v in self._metrics_vars.items()}
                add_watchlist(symbol, notes, tags, target, **metrics)
                msg = f"✅  '{symbol}' added to watchlist."
                self.after(0, lambda: self._post_save(msg))
            except ValueError as exc:
                self.after(0, lambda: self._flash_status(f"⚠  {exc}", error=True))
            except Exception as exc:
                self.after(0, lambda: self._flash_status(f"⚠  {exc}", error=True))

        threading.Thread(target=_bg, daemon=True).start()

    def _on_delete(self) -> None:
        if self._selected_id is None:
            return
        symbol = self._v_symbol.get().strip().upper() or str(self._selected_id)
        if not messagebox.askyesno(
            "Delete from Watchlist",
            f"Remove '{symbol}' from your watchlist?",
            parent=self,
        ):
            return

        row_id = self._selected_id

        def _bg():
            try:
                from model.watchlist_db import delete_watchlist
                delete_watchlist(row_id)
                self.after(0, lambda: self._post_save(f"🗑  '{symbol}' removed."))
            except Exception as exc:
                self.after(0, lambda: self._flash_status(f"⚠  {exc}", error=True))

        threading.Thread(target=_bg, daemon=True).start()

    def _post_save(self, msg: str) -> None:
        """Refresh table, clear form, show success message."""
        self._clear_form()
        self._flash_status(msg, error=False)
        self.load_data()

    def _flash_status(self, msg: str, *, error: bool = False) -> None:
        try:
            from ui_utils import show_toast
            
            # Clean up the emoji since the toast provides its own
            clean_msg = msg.replace("✅  ", "").replace("🗑  ", "").replace("⚠  ", "").replace("✅ ", "").replace("🗑 ", "").replace("⚠ ", "")
            show_toast(self.winfo_toplevel(), clean_msg, type="error" if error else "success")
            
            # Fallback for the old label, clear it out
            self._form_status.config(text="")
        except Exception:
            # Absolute fallback if ui_utils fails
            color = ModernStyle.ERROR if error else ModernStyle.SUCCESS
            self._form_status.config(text=msg, fg=color)

# ── Edit Metrics Dialog ───────────────────────────────────────────────────


    # ── Auto Fetch Metrics (yfinance) ─────────────────────────────────────────

    def _auto_fetch_metrics(self):
        symbol = self._v_symbol.get().strip().upper()
        if not symbol:
            self._flash_status("⚠ Enter a symbol first to auto-fetch.", error=True)
            return
            
        # Optional NS suffix handling for Indian stocks
        yf_symbol = symbol
        if not yf_symbol.endswith('.NS') and not yf_symbol.endswith('.BO'):
            # If standard Indian symbol length and no dot, default to NSE
            if len(yf_symbol) < 10 and '.' not in yf_symbol:
                yf_symbol += '.NS'

        try:
            if hasattr(self, "_fetch_btn"):
                self._fetch_btn.set_text("🔄 Fetching...")
                self._fetch_btn.set_disabled(True)
        except Exception:
            pass

        def bg_fetch():
            try:
                # import yfinance as yf
                ticker = yf.Ticker(yf_symbol)
                info = ticker.info
                
                # Fetch RSI, Sharpe Ratio, MACD, etc using historical data
                hist = ticker.history(period="3y")
                rsi_val = ""
                sharpe_val = ""
                macd_val = ""
                supp_res = ""
                
                if not hist.empty and len(hist) >= 30:
                    recent_hist = hist.tail(252) # Use last year for technicals
                    
                    # RSI
                    delta = recent_hist['Close'].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                    rs = gain / loss
                    rsi = 100 - (100 / (1 + rs))
                    rsi_last = rsi.iloc[-1]
                    if pd.notna(rsi_last):
                        rsi_val = f"{rsi_last:.1f}"
                        
                    # MACD
                    exp12 = recent_hist['Close'].ewm(span=12, adjust=False).mean()
                    exp26 = recent_hist['Close'].ewm(span=26, adjust=False).mean()
                    macd_line = exp12 - exp26
                    signal_line = macd_line.ewm(span=9, adjust=False).mean()
                    
                    if pd.notna(macd_line.iloc[-1]) and pd.notna(signal_line.iloc[-1]):
                        macd_val = f"{(macd_line.iloc[-1] - signal_line.iloc[-1]):.2f}"
                        
                    # Target Support / Resistance
                    # cur_p = recent_hist['Close'].iloc[-1] # Not used directly for supp_res string
                    recent_min = recent_hist['Low'].tail(60).min()
                    recent_max = recent_hist['High'].tail(60).max()
                    if pd.notna(recent_min) and pd.notna(recent_max):
                        supp_res = f"{recent_min:.0f} / {recent_max:.0f}"
                
                    # Sharpe Ratio (Approximate)
                    returns = recent_hist['Close'].pct_change().dropna()
                    if len(returns) > 20:
                        # Annualized return - risk free (7%) / Annualized Volatility
                        rf = 0.07 / 252 # Daily risk free
                        excess_ret = returns - rf
                        if excess_ret.std() > 0:
                            sharpe = (excess_ret.mean() / excess_ret.std()) * (252**0.5)
                            sharpe_val = f"{sharpe:.2f}"

                # GUI Update Helper
                def update_field(key, val, fmt="{}"):
                    if val is not None and str(val).strip() != "" and str(val).lower() != "nan":
                        try:
                            self._metrics_vars[key].set(fmt.format(val))
                        except Exception:
                            pass

                scr_data = self._fetch_screener_fallback(yf_symbol) if yf_symbol.endswith('.NS') or yf_symbol.endswith('.BO') else {}

                def apply_data():
                    pe = info.get("trailingPE") or scr_data.get("stock p/e")
                    update_field("pe_ratio", pe, "{:.1f}")
                    
                    update_field("peg_ratio", info.get("pegRatio"), "{:.2f}")
                    update_field("eps", info.get("trailingEps"), "₹{:.1f}")
                    
                    debt_eq = info.get("debtToEquity")
                    if debt_eq is not None:
                        update_field("debt_to_equity", debt_eq / 100, "{:.2f}")
                        
                    update_field("book_value", info.get("bookValue"), "₹{:.1f}")
                    
                    roe = info.get("returnOnEquity")
                    scr_roe = scr_data.get("roe")
                    if roe is not None:
                        update_field("roe", roe * 100, "{:.1f}%")
                    elif scr_roe is not None:
                        update_field("roe", scr_roe, "{:.1f}%")
                        
                    scr_roce = scr_data.get("roce")
                    if scr_roce is not None:
                        update_field("roce", scr_roce, "{:.1f}%")
                        
                    opm = info.get("operatingMargins")
                    if opm is not None:
                        update_field("opm", opm * 100, "{:.1f}%")

                    fcf = info.get("freeCashflow")
                    if fcf is not None:
                        # Format in Crores if very large
                        if abs(fcf) > 10_000_000:
                            update_field("free_cash_flow", fcf / 10_000_000, "₹{:.1f} Cr")
                        else:
                            update_field("free_cash_flow", fcf, "₹{:,}")
                            
                    stock_name = info.get("longName") or info.get("shortName") or ""
                    if stock_name:
                        # We save it in the DB quietly alongside other metrics
                        update_field("stock_name", stock_name, "{}")

                    rev_gr = info.get("revenueGrowth")
                    if rev_gr is not None:
                        update_field("sales_growth", rev_gr * 100, "{:.1f}%")
                        
                    ern_gr = info.get("earningsGrowth")
                    if ern_gr is not None:
                        update_field("profit_growth", ern_gr * 100, "{:.1f}%")
                        
                    insiders = info.get("heldPercentInsiders")
                    if insiders is not None:
                        update_field("promoter_holding", insiders * 100, "{:.1f}%")
                        
                    inst = info.get("heldPercentInstitutions")
                    if inst is not None:
                        update_field("fii_dii_holding", inst * 100, "{:.1f}%")

                    dma_50 = info.get("fiftyDayAverage")
                    dma_200 = info.get("twoHundredDayAverage")
                    if dma_50 and dma_200:
                        update_field("dma_50_200", f"{dma_50:.0f} / {dma_200:.0f}")

                    if rsi_val:
                        update_field("rsi", rsi_val)
                    update_field("macd", macd_val)
                    update_field("support_resistance", supp_res)
                    update_field("sharpe_ratio", sharpe_val)

                    # New Requested Metrics
                    eb_m = info.get("ebitdaMargins")
                    if eb_m is not None:
                        update_field("ebitda_margin", eb_m * 100, "{:.1f}%")

                    np_m = info.get("profitMargins")
                    if np_m is not None:
                        update_field("net_profit_margin", np_m * 100, "{:.1f}%")

                    # Additional Valuation & Risk Metrics
                    update_field("beta", info.get("beta"), "{:.2f}")
                    update_field("pb_ratio", info.get("priceToBook"), "{:.2f}")
                    
                    eps_raw = info.get("trailingEps")
                    bvps = info.get("bookValue")
                    if eps_raw and bvps and eps_raw > 0 and bvps > 0:
                        try:
                            import math
                            graham_num = math.sqrt(22.5 * eps_raw * bvps)
                            update_field("graham_number", graham_num, "₹{:.2f}")
                        except: pass
                    
                    # Financials (CAGR)
                    try:
                        inc_stmt = ticker.financials
                        if not inc_stmt.empty and "Total Revenue" in inc_stmt.index:
                            revs = inc_stmt.loc["Total Revenue"].dropna()
                            if len(revs) >= 4: # Need at least 4 years for 3-year CAGR
                                y0 = revs.iloc[0]
                                y3 = revs.iloc[3]
                                if y3 and y3 > 0:
                                    rev_cagr = ((y0 / y3) ** (1/3)) - 1
                                    update_field("revenue_cagr_3y", rev_cagr * 100, "{:.1f}%")
                                    
                        if not inc_stmt.empty and "Net Income" in inc_stmt.index:
                            incomes = inc_stmt.loc["Net Income"].dropna()
                            if len(incomes) >= 4: # Need at least 4 years for 3-year CAGR
                                y0 = incomes.iloc[0]
                                y3 = incomes.iloc[3]
                                if y3 and y3 > 0:
                                    prof_cagr = ((y0 / y3) ** (1/3)) - 1
                                    update_field("profit_cagr_3y", prof_cagr * 100, "{:.1f}%")
                    except: pass

                    update_field("current_ratio", info.get("currentRatio"), "{:.2f}")

                    dy = info.get("dividendYield")
                    if dy is not None:
                        update_field("dividend_yield", dy * 100, "{:.2f}%")

                    mc = info.get("marketCap")
                    if mc is not None:
                        if mc > 1e12:
                            update_field("market_cap", mc / 1e7, "₹{:.0f} Cr")  # lakhs
                        elif mc > 1e9:
                            update_field("market_cap", mc / 1e7, "₹{:.0f} Cr")
                        else:
                            update_field("market_cap", mc / 1e7, "₹{:.1f} Cr")

                    atp = info.get("targetMeanPrice")
                    if atp is not None:
                        update_field("analyst_target", atp, "₹{:.1f}")

                    h52 = info.get("fiftyTwoWeekHigh")
                    l52 = info.get("fiftyTwoWeekLow")
                    if h52 and l52:
                        update_field("week52_range", f"{l52:.0f} – {h52:.0f}")

                    # Sector, Industry, Current Price
                    sector = info.get("sector") or ""
                    if sector:
                        self._metrics_vars["sector"].set(sector)
                    industry = info.get("industry") or ""
                    if industry:
                        self._metrics_vars["industry"].set(industry)

                    cur_price = info.get("currentPrice") or info.get("regularMarketPrice")
                    if cur_price is not None:
                        update_field("current_value", cur_price, "₹{:.2f}")

                    # Auto-calculate Intrinsic Value using DCF engine
                    try:
                        from model.engine import calculate_intrinsic_value as _calc_iv
                        eps_raw = info.get("trailingEps")
                        if eps_raw and eps_raw > 0:
                            iv_val = _calc_iv(eps_raw)
                            if iv_val > 0:
                                update_field("intrinsic_value", iv_val, "₹{:.2f}")
                    except Exception:
                        pass

                    # Capex & Quarterly Op Profit (Slower calls)
                    try:
                        cf = ticker.cashflow
                        if not cf.empty and "Capital Expenditure" in cf.index:
                            capex_val = cf.loc["Capital Expenditure"].iloc[0]
                            if pd.notna(capex_val):
                                # Convert negative capex to positive for display
                                capex_abs = abs(capex_val)
                                if capex_abs > 10_000_000:
                                    update_field("capex", capex_abs / 10_000_000, "₹{:.1f} Cr")
                                else:
                                    update_field("capex", capex_abs, "₹{:,}")
                    except: pass

                    try:
                        qf = ticker.quarterly_financials
                        if not qf.empty and "Operating Income" in qf.index:
                            op_profit = qf.loc["Operating Income"].iloc[0]
                            if pd.notna(op_profit):
                                if abs(op_profit) > 10_000_000:
                                    update_field("qoq_op_profit", op_profit / 10_000_000, "₹{:.1f} Cr")
                                else:
                                    update_field("qoq_op_profit", op_profit, "₹{:,}")
                    except: pass

                    vol = info.get("volume") or info.get("averageVolume")
                    if vol is not None:
                        if vol > 1_000_000_000:
                            update_field("volume", vol / 1_000_000_000, "{:.1f}B")
                        elif vol > 1_000_000:
                            update_field("volume", vol / 1_000_000, "{:.1f}M")
                        else:
                            update_field("volume", vol, "{:,}")
                            
                    try:
                        if hasattr(self, "_fetch_btn"):
                            self._fetch_btn.set_text("✅ Downloaded")
                    except Exception:
                        pass

                self.after(0, apply_data)
                
            except Exception as e:
                print(f"Error auto-fetching yfinance for {yf_symbol}: {e}")
                self.after(0, lambda: self._fetch_btn.set_text("⚠ Failed") if hasattr(self, "_fetch_btn") else None)
            finally:
                self.after(2000, lambda: getattr(self, "_fetch_btn").set_text("�� Auto-Fill (yfinance)") if hasattr(self, "_fetch_btn") else None)
                self.after(2000, lambda: getattr(self, "_fetch_btn").set_disabled(False) if hasattr(self, "_fetch_btn") else None)

        import threading
        import pandas as pd
        threading.Thread(target=bg_fetch, daemon=True).start()

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
                # Try standalone non-consolidated
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

    # ── Bulk Auto Fetch Metrics (yfinance) ────────────────────────────────────

    def _bulk_refresh_metrics(self):
        if not self._data:
            self._flash_status("⚠ Watchlist is empty.", error=True)
            return

        self._btn_refresh_all.set_disabled(True)
        total = len(self._data)
        
        def bg_refresh():
            try:
                from model.watchlist_db import update_watchlist
                
                for idx, row in enumerate(self._data):
                    self.after(0, lambda i=idx: self._btn_refresh_all.set_text(f"🔄 Updating {i+1}/{total}"))
                    
                    symbol = row["symbol"]
                    yf_symbol = symbol
                    if not yf_symbol.endswith('.NS') and not yf_symbol.endswith('.BO'):
                        if len(yf_symbol) < 10 and '.' not in yf_symbol:
                            yf_symbol += '.NS'
                            
                    try:
                        ticker = yf.Ticker(yf_symbol)
                        info = ticker.info
                        
                        # Preserve existing manual metrics
                        metrics = {k: row.get(k, "") for k in self._metrics_keys}
                        
                        scr_data = self._fetch_screener_fallback(yf_symbol) if yf_symbol.endswith('.NS') or yf_symbol.endswith('.BO') else {}

                        def mset(key, val, fmt="{}"):
                            if val is not None and str(val).strip() != "" and str(val).lower() != "nan":
                                metrics[key] = fmt.format(val)
                                
                        pe = info.get("trailingPE") or scr_data.get("stock p/e")
                        mset("pe_ratio", pe, "{:.1f}")
                        
                        mset("peg_ratio", info.get("pegRatio"), "{:.2f}")
                        mset("eps", info.get("trailingEps"), "₹{:.1f}")
                        
                        debt_eq = info.get("debtToEquity")
                        if debt_eq is not None:
                            mset("debt_to_equity", debt_eq / 100, "{:.2f}")
                            
                        mset("book_value", info.get("bookValue"), "₹{:.1f}")
                        
                        roe = info.get("returnOnEquity")
                        scr_roe = scr_data.get("roe")
                        if roe is not None:
                            mset("roe", roe * 100, "{:.1f}%")
                        elif scr_roe is not None:
                            mset("roe", scr_roe, "{:.1f}%")
                            
                        scr_roce = scr_data.get("roce")
                        if scr_roce is not None:
                            mset("roce", scr_roce, "{:.1f}%")
                            
                        opm = info.get("operatingMargins")
                        if opm is not None:
                            mset("opm", opm * 100, "{:.1f}%")

                        fcf = info.get("freeCashflow")
                        if fcf is not None:
                            if abs(fcf) > 10_000_000:
                                mset("free_cash_flow", fcf / 10_000_000, "₹{:.1f} Cr")
                            else:
                                mset("free_cash_flow", fcf, "₹{:,}")

                        rev_gr = info.get("revenueGrowth")
                        if rev_gr is not None:
                            mset("sales_growth", rev_gr * 100, "{:.1f}%")
                            
                        ern_gr = info.get("earningsGrowth")
                        if ern_gr is not None:
                            mset("profit_growth", ern_gr * 100, "{:.1f}%")
                            
                        insiders = info.get("heldPercentInsiders")
                        if insiders is not None:
                            mset("promoter_holding", insiders * 100, "{:.1f}%")
                            
                        inst = info.get("heldPercentInstitutions")
                        if inst is not None:
                            mset("fii_dii_holding", inst * 100, "{:.1f}%")

                        eb_m = info.get("ebitdaMargins")
                        if eb_m is not None:
                            mset("ebitda_margin", eb_m * 100, "{:.1f}%")

                        np_m = info.get("profitMargins")
                        if np_m is not None:
                            mset("net_profit_margin", np_m * 100, "{:.1f}%")

                        try:
                            cf = ticker.cashflow
                            if not cf.empty and "Capital Expenditure" in cf.index:
                                capex_val = cf.loc["Capital Expenditure"].iloc[0]
                                if pd.notna(capex_val):
                                    capex_abs = abs(capex_val)
                                    if capex_abs > 10_000_000:
                                        mset("capex", capex_abs / 10_000_000, "₹{:.1f} Cr")
                                    else:
                                        mset("capex", capex_abs, "₹{:,}")
                        except: pass

                        try:
                            qf = ticker.quarterly_financials
                            if not qf.empty and "Operating Income" in qf.index:
                                op_profit = qf.loc["Operating Income"].iloc[0]
                                if pd.notna(op_profit):
                                    if abs(op_profit) > 10_000_000:
                                        mset("qoq_op_profit", op_profit / 10_000_000, "₹{:.1f} Cr")
                                    else:
                                        mset("qoq_op_profit", op_profit, "₹{:,}")
                        except: pass

                        # Additional Risk & Valuation Metrics
                        mset("beta", info.get("beta"), "{:.2f}")
                        mset("pb_ratio", info.get("priceToBook"), "{:.2f}")
                        mset("current_ratio", info.get("currentRatio"), "{:.2f}")
                        dy = info.get("dividendYield")
                        if dy is not None:
                            mset("dividend_yield", dy * 100, "{:.2f}%")
                        mc = info.get("marketCap")
                        if mc is not None:
                            mset("market_cap", mc / 1e7, "₹{:.0f} Cr")
                        atp = info.get("targetMeanPrice")
                        if atp is not None:
                            mset("analyst_target", atp, "₹{:.1f}")
                        h52 = info.get("fiftyTwoWeekHigh")
                        l52 = info.get("fiftyTwoWeekLow")
                        if h52 and l52:
                            mset("week52_range", f"{l52:.0f} – {h52:.0f}")

                        # Compute Sector, Industry, Current Price & Intrinsic Value
                        sector = info.get("sector") or ""
                        if sector:
                            mset("sector", sector, "{}")
                        industry = info.get("industry") or ""
                        if industry:
                            mset("industry", industry, "{}")

                        cur_price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
                        if cur_price is not None:
                            mset("current_value", cur_price, "₹{:.2f}")
                            
                        stock_name = info.get("longName") or info.get("shortName") or ""
                        if stock_name:
                            mset("stock_name", stock_name, "{}")

                        try:
                            from model.engine import calculate_intrinsic_value as _calc_iv
                            eps_raw = info.get("trailingEps")
                            if eps_raw and eps_raw > 0:
                                iv_val = _calc_iv(eps_raw)
                                if iv_val > 0:
                                    mset("intrinsic_value", iv_val, "₹{:.2f}")
                        except Exception:
                            pass

                        # Compute signal and store
                        badge, _ = self._compute_signal(metrics)
                        metrics["action_signal"] = badge
                            
                        dma_50 = info.get("fiftyDayAverage")
                        dma_200 = info.get("twoHundredDayAverage")
                        if dma_50 and dma_200:
                            mset("dma_50_200", f"{dma_50:.0f} / {dma_200:.0f}")

                        vol = info.get("volume") or info.get("averageVolume")
                        if vol is not None:
                            if vol > 1_000_000_000:
                                mset("volume", vol / 1_000_000_000, "{:.1f}B")
                            elif vol > 1_000_000:
                                mset("volume", vol / 1_000_000, "{:.1f}M")
                            else:
                                mset("volume", vol, "{:,}")

                        hist = ticker.history(period="1mo")
                        if not hist.empty and len(hist) >= 15:
                            delta = hist['Close'].diff()
                            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                            rs = gain / loss
                            rsi = 100 - (100 / (1 + rs))
                            rsi_last = rsi.iloc[-1]
                            if pd.notna(rsi_last):
                                mset("rsi", rsi_last, "{:.1f}")

                        # Write to database (preserves manually entered tags, targets, notes, etc.)
                        target = float(row.get("target_price", 0.0) or 0.0)
                        update_watchlist(row["id"], symbol, row.get("notes", ""), row.get("tags", ""), target, **metrics)
                        
                    except Exception as e:
                        print(f"Error refreshing {symbol}: {e}")

                self.after(0, lambda: self._post_save("✅ Bulk refresh complete."))
            except Exception as e:
                print(f"Bulk refresh error: {e}")
            finally:
                self.after(0, lambda: self._btn_refresh_all.set_text("🔄 Refresh All"))
                self.after(0, lambda: self._btn_refresh_all.set_disabled(False))

        threading.Thread(target=bg_refresh, daemon=True).start()

    def _open_metrics_dialog(self):
        sym = self._v_symbol.get().strip().upper() or "New Symbol"
        top = PremiumModal(self, title=f"Advanced Metrics", geometry="800x850", icon="📋")
        top.add_chip("📈", sym, bg_color=ModernStyle.ACCENT_PRIMARY, fg_color=ModernStyle.SLATE_300)
        
        main_frame = tk.Frame(top.content_frame, bg=ModernStyle.SLATE_50)
        main_frame.pack(fill="both", expand=True)
        
        canvas = tk.Canvas(main_frame, bg=ModernStyle.SLATE_50, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=ModernStyle.SLATE_50)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Mousewheel binding
        def _on_mousewheel(event):
            if event.widget.winfo_toplevel() == top:
                delta = event.delta
                if abs(delta) >= 120: delta = delta / 120
                if delta == 0: delta = 1 if event.delta > 0 else -1
                canvas.yview_scroll(int(-1 * delta), "units")
        top.bind_all("<MouseWheel>", _on_mousewheel)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        groups = [
            ("Financial Ratios & Valuation", ModernStyle.ACCENT_PRIMARY, [
                ("P/E Ratio", "pe_ratio"), ("PEG Ratio", "peg_ratio"), ("EPS", "eps"),
                ("Debt to Equity", "debt_to_equity"), ("Book Value", "book_value"), ("Intrinsic Value", "intrinsic_value")
            ]),
            ("Profitability & Efficiency", ModernStyle.SUCCESS, [
                ("ROE", "roe"), ("ROCE", "roce"), ("OPM (%)", "opm"), ("EBITDA Margin (%)", "ebitda_margin"),
                ("Net Profit Margin (%)", "net_profit_margin"), ("Free Cash Flow", "free_cash_flow"), 
                ("Inventory Days", "inventory_days"), ("Capex", "capex"), ("QoQ Op. Profit", "qoq_op_profit")
            ]),
            ("Growth Metrics (3-Year & 5-Year)", ModernStyle.WARNING, [
                ("Sales Growth", "sales_growth"), ("Profit Growth", "profit_growth")
            ]),
            ("Operational & Ownership", ModernStyle.BRAND_GOLD, [
                ("Promoter Holding", "promoter_holding"), ("Pledged Shares", "pledged_shares"),
                ("FII / DII Holding", "fii_dii_holding"), ("Order Book", "order_book")
            ]),
            ("Technical Analysis (Entry/Exit)", ModernStyle.ACCENT_SECONDARY, [
                ("50 & 200 DMA", "dma_50_200"), ("RSI", "rsi"), ("Sharpe Ratio", "sharpe_ratio"), ("Volume", "volume")
            ])
        ]
        
        for group_name, accent_color, fields in groups:
            # Container for the group
            group_wrapper = tk.Frame(scrollable_frame, bg=ModernStyle.SLATE_50)
            group_wrapper.pack(fill="x", pady=(0, 15))
            
            # Header color bar
            tk.Frame(group_wrapper, bg=accent_color, height=3).pack(fill="x")
            
            group_frame = tk.Frame(group_wrapper, bg=ModernStyle.SLATE_100, highlightthickness=1, highlightbackground=ModernStyle.SLATE_200)
            group_frame.pack(fill="x", ipady=12)
            
            tk.Label(
                group_frame, text=group_name,
                fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.SLATE_100,
                font=ModernStyle.FONT_MODAL_TITLE
            ).pack(anchor="w", padx=20, pady=(6, 12))
            
            grid = tk.Frame(group_frame, bg=ModernStyle.SLATE_100)
            grid.pack(fill="x", padx=20)
            
            for i, (label_text, key) in enumerate(fields):
                col = i % 2
                row = i // 2
                f = tk.Frame(grid, bg=ModernStyle.SLATE_100)
                f.grid(row=row, column=col, padx=12, pady=8, sticky="ew")
                grid.grid_columnconfigure(col, weight=1)
                
                tk.Label(
                    f, text=label_text,
                    fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.SLATE_100,
                    font=ModernStyle.FONT_SUBHEADING,
                    width=20, anchor="w"
                ).pack(side="left", padx=(0, 10))
                
                e = tk.Entry(
                    f, textvariable=self._metrics_vars[key],
                    bg=ModernStyle.ENTRY_BG, fg=ModernStyle.TEXT_PRIMARY,
                    font=ModernStyle.FONT_TABLE, relief=tk.FLAT,
                    highlightthickness=1, highlightbackground=ModernStyle.BORDER_COLOR,
                    highlightcolor=accent_color, insertbackground=ModernStyle.TEXT_PRIMARY
                )
                e.pack(side="left", fill="x", expand=True, ipady=7)
                
        # Footer buttons embedded in actions_frame of PremiumModal
        self._fetch_btn = ModernButton(
            top.actions_frame, text="🔄 Auto-Fill (yfinance)", command=self._auto_fetch_metrics,
            bg=ModernStyle.BRAND_GOLD, fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.SLATE_50, width=210, height=40, radius=8,
            font=ModernStyle.FONT_TABLE_BOLD
        )
        self._fetch_btn.pack(side="left", padx=(0, 10))

        ModernButton(
            top.actions_frame, text="✓ Done", command=top.destroy,
            bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.SLATE_50, width=120, height=40, radius=8,
            font=ModernStyle.FONT_TABLE_BOLD
        ).pack(side="right")

# ── Double Click Diagnostic Popup ─────────────────────────────────────────
    def _open_diagnostic_popup(self, row: dict):
        sym = row.get("symbol", "Symbol")
        stock_name = row.get("stock_name", "")
        popup_title = f"{stock_name} ({sym})" if stock_name else sym
        
        top = PremiumModal(self, title=popup_title, geometry="1000x1100", icon="📊")
        top.add_chip("📈", sym, bg_color=ModernStyle.ACCENT_PRIMARY, fg_color=ModernStyle.SLATE_300)

        # ── Master Scrollable Canvas ──
        canvas = tk.Canvas(top.content_frame, bg=ModernStyle.SLATE_50, highlightthickness=0)
        scrollbar = ttk.Scrollbar(top.content_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=ModernStyle.SLATE_50)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        def _on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        # Mousewheel scrolling support across the entire popup window
        def _on_mousewheel(event):
            try:
                if event.widget.winfo_toplevel() != top:
                    return
                delta = event.delta
                if abs(delta) >= 120:
                    delta = delta / 120
                if delta == 0:
                    delta = 1 if event.delta > 0 else -1
                canvas.yview_scroll(int(-1 * delta), "units")
            except: pass
        def _on_unix_scroll_up(event):
            try:
                if event.widget.winfo_toplevel() == top:
                    canvas.yview_scroll(-1, "units")
            except: pass
        def _on_unix_scroll_down(event):
            try:
                if event.widget.winfo_toplevel() == top:
                    canvas.yview_scroll(1, "units")
            except: pass

        # Bind globally but safely restricted to popup
        top.bind_all("<MouseWheel>", _on_mousewheel)
        top.bind_all("<Button-4>", _on_unix_scroll_up)
        top.bind_all("<Button-5>", _on_unix_scroll_down)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ModernButton(
            top.actions_frame, text="✕  Close", command=top.destroy,
            bg=ModernStyle.SALMON, fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.SLATE_50, width=100, height=36, radius=8,
            font=ModernStyle.FONT_SUBHEADING
        ).pack(side="right")

        # ── Signal Banner ──────────────────────────────────────────────────
        badge, tip = self._compute_signal(row)
        badge_colors = {
            "🟢 Strong Buy": (ModernStyle.SUCCESS, ModernStyle.ACCENT_SECONDARY_PALE),
            "🟡 Accumulate": (ModernStyle.WARNING, ModernStyle.ACCENT_TERTIARY_PALE),
            "⏳ Wait / Watch": (ModernStyle.TEXT_TERTIARY, ModernStyle.SLATE_50),
            "🔴 Avoid": (ModernStyle.ERROR, ModernStyle.ERROR_PALE),
        }
        badge_fg, badge_bg = badge_colors.get(badge, (ModernStyle.TEXT_PRIMARY, ModernStyle.BG_SECONDARY))
        
        sig_frame = tk.Frame(scrollable_frame, bg=badge_bg, highlightthickness=1, highlightbackground=badge_fg)
        sig_frame.pack(fill="x", padx=20, pady=(0, 20))

        sig_inner = tk.Frame(sig_frame, bg=badge_bg)
        sig_inner.pack(fill="both", padx=12, pady=8)

        tk.Label(
            sig_inner, text=badge,
            fg=badge_fg, bg=badge_bg,
            font=ModernStyle.FONT_MODAL_TITLE
        ).pack(anchor="w")

        tk.Label(
            sig_inner, text="ℹ️ Decision Rationale:",
            fg=badge_fg, bg=badge_bg,
            font=ModernStyle.FONT_HEADING
        ).pack(anchor="w", pady=(8, 4))

        # Split tip into lines for better formatting
        for line in tip.split("\n"):
            if not line.strip(): continue
            font_conf = ModernStyle.FONT_TABLE
            if "Signal:" in line: font_conf = ModernStyle.FONT_HEADING
            
            tk.Label(
                sig_inner, text=line,
                fg=badge_fg, bg=badge_bg,
                font=font_conf,
                justify="left", anchor="w", wraplength=920
            ).pack(anchor="w", padx=5)

        # Helper to parse string values and compare against benchmark
        def evaluate_benchmark(key: str, val_str: str) -> bool | None:
            if not val_str or val_str in ("-", "None", ""): return None
            
            # Clean string for float conversion
            clean = val_str.replace(",", "").replace("%", "").replace("₹", "").replace(" ", "")
            try:
                val = float(clean)
            except ValueError:
                # If it's a fractional string like "500/600" for Support/Resistance, we can't easily eval it as a simple float
                return None

            if key in ("eps", "roe", "roce", "opm", "sales_growth", "profit_growth", "ebitda_margin", "net_profit_margin", "revenue_cagr_3y", "profit_cagr_3y"):
                return val >= 10.0
            if key in ("pe_ratio",):
                return None # Requires industry comparison
            if key in ("peg_ratio", "pb_ratio"):
                return val < 2.0  # P/B < 2 is reasonably valued
            if key in ("debt_to_equity",):
                return val < 1.0
            if key in ("free_cash_flow", "qoq_op_profit", "macd"):
                return val > 0.0
            if key in ("sharpe_ratio",):
                return val >= 1.0
            if key in ("rsi",):
                return 30.0 <= val <= 65.0
            if key in ("beta",):
                return val < 1.5
            if key in ("current_ratio",):
                return val >= 1.5
            return None

        groups = [
            ("Financial Ratios & Valuation Metrics", [
                ("P/E Ratio", "pe_ratio", "Compare with Industry"),
                ("PEG Ratio", "peg_ratio", "< 1.0 (Best) or < 2.0"),
                ("EPS", "eps", "Double Digits (>10)"),
                ("Debt to Equity", "debt_to_equity", "< 1.0"),
                ("Book Value", "book_value", "Compare to Price"),
                ("Intrinsic Value", "intrinsic_value", "Higher than Market Price"),
                ("Graham Number", "graham_number", "Higher than Market Price")
            ]),
            ("Profitability & Efficiency Metrics", [
                ("ROE", "roe", "Double Digits"),
                ("ROCE", "roce", "Double Digits"),
                ("OPM (%)", "opm", "> 10% - 15%"),
                ("Free Cash Flow", "free_cash_flow", "Must be Positive"),
                ("Inventory Days", "inventory_days", "Lower is generally better")
            ]),
            ("Growth Metrics (3-Year & 5-Year)", [
                ("3Y Rev CAGR", "revenue_cagr_3y", "Consistent > 10%"),
                ("3Y Profit CAGR", "profit_cagr_3y", "Consistent > 10%"),
                ("Sales Growth", "sales_growth", "Double Digits"),
                ("Profit Growth", "profit_growth", "Double Digits"),
                ("QoQ Op. Profit", "qoq_op_profit", "Positive / Growth")
            ]),
            ("Operational & Ownership Metrics", [
                ("Promoter Holding", "promoter_holding", "High & Stable"),
                ("Pledged Shares", "pledged_shares", "Zero (Ideal)"),
                ("FII / DII Holding", "fii_dii_holding", "Increasing / Stable"),
                ("Order Book", "order_book", "High Visibility")
            ]),
            ("Technical Analysis Metrics (Entry/Exit)", [
                ("50 & 200 DMA", "dma_50_200", "Above the lines"),
                ("RSI", "rsi", "30 (Oversold) / 70 (Overbought)"),
                ("MACD", "macd", "Positive Momentum"),
                ("Support/Resistance", "support_resistance", "Context Near Support"),
                ("Volume", "volume", "Increasing")
            ]),
            ("Additional Valuation & Risk Metrics", [
                ("EBITDA Margin (%)", "ebitda_margin", "> 15%"),
                ("Net Profit Margin (%)", "net_profit_margin", "> 10%"),
                ("P/B Ratio", "pb_ratio", "< 2.0 (Fairly Valued)"),
                ("Current Ratio", "current_ratio", ">= 1.5 (Liquid)"),
                ("Beta", "beta", "< 1.5 (Lower Vol)"),
                ("Dividend Yield", "dividend_yield", "Stable / Growing"),
                ("Capex", "capex", "Expansion Indicator")
            ]),
            ("Market Overview", [
                ("Market Cap", "market_cap", "Context Only"),
                ("52-Week Range", "week52_range", "Context Only"),
                ("Analyst Target", "analyst_target", "vs Current Price"),
                ("Sharpe Ratio", "sharpe_ratio", "> 1.0 (Good Risk-Return)")
            ])
        ]

        # Use improved card layout for the groups
        for i, (group_name, fields) in enumerate(groups):
            card_outer = tk.Frame(scrollable_frame, bg=ModernStyle.BG_SECONDARY, highlightthickness=1, highlightbackground=ModernStyle.BORDER_COLOR)
            card_outer.pack(fill="x", pady=(0, 20), padx=25)
            
            tk.Frame(card_outer, bg=ModernStyle.ACCENT_PRIMARY, height=3).pack(fill="x")
            
            card = tk.Frame(card_outer, bg=ModernStyle.BG_SECONDARY)
            card.pack(fill="both", expand=True, padx=20, pady=15)
            
            tk.Label(
                card, text=group_name,
                fg=ModernStyle.ACCENT_PRIMARY, bg=ModernStyle.BG_SECONDARY,
                font=ModernStyle.FONT_MODAL_TITLE
            ).pack(anchor="w", pady=(0, 15))
            
            # Header Row
            hdr_row = tk.Frame(card, bg=ModernStyle.BG_SECONDARY)
            hdr_row.pack(fill="x", pady=(0, 10))
            
            # Text based header
            is_technical = "Technical" in group_name
            target_hdr = "Observation" if is_technical else "Ideal Benchmark / Target"
            
            tk.Label(hdr_row, text="Metric / Ratio", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TABLE_BOLD, width=22, anchor="w").pack(side="left")
            tk.Label(hdr_row, text="Actual Value", fg=ModernStyle.TEXT_ON_ACCENT, bg=ModernStyle.ACCENT_TERTIARY, font=ModernStyle.FONT_SUBHEADING, width=16, anchor="w", padx=10).pack(side="left", padx=20)
            tk.Label(hdr_row, text=target_hdr, fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TABLE_BOLD, anchor="w").pack(side="left")

            tk.Frame(card, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", pady=(0, 12))

            for label_text, key, target_desc in fields:
                val_str = str(row.get(key, ""))
                
                # Determine text coloring
                fg_col = ModernStyle.TEXT_PRIMARY
                is_pass = evaluate_benchmark(key, val_str)
                if is_pass is True:
                    fg_col = ModernStyle.SUCCESS
                elif is_pass is False:
                    fg_col = ModernStyle.ERROR
                
                display_val = val_str if val_str and val_str not in ("None", "") else "—"

                row_fr = tk.Frame(card, bg=ModernStyle.BG_SECONDARY)
                row_fr.pack(fill="x", pady=8)
                
                tk.Label(row_fr, text=label_text, fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_HEADING, width=22, anchor="w").pack(side="left")
                tk.Label(row_fr, text=display_val, fg=fg_col, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_INPUT, width=16, anchor="w").pack(side="left", padx=20)
                
                # Benchmarks often bold in screenshot
                tk.Label(row_fr, text=target_desc, fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TABLE_BOLD, anchor="w").pack(side="left")
