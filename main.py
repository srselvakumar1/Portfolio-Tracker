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


# ── Collapsed-mode tooltip helper ─────────────────────────────────────────────
class _NavTooltip:
    """Lightweight tooltip that appears next to the sidebar when collapsed."""

    def __init__(self, widget: tk.Widget, text: str, sidebar_bg: str):
        self._widget = widget
        self._text = text
        self._sidebar_bg = sidebar_bg
        self._win: tk.Toplevel | None = None
        self._after_id: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self._after_id = self._widget.after(500, self._show)

    def _cancel(self):
        if self._after_id:
            try:
                self._widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self, _e=None):
        self._hide()
        try:
            x = self._widget.winfo_rootx() + self._widget.winfo_width() + 4
            y = self._widget.winfo_rooty() + (self._widget.winfo_height() // 2) - 10
            self._win = tk.Toplevel(self._widget)
            self._win.wm_overrideredirect(True)
            self._win.wm_geometry(f"+{x}+{y}")
            self._win.attributes("-topmost", True)
            lbl = tk.Label(
                self._win, text=self._text,
                bg="#1A2740", fg="#E2E8F0",
                font=ModernStyle.FONT_SMALL_BOLD,
                padx=10, pady=5,
                relief="flat",
            )
            lbl.pack()
        except Exception:
            self._win = None

    def _hide(self, _e=None):
        self._cancel()
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None


class Sidebar(tk.Frame):
    def __init__(self, parent, on_navigate: Callable):
        # ── Colour tokens mapped from ModernStyle where possible ──────────────
        self.sidebar_bg     = ModernStyle.SLATE_800      # "#1E293B"
        self.accent_primary = ModernStyle.BRAND_GOLD     # "#D4AF37"
        self.accent_hover   = ModernStyle.SLATE_700      # "#334155"
        self.accent_pressed = ModernStyle.SLATE_600      # "#475569"
        self.accent_gradient = ModernStyle.SLATE_700     # "#334155"

        super().__init__(parent, bg=self.sidebar_bg, width=248)
        self.pack(side=tk.LEFT, fill=tk.Y)
        self.pack_propagate(False)

        # Subtle right border for depth
        tk.Frame(self, bg="#0F172A", width=1).pack(side=tk.RIGHT, fill=tk.Y)

        self.on_navigate = on_navigate
        self.buttons = {}
        self._indicators: dict[int, tk.Frame] = {}
        self._icons: dict[str, tk.PhotoImage] = {}
        self._active_idx: int | None = None
        self._nav_labels: dict[int, str] = {}
        self._nav_has_icon: dict[int, bool] = {}
        self._collapsed = False
        self._tooltips: list[_NavTooltip] = []   # keep references alive

        # Animated sliding indicator (Pill-shaped)
        self._sliding_indicator = tk.Canvas(self, bg=self.sidebar_bg, width=4, highlightthickness=0)
        self._sliding_indicator_id = self._sliding_indicator.create_line(
            2, 4, 2, 42, fill=self.accent_primary, width=4, capstyle=tk.ROUND
        )
        self._anim_id = None
        self._current_indicator_y = 0.0

        # Size tokens
        self._w_expanded  = 240
        self._w_collapsed = 78
        self._btn_w_expanded  = 200
        self._btn_w_collapsed = 52

        # ── Header container ──────────────────────────────────────────────────
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

        # Title + Badge stack (save ref so toggle can hide/show it)
        self._title_stack = tk.Frame(top_row, bg=self.sidebar_bg)
        self._title_stack.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0))

        title_badge_row = tk.Frame(self._title_stack, bg=self.sidebar_bg)
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

        # LOGO ROW
        self._logo_container = tk.Frame(self._header_container, bg=self.sidebar_bg)
        self._logo_container.pack(fill=tk.X, pady=(14, 0))

        try:
            import sys
            from pathlib import Path
            logo_path = Path(__file__).resolve().parent / "assets" / "images" / "logo.png"
            if logo_path.exists():
                from PIL import Image, ImageTk, ImageEnhance, ImageDraw

                pil_img = Image.open(logo_path).convert("RGBA")
                base_size = 64
                pil_img = pil_img.resize((base_size, base_size), Image.Resampling.LANCZOS)

                enhancer = ImageEnhance.Brightness(pil_img)
                pil_img = enhancer.enhance(1.1)
                contrast = ImageEnhance.Contrast(pil_img)
                pil_img = contrast.enhance(1.1)

                mask = Image.new('L', (base_size, base_size), 0)
                draw = ImageDraw.Draw(mask)
                draw.rounded_rectangle((0, 0, base_size, base_size), radius=14, fill=255)

                rounded_img = Image.new('RGBA', (base_size, base_size), (0, 0, 0, 0))
                rounded_img.paste(pil_img, (0, 0), mask=mask)

                border_draw = ImageDraw.Draw(rounded_img)
                border_draw.rounded_rectangle((1, 1, base_size-2, base_size-2), radius=14, outline=self.accent_primary, width=2)

                pil_img = rounded_img

                self._logo_img = ImageTk.PhotoImage(pil_img)
                self._logo_lbl = tk.Label(
                    self._logo_container,
                    image=self._logo_img,
                    bg=self.sidebar_bg,
                )
                self._logo_lbl.pack(pady=(5, 0))
        except Exception as e:
            print(f"Logo load error: {e}")

        # ── Pulsing Live Status Dot ───────────────────────────────────────────
        self._status_row = tk.Frame(self._header_container, bg=self.sidebar_bg)
        self._status_row.pack(fill=tk.X, pady=(6, 0))

        self._pulse_canvas = tk.Canvas(
            self._status_row, width=14, height=14,
            bg=self.sidebar_bg, highlightthickness=0, bd=0,
        )
        self._pulse_canvas.pack(side=tk.LEFT, padx=(0, 6))
        self._pulse_glow = self._pulse_canvas.create_oval(
            1, 1, 13, 13, fill="", outline="#16A34A", width=2
        )
        self._pulse_dot = self._pulse_canvas.create_oval(
            4, 4, 10, 10, fill="#16A34A", outline=""
        )
        self._pulse_phase = 0
        self._pulse_anim_id = None

        self._status_badge = tk.Label(
            self._status_row, text="⏳ Syncing…",
            bg=self.sidebar_bg, fg=ModernStyle.SLATE_400,
            font=ModernStyle.FONT_TINY, anchor="w",
        )
        self._status_badge.pack(side=tk.LEFT, fill=tk.X)

        self.after(100, self._refresh_status_badge)
        self.after(100, self._pulse_step)

        # ── Portfolio Summary Card ────────────────────────────────────────────
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

        # ── Navigation Section Label ──────────────────────────────────────────
        self._nav_header = tk.Frame(self, bg=self.sidebar_bg)
        self._nav_header.pack(fill=tk.X, padx=16, pady=(10, 0))

        self._menu_lbl = tk.Label(
            self._nav_header, text="N A V I G A T I O N",
            font=ModernStyle.FONT_SMALL_BOLD,
            bg=self.sidebar_bg, fg=self.accent_primary, anchor="w",
        )
        self._menu_lbl.pack(fill=tk.X)

        # Gold Separator — placed before the first nav button (Dashboard)
        self._nav_gold_sep = tk.Frame(self, bg=self.sidebar_bg)
        self._nav_gold_sep.pack(fill=tk.X, padx=16, pady=(4, 2))
        tk.Frame(self._nav_gold_sep, bg=self.accent_primary, height=1).pack(fill=tk.X)

        # ── Navigation Items ──────────────────────────────────────────────────
        nav_items = [
            ("🌐  Dashboard",    0),
            ("💼  My Holdings",  1),
            ("💹  Trade Entry",  2),
            ("🕒  Trade History", 3),
            ("🧾  Tax Report",   4),
            ("👁  Watchlist",    5),
            ("💠  Valuation",    6),
            ("⚙️  Settings",     7),
            ("🔆  Help",         8),
        ]

        self._nav_labels = {idx: label for (label, idx) in nav_items}
        _divider_after = {3, 6}  # Core | Analysis | System
        for label, idx in nav_items:
            self._add_nav_button(label, idx)
            if idx in _divider_after:
                tk.Frame(self, bg=ModernStyle.SLATE_700, height=1).pack(fill=tk.X, padx=28, pady=(4, 4))

        # Spacer (pushes bottom section down)
        tk.Frame(self, bg=self.sidebar_bg).pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # ── Bottom section (stacked with side=BOTTOM, reverse order) ─────────

        # QUIT BUTTON — very bottom
        quit_container = tk.Frame(self, bg=self.sidebar_bg)
        quit_container.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 16), padx=16)

        self._exit_btn = tk.Label(
            quit_container, text="⏻  Quit / Logout",
            bg="#2A1B24", fg="#FCA5A5",
            font=(ModernStyle.FONT_FAMILY, 13, "bold"),
            cursor="hand2", anchor="center",
            pady=10
        )
        self._exit_btn.pack(fill=tk.X)

        # FIX: use destroy() so DB cleanup via atexit runs, not just quit()
        self._exit_btn.bind("<Button-1>", lambda e: self._do_quit())
        self._exit_btn.bind("<Enter>", lambda e: self._exit_btn.configure(bg="#451A24", fg="#FECACA"))
        self._exit_btn.bind("<Leave>", lambda e: self._exit_btn.configure(bg="#2A1B24", fg="#FCA5A5"))

        # Divider above Quit
        tk.Frame(self, bg=ModernStyle.SLATE_700, height=1).pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(0, 4))

        # PROFILE SECTION
        profile_row = tk.Frame(self, bg=self.sidebar_bg)
        profile_row.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(0, 12))

        avatar = tk.Canvas(profile_row, width=32, height=32, bg=self.sidebar_bg, highlightthickness=0)
        avatar.pack(side=tk.LEFT)
        
        try:
            from PIL import Image, ImageTk, ImageDraw
            import os, sys
            from pathlib import Path
            
            if getattr(sys, 'frozen', False):
                base_dir = Path(sys._MEIPASS)
            else:
                base_dir = Path(__file__).resolve().parent
            
            profile_path = base_dir / "assets" / "images" / "profile.png"
            
            if os.path.exists(profile_path):
                pil_img = Image.open(profile_path).convert("RGBA")
                pil_img = pil_img.resize((30, 30), Image.Resampling.LANCZOS)
                
                mask = Image.new('L', (30, 30), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, 30, 30), fill=255)
                
                circular_img = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
                circular_img.paste(pil_img, (1, 1), mask=mask)
                
                border_draw = ImageDraw.Draw(circular_img)
                border_draw.ellipse((1, 1, 30, 30), outline=self.accent_primary, width=2)
                
                self._profile_img = ImageTk.PhotoImage(circular_img)
                avatar.create_image(16, 16, image=self._profile_img)
            else:
                avatar.create_oval(2, 2, 30, 30, fill=self.accent_primary, outline="")
                avatar.create_text(16, 16, text="S", fill=ModernStyle.TEXT_ON_ACCENT, font=(ModernStyle.FONT_FAMILY, 14, "bold"))
        except Exception as e:
            print(f"Profile image load error: {e}")
            avatar.create_oval(2, 2, 30, 30, fill=self.accent_primary, outline="")
            avatar.create_text(16, 16, text="S", fill=ModernStyle.TEXT_ON_ACCENT, font=(ModernStyle.FONT_FAMILY, 14, "bold"))

        self._profile_name_lbl = tk.Label(
            profile_row, text="Selvakumar",
            bg=self.sidebar_bg, fg="#E2E8F0",
            font=(ModernStyle.FONT_FAMILY, 13, "bold")
        )
        self._profile_name_lbl.pack(side=tk.LEFT, padx=(10, 0))

        # Make profile row clickable → navigate to Settings (idx 7)
        for w in (avatar, self._profile_name_lbl, profile_row):
            w.bind("<Button-1>", lambda e: self.on_navigate(7))
            w.bind("<Enter>", lambda e: self._profile_name_lbl.configure(fg=self.accent_primary))
            w.bind("<Leave>", lambda e: self._profile_name_lbl.configure(fg="#E2E8F0"))
        avatar.configure(cursor="hand2")
        profile_row.configure(cursor="hand2")
        self._profile_name_lbl.configure(cursor="hand2")

        # Divider above Profile
        tk.Frame(self, bg=ModernStyle.SLATE_700, height=1).pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(0, 8))

        # MINI MARKET TICKERS
        self._ticker_frame = tk.Frame(self, bg=self.sidebar_bg)
        self._ticker_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 12))

        self._ticker_labels = {}

        tk.Label(
            self._ticker_frame, text="M A R K E T S [Live]",
            font=ModernStyle.FONT_BODY_BOLD,
            bg=self.sidebar_bg, fg=self.accent_primary, anchor="w"
        ).pack(fill=tk.X, padx=16, pady=(0, 0))

        tk.Frame(self._ticker_frame, bg=self.accent_primary, height=1).pack(fill=tk.X, padx=16, pady=(0, 6))

        self._ticker_time_lbl = tk.Label(
            self._ticker_frame, text="⚡ Last Updated: —",
            font=(ModernStyle.FONT_FAMILY, 12, "bold italic"),
            bg=self.sidebar_bg, fg="yellow", anchor="w"
        )
        self._ticker_time_lbl.pack(fill=tk.X, padx=20, pady=(0, 4))

        self.tickers_container = tk.Frame(self._ticker_frame, bg=self.sidebar_bg)
        self.tickers_container.pack(fill=tk.X, padx=20, pady=(0, 6))

        import model.tickers as tck
        self._show_ticker_loading()
        tck.refresh_mini_tickers(callback=self._on_tickers_fetched)

        # ── Keyboard shortcut bindings (Alt+1..9) ────────────────────────────
        self._setup_keyboard_shortcuts()

        # ── Cleanup on widget destroy ─────────────────────────────────────────
        self.bind("<Destroy>", self._on_destroy)

    # ── Keyboard shortcuts ────────────────────────────────────────────────────
    def _setup_keyboard_shortcuts(self):
        """Bind Alt+1…9 to navigate to the corresponding sidebar item."""
        try:
            root = self.winfo_toplevel()
            for idx in range(9):
                key = idx + 1
                root.bind_all(f"<Alt-Key-{key}>", lambda e, i=idx: self.on_navigate(i))
        except Exception:
            pass

    # ── Quit helper ───────────────────────────────────────────────────────────
    def _do_quit(self):
        """Clean shutdown: cancel animations, close DB, destroy window."""
        # Cancel any pending after() callbacks
        try:
            if self._pulse_anim_id:
                self.after_cancel(self._pulse_anim_id)
        except Exception:
            pass
        try:
            if self._anim_id:
                self.after_cancel(self._anim_id)
        except Exception:
            pass
        try:
            close_all_connections(optimize=False)
        except Exception:
            pass
        try:
            self.winfo_toplevel().destroy()
        except Exception:
            pass

    # ── Widget-destroy cleanup ────────────────────────────────────────────────
    def _on_destroy(self, _e=None):
        """Cancel all after() callbacks to avoid TclError on dead widgets."""
        try:
            if self._pulse_anim_id:
                self.after_cancel(self._pulse_anim_id)
                self._pulse_anim_id = None
        except Exception:
            pass
        try:
            if self._anim_id:
                self.after_cancel(self._anim_id)
                self._anim_id = None
        except Exception:
            pass

    def set_active(self, idx: int) -> None:
        self._active_idx = idx
        target_y = None

        self.update_idletasks()  # Ensure geometry is computed before getting winfo_y

        for i, btn in self.buttons.items():
            if i == idx:
                target_y = btn.master.winfo_y() + btn.winfo_y()
                btn.set_disabled(False)
                btn.set_palette(
                    bg=self.accent_gradient,
                    fg="#ffffff",
                    hover_bg=self.accent_primary,
                    pressed_bg=self.accent_primary,
                )
            else:
                btn.set_disabled(False)
                btn.set_palette(
                    bg=self.sidebar_bg,
                    fg="#E2E8F0",
                    hover_bg=self.accent_hover,
                    pressed_bg=self.accent_pressed,
                )

        if target_y is not None and not self._collapsed:
            self._animate_indicator(target_y)

    def _animate_indicator(self, target_y: float) -> None:
        if self._anim_id:
            self.after_cancel(self._anim_id)

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

            pil_img = Image.open(path)
            pil_img = pil_img.resize((24, 24), Image.Resampling.LANCZOS)
            self._icons[label] = ImageTk.PhotoImage(pil_img)
        except Exception as e:
            print(f"Icon load error ({label}): {e}")
            return

    def _add_nav_button(self, label: str, idx: int):
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
            fg="#E2E8F0",
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

        # FIX: suppress hover shift for the currently active button
        def _on_hover(e, is_hover=True, r=row, i=idx):
            if not self._collapsed and i != self._active_idx:
                r.pack_configure(padx=(20, 8) if is_hover else (12, 16))

        btn.bind("<Enter>", lambda e: _on_hover(e, True), add="+")
        btn.bind("<Leave>", lambda e: _on_hover(e, False), add="+")

        # Attach tooltip (visible only in collapsed mode)
        # Strip emoji prefix from label for clean tooltip text
        clean = label.strip()
        for sep in ("  ", " "):
            if sep in clean:
                clean = clean.split(sep, 1)[-1].strip()
                break
        tip = _NavTooltip(btn, clean, self.sidebar_bg)
        self._tooltips.append(tip)

    def toggle(self) -> None:
        """Collapse/expand the sidebar."""
        self._collapsed = not bool(self._collapsed)

        abbr = {
            0: "📊", 1: "💼", 2: "➕", 3: "🧬",
            4: "📄", 5: "👁", 6: "💠", 7: "⚙️", 8: "🔅",
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
            try: self._status_row.pack_forget()
            except Exception: pass
            try: self._ticker_frame.pack_forget()
            except Exception: pass
            try: self._toggle_btn.set_text("→")
            except Exception: pass
            try: self._profile_name_lbl.pack_forget()
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
            # ── Expand ────────────────────────────────────────────────────────
            self.configure(width=self._w_expanded)

            try: self._title_stack.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
            except Exception: pass
            try: self._menu_lbl.pack(fill=tk.X)
            except Exception: pass
            try:
                self._summary_card.pack(fill=tk.X, padx=16, pady=(4, 8), before=self._nav_header)
            except Exception: pass
            try:
                self._status_row.pack(fill=tk.X, pady=(6, 0))
            except Exception: pass
            try:
                self._ticker_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 12))
            except Exception: pass
            try: self._toggle_btn.set_text("≡")
            except Exception: pass
            try: self._profile_name_lbl.pack(side=tk.LEFT, padx=(10, 0))
            except Exception: pass

            for idx, btn in self.buttons.items():
                try:
                    btn.set_text(self._nav_labels.get(idx, ""))
                    btn.set_size(width=self._btn_w_expanded)
                except Exception:
                    pass

            try: self._exit_btn.configure(text="⏻  Quit / Logout")
            except Exception: pass

        # Re-apply active styling (FIX: use `in` instead of fragile string comparison)
        try:
            if self._active_idx is not None and self._active_idx in self.buttons:
                self.after(50, lambda: self.set_active(self._active_idx))
        except Exception:
            pass

    def _refresh_summary_card(self):
        """Fetch portfolio totals and update the summary card.

        Called once at startup and again when the dashboard Refresh button
        is clicked (via refresh_sidebar_data).
        """
        try:
            from model.database import db_session
            from model.engine import get_exchange_rate
            with db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT qty, avg_price, running_pnl, currency FROM holdings WHERE qty > 0")
                count = 0
                invested = 0.0
                pnl = 0.0
                for row in cur.fetchall():
                    qty = float(row[0] or 0)
                    price = float(row[1] or 0)
                    running_pnl = float(row[2] or 0)
                    currency = str(row[3] or 'INR').strip().upper()
                    
                    rate = get_exchange_rate(currency)
                    count += 1
                    invested += (qty * price) * rate
                    pnl += running_pnl * rate
                    
                self._update_summary_ui(count, invested, pnl)
        except Exception as e:
            print(f"Summary card error: {e}")

    def _update_summary_ui(self, count, invested, pnl):
        try:
            # Correctly labelled as "Invested" since it is cost basis, not market value
            self._summary_value_lbl.configure(text=f"₹{invested:,.0f}  Invested")
            color = ModernStyle.SUCCESS if pnl >= 0 else ModernStyle.ERROR
            arrow = "▲" if pnl >= 0 else "▼"
            self._summary_pnl_lbl.configure(text=f"{arrow} P&L: ₹{pnl:,.0f}", fg=color)
            self._summary_count_lbl.configure(text=f"{count} holdings")
        except Exception: pass

    def _refresh_status_badge(self):
        """Fetch last sync time and update the status badge.

        Called once at startup and again via refresh_sidebar_data.
        """
        try:
            from model.database import db_session
            from datetime import datetime
            with db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM holdings WHERE qty > 0")
                row1 = cur.fetchone()
                count = row1[0] if row1 else 0
                
                cur.execute("SELECT MAX(last_updated) FROM marketdata")
                row2 = cur.fetchone()
                last_ts = row2[0] if row2 else None
                
            time_str = "Unknown"
            if last_ts:
                try:
                    dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
                    diff = int((datetime.now() - dt).total_seconds() / 60)
                    if diff < 1: time_str = "Just now"
                    elif diff < 60: time_str = f"{diff}m ago"
                    else: time_str = f"{diff // 60}h ago"
                except Exception: pass
                
            self._status_badge.configure(text=f"{count} active · {time_str}", fg=ModernStyle.SLATE_300)
        except Exception as e:
            print(f"Status badge error: {e}")
            self._status_badge.configure(text=f"Sync error", fg=ModernStyle.ERROR)

    def refresh_sidebar_data(self):
        """Public method: re-fetch sidebar investment & status data.

        Called by the Dashboard refresh button after market data is updated.
        """
        self._refresh_summary_card()
        self._refresh_status_badge()

    def _pulse_step(self):
        """Animate the status dot with a smooth heartbeat pulse."""
        try:
            self._pulse_phase = (self._pulse_phase + 1) % 20
            import math
            t = math.sin(self._pulse_phase / 20.0 * math.pi * 2) * 0.5 + 0.5

            r = int(10 + (34 - 10) * t)
            g = int(92 + (197 - 92) * t)
            b = int(47 + (94 - 47) * t)
            color = f"#{r:02x}{g:02x}{b:02x}"

            self._pulse_canvas.itemconfig(self._pulse_glow, outline=color)
            self._pulse_canvas.itemconfig(self._pulse_dot, fill=color)

            expand = int(t * 2)
            self._pulse_canvas.coords(
                self._pulse_glow,
                1 - expand, 1 - expand, 13 + expand, 13 + expand
            )
        except Exception:
            pass

        try:
            self._pulse_anim_id = self.after(80, self._pulse_step)
        except Exception:
            pass

    def _show_ticker_loading(self):
        """Show the Loading... placeholder before data arrives."""
        for w in self.tickers_container.winfo_children():
            w.destroy()
        tk.Label(self.tickers_container, text="Loading...", bg=self.sidebar_bg, fg=ModernStyle.TEXT_ON_ACCENT, font=ModernStyle.FONT_SMALL).pack(anchor="w")

    def _on_tickers_fetched(self):
        """Callback invoked from background thread when tickers are ready."""
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
            self._ticker_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 12))

        data = tck.get_mini_tickers()

        for w in self.tickers_container.winfo_children():
            w.destroy()

        if not data:
            # FIX: show retry button on failure
            err_row = tk.Frame(self.tickers_container, bg=self.sidebar_bg)
            err_row.pack(fill=tk.X)
            tk.Label(err_row, text="No data", bg=self.sidebar_bg, fg=ModernStyle.TEXT_ON_ACCENT, font=ModernStyle.FONT_SMALL).pack(side=tk.LEFT)
            retry_lbl = tk.Label(err_row, text="↺ Retry", bg=self.sidebar_bg, fg=self.accent_primary,
                                 font=ModernStyle.FONT_SMALL_BOLD, cursor="hand2")
            retry_lbl.pack(side=tk.RIGHT)
            retry_lbl.bind("<Button-1>", lambda e: self.refresh_tickers())
        else:
            for name, info in data.items():
                row = tk.Frame(self.tickers_container, bg=self.sidebar_bg)
                row.pack(fill=tk.X, pady=1)

                tk.Label(row, text=name, bg=self.sidebar_bg, fg=ModernStyle.TEXT_ON_ACCENT, font=ModernStyle.FONT_SUBHEADING).pack(side=tk.LEFT)

                pct = info.get("pct", 0.0)
                cp  = info.get("price", 0.0)

                # FIX: use red for negative moves (financial standard), not gold
                color = ModernStyle.SUCCESS if pct >= 0 else ModernStyle.ERROR
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

        # ── Status Bar (Bottom) ──────────────────────────────────────────────
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
                text=f"🟢 Last updated: {time_str}   |   📦 {count} active holdings   |   💰 ₹{val:,.2f} total value (INR equiv.)"
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

            pil_img = Image.open(icon_path).convert("RGBA")
            icon_size = 128
            pil_img = pil_img.resize((icon_size, icon_size), Image.Resampling.LANCZOS)

            from PIL import ImageDraw
            mask = Image.new('L', (icon_size, icon_size), 0)
            draw = ImageDraw.Draw(mask)
            draw.rounded_rectangle((0, 0, icon_size, icon_size), radius=int(icon_size * 0.225), fill=255)

            rounded_img = Image.new('RGBA', (icon_size, icon_size), (0, 0, 0, 0))
            rounded_img.paste(pil_img, (0, 0), mask=mask)

            self._app_icon = ImageTk.PhotoImage(rounded_img)

            try:
                self.root.iconphoto(True, self._app_icon)
            except Exception:
                try:
                    self.root.tk.call("wm", "iconphoto", self.root._w, self._app_icon)  # type: ignore
                except Exception:
                    pass

            if sys.platform == "darwin":
                try:
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
