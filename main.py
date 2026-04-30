#!/usr/bin/env python3
"""
PTracker - Portfolio Tracker
Modern Tkinter Implementation with Premium Aesthetic
"""

import tkinter as tk
from tkinter import ttk
import sys
import os
import threading
from pathlib import Path
from typing import Dict, Callable
import atexit

from model.state import AppState
from PIL import Image, ImageTk
from model.database import initialize_database, close_all_connections
from ui_theme import ModernStyle
from ui_widgets import ModernButton, ModernCard
from ui_utils import center_window

def _install_macos_openpanel_stderr_filter() -> None:
    if sys.platform != "darwin":
        return

    try:
        original = sys.stderr
    except Exception:
        return

    needle_1 = "The class 'NSOpenPanel' overrides the method identifier"
    needle_2 = "This method is implemented by class 'NSWindow'"

    class _FilteredStderr:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self._buf = ""

        def write(self, s):
            try:
                text = str(s)
            except Exception:
                return 0

            self._buf += text
            if "\n" not in self._buf:
                return len(text)

            lines = self._buf.splitlines(True)
            self._buf = "" if lines[-1].endswith("\n") else lines.pop()  # keep partial

            out = []
            for line in lines:
                if needle_1 in line and needle_2 in line:
                    continue
                out.append(line)

            if out:
                try:
                    return self._wrapped.write("".join(out))
                except Exception:
                    return len(text)
            return len(text)

        def flush(self):
            try:
                if self._buf:
                    # If there is a partial line, pass it through.
                    self._wrapped.write(self._buf)
                    self._buf = ""
            except Exception:
                pass
            try:
                self._wrapped.flush()
            except Exception:
                pass

        def isatty(self):
            try:
                return self._wrapped.isatty()
            except Exception:
                return False

    try:
        sys.stderr = _FilteredStderr(original)
    except Exception:
        pass


class ViewManager:
    def __init__(self, container: tk.Frame, app_state=None):
        self.container = container
        self.app_state = app_state
        self.views: Dict[str, tk.Frame] = {}
        self.current_view: str = None
        self.view_classes: Dict[str, type] = {}
        self._fade_id = None
    
    def register_view(self, name: str, view_class: type):
        """Register a view class for lazy loading."""
        self.view_classes[name] = view_class
    
    def show_view(self, name: str):
        """Show a view with a subtle fade-in transition."""
        if name not in self.views:
            view_class = self.view_classes.get(name)
            if not view_class:
                raise ValueError(f"View {name} not registered")
            try:
                self.views[name] = view_class(self.container, app_state=self.app_state)
            except TypeError:
                self.views[name] = view_class(self.container)
        
        # Hide current view
        if self.current_view and self.current_view in self.views:
            self.views[self.current_view].pack_forget()
            if hasattr(self.views[self.current_view], 'on_hide'):
                self.views[self.current_view].on_hide()
        
        # Show new view with fade-in
        new_view = self.views[name]
        new_view.pack(fill=tk.BOTH, expand=True)
        self.current_view = name
        
        # Fade-in animation: brief opacity ramp via alpha (works on toplevel approach)
        # For frames we simulate with a quick overlay fade
        self._fade_in_view(new_view)
        
        if hasattr(new_view, 'on_show'):
            new_view.on_show()
        
        try:
            root = self.container.winfo_toplevel()
            root.update_idletasks()
            root.update()
        except Exception:
            pass

    def _fade_in_view(self, view):
        """Simulate a subtle fade-in by briefly showing a translucent overlay that dissolves."""
        if self._fade_id:
            try: self.container.after_cancel(self._fade_id)
            except Exception: pass
            self._fade_id = None
        try:
            overlay = tk.Frame(self.container, bg=ModernStyle.BG_PRIMARY)
            overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            overlay.lift()
            # Dissolve in 3 quick steps
            def _step(n=0):
                if n >= 3:
                    overlay.destroy()
                    self._fade_id = None
                    return
                # Progressively lower the overlay so the view shows through
                try:
                    overlay.lower(view)
                    overlay.destroy()
                except Exception: pass
                self._fade_id = None
            self._fade_id = self.container.after(60, lambda: _step(0))
        except Exception:
            pass


class ModernFrame(tk.Frame):
    def __init__(self, parent, bg: str = ModernStyle.BG_SECONDARY, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)


