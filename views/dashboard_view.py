"""
Dashboard view for TKinter-based PTracker application.
Enhanced with better readability, visual hierarchy, and refined aesthetics.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
from datetime import datetime

from views.base_view import BaseView, _enable_canvas_mousewheel
from ui_theme import ModernStyle
from ui_widgets import ModernButton, PremiumModal, ModernCard
from ui_utils import center_window, add_treeview_copy_menu

# ── Small utility helpers ──────────────────────────────────────────────────────

def _money(v, currency: str = "INR") -> str:
    """Format a float with correct currency symbol."""
    from ui_utils import format_money
    return format_money(v, currency)


def _pct(v) -> str:
    """Format a float as percentage."""
    try:
        return f"{float(v or 0.0):,.2f}%"
    except Exception:
        return "0.00%"


def _compact_money(v, currency: str = "INR") -> str:
    """Format large amounts as compact strings (1.2L / 50K / etc.) with correct symbol."""
    from ui_utils import format_money
    symbols = {"INR": "₹", "JPY": "¥", "USD": "$", "GBP": "£", "CNY": "¥"}
    sym = symbols.get(currency.upper(), "₹")
    try:
        f = float(v or 0.0)
        if abs(f) >= 1_00_000:
            return f"{sym}{f/1_00_000:.2f}L"
        if abs(f) >= 1_000:
            return f"{sym}{f/1_000:.1f}K"
        return f"{sym}{f:,.0f}"
    except Exception:
        return f"{sym}0"


class DashboardView(BaseView):
    """Portfolio dashboard with summary metrics and overview."""

    def build(self):
        self._ui_built = False
        self._data_loaded = False
        self._refresh_inflight = False
        self._payload_data = None
        self._polling_active = False # Tracks if the robust poller is running

        self.currency_var = tk.StringVar(value="INR")
        self.currency_var.trace_add("write", lambda *a: self.load_data(force=True))

        self._main_canvas = tk.Canvas(self, bg=ModernStyle.BG_PRIMARY, highlightthickness=0)
        self._main_canvas.pack(side="left", fill="both", expand=True)

        self._content = tk.Frame(self._main_canvas, bg=ModernStyle.BG_PRIMARY)
        self._content_id = self._main_canvas.create_window((0, 0), window=self._content, anchor="nw")

        def _on_configure(_e=None):
            self._main_canvas.configure(scrollregion=self._main_canvas.bbox("all"))
            self._main_canvas.itemconfigure(self._content_id, width=self._main_canvas.winfo_width())

        self._content.bind("<Configure>", _on_configure)
        self._main_canvas.bind("<Configure>", _on_configure)
        _enable_canvas_mousewheel(self._main_canvas, include_widget=self._content)

        # ── Gradient Header Banner ─────────────────────────────────────────────
        self._header_canvas = tk.Canvas(
            self._content, bg=ModernStyle.BG_PRIMARY, highlightthickness=0, height=75
        )
        self._header_canvas.pack(fill="x", padx=20, pady=(6, 4))

        # Gradient colors: deep blue → teal
        self._grad_start = (30, 58, 138)   # #1E3A8A
        self._grad_end   = (13, 148, 136)  # #0D9488

        def _draw_header_gradient(event=None):
            w = event.width if event else self._header_canvas.winfo_width()
            h = event.height if event else self._header_canvas.winfo_height()
            if w < 10:
                return
            self._header_canvas.delete("gradient")
            steps = max(1, w // 4)  # ~1 rect per 4px for performance
            for i in range(steps):
                t = i / max(1, steps - 1)
                r = int(self._grad_start[0] + (self._grad_end[0] - self._grad_start[0]) * t)
                g = int(self._grad_start[1] + (self._grad_end[1] - self._grad_start[1]) * t)
                b = int(self._grad_start[2] + (self._grad_end[2] - self._grad_start[2]) * t)
                color = f"#{r:02x}{g:02x}{b:02x}"
                x0 = int(i * w / steps)
                x1 = int((i + 1) * w / steps) + 1
                self._header_canvas.create_rectangle(x0, 0, x1, h, fill=color, outline="", tags="gradient")
            # Dynamically match right frame background to the gradient color
            t_right = max(0, min(1, (w - 70) / max(1, w)))
            r = int(self._grad_start[0] + (self._grad_end[0] - self._grad_start[0]) * t_right)
            g = int(self._grad_start[1] + (self._grad_end[1] - self._grad_start[1]) * t_right)
            b = int(self._grad_start[2] + (self._grad_end[2] - self._grad_start[2]) * t_right)
            right_color = f"#{r:02x}{g:02x}{b:02x}"
            try:
                _right_frame.config(bg=right_color)
                self.refresh_status.config(bg=right_color)
                self.refresh_btn.config(bg=right_color)
                self.refresh_btn._canvas_bg = right_color
                # Recalculate shadow color and update shadow item
                shadow_alpha = 0.08
                shadow_color = self.refresh_btn._blend("#000000", right_color, shadow_alpha)
                if "shadow" in self.refresh_btn._canvas_ids:
                    for shadow_item in self.refresh_btn._canvas_ids["shadow"]:
                        self.refresh_btn.itemconfig(shadow_item, fill=shadow_color, outline=shadow_color)
            except Exception:
                pass

            # Raise text items above gradient
            self._header_canvas.tag_raise("header_content")

        # Greeting text on the gradient
        hour = datetime.now().hour
        if 5 <= hour < 12:
            greeting = "Good Morning ☀️"
        elif 12 <= hour < 17:
            greeting = "Good Afternoon 🌤️"
        else:
            greeting = "Good Evening 🌙"

        # Draw Greeting directly on the canvas for true 100% transparent background
        self._header_canvas.create_text(
            20, 22,
            text=f"⚡ {greeting}, Selvakumar Rajagopalan",
            fill="#FFFFFF",
            font=ModernStyle.FONT_PAGE_TITLE,
            anchor="w",
            tags="header_content"
        )

        self._header_subtitle = self._header_canvas.create_text(
            20, 48,
            text="Loading portfolio data…",
            fill="#94A3B8",
            font=ModernStyle.FONT_BODY,
            anchor="w",
            tags="header_content"
        )

        # Right side: refresh status + button
        _right_frame = tk.Frame(self._header_canvas, bg="#0D9488")
        self.refresh_status = tk.Label(
            _right_frame,
            text="",
            fg="#CBD5E1",
            bg="#0D9488",
            font=ModernStyle.FONT_SMALL,
        )
        self.refresh_status.pack(anchor="e", pady=(0, 4))

        self.refresh_btn = ModernButton(
            _right_frame,
            text="⚡️ Refresh",
            command=self._on_refresh_market_data,
            bg="#D97706",
            fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg="#0D9488",
            width=100,
            height=32,
            radius=10,
            font=ModernStyle.FONT_SUBHEADING,
        )
        self.refresh_btn.pack(anchor="e")
        self._header_canvas.create_window(
            0, 37, window=_right_frame, anchor="e", tags=("header_content", "right_hdr")
        )

        # Reposition right_frame to the right edge on resize
        def _reposition_right(event=None):
            w = event.width if event else self._header_canvas.winfo_width()
            if w > 10:
                self._header_canvas.coords("right_hdr", w - 20, 37)
        self._header_canvas.bind("<Configure>", lambda e: (_draw_header_gradient(e), _reposition_right(e)))

        # Thin accent divider under header
        tk.Frame(self._content, bg=ModernStyle.BRAND_GOLD, height=2).pack(
            fill="x", padx=20, pady=(4, 0)
        )

        # ── KPI Cards ─────────────────────────────────────────────────────────
        self.kpi_labels = {}
        self._kpi_cards = {}

        def _kpi_card(
            parent,
            title: str,
            key: str,
            *,
            color: str,
            icon: str,
            metric_key: str | None,
            is_currency: bool = True,
        ) -> ModernCard:
            """Create a premium KPI card with accent bar, icon, value, and trend."""
            card = ModernCard(
                parent,
                bg=ModernStyle.BG_SECONDARY,
                highlight_color=ModernStyle.BORDER_COLOR,
                highlight_thickness=1,
                radius=10,
                canvas_bg=ModernStyle.BG_PRIMARY,
                height=ModernStyle.KPI_CARD_HEIGHT,
                expand_height=True,
            )
            # Pin the content frame to the card's fixed height so children can expand
            card.content.config(height=ModernStyle.KPI_CARD_HEIGHT - 2)

            # 1. Left Accent Bar
            body_wrapper = tk.Frame(card.content, bg=ModernStyle.BG_SECONDARY)
            body_wrapper.pack(fill="both", expand=True)
            
            # Left vertical stripe
            accent_bar = tk.Frame(body_wrapper, bg=color, width=4)
            accent_bar.pack(side="left", fill="y")

            # Body
            body = tk.Frame(body_wrapper, bg=ModernStyle.BG_SECONDARY)
            body.pack(side="left", fill="both", expand=True, padx=14, pady=10)

            # Icon + Title row
            title_row = tk.Frame(body, bg=ModernStyle.BG_SECONDARY)
            title_row.pack(fill="x")
            
            icon_lbl = tk.Label(
                title_row,
                text=icon,
                fg=color,
                bg=ModernStyle.BG_SECONDARY,
                font=ModernStyle.FONT_ICON,
            )
            icon_lbl.pack(side="left", padx=(0, 6))
            
            title_lbl = tk.Label(
                title_row,
                text=title,
                fg=ModernStyle.TEXT_SECONDARY,
                bg=ModernStyle.BG_SECONDARY,
                font=ModernStyle.FONT_KPI_LABEL,
            )
            title_lbl.pack(side="left", pady=(2, 0))

            if key == "total_value":
                self.switch_frame = tk.Frame(title_row, bg=ModernStyle.BG_SECONDARY)
                self.switch_frame.pack(side="right")
                
                self.curr_buttons = {}
                currencies = [("INR", "#10B981"), ("JPY", "#EF4444")]
                
                for c_name, c_color in currencies:
                    btn = tk.Label(
                        self.switch_frame,
                        text=c_name,
                        bg=ModernStyle.BG_TERTIARY,
                        fg=c_color,
                        font=ModernStyle.FONT_TINY_BOLD,
                        padx=6,
                        pady=2,
                        cursor="hand2",
                    )
                    btn.pack(side="left", padx=2)
                    self.curr_buttons[c_name] = (btn, c_color)
                    
                    btn.bind("<Button-1>", lambda e, name=c_name: self.currency_var.set(name))

            # Value label (large, bold, colored for typographic contrast)
            val = tk.Label(
                body,
                text="—",
                fg=color,
                bg=ModernStyle.BG_SECONDARY,
                font=ModernStyle.FONT_KPI_VALUE,
            )
            val.pack(anchor="w", pady=(6, 0))
            self.kpi_labels[key] = val

            # 3. Delta Badge (Trend label)
            trend_frame = tk.Frame(body, bg=ModernStyle.BG_SECONDARY)
            trend_frame.pack(anchor="w", pady=(2, 4))
            
            trend_lbl = tk.Label(
                trend_frame,
                text="",
                fg=ModernStyle.TEXT_SECONDARY,
                bg=ModernStyle.BG_TERTIARY,
                font=ModernStyle.FONT_TINY_BOLD,
                padx=6, pady=2
            )
            trend_lbl.pack(anchor="w")
            
            # Store the card itself for styling
            self._kpi_cards[key] = card
            # Store a ref so we can update it later
            setattr(val, "_trend_lbl", trend_lbl)

            # Sparkline Canvas
            spark_cvs = tk.Canvas(
                body,
                bg=ModernStyle.BG_SECONDARY,
                highlightthickness=0,
                height=26,
            )
            spark_cvs.pack(side="bottom", fill="x", pady=(4, 0))
            setattr(val, "_spark_cvs", spark_cvs)

            if metric_key:
                def _click(_e=None, t=title, mk=metric_key, cur=is_currency, col=color):
                    self._show_broker_breakdown(t, mk, is_currency=cur, color=col)

                def _set_bg(c):
                    card.bg_color = c
                    try:
                         for i in card._bg_items:
                              card.itemconfig(i, fill=c)
                    except Exception:
                         pass
                    card.content.configure(bg=c)
                    body_wrapper.configure(bg=c)
                    body.configure(bg=c)
                    title_row.configure(bg=c)
                    for child in title_row.winfo_children():
                        child.configure(bg=c)
                    val.configure(bg=c)
                    trend_frame.configure(bg=c)
                    trend_lbl.configure(bg=c)
                    try:
                        spark_cvs.configure(bg=c)
                    except Exception:
                        pass

                def _hover_in(_e=None):
                    card.highlight_color = color
                    card.highlight_thickness = 2
                    card._on_resize(tk.Event())
                    try: card.move(card.content_id, 0, -2)
                    except: pass
                    _set_bg(ModernStyle.BG_TERTIARY)

                def _hover_out(_e=None):
                    card.highlight_color = ModernStyle.BORDER_COLOR
                    card.highlight_thickness = 1
                    card._on_resize(tk.Event())
                    try: card.move(card.content_id, 0, 2)
                    except: pass
                    _set_bg(ModernStyle.BG_SECONDARY)

                card.configure(cursor="hand2")
                for w in (card, card.content, body, val, trend_lbl, title_row, spark_cvs):
                    try:
                        w.bind("<Double-1>", _click)
                        w.bind("<Enter>", _hover_in)
                        w.bind("<Leave>", _hover_out)
                    except Exception:
                        pass

            return card

        # ── KPI Row 1: Primary metrics ─────────────────────────────────────────
        row1 = tk.Frame(self._content, bg=ModernStyle.BG_PRIMARY)
        row1.pack(fill="x", padx=20, pady=(18, 6))
        for i in range(4):
            row1.grid_columnconfigure(i, weight=1, uniform="kpi1")

        kpi_row1_specs = [
            ("Portfolio Value", "total_value",   ModernStyle.ACCENT_PRIMARY,    "💼", True),
            ("Total Invested",  "total_invested",ModernStyle.ACCENT_SECONDARY,  "📥", True),
            ("Overall P&L",     "overall_pnl",   "#7C3AED",                     "📊", True),
            ("Unrealized P&L",  "unrealized_pnl",ModernStyle.ACCENT_PRIMARY,    "📈", True),
        ]
        for col, (title, key, color, icon, cur) in enumerate(kpi_row1_specs):
            c = _kpi_card(row1, title, key, color=color, icon=icon, metric_key=key, is_currency=cur)
            self._kpi_cards[key] = c
            c.grid(row=0, column=col, sticky="nsew", padx=6, pady=4)

        # ── KPI Row 2: Detail metrics ──────────────────────────────────────────
        row2 = tk.Frame(self._content, bg=ModernStyle.BG_PRIMARY)
        row2.pack(fill="x", padx=20, pady=(0, 6))
        for i in range(5):
            row2.grid_columnconfigure(i, weight=1, uniform="kpi2")

        kpi_row2_specs = [
            ("Unrealized Loss", "unrealized_loss", ModernStyle.ERROR,             "📉", True),
            ("Realized P&L",    "realized_pnl",    ModernStyle.ACCENT_SECONDARY,  "🔷", True),
            ("Realized Loss",   "realized_loss",   ModernStyle.ERROR,             "🔻", True),
            ("XIRR",            "overall_xirr",    ModernStyle.ACCENT_TERTIARY,   "🎯", False),
            ("CAGR",            "overall_cagr",    ModernStyle.INFO,              "📐", False),
        ]
        for col, (title, key, color, icon, cur) in enumerate(kpi_row2_specs):
            c = _kpi_card(row2, title, key, color=color, icon=icon, metric_key=key, is_currency=cur)
            self._kpi_cards[key] = c
            c.grid(row=0, column=col, sticky="nsew", padx=6, pady=4)

        # ── 2×2 Section grid ──────────────────────────────────────────────────
        grid = tk.Frame(self._content, bg=ModernStyle.BG_PRIMARY)
        grid.pack(fill="both", expand=True, padx=20, pady=(10, 20))
        grid.grid_columnconfigure(0, weight=1, uniform="p")
        grid.grid_columnconfigure(1, weight=1, uniform="p")
        grid.grid_rowconfigure(0, weight=0)
        grid.grid_rowconfigure(1, weight=0)

        def _section_card(parent, title: str, icon: str, accent: str, copy_command=None, hdr_bg=None) -> tuple[ModernCard, tk.Frame]:
            """Create a section card with fixed-height scrollable body."""
            card = ModernCard(
                parent,
                bg=ModernStyle.BG_SECONDARY,
                highlight_color=ModernStyle.BORDER_COLOR,
                highlight_thickness=1,
                radius=10,
                canvas_bg=ModernStyle.BG_PRIMARY
            )

            # Accent bar (top) + left accent strip for visual continuity
            tk.Frame(card.content, bg=accent, height=3).pack(fill="x")

            # Left accent strip wrapper
            hdr_wrapper = tk.Frame(card.content, bg=ModernStyle.BG_SECONDARY)
            hdr_wrapper.pack(fill="x")
            tk.Frame(hdr_wrapper, bg=accent, width=4).pack(side="left", fill="y")

            # Header row
            hdr = tk.Frame(hdr_wrapper, bg=hdr_bg or ModernStyle.BG_SECONDARY)
            hdr.pack(fill="x", padx=10, pady=(10, 6))
            tk.Label(
                hdr,
                text=icon,
                fg=ModernStyle.ACCENT_PRIMARY if not hdr_bg else ModernStyle.BG_PRIMARY,
                bg=hdr_bg or ModernStyle.BG_SECONDARY,
                font=ModernStyle.FONT_TITLE,
            ).pack(side="left", padx=(0, 6))
            title_lbl = tk.Label(
                hdr,
                text=title,
                fg=ModernStyle.SALMON if not hdr_bg else ModernStyle.BG_PRIMARY,
                bg=hdr_bg or ModernStyle.BG_SECONDARY,
                font=ModernStyle.FONT_TITLE,
            )
            title_lbl.pack(side="left")

            # Counter Badge – matches header background
            count_lbl = tk.Label(
                hdr,
                text="[0]",
                fg=ModernStyle.ACCENT_PRIMARY,
                bg=hdr_bg or ModernStyle.BG_SECONDARY,
                font=ModernStyle.FONT_HEADING,
                padx=4, pady=2,
            )
            count_lbl.pack(side="left", padx=(8, 0))
            
            if copy_command:
                # Add copy clipboard icon aligned to the right
                copy_lbl = tk.Label(
                    hdr,
                    text="🛍️",
                    fg=ModernStyle.TEXT_SECONDARY if not hdr_bg else ModernStyle.BG_PRIMARY,
                    bg=hdr_bg or ModernStyle.BG_SECONDARY,
                    font=ModernStyle.FONT_HEADING,
                    cursor="hand2"
                )
                copy_lbl.pack(side="right", padx=(0, 4))
                
                # Setup hover/click
                def _c_in(e): copy_lbl.configure(fg=ModernStyle.ACCENT_PRIMARY)
                def _c_out(e): copy_lbl.configure(fg=ModernStyle.TEXT_SECONDARY)
                copy_lbl.bind("<Enter>", _c_in)
                copy_lbl.bind("<Leave>", _c_out)
                copy_lbl.bind("<Button-1>", lambda e: copy_command())

            # Thin divider
            tk.Frame(card.content, bg=ModernStyle.DIVIDER_COLOR, height=0).pack(fill="x", padx=12)

            # Fixed-height scrollable body area
            body_outer = tk.Frame(card.content, bg=ModernStyle.BG_SECONDARY, height=ModernStyle.DASH_SECTION_CARD_HEIGHT)
            body_outer.pack(fill="x", padx=0, pady=(4, 8))
            body_outer.pack_propagate(False)

            body_canvas = tk.Canvas(
                body_outer, bg=ModernStyle.BG_SECONDARY, highlightthickness=0, bd=0
            )
            body_vsb = ttk.Scrollbar(body_outer, orient="vertical", command=body_canvas.yview)
            body_canvas.configure(yscrollcommand=body_vsb.set)
            body_vsb.pack(side="right", fill="y")
            body_canvas.pack(side="left", fill="both", expand=True)

            body = tk.Frame(body_canvas, bg=ModernStyle.BG_SECONDARY)
            body_win = body_canvas.create_window((0, 0), window=body, anchor="nw")
            
            # Store ref to count_lbl
            setattr(body, "_count_lbl", count_lbl)

            def _on_body_cfg(e):
                body_canvas.configure(scrollregion=body_canvas.bbox("all"))
                body_canvas.itemconfigure(body_win, width=body_canvas.winfo_width())

            def _on_canvas_cfg(e):
                body_canvas.itemconfigure(body_win, width=e.width)

            body.bind("<Configure>", _on_body_cfg)
            body_canvas.bind("<Configure>", _on_canvas_cfg)
            _enable_canvas_mousewheel(body_canvas, include_widget=body)

            return card, body

        self.top_card, self.top_body = _section_card(grid, "Top Performers", "🏆", ModernStyle.ACCENT_SECONDARY, copy_command=lambda: self._copy_performers(is_top=True))
        self.worst_card, self.worst_body = _section_card(grid, "Worst Performers", "🌊", ModernStyle.ERROR, copy_command=lambda: self._copy_performers(is_top=False))
        self.insights_card, self.insights_body = _section_card(grid, "Actionable Insights", "🧩", ModernStyle.ACCENT_TERTIARY, copy_command=self._copy_insights)
        self.harvest_card, self.harvest_body = _section_card(grid, "Tax Harvesting Options", "🏦", "#7C3AED", copy_command=self._copy_harvesting)

        self.top_card.grid(row=0, column=0, sticky="nsew", padx=6, pady=4)
        self.worst_card.grid(row=0, column=1, sticky="nsew", padx=6, pady=4)
        self.insights_card.grid(row=1, column=0, sticky="nsew", padx=6, pady=4)
        self.harvest_card.grid(row=1, column=1, sticky="nsew", padx=6, pady=4)

        self._ui_built = True

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle & Loading
    # ──────────────────────────────────────────────────────────────────────────

    def on_show(self):
        super().on_show()
        # MacOS Tkinter Bug: When a massive Scrollable Canvas is unmapped (pack_forget)
        # and re-mapped (pack), macOS puts its geometric <Configure> calculations on hold 
        # until physical mouse motion wakes the runloop. Because the geometry isn't processed,
        # the inner frame width/height evaluate to 0 and the view looks frozen or empty.
        # We must forcefully poke the canvas and the Tcl event queue to process layout exactly now.
        try:
            # Step 1: Force Tkinter to evaluate the pack() geometry from ViewManager
            self.update_idletasks()
            
            # Step 2: Extract the true mapped width 
            w = self._main_canvas.winfo_width()
            if w > 10:
                # Step 3: Impart the width to the hidden child frame BEFORE the background
                # OS event loop has a chance to stall the normal <Configure> event.
                self._main_canvas.itemconfigure(self._content_id, width=w)
                self._main_canvas.configure(scrollregion=self._main_canvas.bbox("all"))
                
                # Step 4: Flush the final geometry to the screen buffer
                self.update_idletasks()
        except Exception:
            pass

    def load_data(self, force: bool = False):
        """Load dashboard data asynchronously to avoid blocking the UI.

        All heavy DB queries (metrics, performers, insights, tax harvesting)
        run in a background thread.  A lightweight loading skeleton is shown
        instantly so the user sees immediate visual feedback.
        """
        if getattr(self, "_data_loaded", False) and not force:
            return
        self._data_loaded = True

        # Show loading skeleton immediately (main thread — instant)
        self._show_loading_skeleton()

        c_val = getattr(self, "currency_var", None).get() if hasattr(self, "currency_var") else "INR"

        def _bg():
            try:
                from model.engine import (
                    get_dashboard_metrics, get_top_worst_performers,
                    get_actionable_insights, get_tax_harvesting_opportunities,
                )
                metrics    = get_dashboard_metrics(currency_filter=c_val)
                performers = get_top_worst_performers(10, currency_filter=c_val)
                insights   = get_actionable_insights(currency_filter=c_val)
                harvesting = get_tax_harvesting_opportunities(500.0, currency_filter=c_val)

                # Apply on main thread for thread-safe Tk updates
                try:
                    self.after(0, lambda: self._apply_payload(metrics, performers, insights, harvesting))
                except Exception:
                    pass
            except Exception as e:
                print(f"Dashboard load error: {e}")

        threading.Thread(target=_bg, daemon=True).start()

    def _show_loading_skeleton(self):
        """Show brief loading placeholders in the KPI labels."""
        try:
            for key, lbl in self.kpi_labels.items():
                lbl.config(text="⏳ Loading…", fg=ModernStyle.TEXT_TERTIARY)
                trend = getattr(lbl, "_trend_lbl", None)
                if trend:
                    trend.config(text="")
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # Animated KPI counter
    # ──────────────────────────────────────────────────────────────────────────

    def _animate_counter(
        self,
        label: tk.Label,
        end_val: float,
        *,
        is_currency: bool = True,
        duration_ms: int = 400,
        fg: str | None = None,
    ) -> None:
        """Animate a label's text from 0 to end_val with ease-out cubic easing."""
        if fg:
            label.config(fg=fg)

        # Cancel any existing animation on this label
        anim_key = f"_anim_{id(label)}"
        old_id = getattr(self, anim_key, None)
        if old_id:
            try:
                self.after_cancel(old_id)
            except Exception:
                pass

        start_val = 0.0
        frame_ms = 16  # ~60fps
        total_frames = max(1, duration_ms // frame_ms)
        frame = [0]  # mutable counter

        def _fmt(v: float) -> str:
            if is_currency:
                c_val = getattr(self, "currency_var", None).get() if hasattr(self, "currency_var") else "INR"
                c_sym = {"JPY": "¥", "USD": "$"}.get(c_val, "₹")
                return f"{c_sym}{v:,.2f}"
            else:
                return f"{v:,.2f}%"

        def _ease_out_cubic(t: float) -> float:
            return 1.0 - (1.0 - t) ** 3

        def _step():
            frame[0] += 1
            t = min(1.0, frame[0] / total_frames)
            eased = _ease_out_cubic(t)
            current = start_val + (end_val - start_val) * eased
            try:
                label.config(text=_fmt(current))
            except Exception:
                return
            if t < 1.0:
                aid = self.after(frame_ms, _step)
                setattr(self, anim_key, aid)
            else:
                label.config(text=_fmt(end_val))  # ensure exact final value
                setattr(self, anim_key, None)

        # Start immediately
        label.config(text=_fmt(0.0))
        aid = self.after(frame_ms, _step)
        setattr(self, anim_key, aid)

    def _tint_kpi_card(
        self,
        key: str,
        value: float,
        *,
        force_negative: bool = False,
    ) -> None:
        """Apply a faint green/red background tint to a KPI card based on its value."""
        card = self._kpi_cards.get(key)
        if card is None:
            return

        # Dark theme tints removed – no background coloring applied
        return  # No tint for zero

        try:
            # Update the card's content frame background
            card.content.configure(bg=tint_inner)
            # Update all immediate children of content
            for child in card.content.winfo_children():
                try:
                    child.configure(bg=tint_inner)
                except Exception:
                    pass
                # And their children (body, title_row, labels)
                for grandchild in child.winfo_children():
                    try:
                        grandchild.configure(bg=tint_inner)
                    except Exception:
                        pass
                    for gc in grandchild.winfo_children():
                        try:
                            gc.configure(bg=tint_inner)
                        except Exception:
                            pass
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # Payload application
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_payload(
        self,
        metrics: dict,
        performers: dict,
        insights: list,
        harvesting: list,
    ) -> None:
        self._current_harvest_data = harvesting
        self._current_performers = performers
        self._current_insights = insights

        # KPI values
        try:
            def _set(key: str, text: str, fg: str | None = None):
                lbl = self.kpi_labels.get(key)
                if lbl is None:
                    return
                lbl.config(text=text)
                if fg:
                    lbl.config(fg=fg)

            total_v   = float(metrics.get("total_value", 0.0) or 0.0)
            total_inv = float(metrics.get("total_invested", 0.0) or 0.0)
            pnl       = float(metrics.get("overall_pnl", 0.0) or 0.0)
            upnl      = float(metrics.get("unrealized_pnl", 0.0) or 0.0)
            uloss     = float(metrics.get("unrealized_loss", 0.0) or 0.0)
            rpnl      = float(metrics.get("realized_pnl", 0.0) or 0.0)
            rloss     = float(metrics.get("realized_loss", 0.0) or 0.0)
            xirr      = float(metrics.get("overall_xirr", 0.0) or 0.0)
            cagr      = float(metrics.get("overall_cagr", 0.0) or 0.0)

            # ── Animated KPI counters (count-up from 0) ────────────────────
            def _anim(key: str, val: float, *, is_cur: bool = True, fg: str | None = None):
                lbl = self.kpi_labels.get(key)
                if lbl is None:
                    return
                self._animate_counter(lbl, val, is_currency=is_cur, fg=fg)

            _anim("total_value",    total_v)
            _anim("total_invested", total_inv)
            _anim("overall_pnl",    pnl,   fg=ModernStyle.SUCCESS if pnl >= 0 else ModernStyle.ERROR)
            _anim("unrealized_pnl", upnl,  fg=ModernStyle.SUCCESS if upnl >= 0 else ModernStyle.ERROR)
            _anim("unrealized_loss", uloss, fg=ModernStyle.ERROR)
            _anim("realized_pnl",   rpnl,  fg=ModernStyle.SUCCESS if rpnl >= 0 else ModernStyle.ERROR)
            _anim("realized_loss",  rloss, fg=ModernStyle.ERROR)
            _anim("overall_xirr",   xirr,  is_cur=False, fg=ModernStyle.SUCCESS if xirr >= 0 else ModernStyle.ERROR)
            _anim("overall_cagr",   cagr,  is_cur=False, fg=ModernStyle.SUCCESS if cagr >= 0 else ModernStyle.ERROR)

            # ── Color-coded P&L background tinting ────────────────────────
            self._tint_kpi_card("overall_pnl",    pnl)
            self._tint_kpi_card("unrealized_pnl", upnl)
            self._tint_kpi_card("unrealized_loss", uloss, force_negative=True)
            self._tint_kpi_card("realized_pnl",   rpnl)
            self._tint_kpi_card("realized_loss",  rloss, force_negative=True)

            # Trend labels and Sparklines
            def _set_trend(key: str, text: str, trend_points: list = None):
                lbl = self.kpi_labels.get(key)
                if lbl is None:
                    return
                trend = getattr(lbl, "_trend_lbl", None)
                if trend:
                    trend.config(text=text)
                
                cvs = getattr(lbl, "_spark_cvs", None)
                if cvs:
                    if not trend_points:
                        import math
                        n = 20
                        trend_points = [math.sin(i/2.0) + (i*0.1) for i in range(n)]
                        if key in ("realized_loss", "unrealized_loss"):
                            trend_points.reverse()

                    min_p, max_p = min(trend_points), max(trend_points)
                    rng = max_p - min_p if max_p != min_p else 1
                    
                    color = lbl.cget("fg")
                    fill_color = ModernStyle.SLATE_800
                    
                    def redraw(e=None):
                        cvs.delete("all")
                        req_w = e.width if e else cvs.winfo_width()
                        req_h = e.height if e else int(cvs.cget("height"))
                        if req_w < 10: 
                            return
                        
                        coords = []
                        step = req_w / max(1, len(trend_points) - 1)
                        for i, p in enumerate(trend_points):
                            x = i * step
                            y = req_h - (((p - min_p) / rng) * (req_h - 6)) - 3
                            coords.extend([x, y])
                        
                        fill_coords = [0, req_h] + coords + [req_w, req_h]
                        cvs.create_polygon(fill_coords, fill=fill_color, outline="")
                        cvs.create_line(coords, fill=color, width=2, smooth=True)

                    cvs.bind("<Configure>", redraw)
                    if cvs.winfo_width() > 10:
                        redraw()

            pnl_pct = ((pnl / total_inv) * 100.0) if total_inv else 0.0
            arrow = "▲" if pnl >= 0 else "▼"
            _set_trend("total_value",    f"Invested {_compact_money(total_inv)}")
            _set_trend("total_invested", f"{len(performers.get('top', []) or [])} Positions")
            _set_trend("overall_pnl",    f"{arrow} {pnl_pct:+.2f}% overall return")
            _set_trend("unrealized_pnl", f"{'▲' if upnl >= 0 else '▼'} Open positions")
            _set_trend("realized_pnl",   f"{'▲' if rpnl >= 0 else '▼'} Closed trades")
            _set_trend("realized_loss",  "Losses from closed trades")
            _set_trend("overall_xirr",   "Annualized return (XIRR)")
            _set_trend("overall_cagr",   "Compound annual growth")

            # Update header subtitle
            try:
                self._header_canvas.itemconfig(
                    self._header_subtitle,
                    text=f"Total Portfolio: {_money(total_v)}  •  P&L: {_money(pnl)} ({pnl_pct:+.2f}%)"
                          f"  •  Updated {datetime.now().strftime('%H:%M')}"
                )
            except Exception:
                pass

        except Exception as e:
            print(f"KPI apply error: {e}")

        # Section lists
        self._render_performers(self.top_body, performers.get("top", []) or [],   is_top=True)
        self._render_performers(self.worst_body, performers.get("worst", []) or [], is_top=False)
        self._render_simple_list(self.insights_body, insights or [],    kind="insight")
        self._render_simple_list(self.harvest_body, harvesting or [],   kind="harvest")
        # Update counter badge for Tax Harvesting section
        if hasattr(self.harvest_body, "_count_lbl"):
            self.harvest_body._count_lbl.config(text=f"[{len(harvesting) if harvesting else 0}]")
        # Update counter badge for Actionable Insights section
        if hasattr(self.insights_body, "_count_lbl"):
            self.insights_body._count_lbl.config(text=f"[{len(insights) if insights else 0}]")

        # MacOS Tkinter bug: The native OS event loop will not swap the rendering
        # buffers into view if no physical mouse movement is currently firing, entirely
        # ignoring the passive `self.update()` request. 
        # Fix: We silently jitter the root window height by 1 pixel and revert it. 
        # This forces `drawRect:` on `NSRunLoop`, updating the screen instantly.
        try:
            top = self.winfo_toplevel()
            w = top.winfo_width()
            h = top.winfo_height()
            top.geometry(f"{w}x{h+1}")
            top.update_idletasks()
            top.geometry(f"{w}x{h}")
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────────────────
    # Section renderers
    # ──────────────────────────────────────────────────────────────────────────

    def _clear_frame(self, frame: tk.Frame) -> None:
        for w in frame.winfo_children():
            w.destroy()

    def _empty_state(self, frame: tk.Frame, msg: str = "No data available") -> None:
        """Show a friendly empty-state message."""
        tk.Label(
            frame,
            text=f"—  {msg}",
            fg=ModernStyle.TEXT_TERTIARY,
            bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_SMALL,
        ).pack(anchor="w", pady=4)

    def _render_performers(self, frame: tk.Frame, data: list, *, is_top: bool) -> None:
        self._clear_frame(frame)
        data = (data or [])[:10]

        if hasattr(frame, "_count_lbl"):
            frame._count_lbl.config(text=f"[{len(data)}]")

        if not data:
            self._empty_state(frame)
            return

        # Compute max |pnl| for bar scaling
        max_abs = max((abs(float(d.get("pnl", 0.0) or 0.0)) for d in data), default=1) or 1

        c_val = getattr(self, "currency_var", None).get() if hasattr(self, "currency_var") else "INR"
        c_sym = {"JPY": "¥", "USD": "$"}.get(c_val, "₹")

        for i, item in enumerate(data):
            sym       = str(item.get("symbol", ""))
            pnl       = float(item.get("pnl", 0.0) or 0.0)
            invested  = float(item.get("invested", 1.0) or 1.0)
            avg_price = float(item.get("avg_price", 0.0) or 0.0)
            cur_price = float(item.get("current_price", 0.0) or 0.0)
            roi       = (pnl / invested * 100.0) if invested > 0 else 0.0
            bar_frac  = min(1.0, abs(pnl) / max_abs)

            accent = ModernStyle.SUCCESS if pnl >= 0 else ModernStyle.ERROR

            # Refined zebra: white / Slate-50
            row_bg = ModernStyle.BG_SECONDARY if i % 2 == 0 else ModernStyle.SLATE_50

            # ── Thin divider between rows ────────────────────────────────────
            if i > 0:
                tk.Frame(frame, bg=ModernStyle.DIVIDER_COLOR, height=1).pack(fill="x", padx=8)

            # ── Row container ────────────────────────────────────────────────
            row = tk.Frame(frame, bg=row_bg)
            row.pack(fill="x", pady=0)

            # Left accent strip (hidden initially, shown on hover)
            accent_strip = tk.Frame(row, bg=row_bg, width=4)
            accent_strip.pack(side="left", fill="y")

            content = tk.Frame(row, bg=row_bg)
            content.pack(fill="x", padx=(6, 10), pady=(8, 8))

            # ── Col 1: Rank badge ────────────────────────────────────────────
            badge_text = {0: "🥇", 1: "🥈", 2: "🥉"}.get(i)
            if badge_text:
                badge_lbl = tk.Label(
                    content, text=badge_text,
                    fg=ModernStyle.TEXT_PRIMARY, bg=row_bg,
                    font=ModernStyle.FONT_HEADING,
                )
            else:
                # Positions 4+ get a colored circle badge
                badge_lbl = tk.Label(
                    content, text=f" {i+1} ",
                    fg=ModernStyle.TEXT_ON_ACCENT,
                    bg=ModernStyle.ACCENT_PRIMARY,
                    font=ModernStyle.FONT_SMALL_BOLD,
                    padx=4, pady=1,
                )
            badge_lbl.pack(side="left", padx=(0, 6))

            # ── Col 2: Symbol name (fixed width for alignment) ───────────────
            sym_lbl = tk.Label(
                content, text=sym, width=14, anchor="w",
                fg=ModernStyle.ACCENT_PRIMARY, bg=row_bg,
                font=ModernStyle.FONT_HEADING,
            )
            sym_lbl.pack(side="left", padx=(0, 8))

            # ── Col 3: Avg & LTP prices (expandable middle) ─────────────────
            price_lbl = tk.Label(
                content,
                text=f"Avg {c_sym}{avg_price:,.1f}  •  LTP {c_sym}{cur_price:,.1f}",
                fg=ModernStyle.TEXT_SECONDARY, bg=row_bg,
                font=ModernStyle.FONT_BODY,
            )
            price_lbl.pack(side="left", padx=(0, 10), expand=True, fill="x")

            # ── Col 4: Inline progress bar ───────────────────────────────────
            pbar = tk.Canvas(
                content, bg=ModernStyle.BG_TERTIARY,
                height=6, highlightthickness=0, width=100,
            )
            pbar.pack(side="left", padx=(0, 10), pady=2)

            def _draw_bar(e, c=pbar, frac=bar_frac, col=accent):
                c.delete("all")
                w = e.width if e else int(c.cget("width"))
                h = e.height if e else int(c.cget("height"))
                bar_w = max(2, int(w * frac))
                # Filled portion (right-aligned)
                c.create_rectangle(w - bar_w, 0, w, h, fill=col, outline="")

            pbar.bind("<Configure>", _draw_bar)

            # ── Col 5: P&L + ROI% ───────────────────────────────────────────
            arrow = "▲" if pnl >= 0 else "▼"
            pnl_disp = _compact_money(abs(pnl), c_val)

            pnl_lbl = tk.Label(
                content, text=f"{arrow} {pnl_disp}",
                fg=accent, bg=row_bg,
                font=ModernStyle.FONT_HEADING,
            )
            pnl_lbl.pack(side="right", padx=(4, 0))

            roi_lbl = tk.Label(
                content, text=f"({roi:+.1f}%)",
                fg=accent, bg=row_bg,
                font=ModernStyle.FONT_HEADING,
            )
            roi_lbl.pack(side="right", padx=(0, 2))

            # ── Collect all widgets for hover & click ────────────────────────
            all_widgets = [row, accent_strip, content, badge_lbl, sym_lbl, price_lbl, pnl_lbl, roi_lbl]

            # List of widgets to change background color on hover
            bg_widgets = [row, content, sym_lbl, price_lbl, pnl_lbl, roi_lbl]
            if i < 3:
                bg_widgets.append(badge_lbl)

            def _click_fn(e=None, s=sym):
                self._open_trade_drilldown(s)

            def _hover_in(e, _row=row, _strip=accent_strip, _acc=accent, _bg_w=bg_widgets):
                _strip.configure(bg=_acc)
                for w in _bg_w:
                    try:
                        w.configure(bg=ModernStyle.BG_TERTIARY)
                    except Exception:
                        pass

            def _hover_out(e, _row=row, _strip=accent_strip, _bg=row_bg, _bg_w=bg_widgets):
                _strip.configure(bg=_bg)
                for w in _bg_w:
                    try:
                        w.configure(bg=_bg)
                    except Exception:
                        pass

            row.configure(cursor="hand2")
            for w in all_widgets + [pbar]:
                try:
                    w.bind("<Double-1>", _click_fn)
                    w.bind("<Enter>", _hover_in)
                    w.bind("<Leave>", _hover_out)
                except Exception:
                    pass

    def _render_simple_list(self, frame: tk.Frame, data: list, *, kind: str) -> None:
        self._clear_frame(frame)

        if not data:
            self._empty_state(frame)
            return

        # ── Tax Harvesting ─────────────────────────────────────────────────────
        if kind == "harvest":
            from ui_utils import format_money

            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                sym    = str(item.get("symbol", "")).strip()
                loss   = float(item.get("unrealized_loss", 0.0) or 0.0)
                qty    = item.get("qty", "")
                avg    = float(item.get("avg_price", 0.0) or 0.0)
                broker = str(item.get("broker", "") or "").strip()
                _cur   = str(item.get("currency", "INR") or "INR").upper()

                row_bg = ModernStyle.BG_SECONDARY if i % 2 == 0 else ModernStyle.SLATE_50

                # Divider between rows
                if i > 0:
                    tk.Frame(frame, bg=ModernStyle.DIVIDER_COLOR, height=1).pack(fill="x", padx=8)

                row = tk.Frame(frame, bg=row_bg)
                row.pack(fill="x", pady=0)

                # Left accent strip (shown on hover)
                accent_strip = tk.Frame(row, bg=row_bg, width=4)
                accent_strip.pack(side="left", fill="y")

                line = tk.Frame(row, bg=row_bg)
                line.pack(fill="x", padx=(6, 10), pady=(8, 8))

                # Icon
                icon_lbl = tk.Label(line, text="⚠️", bg=row_bg, font=ModernStyle.FONT_HEADING)
                icon_lbl.pack(side="left", padx=(0, 6))

                # Symbol (fixed width for alignment)
                sym_lbl = tk.Label(
                    line, text=sym or "—", width=14, anchor="w",
                    fg=ModernStyle.ACCENT_PRIMARY, bg=row_bg,
                    font=ModernStyle.FONT_HEADING,
                )
                sym_lbl.pack(side="left", padx=(0, 8))

                # Qty & Avg detail (expandable middle)
                detail_lbl = tk.Label(
                    line,
                    text=f"Qty {qty}  •  Avg {format_money(avg, _cur)}",
                    fg=ModernStyle.TEXT_SECONDARY, bg=row_bg,
                    font=ModernStyle.FONT_BODY,
                )
                detail_lbl.pack(side="left", expand=True, fill="x")

                # Loss amount (right-aligned)
                loss_lbl = tk.Label(
                    line,
                    text=format_money(loss, _cur),
                    fg=ModernStyle.ERROR if loss < 0 else ModernStyle.SUCCESS,
                    bg=row_bg,
                    font=ModernStyle.FONT_HEADING,
                )
                loss_lbl.pack(side="right")

                # Hover + click
                all_w = [row, accent_strip, line, icon_lbl, sym_lbl, detail_lbl, loss_lbl]

                def _hover_in(e=None, _strip=accent_strip, _all=all_w):
                    _strip.configure(bg=ModernStyle.ERROR)
                    for w in _all:
                        try:
                            if w is not _strip:
                                w.configure(bg=ModernStyle.BG_TERTIARY)
                        except Exception:
                            pass

                def _hover_out(e=None, _strip=accent_strip, _bg=row_bg, _all=all_w):
                    _strip.configure(bg=_bg)
                    for w in _all:
                        try:
                            if w is not _strip:
                                w.configure(bg=_bg)
                        except Exception:
                            pass

                row.configure(cursor="hand2")
                for w in all_w:
                    try:
                        w.bind("<Double-1>", lambda e=None, s=sym, b=broker: self._open_trade_drilldown(s, broker=b or None))
                        w.bind("<Enter>", _hover_in)
                        w.bind("<Leave>", _hover_out)
                    except Exception:
                        pass
            return

        # ── Actionable Insights ────────────────────────────────────────────────
        if kind == "insight":
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    tk.Label(
                        frame, text=f"•  {item}",
                        fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
                        font=ModernStyle.FONT_BODY, justify="left", wraplength=520,
                    ).pack(anchor="w", pady=2)
                    continue

                sym      = str(item.get("symbol", "")).strip()
                signal   = str(item.get("signal", "") or "").strip().upper()
                iv       = float(item.get("iv", 0.0) or 0.0)
                cp       = float(item.get("current_price", 0.0) or 0.0)
                diff_pct = ((iv - cp) / cp * 100.0) if cp else 0.0

                if signal == "ACCUMULATE":
                    sig_icon, sig_color = "📈", ModernStyle.SUCCESS
                elif signal == "REDUCE":
                    sig_icon, sig_color = "📉", ModernStyle.ERROR
                else:
                    sig_icon, sig_color = "⏸️", ModernStyle.TEXT_SECONDARY

                row_bg = ModernStyle.BG_SECONDARY if i % 2 == 0 else ModernStyle.SLATE_50

                # Divider between rows
                if i > 0:
                    tk.Frame(frame, bg=ModernStyle.DIVIDER_COLOR, height=1).pack(fill="x", padx=8)

                row = tk.Frame(frame, bg=row_bg)
                row.pack(fill="x", pady=0)

                # Left accent strip (shown on hover)
                accent_strip = tk.Frame(row, bg=row_bg, width=4)
                accent_strip.pack(side="left", fill="y")

                line = tk.Frame(row, bg=row_bg)
                line.pack(fill="x", padx=(6, 10), pady=(8, 8))

                # Icon
                icon_lbl = tk.Label(line, text=sig_icon, bg=row_bg, font=ModernStyle.FONT_HEADING)
                icon_lbl.pack(side="left", padx=(0, 6))

                # Symbol (fixed width)
                sym_lbl = tk.Label(
                    line, text=sym or "—", width=14, anchor="w",
                    fg=ModernStyle.ACCENT_PRIMARY, bg=row_bg,
                    font=ModernStyle.FONT_HEADING,
                )
                sym_lbl.pack(side="left", padx=(0, 8))

                # IV / Curr / Gap detail (expandable middle)
                _sym_iv = "¥" if str(item.get("currency", "INR")).upper() == "JPY" else "₹"
                detail_lbl = tk.Label(
                    line,
                    text=f"IV {_sym_iv}{iv:,.0f}  •  Curr {_sym_iv}{cp:,.0f}  •  Gap {diff_pct:+.1f}%",
                    fg=ModernStyle.TEXT_SECONDARY, bg=row_bg,
                    font=ModernStyle.FONT_BODY,
                )
                detail_lbl.pack(side="left", expand=True, fill="x")

                # Signal chip (right-aligned)
                chip_lbl = tk.Label(
                    line, text=signal,
                    fg=sig_color, bg=row_bg,
                    font=ModernStyle.FONT_BODY_BOLD,
                )
                chip_lbl.pack(side="right", padx=(0, 2))

                # Hover + click
                all_w = [row, accent_strip, line, icon_lbl, sym_lbl, detail_lbl, chip_lbl]

                def _hover_in(e=None, _strip=accent_strip, _col=sig_color, _all=all_w):
                    _strip.configure(bg=_col)
                    for w in _all:
                        try:
                            if w is not _strip:
                                w.configure(bg=ModernStyle.BG_TERTIARY)
                        except Exception:
                            pass

                def _hover_out(e=None, _strip=accent_strip, _bg=row_bg, _all=all_w):
                    _strip.configure(bg=_bg)
                    for w in _all:
                        try:
                            if w is not _strip:
                                w.configure(bg=_bg)
                        except Exception:
                            pass

                row.configure(cursor="hand2")
                for w in all_w:
                    try:
                        w.bind("<Double-1>", lambda e=None, s=sym: self._open_trade_drilldown(s))
                        w.bind("<Enter>", _hover_in)
                        w.bind("<Leave>", _hover_out)
                    except Exception:
                        pass
            return

        # Default bullet list
        for i, item in enumerate(data):
            text = item.get("text") or item.get("message") or str(item) if isinstance(item, dict) else str(item)
            tk.Label(
                frame, text=f"•  {text}",
                fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
                font=ModernStyle.FONT_BODY, justify="left", wraplength=520,
            ).pack(anchor="w", pady=2)

    # ──────────────────────────────────────────────────────────────────────────
    # Trade Drilldown popup
    # ──────────────────────────────────────────────────────────────────────────

    def _open_trade_drilldown(self, symbol: str, *, broker: str | None = None) -> None:
        symbol = (symbol or "").strip()
        if not symbol:
            return

        top = tk.Toplevel(self)
        top.title(f"Trade Drilldown — {symbol}")
        ModernStyle.style_modal(top)
        top.configure(bg=ModernStyle.BG_PRIMARY)
        top.geometry("980x560")

        try:
            top.transient(self.winfo_toplevel())
        except Exception:
            pass
        try:
            center_window(top, parent=self.winfo_toplevel())
        except Exception:
            pass

        # Header
        hdr = tk.Frame(top, bg=ModernStyle.BG_PRIMARY)
        hdr.pack(fill="x", padx=16, pady=14)
        tk.Frame(hdr, bg=ModernStyle.ACCENT_PRIMARY, width=5).pack(side="left", fill="y", padx=(0, 12))
        
        # Fetch stock name for title
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
            pass

        if display_name != symbol:
            top.title(f"Trade Drilldown — {display_name}")

        title_col = tk.Frame(hdr, bg=ModernStyle.BG_PRIMARY)
        title_col.pack(side="left", fill="y")
        tk.Label(title_col, text=display_name, fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_PRIMARY, font=ModernStyle.FONT_TITLE).pack(anchor="w")
        tk.Label(
            title_col,
            text=f"Broker: {broker}" if broker else "All Brokers",
            fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_PRIMARY,
            font=ModernStyle.FONT_BODY,
        ).pack(anchor="w")

        body = tk.Frame(top, bg=ModernStyle.BG_PRIMARY)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        act = tk.Frame(body, bg=ModernStyle.BG_PRIMARY)
        act.pack(fill="x", pady=(0, 8))

        cols = ("#", "Date", "Trade ID", "Type", "Qty", "Price ₹", "Fees ₹", "Running Qty", "AvgCost ₹", "Running PnL ₹", "Broker")
        table = tk.Frame(body, bg=ModernStyle.BG_PRIMARY)
        table.pack(fill="both", expand=True)

        # Configure style for the drilldown table (matching Trade History view font size)
        style = ttk.Style()
        style.configure("Drilldown.Treeview", font=ModernStyle.FONT_TABLE, rowheight=32)
        style.configure("Drilldown.Treeview.Heading", font=ModernStyle.FONT_TABLE_BOLD)
        
        tv = ttk.Treeview(table, columns=cols, show="headings", height=16, style="Drilldown.Treeview")
        widths = [40, 90, 90, 60, 70, 90, 80, 80, 95, 100, 100]
        for c, w in zip(cols, widths):
            tv.heading(c, text=c, anchor="center")
            tv.column(c, width=w, anchor="center")
            
        add_treeview_copy_menu(tv)

        # Style tags
        try:
            tv.tag_configure("odd",  background=ModernStyle.BG_SECONDARY)
            tv.tag_configure("even", background=ModernStyle.SLATE_50)
            tv.tag_configure("buy",  foreground=ModernStyle.SUCCESS, font=ModernStyle.FONT_TABLE)
            tv.tag_configure("sell", foreground=ModernStyle.ERROR, font=ModernStyle.FONT_TABLE)
        except Exception:
            pass

        def _copy():
            try:
                lines = ["\t".join(cols)]
                for iid in tv.get_children():
                    vals = tv.item(iid, "values")
                    lines.append("\t".join(str(v).replace("₹", "").replace(",", "").replace("%", "").strip() for v in vals))
                self.clipboard_clear()
                self.clipboard_append("\n".join(lines))
                messagebox.showinfo("Drilldown", "Copied trades to clipboard.")
            except Exception as e:
                messagebox.showerror("Drilldown", f"Failed to copy: {e}")

        ModernButton(act, text="🛍️  Copy Trades", command=_copy, bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_PRIMARY, width=140, height=36).pack(side="left")
        
        # Buy/Sell Qty Summary (Compact Line)
        summary_f = tk.Frame(act, bg=ModernStyle.BG_PRIMARY)
        summary_f.pack(side="left", padx=12)
        
        def _small_line(parent, label, color_bg, color_fg):
            f = tk.Frame(parent, bg=color_bg, padx=12, pady=6, highlightbackground=color_fg, highlightthickness=1)
            f.pack(side="left", padx=4)
            tk.Label(f, text=f"{label} : ", bg=color_bg, fg=color_fg, font=ModernStyle.FONT_SMALL_BOLD).pack(side="left")
            val = tk.Label(f, text="—", bg=color_bg, fg=color_fg, font=ModernStyle.FONT_BODY_BOLD)
            val.pack(side="left")
            return val

        buy_qty_val = _small_line(summary_f, "Buy Volume", ModernStyle.SUCCESS_PALE, ModernStyle.SUCCESS)
        sell_qty_val = _small_line(summary_f, "Sell Volume", ModernStyle.ERROR_PALE, ModernStyle.ERROR)

        ModernButton(act, text="✕  Close", command=lambda: top.destroy(), bg=ModernStyle.SALMON, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_PRIMARY, width=100, height=36).pack(side="right")

        vsb = ttk.Scrollbar(table, orient="vertical", command=tv.yview)
        hsb = ttk.Scrollbar(table, orient="horizontal", command=tv.xview)
        tv.configure(yscroll=vsb.set, xscroll=hsb.set)
        tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table.grid_rowconfigure(0, weight=1)
        table.grid_columnconfigure(0, weight=1)

        def _load():
            try:
                from model.data_cache import TradeHistoryFilters
                if self.app_state is not None and hasattr(self.app_state, "data_cache"):
                    cache = self.app_state.data_cache
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
            except Exception:
                df = None

            def _apply():
                for it in tv.get_children():
                    tv.delete(it)
                if df is None or getattr(df, "empty", True):
                    return
                
                total_buy = 0.0
                total_sell = 0.0
                
                for idx, r in enumerate(df.itertuples(index=False)):
                    rtype = str(getattr(r, "type", "")).upper()
                    qty   = float(getattr(r, "qty", 0.0) or 0.0)
                    price = float(getattr(r, "price", 0.0) or 0.0)
                    fee   = float(getattr(r, "fee", 0.0) or 0.0)
                    run_qty = float(getattr(r, "run_qty", 0.0) or 0.0)
                    avg_cost = float(getattr(r, "avg_cost", 0.0) or 0.0)
                    rpnl  = float(getattr(r, "running_pnl", 0.0) or 0.0)
                    row_currency = str(getattr(r, "currency", "INR") or "INR").upper()
                    from ui_utils import format_money

                    if rtype in {"BUY", "B"}:
                        total_buy += qty
                    elif rtype in {"SELL", "S"}:
                        total_sell += qty

                    type_disp = rtype
                    if rtype in {"BUY", "B"}:
                        type_disp = "🌲 Buy"
                    elif rtype in {"SELL", "S"}:
                        type_disp = "🔻 Sell"

                    raw_d = str(getattr(r, "date", ""))
                    try:
                        from datetime import datetime
                        disp_d = datetime.strptime(raw_d, "%Y-%m-%d").strftime("%Y-%b-%d")
                    except Exception:
                        disp_d = raw_d
                    vals  = (
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
                    stripe   = "odd" if idx % 2 else "even"
                    type_tag = "buy" if rtype == "BUY" else "sell"
                    tv.insert("", "end", values=vals, tags=(stripe, type_tag))

                buy_qty_val.configure(text=f"{total_buy:g}")
                sell_qty_val.configure(text=f"{total_sell:g}")

            self.after(200, _apply)

        threading.Thread(target=_load, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────────────
    # Broker breakdown popup
    # ──────────────────────────────────────────────────────────────────────────

    def _show_broker_breakdown(self, title: str, metric_key: str, *, is_currency: bool = True, color: str = ModernStyle.ACCENT_PRIMARY) -> None:
        c_val = getattr(self, "currency_var", None).get() if hasattr(self, "currency_var") else "INR"
        try:
            from model.engine import get_metrics_by_broker
            broker_metrics = get_metrics_by_broker(currency_filter=c_val)
        except Exception as e:
            messagebox.showerror("Breakdown", f"Failed to load broker breakdown: {e}")
            return

        rows = []
        total = 0.0
        for broker, m in (broker_metrics or {}).items():
            v = float((m or {}).get(metric_key, 0.0) or 0.0)
            rows.append((str(broker), v))
            total += v
        rows.sort(key=lambda x: x[1], reverse=True)

        modal = PremiumModal(self, title=title, geometry="600x400")
        modal.add_chip("📊", "Breakdown", bg_color=ModernStyle.SLATE_100, fg_color=color)
        if is_currency:
            modal.status_lbl.configure(text=f"Total Across Brokers: {_money(total, c_val)}")
        else:
            modal.status_lbl.configure(text=f"Displaying individual {title} calculated per broker.")
        
        # Add dynamically colored Close button at the top header area
        close_btn = ModernButton(
            modal.inner_hdr, 
            text="✕  Close", 
            command=modal.destroy, 
            bg=color,  
            fg=ModernStyle.TEXT_ON_ACCENT, 
            canvas_bg=ModernStyle.BG_PRIMARY,
            width=110, 
            height=36,
            radius=8,
            font=ModernStyle.FONT_BODY_BOLD
        )
        close_btn.pack(side="right", anchor="e")
        
        # Override header accent to match KPI color
        for w in modal.header.winfo_children():
            if isinstance(w, tk.Frame) and w.cget("height") == 3:
                w.configure(bg=color)
        for w in modal.body_card.winfo_children():
            if isinstance(w, tk.Frame) and w.cget("height") == 2:
                w.configure(bg=color)

        # Body area: pack modal.content_frame expanded so Treeview fills
        table_frame = modal.content_frame
        table_frame.pack_configure(fill="both", expand=True)
        
        cols = ("Broker", "Value", "% of Total") if is_currency else ("Broker", "Performance Rate")
        tv = ttk.Treeview(table_frame, columns=cols, show="headings", height=16)
        
        # Custom Treeview Styling for this modal (Centering and Larger Font)
        style_name = f"Breakdown.Treeview"
        s = ttk.Style()
        # Increased font size and rowheight for readability
        s.configure(style_name, rowheight=42, font=ModernStyle.FONT_TABLE)
        tv.configure(style=style_name)

        for c in cols:
            tv.heading(c, text=c, anchor="center")
            if not is_currency and c == "Performance Rate":
                tv.column(c, width=220, anchor="center")
            else:
                tv.column(c, width=220 if c == "Broker" else 160, anchor="center")

        tv.tag_configure("odd",  background="#FFFFFF")
        tv.tag_configure("even", background=ModernStyle.SLATE_50)
        tv.tag_configure("sym",  foreground=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_BODY)
        # P&L Specific Tags
        tv.tag_configure("profit", foreground=ModernStyle.SUCCESS, font=ModernStyle.FONT_TABLE_BOLD)
        tv.tag_configure("loss",   foreground=ModernStyle.ERROR, font=ModernStyle.FONT_TABLE_BOLD)

        add_treeview_copy_menu(tv)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tv.yview)
        tv.configure(yscroll=vsb.set)
        
        tv.pack(side="left", fill="both", expand=True)
        # Only show scrollbar if more than 8 items? Actually, let's keep it tidy
        if len(rows) > 8:
            vsb.pack(side="right", fill="y")

        for idx, (broker, v) in enumerate(rows):
            disp = _money(v, c_val) if is_currency else _pct(v)
            
            # Semantic tags based on Value
            tags = ["odd" if idx % 2 == 0 else "even"]
            # Apply Profit/Loss coloring for specific metric types
            if metric_key in {"overall_pnl", "unrealized_pnl", "realized_pnl", "overall_xirr", "overall_cagr"}:
                if v > 0: tags.append("profit")
                elif v < 0: tags.append("loss")
            elif metric_key in {"unrealized_loss", "realized_loss"}:
                tags.append("loss")
            
            if is_currency:
                pct = (v / total * 100.0) if total != 0 else 0.0
                tv.insert("", "end", iid=broker, values=(broker, disp, f"{pct:.1f}%"), tags=tuple(tags))
            else:
                tv.insert("", "end", iid=broker, values=(broker, disp), tags=tuple(tags))

        # Add symbol breakdown as tree children
        try:
            from model.database import db_session
            with db_session() as conn:
                cur = conn.cursor()
                sql = None
                if metric_key == "total_value":
                    sql = "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)) as val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)) > 0 ORDER BY val DESC"
                elif metric_key == "total_invested":
                    sql = "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), (h.qty * h.avg_price) as val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND (h.qty * h.avg_price) > 0 ORDER BY val DESC"
                elif metric_key == "overall_pnl":
                    sql = "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), running_pnl as val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND running_pnl != 0 ORDER BY val DESC"
                elif metric_key == "unrealized_pnl":
                    sql = "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price) - h.qty*h.avg_price) as val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price) - h.qty*h.avg_price) != 0 ORDER BY val DESC"
                elif metric_key == "unrealized_loss":
                    sql = "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price) - h.qty*h.avg_price) as val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price) - h.qty*h.avg_price) < 0 ORDER BY val ASC"
                elif metric_key == "realized_pnl":
                    sql = "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), realized_pnl as val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND realized_pnl != 0 ORDER BY val DESC"
                elif metric_key == "realized_loss":
                    sql = "SELECT h.symbol, COALESCE(m.stock_name, h.symbol), realized_pnl as val FROM holdings h LEFT JOIN marketdata m USING(symbol) WHERE broker = ? AND h.currency = ? AND realized_pnl < 0 ORDER BY val ASC"

                if sql:
                    for broker, total_v in rows:
                        cur.execute(sql, (broker, c_val.upper()))
                        for sym, name, val in cur.fetchall():
                            if abs(val) > 0.01:
                                sym_pct_str = f"{(abs(val)/abs(total_v) * 100):.1f}%" if abs(total_v) > 0 else "0.0%"
                                sym_disp = _money(val, c_val) if is_currency else f"{val:.2f}"
                                
                                # Use name if it's different from symbol
                                label = f"   ↳ {name}" if name and name != sym else f"   ↳ {sym}"
                                tv.insert(broker, "end", values=(label, sym_disp, sym_pct_str), tags=("sym",))
        except Exception as e:
            print(f"Failed to fetch symbol breakdown: {e}")



    # ──────────────────────────────────────────────────────────────────────────
    # Market Data Refresh
    # ──────────────────────────────────────────────────────────────────────────

    def _on_refresh_market_data(self) -> None:
        if getattr(self, "_refresh_inflight", False):
            return
        self._refresh_inflight = True
        self.refresh_status.config(text="Refreshing…")
        try:
            self.refresh_btn.set_disabled(True)
        except Exception:
            pass

        def _bg():
            try:
                from model.database import db_session
                from model.engine import fetch_and_update_market_data, rebuild_holdings
                with db_session() as conn:
                    cur = conn.cursor()
                    # Manual refresh: fetch all historical trades + all watchlist symbols
                    cur.execute("""
                        SELECT DISTINCT symbol FROM trades
                        UNION
                        SELECT DISTINCT symbol FROM watchlist
                    """)
                    symbols = [r[0] for r in cur.fetchall() if r[0]]
                if symbols:
                    fetch_and_update_market_data(symbols)
                
                # Refresh sidebar market tickers via the sidebar's callback path
                try:
                    if self.app_state and hasattr(self.app_state, 'sidebar'):
                        self.app_state.sidebar.refresh_tickers()
                except Exception:
                    pass
                
                rebuild_holdings()
                if self.app_state and hasattr(self.app_state, "refresh_data_cache"):
                    self.app_state.refresh_data_cache()
                self.after(200, self._finish_refresh)
            except Exception as e:
                self.after(200, lambda err_msg=str(e): self._finish_refresh(err=err_msg))

        threading.Thread(target=_bg, daemon=True).start()

    def _finish_refresh(self, err: str | None = None) -> None:
        self._refresh_inflight = False
        try:
            self.refresh_btn.set_disabled(False)
        except Exception:
            pass
        if err:
            self.refresh_status.config(text=f"⚠️ Refresh failed: {err[:60]}")
        else:
            self.refresh_status.config(text=f"✅ Updated {datetime.now().strftime('%H:%M:%S')}")
            self._data_loaded = False
            self.load_data()
            # Also refresh sidebar investment & status data
            try:
                if self.app_state and hasattr(self.app_state, 'sidebar'):
                    self.app_state.sidebar.refresh_sidebar_data()
            except Exception:
                pass

    def _copy_performers(self, is_top: bool):
        try:
            data_dict = getattr(self, "_current_performers", {})
            data = data_dict.get("top" if is_top else "worst", [])
            data = (data or [])[:10]
            
            if not data:
                messagebox.showinfo("Copy", "No data to copy.")
                return
                
            lines = ["Rank	Symbol	P&L	ROI%"]
            for i, item in enumerate(data):
                sym = str(item.get("symbol", ""))
                pnl = float(item.get("pnl", 0.0) or 0.0)
                inv = float(item.get("invested", 1.0) or 1.0)
                roi = (pnl / inv * 100.0) if inv > 0 else 0.0
                rank = f"#{i+1}"
                pnl_str = _compact_money(pnl)
                lines.append(f"{rank}	{sym}	{pnl_str}	{roi:+.1f}%")
                
            text = "\n".join(lines)
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("Copy", f"Copied {len(data)} performers to clipboard.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy performers: {e}")

    def _copy_insights(self):
        try:
            data = getattr(self, "_current_insights", [])
            if not data:
                messagebox.showinfo("Copy", "No insights to copy.")
                return
                
            lines = ["Signal	Symbol	IV	Current	Gap"]
            for item in data:
                if not isinstance(item, dict):
                    continue
                sym = str(item.get("symbol", "")).strip()
                signal = str(item.get("signal", "") or "").strip().upper()
                iv = float(item.get("iv", 0.0) or 0.0)
                cp = float(item.get("current_price", 0.0) or 0.0)
                cur = str(item.get("currency", "INR") or "INR").upper()
                diff = ((iv - cp) / cp * 100.0) if cp else 0.0
                _s = "¥" if cur == "JPY" else "₹"
                lines.append(f"{signal}	{sym}	{_s}{iv:,.0f}	{_s}{cp:,.0f}	{diff:+.1f}%")
                
            if len(lines) == 1:
                messagebox.showinfo("Copy", "No structured insights to copy.")
                return
                
            text = "\n".join(lines)
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("Copy", f"Copied {len(lines)-1} insights to clipboard.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy insights: {e}")

    def _copy_harvesting(self):
        try:
            data = getattr(self, "_current_harvest_data", [])
            
            if not data:
                messagebox.showinfo("Copy", "No symbols to copy.")
                return
                
            lines = ["Symbol	Loss	Qty	Avg Price	Broker"]
            for item in data:
                if isinstance(item, dict):
                    sym = str(item.get("symbol", "")).strip()
                    loss = float(item.get("unrealized_loss", 0.0) or 0.0)
                    qty = item.get("qty", "")
                    avg = float(item.get("avg_price", 0.0) or 0.0)
                    broker = str(item.get("broker", "") or "").strip()
                    cur = str(item.get("currency", "INR") or "INR").upper()
                    from ui_utils import format_money
                    if sym:
                        lines.append(f"{sym}	{format_money(loss, cur)}	{qty}	{format_money(avg, cur)}	{broker}")
                
            if len(lines) == 1:
                messagebox.showinfo("Copy", "No structured symbols to copy.")
                return
                
            text = "\n".join(lines)
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("Copy", f"Copied {len(lines)-1} symbols to clipboard.\n\nPreview:\n" + "\n".join(lines[:3]) + ("\n..." if len(lines) > 4 else ""))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy symbols: {e}")
    def _copy_harvest_symbols(self):
        try:
            data = getattr(self, "_current_harvest_data", [])
            symbols = []
            for item in data:
                if isinstance(item, dict):
                    sym = str(item.get("symbol", "")).strip()
                    if sym:
                        symbols.append(sym)
            
            if not symbols:
                messagebox.showinfo("Copy", "No symbols to copy.")
                return
                
            text = ", ".join(symbols)
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("Copy", f"Copied {len(symbols)} symbols to clipboard.\n\n{text}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy symbols: {e}")