class Sidebar(tk.Frame):
    def __init__(self, parent, on_navigate: Callable):
        # "Institutional Pro Soft" (Lighter Slate & Gold)
        self.sidebar_bg = "#1E293B"       # Soft Slate Blue
        self.accent_primary = "#D4AF37"   # Muted Elegant Gold
        self.accent_hover = "#334155"     # Lighter Slate Hover
        self.accent_pressed = "#475569"   # Even lighter pressing shade
        self.accent_gradient = "#334155"  # Lighter contrast for the active card
        
        super().__init__(parent, bg=self.sidebar_bg, width=248)
        self.pack(side=tk.LEFT, fill=tk.Y)
        self.pack_propagate(False)
        
        self.on_navigate = on_navigate
        self.buttons = {}
        self._indicators: dict[int, tk.Frame] = {}
        self._icons: dict[str, tk.PhotoImage] = {}
        self._active_idx: int | None = None
        self._nav_labels: dict[int, str] = {}
        self._nav_has_icon: dict[int, bool] = {}
        self._collapsed = False

        # Animated sliding indicator
        self._sliding_indicator = tk.Frame(self, bg=self.accent_primary, width=4)
        self._anim_id = None
        self._current_indicator_y = 0.0

        # Size tokens
        self._w_expanded = 240
        self._w_collapsed = 78
        self._btn_w_expanded = 200
        self._btn_w_collapsed = 52
        
        # Header container - stacked vertically (Top Row, then Logo)
        self._header_container = tk.Frame(self, bg=self.sidebar_bg)
        self._header_container.pack(fill=tk.X, padx=16, pady=(16, 16))

        # TOP ROW: Toggle Button + Title + PRO Badge
        top_row = tk.Frame(self._header_container, bg=self.sidebar_bg)
        top_row.pack(fill=tk.X)

        # Refined toggle button at the top left
        self._toggle_btn = ModernButton(
            top_row,
            text="☰",
            command=self.toggle,
            invoke_on_press=True,
            bg=self.sidebar_bg,
            fg=self.accent_primary,
            canvas_bg=self.sidebar_bg,
            width=32,
            height=32,
            radius=6,
            font=ModernStyle.FONT_TITLE,
        )
        self._toggle_btn.set_palette(
            bg=self.sidebar_bg,
            fg=self.accent_primary,
            hover_bg=self.accent_hover,
            pressed_bg=self.accent_pressed
        )
        self._toggle_btn.pack(side=tk.LEFT)

        # Title + Badge stack
        title_stack = tk.Frame(top_row, bg=self.sidebar_bg)
        title_stack.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))
        
        # Centering the title vertically next to the 32px button
        title_badge_row = tk.Frame(title_stack, bg=self.sidebar_bg)
        title_badge_row.pack(expand=True, anchor="w")

        self._title_lbl = tk.Label(
            title_badge_row,
            text="PTracker",
            font=ModernStyle.FONT_SIDEBAR_TITLE,
            bg=self.sidebar_bg,
            fg=ModernStyle.TEXT_ON_ACCENT,
            anchor="w",
        )
        self._title_lbl.pack(side=tk.LEFT)
        
        # PRO / Version Badge
        badge_frame = tk.Frame(title_badge_row, bg=ModernStyle.ACCENT_TERTIARY_PALE, padx=5, pady=2)
        badge_frame.pack(side=tk.LEFT, padx=(8, 0), pady=(3, 0))
        tk.Label(
            badge_frame, text="PRO", 
            font=ModernStyle.FONT_SIDEBAR_BADGE,
            bg=ModernStyle.ACCENT_TERTIARY_PALE, fg=ModernStyle.ACCENT_TERTIARY
        ).pack()

        # LOGO ROW: Logo below with spacing
        self._logo_container = tk.Frame(self._header_container, bg=self.sidebar_bg)
        self._logo_container.pack(fill=tk.X, pady=(14, 0))

        try:
            logo_path = Path(__file__).resolve().parent / "assets" / "images" / "logo.png"
            if logo_path.exists():
                from PIL import ImageEnhance, ImageDraw
                
                pil_img = Image.open(logo_path).convert("RGBA")
                
                # Use a medium size (64px) for a balanced sidebar look
                base_size = 64
                pil_img = pil_img.resize((base_size, base_size), Image.Resampling.LANCZOS)
                
                # Make it even "brighter" and more vibrant
                enhancer = ImageEnhance.Brightness(pil_img)
                pil_img = enhancer.enhance(1.1)
                contrast = ImageEnhance.Contrast(pil_img)
                pil_img = contrast.enhance(1.1)
                
                # Apply rounded corners (macOS icon style)
                mask = Image.new('L', (base_size, base_size), 0)
                draw = ImageDraw.Draw(mask)
                draw.rounded_rectangle((0, 0, base_size, base_size), radius=14, fill=255)
                
                rounded_img = Image.new('RGBA', (base_size, base_size), (0, 0, 0, 0))
                rounded_img.paste(pil_img, (0, 0), mask=mask)
                
                # Draw a sleek gold border to cleanly frame the logo against the sidebar background
                border_draw = ImageDraw.Draw(rounded_img)
                border_draw.rounded_rectangle((1, 1, base_size-2, base_size-2), radius=14, outline=self.accent_primary, width=2)
                
                pil_img = rounded_img
                
                self._logo_img = ImageTk.PhotoImage(pil_img)
                self._logo_lbl = tk.Label(
                    self._logo_container,
                    image=self._logo_img,
                    bg=self.sidebar_bg,
                )
                # Centered alignment for the oversized logo
                self._logo_lbl.pack(pady=(5, 0))
        except Exception as e:
            print(f"Logo load error: {e}")
        
        # ── Status Badge (below logo) ──────────────────────────────
        self._status_badge = tk.Label(
            self._header_container, text="⏳ Syncing…",
            bg=self.sidebar_bg, fg=ModernStyle.SLATE_400,
            font=ModernStyle.FONT_TINY, anchor="center",
        )
        self._status_badge.pack(fill=tk.X, pady=(6, 0))
        self.after(3000, self._refresh_status_badge)

        # ── Portfolio Summary Card ─────────────────────────────────
        _card_bg = "#253347"
        self._summary_card = tk.Frame(self, bg=_card_bg, highlightbackground=self.accent_primary, highlightthickness=1)
        self._summary_card.pack(fill=tk.X, padx=16, pady=(4, 8))
        self._summary_value_lbl = tk.Label(self._summary_card, text="₹ —", bg=_card_bg, fg="#FFFFFF", font=(ModernStyle.FONT_FAMILY, 18, "bold"), anchor="w")
        self._summary_value_lbl.pack(fill=tk.X, padx=12, pady=(10, 2))
        _srow = tk.Frame(self._summary_card, bg=_card_bg)
        _srow.pack(fill=tk.X, padx=12, pady=(0, 10))
        self._summary_pnl_lbl = tk.Label(_srow, text="P&L: —", bg=_card_bg, fg=ModernStyle.SUCCESS, font=ModernStyle.FONT_SMALL_BOLD, anchor="w")
        self._summary_pnl_lbl.pack(side=tk.LEFT)
        self._summary_count_lbl = tk.Label(_srow, text="0 holdings", bg=_card_bg, fg=ModernStyle.SLATE_400, font=ModernStyle.FONT_SMALL, anchor="e")
        self._summary_count_lbl.pack(side=tk.RIGHT)
        self.after(2000, self._refresh_summary_card)

        # ── Gold Separator ─────────────────────────────────────────
        glow_frame = tk.Frame(self, bg=self.sidebar_bg)
        glow_frame.pack(fill=tk.X, padx=16, pady=(4, 8))
        tk.Frame(glow_frame, bg=self.accent_primary, height=1).pack(fill=tk.X)

        # ── Navigation Section Label ───────────────────────────────
        self._menu_lbl = tk.Label(
            self, text="N A V I G A T I O N",
            font=ModernStyle.FONT_SMALL_BOLD,
            bg=self.sidebar_bg, fg=self.accent_primary, anchor="w",
        )
        self._menu_lbl.pack(fill=tk.X, padx=20, pady=(0, 8))

        # ── Navigation Items with Group Dividers ───────────────────
        nav_items = [
            ("📊  Dashboard",    0),
            ("🌟  My Holdings",  1),
            ("🌀  Trade Entry",  2),
            ("🧬  Trade History", 3),
            ("✨  Tax Report",   4),
            ("👁  Watchlist",    5),
            ("💠  Valuation",    6),
            ("🛡️  Settings",     7),
            ("🔅  Help",         8),
        ]
        self._nav_labels = {idx: label for (label, idx) in nav_items}
        _divider_after = {3, 6}  # Core | Analysis | System
        for label, idx in nav_items:
            self._add_nav_button(label, idx)
            if idx in _divider_after:
                tk.Frame(self, bg=ModernStyle.SLATE_700, height=1).pack(fill=tk.X, padx=28, pady=(4, 4))

        # ── Quit — muted text, thin separator above ────────────────
        self._quit_sep = tk.Frame(self, bg=ModernStyle.SLATE_700, height=1)
        self._quit_sep.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(0, 6))
        exit_btn = tk.Label(self, text="⏻  Quit PTracker", bg=self.sidebar_bg, fg="#FCA5A5", font=ModernStyle.FONT_BODY_BOLD, cursor="hand2", anchor="center")
        exit_btn.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(0, 12))
        exit_btn.bind("<Button-1>", lambda e: parent.quit())
        exit_btn.bind("<Enter>", lambda e: exit_btn.configure(fg="#EF4444"))
        exit_btn.bind("<Leave>", lambda e: exit_btn.configure(fg="#FCA5A5"))
        self._exit_btn = exit_btn
        
        # ── Mini Market Tickers ──
        self._ticker_frame = tk.Frame(self, bg=self.sidebar_bg)
        self._ticker_labels = {}

        tk.Label(
            self._ticker_frame, text="MARKETS [Live]", 
            font=ModernStyle.FONT_BODY_BOLD,
            bg=self.sidebar_bg, fg=self.accent_primary, anchor="w"
        ).pack(fill=tk.X, padx=20, pady=(0, 0))
        
        tk.Frame(self._ticker_frame, bg=ModernStyle.DIVIDER_COLOR, height=1).pack(fill=tk.X, padx=16, pady=(0, 6))
        
        self._ticker_time_lbl = tk.Label(
            self._ticker_frame, text="⚡ Last Updated: —", 
            font=(ModernStyle.FONT_FAMILY, 12, "bold italic"),
            bg=self.sidebar_bg, fg="yellow", anchor="w"
        )
        self._ticker_time_lbl.pack(fill=tk.X, padx=20, pady=(0, 4))
        
        self.tickers_container = tk.Frame(self._ticker_frame, bg=self.sidebar_bg)
        self.tickers_container.pack(fill=tk.X, padx=20, pady=(0, 6))
        
        # We will populate the tickers dynamically after a background fetch
        import model.tickers as tck
        self._ticker_frame.pack(side=tk.BOTTOM, fill=tk.X)
        # Show Loading... immediately, then trigger a one-time background fetch
        self._show_ticker_loading()
        tck.refresh_mini_tickers(callback=self._on_tickers_fetched)
        
        # Spacer with sidebar background (takes remaining space)
        tk.Frame(self, bg=self.sidebar_bg).pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    def set_active(self, idx: int) -> None:
        self._active_idx = idx
        target_y = None

        for i, btn in self.buttons.items():
            if i == idx:
                target_y = btn.master.winfo_y() + btn.winfo_y()
                # Keep active button interactive but visually distinct
                btn.set_disabled(False)
                btn.set_palette(
                    bg=self.accent_gradient,  # Use gradient base instead of solid primary
                    fg="#ffffff",
                    hover_bg=self.accent_primary,
                    pressed_bg=self.accent_primary,
                )
            else:
                btn.set_disabled(False)
                btn.set_palette(
                    bg=self.sidebar_bg,  # fallback to match background
                    fg="#E2E8F0",        # Bright crisp text
                    hover_bg=self.accent_hover,
                    pressed_bg=self.accent_pressed,
                )
                
        if target_y is not None and not self._collapsed:
            self._animate_indicator(target_y)

    def _animate_indicator(self, target_y: float) -> None:
        if self._anim_id:
            self.after_cancel(self._anim_id)
        
        # If it's the first time displaying, snap instantly
        if not self._sliding_indicator.winfo_ismapped():
            self._current_indicator_y = target_y
            self._sliding_indicator.place(x=0, y=int(self._current_indicator_y), width=4, height=46)
            return

        def _step():
            dy = target_y - self._current_indicator_y
            if abs(dy) < 1.0:
                self._current_indicator_y = target_y
                self._sliding_indicator.place(y=int(self._current_indicator_y))
                self._anim_id = None
                return
                
            # Smooth spring physics easing
            self._current_indicator_y += dy * 0.25
            self._sliding_indicator.place(y=int(self._current_indicator_y))
            self._anim_id = self.after(16, _step)

        _step()

    def _try_load_icon(self, label: str, filename: str, *, subsample: int = 1) -> None:
        try:
            if getattr(sys, 'frozen', False):
                base = Path(sys._MEIPASS) / "assets" / "icons"
            else:
                base = Path(__file__).resolve().parent / "assets" / "icons"
            
            path = base / filename
            if not path.exists():
                return
            
            # Use PIL for better PNG support
            pil_img = Image.open(path)
            
            # Force resize icons to standard 24x24 pixels so they fit cleanly in the UI
            pil_img = pil_img.resize((24, 24), Image.Resampling.LANCZOS)
            
            self._icons[label] = ImageTk.PhotoImage(pil_img)
        except Exception as e:
            print(f"Icon load error ({label}): {e}")
            return
    
    def _add_nav_button(self, label: str, idx: int):
        # We need relative positioning to be reliable, so anchor rows properly.
        row = tk.Frame(self, bg=self.sidebar_bg)
        row.pack(fill=tk.X, padx=(12, 16), pady=3)

        icon = self._icons.get(label)
        self._nav_has_icon[idx] = bool(icon)
        btn = ModernButton(
            row,
            text=label,
            command=lambda: self.on_navigate(idx),
            invoke_on_press=True,
            icon=icon,
            bg=self.sidebar_bg,
            fg="#E2E8F0",  # Bright crisp text
            canvas_bg=self.sidebar_bg,
            width=self._btn_w_expanded,
            height=46,
            radius=8,
            font=ModernStyle.FONT_HEADING,
            text_anchor="w",
            text_padx=14,
        )
        btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.buttons[idx] = btn

    def toggle(self) -> None:
        """Collapse/expand the sidebar."""
        self._collapsed = not bool(self._collapsed)

        # Emoji abbreviations used when sidebar is collapsed (no PNG icons)
        abbr = {
            0: "📊",
            1: "💼",
            2: "➕",
            3: "🧬",
            4: "📄",
            5: "👁",
            6: "💠",
            7: "⚙️",
            8: "🔅",
        }

        if self._collapsed:
            self.configure(width=self._w_collapsed)
            self._sliding_indicator.place_forget()
            if self._anim_id:
                self.after_cancel(self._anim_id)
                self._anim_id = None
                
            try: self._title_stack.pack_forget()
            except Exception: pass
            try: self._menu_lbl.pack_forget()
            except Exception: pass
            try: self._summary_card.pack_forget()
            except Exception: pass
            try: self._status_badge.pack_forget()
            except Exception: pass
            try: self._toggle_btn.set_text("→")
            except Exception: pass

            for idx, btn in self.buttons.items():
                try:
                    if self._nav_has_icon.get(idx, False):
                        btn.set_text("")
                    else:
                        btn.set_text(abbr.get(idx, ""))
                    btn.set_size(width=self._btn_w_collapsed)
                except Exception:
                    pass

            try: self._exit_btn.configure(text="⏻")
            except Exception: pass
        else:
            self.configure(width=self._w_expanded)
            try:
                self._title_stack.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
            except Exception:
                pass
            try:
                self._menu_lbl.pack(fill=tk.X, padx=16, pady=(6, 8))
            except Exception:
                pass
            try:
                self._toggle_btn.set_text("≡")
            except Exception:
                pass

            for idx, btn in self.buttons.items():
                try:
                    btn.set_text(self._nav_labels.get(idx, ""))
                    btn.set_size(width=self._btn_w_expanded)
                except Exception:
                    pass

            try: self._exit_btn.configure(text="⏻  Quit PTracker")
            except Exception: pass

        # Ensure active styling remains correct.
        try:
            if self._active_idx is not None and str(self._active_idx) in str(self.buttons.keys()):
                # Re-check placement when re-expanding since coords might shift slightly
                self.after(50, lambda: self.set_active(self._active_idx))
        except Exception:
            pass

    def _refresh_summary_card(self):
        """Fetch portfolio totals and update the summary card."""
        def _bg():
            try:
                from model.database import db_session
                with db_session() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*), SUM(qty * avg_price), SUM(running_pnl) FROM holdings WHERE qty > 0")
                    row = cur.fetchone()
                    count, invested, pnl = int(row[0] or 0), float(row[1] or 0), float(row[2] or 0)
                self.after(0, lambda: self._update_summary_ui(count, invested, pnl))
            except Exception: pass
        import threading
        threading.Thread(target=_bg, daemon=True).start()

    def _update_summary_ui(self, count, invested, pnl):
        try:
            self._summary_value_lbl.configure(text=f"₹{invested:,.0f}")
            color = ModernStyle.SUCCESS if pnl >= 0 else "#FCA5A5"
            arrow = "▲" if pnl >= 0 else "▼"
            self._summary_pnl_lbl.configure(text=f"{arrow} P&L: ₹{pnl:,.0f}", fg=color)
            self._summary_count_lbl.configure(text=f"{count} holdings")
        except Exception: pass

    def _refresh_status_badge(self):
        """Fetch last sync time and update the status badge."""
        def _bg():
            try:
                from model.database import db_session
                from datetime import datetime
                with db_session() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM holdings WHERE qty > 0")
                    count = cur.fetchone()[0]
                    cur.execute("SELECT MAX(last_updated) FROM marketdata")
                    last_ts = cur.fetchone()[0]
                time_str = "Unknown"
                if last_ts:
                    try:
                        dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
                        diff = int((datetime.now() - dt).total_seconds() / 60)
                        if diff < 1: time_str = "Just now"
                        elif diff < 60: time_str = f"{diff}m ago"
                        else: time_str = f"{diff // 60}h ago"
                    except Exception: pass
                self.after(0, lambda: self._status_badge.configure(text=f"🟢 {count} active · Synced {time_str}", fg=ModernStyle.SLATE_300))
            except Exception: pass
        import threading
        threading.Thread(target=_bg, daemon=True).start()

    def _show_ticker_loading(self):
        """Show the Loading... placeholder before data arrives."""
        for w in self.tickers_container.winfo_children():
            w.destroy()
        tk.Label(self.tickers_container, text="Loading...", bg=self.sidebar_bg, fg=ModernStyle.TEXT_ON_ACCENT, font=ModernStyle.FONT_SMALL).pack(anchor="w")
    
    def _on_tickers_fetched(self):
        """Callback invoked from background thread when tickers are ready."""
        # Use after(0, ...) to safely update Tkinter from the background thread.
        try:
            self.after(0, self._render_tickers)
        except Exception:
            pass

    def _render_tickers(self):
        """Redraw the ticker labels using cached data."""
        import model.tickers as tck
        from datetime import datetime
        
        try:
            self._ticker_time_lbl.config(text=f"⚡ Last Updated : {datetime.now().strftime('%H:%M:%S')}")
        except Exception:
            pass
        
        if self._collapsed:
            return
        if not self._ticker_frame.winfo_ismapped():
            self._ticker_frame.pack(side=tk.BOTTOM, fill=tk.X, after=self._exit_btn)

        data = tck.get_mini_tickers()
        
        for w in self.tickers_container.winfo_children():
            w.destroy()
            
        if not data:
            tk.Label(self.tickers_container, text="No data", bg=self.sidebar_bg, fg=ModernStyle.TEXT_ON_ACCENT, font=ModernStyle.FONT_SMALL).pack(anchor="w")
        else:
            for name, info in data.items():
                row = tk.Frame(self.tickers_container, bg=self.sidebar_bg)
                row.pack(fill=tk.X, pady=1)
                
                tk.Label(row, text=name, bg=self.sidebar_bg, fg=ModernStyle.TEXT_ON_ACCENT, font=ModernStyle.FONT_SUBHEADING).pack(side=tk.LEFT)
                
                pct = info.get("pct", 0.0)
                cp = info.get("price", 0.0)
                
                color = ModernStyle.SUCCESS if pct >= 0 else ModernStyle.BRAND_GOLD
                arrow = "▲" if pct >= 0 else "▼"
                
                if "USD" in name:
                    val_str = f"{cp:.2f}"
                else:
                    val_str = f"{cp:,.3f}"
                    
                tk.Label(row, text=f"{val_str} {arrow}{abs(pct):.1f}%", bg=self.sidebar_bg, fg=color, font=ModernStyle.FONT_TICKER).pack(side=tk.RIGHT)

    def refresh_tickers(self):
        """Trigger a fresh background fetch, then re-render. Called by the Dashboard Refresh button."""
        import model.tickers as tck
        self._show_ticker_loading()
        tck.refresh_mini_tickers(callback=self._on_tickers_fetched)

class PTrackerApp:
    """Main application controller."""
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PTracker - Portfolio Tracker")
        
        # Dynamic sizing based on screen dimensions
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        
        target_w = min(1700, int(screen_w * 0.95))
        target_h = min(1150, int(screen_h * 0.90))
        self.root.geometry(f"{target_w}x{target_h}")
        
        # If the screen is small, start maximized
        if screen_w <= 1366 or screen_h <= 768:
            try:
                if sys.platform == "win32":
                    self.root.state('zoomed')
                else:
                    self.root.attributes('-zoomed', True)
            except Exception:
                pass

        # Center on screen after initial sizing
        try:
            center_window(self.root)
        except Exception:
            pass

        # Optional: PNG app icon (place it at `assets/app_icon.png`)
        self._app_icon: tk.PhotoImage | None = None
        self._set_app_icon()
        
        # Apply theme
        ModernStyle.apply_theme(root)
        
        # Initialize database
        from model.database import initialize_database, ensure_marketdata_schema, ensure_watchlist_schema
        initialize_database()
        ensure_marketdata_schema()
        ensure_watchlist_schema()
        
        # Store for cleanup
        atexit.register(lambda: close_all_connections(optimize=False))
        
        # Create app state
        self.app_state = AppState(root)
        try:
            self.app_state.refresh_data_cache_async()
        except Exception as e:
            print(f"Warning: Could not initialize data cache: {e}")
        
        # ── Status Bar (Bottom) ─────────────────────────────────────────────
        self.status_bar_frame = tk.Frame(root, bg=ModernStyle.BG_TERTIARY, height=28)
        self.status_bar_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_bar_frame.pack_propagate(False)
        tk.Frame(self.status_bar_frame, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", side=tk.TOP)
        self.status_lbl = tk.Label(
            self.status_bar_frame, 
            text="🟢 Starting up...", 
            fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_TERTIARY, 
            font=ModernStyle.FONT_SMALL
        )
        self.status_lbl.pack(side=tk.LEFT, padx=16)

        # Market open/close indicator
        self._market_status_lbl = tk.Label(
            self.status_bar_frame, text="",
            fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_TERTIARY,
            font=ModernStyle.FONT_SMALL
        )
        self._market_status_lbl.pack(side=tk.LEFT, padx=(8, 0))

        # Version label (far right)
        tk.Label(
            self.status_bar_frame, text="v2.0 PRO",
            fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_TERTIARY,
            font=ModernStyle.FONT_TINY
        ).pack(side=tk.RIGHT, padx=16)

        # Main container
        main_frame = ModernFrame(root, bg=ModernStyle.BG_PRIMARY)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Sidebar
        self.sidebar = Sidebar(main_frame, self.navigate)
        
        # Content area
        self.content_frame = ModernFrame(main_frame, bg=ModernStyle.BG_PRIMARY)
        self.content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # View manager (with app_state)
        self.view_manager = ViewManager(self.content_frame, app_state=self.app_state)
        
        # Initialize views (import them here to avoid circular imports)
        self._setup_views()
        
        # Show first view
        self.navigate(0)

        # Expose app on root window so views can find ViewManager via winfo_toplevel()
        try:
            self.root._ptracker_app = self
        except Exception:
            pass

        # Start background tasks
        self._start_auto_refresh()
        self._update_status_loop()

    def _update_status_loop(self):
        """Periodically update the bottom status bar."""
        try:
            from model.database import db_session
            from model.engine import get_dashboard_metrics
            import time
            from datetime import datetime

            metrics = get_dashboard_metrics(force_refresh=False)
            val = metrics.get('total_value', 0.0)
            
            with db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT count(1) FROM holdings WHERE qty > 0")
                count = cur.fetchone()[0]
                cur.execute("SELECT max(last_updated) FROM marketdata")
                last_ts = cur.fetchone()[0]

            time_str = "Unknown"
            if last_ts:
                try:
                    dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
                    diff = int((datetime.now() - dt).total_seconds() / 60)
                    if diff < 1:
                        time_str = "Just now"
                    elif diff < 60:
                        time_str = f"{diff} min ago"
                    else:
                        time_str = f"{diff // 60} hrs ago"
                except Exception:
                    pass

            self.status_lbl.config(
                text=f"🟢 Last updated: {time_str}   |   📦 {count} active holdings   |   💰 ₹{val:,.2f} portfolio value"
            )

            # Market open/close status (NSE: IST 9:15 AM - 3:30 PM, Mon-Fri)
            try:
                from datetime import timezone, timedelta
                ist = timezone(timedelta(hours=5, minutes=30))
                now_ist = datetime.now(ist)
                weekday = now_ist.weekday()  # 0=Mon, 6=Sun
                t_min = now_ist.hour * 60 + now_ist.minute
                if weekday < 5 and 555 <= t_min <= 930:  # 9:15 - 15:30
                    self._market_status_lbl.config(text="│  🟢 NSE Open", fg=ModernStyle.SUCCESS)
                elif weekday < 5 and 540 <= t_min < 555:  # 9:00 - 9:15
                    self._market_status_lbl.config(text="│  🟡 NSE Pre-Market", fg=ModernStyle.WARNING)
                else:
                    self._market_status_lbl.config(text="│  🔴 NSE Closed", fg=ModernStyle.TEXT_TERTIARY)
            except Exception:
                pass
        except Exception:
            pass
        
        # Re-run every 15 seconds
        self.root.after(15000, self._update_status_loop)

    def _start_auto_refresh(self) -> None:
        def _silent_refresh():
            import threading
            def _bg():
                try:
                    from model.database import db_session
                    from model.engine import fetch_and_update_market_data, rebuild_holdings
                    # 1. Fetch live market prices for owned holdings
                    with db_session() as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT DISTINCT symbol FROM holdings WHERE qty > 0")
                        symbols = [r[0] for r in cur.fetchall()]
                    if symbols:
                        fetch_and_update_market_data(symbols)
                    
                    # 2. Re-compute running PnL, holdings
                    rebuild_holdings(sync_trade_calcs=False)
                    
                    # 3. Reload cache in memory
                    if getattr(self, "app_state", None):
                        self.app_state.refresh_data_cache()
                        
                    # 4. Refresh sidebar tickers silently - use .after(0) for thread safety
                    try:
                        if hasattr(self, "sidebar"):
                            self.root.after(0, self.sidebar.refresh_tickers)
                    except Exception:
                        pass
                    
                    # 5. Tell views to visually reload safely on main thread
                    self.root.after(0, _update_ui)
                except Exception as e:
                    print(f"Silent auto-refresh failed: {e}")

            def _update_ui():
                if not hasattr(self, "view_manager"): return
                for name, v in self.view_manager.views.items():
                    try:
                        v._data_loaded = False
                        if self.view_manager.current_view == name and hasattr(v, "load_data"):
                            v.load_data()
                    except Exception:
                        pass

            threading.Thread(target=_bg, daemon=True).start()
            self.root.after(900000, _silent_refresh)

        # Kickoff after 45 seconds (45,000 ms) instead of waiting 15 mins for first run
        self.root.after(45000, _silent_refresh)

    def _set_app_icon(self) -> None:
        try:
            from pathlib import Path
            import sys
            
            if getattr(sys, 'frozen', False):
                base = Path(sys._MEIPASS) / "assets"
            else:
                base = Path(__file__).resolve().parent / "assets"
            
            candidates = [
                base / "app_icon.png",
                base / "images" / "logo.png",
                base / "icons" / "dashboard.png",
            ]
            
            icon_path = next((p for p in candidates if p.exists()), None)
            if icon_path is None:
                print(f"[ICON] No valid icon file found in candidates. Searched in: {[str(p) for p in candidates]}")
                return
            
            # Use PIL for better PNG support
            pil_img = Image.open(icon_path).convert("RGBA")
            
            # Make the app icon "medium size" and add rounded corners for a native macOS feel
            icon_size = 128
            pil_img = pil_img.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
            
            from PIL import ImageDraw
            mask = Image.new('L', (icon_size, icon_size), 0)
            draw = ImageDraw.Draw(mask)
            # Apple standard corner radius ratio is approx 22.5% of the size
            draw.rounded_rectangle((0, 0, icon_size, icon_size), radius=int(icon_size * 0.225), fill=255)
            
            rounded_img = Image.new('RGBA', (icon_size, icon_size), (0, 0, 0, 0))
            rounded_img.paste(pil_img, (0, 0), mask=mask)
            
            self._app_icon = ImageTk.PhotoImage(rounded_img)
            
            # iconphoto affects window icons on Windows/X11
            try:
                self.root.iconphoto(True, self._app_icon)
            except Exception:
                # Some Tk variants prefer the wm call.
                try:
                    self.root.tk.call("wm", "iconphoto", self.root._w, self._app_icon)  # type: ignore
                except Exception:
                    pass
            
            # macOS specific: setting the Dock icon requires a specific Tk call in some Tk wrapper versions
            if sys.platform == "darwin":
                try:
                    # In newer Tk on Mac, you can sometimes set the dock icon specifically
                    self.root.tk.call("tk::mac::iconBitmap", self.root._w, 128, 128, "-kind", "photo", "-photo", self._app_icon)
                except Exception:
                    pass
        except Exception as e:
            print(f"[ICON] Error setting app icon: {e}")
            self._app_icon = None
    
    def _setup_views(self):
        """Register all views."""
        from views.holdings_view import HoldingsView
        from views.dashboard_view import DashboardView
        from views.trade_entry_view import TradeEntryView
        from views.trade_history_view import TradeHistoryView
        from views.settings_view import SettingsView
        from views.help_view import HelpView
        from views.tax_report_view import TaxReportView
        from views.watchlist_view import WatchlistView
        from views.valuation_view import ValuationView
        
        self.view_manager.register_view('dashboard', DashboardView)
        self.view_manager.register_view('holdings', HoldingsView)
        self.view_manager.register_view('trade_entry', TradeEntryView)
        self.view_manager.register_view('trade_history', TradeHistoryView)
        self.view_manager.register_view('settings', SettingsView)
        self.view_manager.register_view('help', HelpView)
        self.view_manager.register_view('tax', TaxReportView)
        self.view_manager.register_view('watchlist', WatchlistView)
        self.view_manager.register_view('valuation', ValuationView)
    
    def navigate(self, view_idx: int):
        """Navigate to a view by index."""
        views = ['dashboard', 'holdings', 'trade_entry', 'trade_history', 'tax', 'watchlist', 'valuation', 'settings', 'help']
        if 0 <= view_idx < len(views):
            try:
                if hasattr(self, "sidebar") and hasattr(self.sidebar, "set_active"):
                    self.sidebar.set_active(view_idx)
                self.view_manager.show_view(views[view_idx])
            except Exception as e:
                print(f"Error loading view {views[view_idx]}: {e}")

def main():
    """Application entry point."""
    _install_macos_openpanel_stderr_filter()
    
    # Enable High-DPI awareness on Windows before creating the root window
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
            
    root = tk.Tk()
    
    # Cleanup on exit
    def on_closing():
        root.iconify()
    
    def on_reopen():
        root.deiconify()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    # Handle dock icon click on macOS to restore the window
    try:
        root.createcommand('tk::mac::ReopenApplication', on_reopen)
    except Exception:
        pass
    
    app = PTrackerApp(root)
    root.mainloop()

# source .venv/bin/activate
# python3 -m PyInstaller --noconfirm PortfolioTrack.spec

if __name__ == '__main__':
    main()

