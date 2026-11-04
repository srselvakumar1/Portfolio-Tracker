#!/usr/bin/env python3
"""
PTracker - Portfolio Tracker
Modern Tkinter Implementation with Premium Aesthetic
"""

import tkinter as tk
import sys
import os
import threading
import time
from pathlib import Path
from typing import Dict, Callable
import atexit

# ── PyInstaller frozen-app SSL fix ────────────────────────────────────────────
# When bundled with PyInstaller, the certifi CA bundle is extracted to _MEIPASS.
# urllib3/requests won't find it unless we point the env vars there.
if getattr(sys, 'frozen', False):
    _cert_file = os.path.join(sys._MEIPASS, 'certifi', 'cacert.pem')
    if os.path.exists(_cert_file):
        os.environ.setdefault('SSL_CERT_FILE', _cert_file)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', _cert_file)
        os.environ.setdefault('CURL_CA_BUNDLE', _cert_file)

from PIL import Image, ImageTk, ImageDraw
from model.applog import log, setup_logging
from model.state import AppState
from model.database import close_all_connections
from ui.ui_theme import ModernStyle
from ui.ui_widgets import ModernButton
from ui import icons
from ui.ui_utils import center_window, call_on_ui, run_in_background, show_toast, start_ui_dispatcher, install_row_hover


def _asset_path(*parts) -> Path:
    """Path to a bundled asset, both when frozen (PyInstaller) and from source."""
    base = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    return base.joinpath("assets", *parts)

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
        self.view_classes: Dict[str, object] = {}  # str path OR type
    
    def register_view(self, name: str, view_spec):
        """Register a view class or a 'module.ClassName' string for lazy import."""
        self.view_classes[name] = view_spec
    
    def _resolve_class(self, name: str) -> type:
        """Return the view class, importing the module on first call."""
        spec = self.view_classes.get(name)
        if spec is None:
            raise ValueError(f"View '{name}' not registered")
        if isinstance(spec, str):
            # Lazy import: 'views.dashboard_view.DashboardView'
            module_path, cls_name = spec.rsplit(".", 1)
            import importlib
            mod = importlib.import_module(module_path)
            cls = getattr(mod, cls_name)
            # Cache the resolved class so subsequent navigations are instant
            self.view_classes[name] = cls
            return cls
        return spec

    # Pages that stay mapped (moved out of sight) when hidden. Showing a hidden page maps
    # its widgets again one level at a time, and on a Mac each level costs a full-window
    # repaint; these two are the deepest (about 0.7 s each time back), and mapped they
    # return in 0.2–0.3 s. Only these two: every page left mapped makes the first visit
    # to the other pages a little slower.
    KEEP_MAPPED = ("trade_entry", "valuation")

    def show_view(self, name: str):
        """Swap the visible view.

        Tk draws the new view on its own as soon as this returns. Forcing
        update()/update_idletasks() here made each click wait for every redraw
        (on a Retina Mac each full-window redraw costs about 0.1 s), and a
        fade overlay added one more redraw, so they are gone.

        Hidden views are unmapped (pack_forget), except KEEP_MAPPED ones: every view
        left mapped, even out of sight, made each later page build a little slower.
        """
        if name not in self.views:
            view_class = self._resolve_class(name)
            try:
                self.views[name] = view_class(self.container, app_state=self.app_state)
            except TypeError:
                self.views[name] = view_class(self.container)

        # Hide current view
        old_name = self.current_view
        old_view = self.views.get(old_name) if old_name else None
        new_view = self.views[name]
        if old_view is not None and old_view is not new_view:
            if old_name in self.KEEP_MAPPED:
                old_view.place_configure(x=-30000)   # still mapped: it comes back fast
            else:
                old_view.pack_forget()
            if hasattr(old_view, 'on_hide'):
                old_view.on_hide()

        # Show new view
        if name in self.KEEP_MAPPED:
            new_view.place(x=0, y=0, relwidth=1, relheight=1)
        else:
            new_view.pack(fill=tk.BOTH, expand=True)
        self.current_view = name

        if hasattr(new_view, 'on_show'):
            new_view.on_show()


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
                bg=ModernStyle.SIDEBAR_BG_ALT, fg=ModernStyle.SIDEBAR_FG,
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
    # Nav button height: 34 px leaves room for the summary card and all market rows
    # on a typical window (13 pt labels still have plenty of space)
    _NAV_BTN_H = 32
    _NAV_BTN_H_COMPACT = 26   # small windows: shorter menu buttons instead of a scrolling sidebar

    def __init__(self, parent, on_navigate: Callable):
        # ── Colour tokens (the sidebar is dark in both themes) ────────────────
        self.sidebar_bg      = ModernStyle.SIDEBAR_BG
        self.accent_primary  = ModernStyle.BRAND_GOLD
        self.accent_hover    = ModernStyle.SIDEBAR_HOVER
        self.accent_pressed  = ModernStyle.SIDEBAR_PRESSED
        self.accent_gradient = ModernStyle.SIDEBAR_ACTIVE_BG

        # 220 px (was 248): narrower sidebar, more room for each page's tables
        super().__init__(parent, bg=self.sidebar_bg, width=220)
        self.pack(side=tk.LEFT, fill=tk.Y)
        self.pack_propagate(False)

        # Subtle right border for depth
        tk.Frame(self, bg=ModernStyle.SIDEBAR_BORDER, width=1).pack(side=tk.RIGHT, fill=tk.Y)

        self.on_navigate = on_navigate
        self.buttons = {}
        self._indicators: dict[int, tk.Frame] = {}
        self._active_idx: int | None = None
        self._nav_h = self._NAV_BTN_H   # current menu button height (see _fit_to_height)
        self._nav_labels: dict[int, str] = {}
        self._collapsed = False
        self._tooltips: list[_NavTooltip] = []   # keep references alive



        # Size tokens
        self._w_expanded  = 220
        self._w_collapsed = 78
        self._btn_w_expanded  = 184
        self._btn_w_collapsed = 52

        # ── Header container ──────────────────────────────────────────────────
        self._header_container = tk.Frame(self, bg=self.sidebar_bg)
        self._header_container.pack(fill=tk.X, padx=12, pady=(12, 8))

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
            radius=8,
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
        self._title_stack.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))

        title_badge_row = tk.Frame(self._title_stack, bg=self.sidebar_bg)
        title_badge_row.pack(expand=True, anchor="w")

        self._title_lbl = tk.Label(
            title_badge_row,
            text="PTracker",
            font=ModernStyle.FONT_TITLE,   # 16 pt: leaves room for the PRO badge in the 220 px sidebar
            bg=self.sidebar_bg,
            fg=ModernStyle.SIDEBAR_FG,
            anchor="w",
        )
        self._title_lbl.pack(side=tk.LEFT)

        # PRO / Version Badge
        badge_frame = tk.Frame(title_badge_row, bg=ModernStyle.WARNING_PALE, padx=5, pady=2)
        badge_frame.pack(side=tk.LEFT, padx=(8, 0), pady=(3, 0))
        tk.Label(
            badge_frame, text="PRO",
            font=ModernStyle.FONT_SIDEBAR_BADGE,
            bg=ModernStyle.WARNING_PALE, fg=ModernStyle.WARNING
        ).pack()

        # LOGO ROW
        self._logo_container = tk.Frame(self._header_container, bg=self.sidebar_bg)
        self._logo_container.pack(fill=tk.X, pady=(8, 0))

        try:
            # Colourful logo in the header colours (128 px, shown at 64 px for crisp edges);
            # the older dark shield logo is the fallback
            logo_path = _asset_path("images", "sidebar_logo.png")
            if not logo_path.exists():
                logo_path = _asset_path("images", "logo_80.png")
            if logo_path.exists():
                base_size = 64
                pil_img = Image.open(logo_path).convert("RGBA")
                if pil_img.size != (base_size, base_size):
                    pil_img = pil_img.resize((base_size, base_size), Image.Resampling.LANCZOS)

                # Round the corners (the new logo already has them; the old one doesn't)
                mask = Image.new('L', (base_size, base_size), 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, base_size, base_size), radius=14, fill=255)
                rounded_img = Image.new('RGBA', (base_size, base_size), (0, 0, 0, 0))
                rounded_img.paste(pil_img, (0, 0), mask=mask)
                pil_img = rounded_img

                self._logo_img = ImageTk.PhotoImage(pil_img)
                self._logo_lbl = tk.Label(
                    self._logo_container,
                    image=self._logo_img,
                    bg=self.sidebar_bg,
                )
                self._logo_lbl.pack(pady=(2, 0), anchor=tk.CENTER)
        except Exception:
            log.exception("Could not load the sidebar logo")

        # ── Pulsing Live Status Dot ───────────────────────────────────────────
        self._status_row = tk.Frame(self._header_container, bg=self.sidebar_bg)
        self._status_row.pack(fill=tk.X, pady=(6, 0))

        self._pulse_canvas = tk.Canvas(
            self._status_row, width=14, height=14,
            bg=self.sidebar_bg, highlightthickness=0, bd=0,
        )
        self._pulse_canvas.pack(side=tk.LEFT, padx=(0, 6))
        self._pulse_glow = self._pulse_canvas.create_oval(
            1, 1, 13, 13, fill="", outline=ModernStyle.TICKER_UP, width=2
        )
        self._pulse_dot = self._pulse_canvas.create_oval(
            4, 4, 10, 10, fill=ModernStyle.TICKER_UP, outline=""
        )
        self._pulse_anim_id = None

        self._status_badge = tk.Label(
            self._status_row, text="⏳ Syncing…",
            bg=self.sidebar_bg, fg=ModernStyle.SIDEBAR_MUTED,
            font=ModernStyle.FONT_SMALL, anchor="w",
        )
        self._status_badge.pack(side=tk.LEFT, fill=tk.X)

        self.after(50, self._refresh_status_badge)
        self.after(100, self._pulse_step)

        # ── Bottom Fixed Section ──────────────────────────────────────────────
        self.bottom_fixed_frame = tk.Frame(self, bg=self.sidebar_bg)
        self.bottom_fixed_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # PROFILE + QUIT on one row (two rows used ~50 px the menu needs)
        profile_row = tk.Frame(self.bottom_fixed_frame, bg=self.sidebar_bg)
        profile_row.pack(side=tk.BOTTOM, fill=tk.X, padx=16, pady=(4, 12))

        avatar = tk.Canvas(profile_row, width=32, height=32, bg=self.sidebar_bg, highlightthickness=0)
        avatar.pack(side=tk.LEFT)
        
        try:
            # Pre-sized 30 px copy (the full-size original is in assets_src/)
            profile_path = _asset_path("images", "profile_30.png")

            if profile_path.exists():
                pil_img = Image.open(profile_path).convert("RGBA")
                if pil_img.size != (30, 30):
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
                avatar.create_text(16, 16, text="S", fill=ModernStyle.TEXT_ON_ACCENT, font=ModernStyle.FONT_HEADING)
        except Exception:
            avatar.create_oval(2, 2, 30, 30, fill=self.accent_primary, outline="")
            avatar.create_text(16, 16, text="S", fill=ModernStyle.TEXT_ON_ACCENT, font=ModernStyle.FONT_HEADING)

        self._profile_name_lbl = tk.Label(
            profile_row, text="Selvakumar",
            bg=self.sidebar_bg, fg=ModernStyle.SIDEBAR_FG,
            font=ModernStyle.FONT_SMALL_BOLD
        )
        self._profile_name_lbl.pack(side=tk.LEFT, padx=(8, 0))

        self._exit_btn = tk.Label(
            profile_row, text="⏻",
            bg=ModernStyle.QUIT_BG, fg=ModernStyle.QUIT_FG,
            font=ModernStyle.FONT_SMALL_BOLD,
            cursor="hand2", anchor="center", padx=6, pady=5
        )
        self._exit_btn.pack(side=tk.RIGHT)
        from ui.ui_utils import ToolTip
        self._exit_tip = ToolTip(self._exit_btn, "Quit PTracker")
        # destroy() (not just quit()) so the DB cleanup via atexit runs
        self._exit_btn.bind("<Button-1>", lambda e: self._do_quit())
        self._exit_btn.bind("<Enter>", lambda e: self._exit_btn.configure(bg=ModernStyle.QUIT_BG_HOVER, fg=ModernStyle.QUIT_FG_HOVER))
        self._exit_btn.bind("<Leave>", lambda e: self._exit_btn.configure(bg=ModernStyle.QUIT_BG, fg=ModernStyle.QUIT_FG))

        # Make profile row clickable → navigate to Settings (index 9 in nav_items below)
        for w in (avatar, self._profile_name_lbl, profile_row):
            w.bind("<Button-1>", lambda e: self.on_navigate(9))
            w.bind("<Enter>", lambda e: self._profile_name_lbl.configure(fg=self.accent_primary))
            w.bind("<Leave>", lambda e: self._profile_name_lbl.configure(fg=ModernStyle.SIDEBAR_FG))
        avatar.configure(cursor="hand2")
        profile_row.configure(cursor="hand2")
        self._profile_name_lbl.configure(cursor="hand2")

        # Divider above Profile
        self._profile_divider = tk.Frame(self.bottom_fixed_frame, bg=ModernStyle.SIDEBAR_HOVER, height=1)
        self._profile_divider.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(0, 8))

        # ── Middle Scrollable Frame ───────────────────────────────────────────
        # Create canvas for middle contents (scrollbar removed per request)
        self._middle_canvas = tk.Canvas(
            self, bg=self.sidebar_bg, highlightthickness=0, bd=0
        )
        self._middle_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.middle_content = tk.Frame(self._middle_canvas, bg=self.sidebar_bg)
        self._middle_canvas_win = self._middle_canvas.create_window(
            (0, 0), window=self.middle_content, anchor="nw"
        )

        def _on_middle_canvas_configure(e):
            self._middle_canvas.itemconfigure(self._middle_canvas_win, width=e.width)
            self._update_scrollbar_visibility()
            self._schedule_fit()

        self._middle_canvas.bind("<Configure>", _on_middle_canvas_configure)

        def _on_middle_content_configure(e=None):
            self._middle_canvas.configure(scrollregion=self._middle_canvas.bbox("all"))
            self._update_scrollbar_visibility()
            self._schedule_fit()   # e.g. the market list grew when prices arrived

        self.middle_content.bind("<Configure>", _on_middle_content_configure)



        # Animated sliding indicator (Pill-shaped) - height adjusted to 38px
        self._sliding_indicator = tk.Canvas(self.middle_content, bg=self.sidebar_bg, width=4, highlightthickness=0)
        self._sliding_indicator_id = self._sliding_indicator.create_line(
            2, 3, 2, self._NAV_BTN_H - 3, fill=self.accent_primary, width=4, capstyle=tk.ROUND
        )
        self._anim_id = None
        self._current_indicator_y = 0.0

        # Size tokens
        self._w_expanded  = 220
        self._w_collapsed = 78
        self._btn_w_expanded  = 184
        self._btn_w_collapsed = 52

        # ── Portfolio Summary Card ────────────────────────────────────────────
        _card_bg = ModernStyle.SIDEBAR_BG_ALT
        self._summary_card = tk.Frame(self.middle_content, bg=_card_bg, highlightbackground=ModernStyle.SIDEBAR_HOVER, highlightthickness=1)
        self._summary_card.pack(fill=tk.X, padx=16, pady=(4, 8))

        # Header label
        self._summary_header_lbl = tk.Label(self._summary_card, text="Invested", bg=_card_bg,
                                            fg=ModernStyle.SIDEBAR_MUTED, font=ModernStyle.FONT_SMALL, anchor="w")
        self._summary_header_lbl.pack(fill=tk.X, padx=12, pady=(8, 2))

        # Container for per-currency invested + P&L lines (populated dynamically)
        self._summary_values_frame = tk.Frame(self._summary_card, bg=_card_bg)
        self._summary_values_frame.pack(fill=tk.X, padx=12, pady=(0, 8))

        self.after(50, self._refresh_summary_card)

        # ── Navigation Section Label ──────────────────────────────────────────
        self._nav_header = tk.Frame(self.middle_content, bg=self.sidebar_bg)
        self._nav_header.pack(fill=tk.X, padx=16, pady=(6, 0))

        self._menu_lbl = tk.Label(
            self._nav_header, text="N A V I G A T I O N",
            font=ModernStyle.FONT_NAV_SECTION,
            bg=self.sidebar_bg, fg=ModernStyle.SIDEBAR_MUTED, anchor="w",
        )
        self._menu_lbl.pack(fill=tk.X)
        


        # Gold Separator — placed before the first nav button (Dashboard)
        self._nav_gold_sep = tk.Frame(self.middle_content, bg=self.sidebar_bg)
        self._nav_gold_sep.pack(fill=tk.X, padx=16, pady=(2, 2))
        tk.Frame(self._nav_gold_sep, bg=ModernStyle.SIDEBAR_HOVER, height=1).pack(fill=tk.X)


        # ── Navigation Items ──────────────────────────────────────────────────
        nav_items = [
            # (page, Lucide line icon, icon colour, emoji if the icon font is missing, label)
            (0, "layout-dashboard", "#7DD3FC", "🏠", "Dashboard"),
            (1, "briefcase-business", "#6EE7B7", "💼", "My Holdings"),
            (2, "square-pen", "#FCD34D", "✍️", "Trade Entry"),
            (3, "history", "#C4B5FD", "🕒", "Trade History"),
            (4, "receipt-text", "#FDA4AF", "🧾", "Tax Report"),
            (5, "chart-column", "#5EEAD4", "📊", "P&L Report"),
            (6, "eye", "#BEF264", "👀", "Watchlist"),
            (7, "gem", "#F0ABFC", "💎", "Valuation"),
            (8, "newspaper", "#FDBA74", "📰", "Financial News"),
            (9, "settings", "#A5B4FC", "⚙️", "Settings"),
            (10, "circle-help", "#67E8F9", "💡", "Help"),
        ]

        self._nav_short: dict[int, str] = {}   # collapsed text: "" when the icon shows alone
        self._nav_colors: dict[int, str] = {}
        _divider_after = {3, 8}  # Core | Analysis | System
        for idx, icon_name, color, emoji, label in nav_items:
            self._add_nav_button(idx, label, icons.glyph(icon_name), color, emoji)
            if idx in _divider_after:
                div = tk.Frame(self.middle_content, bg=ModernStyle.SIDEBAR_HOVER, height=1)
                div.pack(fill=tk.X, padx=28, pady=(2, 2))


        # Spacer (thin fixed gap above the bottom-docked section)
        tk.Frame(self, bg=self.sidebar_bg, height=4).pack(side=tk.TOP, fill=tk.X)

        # MINI MARKET TICKERS — expands to fill remaining sidebar space
        # Markets sit at the bottom of the sidebar, just above the profile row
        self._ticker_frame = tk.Frame(self.bottom_fixed_frame, bg=self.sidebar_bg)
        self._ticker_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 6))

        self._ticker_labels = {}

        ticker_head = tk.Frame(self._ticker_frame, bg=self.sidebar_bg)
        ticker_head.pack(fill=tk.X, padx=16)
        tk.Label(
            ticker_head, text="M A R K E T S",
            font=ModernStyle.FONT_NAV_SECTION,
            bg=self.sidebar_bg, fg=ModernStyle.SIDEBAR_MUTED, anchor="w"
        ).pack(side=tk.LEFT)

        # When the prices were fetched, on the heading's line (saves a line for the menu)
        self._ticker_time_lbl = tk.Label(
            ticker_head, text="—",
            font=ModernStyle.FONT_ITALIC_SM,
            bg=self.sidebar_bg, fg=ModernStyle.SIDEBAR_MUTED, anchor="e"
        )
        self._ticker_time_lbl.pack(side=tk.RIGHT)
        from ui.ui_utils import ToolTip
        self._ticker_time_tip = ToolTip(self._ticker_time_lbl, "Prices not fetched yet")

        tk.Frame(self._ticker_frame, bg=ModernStyle.SIDEBAR_HOVER, height=1).pack(fill=tk.X, padx=16, pady=(0, 3))

        # Tickers container directly in the frame
        self.tickers_container = tk.Frame(self._ticker_frame, bg=self.sidebar_bg)
        self.tickers_container.pack(fill=tk.BOTH, expand=True, padx=8)

        import model.tickers as tck
        cached_data = tck.get_mini_tickers()
        if cached_data:
            self._render_tickers()
        else:
            self._show_ticker_loading()
        # Fetched once the first page is up: loading the price library (yfinance) is
        # seconds of work that slowed the start of the app down
        self.after(6000, lambda: tck.refresh_mini_tickers(callback=self._on_tickers_fetched))

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
                    fg=ModernStyle.TEXT_ON_ACCENT,
                    hover_bg=self.accent_primary,
                    pressed_bg=self.accent_primary,
                )
                btn.set_font(ModernStyle.FONT_NAV_ACTIVE)
                btn.set_glyph_color(None)   # white, like the text
            else:
                btn.set_disabled(False)
                btn.set_palette(
                    bg=self.sidebar_bg,
                    fg=ModernStyle.SIDEBAR_FG,
                    hover_bg=self.accent_hover,
                    pressed_bg=self.accent_pressed,
                )
                btn.set_font(ModernStyle.FONT_NAV)
                btn.set_glyph_color(self._nav_colors.get(i))

        if target_y is not None and not self._collapsed:
            self._animate_indicator(target_y)

    def _animate_indicator(self, target_y: float) -> None:
        """Move the gold indicator next to the active button.

        It jumps rather than slides: every slide frame made Tk redraw the whole
        window, so the ~20-frame slide blocked the app for 2–3 s per click.
        """
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None
        self._current_indicator_y = target_y
        self._sliding_indicator.place(x=0, y=int(target_y), width=4, height=self._nav_h)

    def _add_nav_button(self, idx: int, label: str, glyph: str, color: str, emoji: str):
        text = label if glyph else f"{emoji}  {label}"
        self._nav_labels[idx] = text
        self._nav_short[idx] = "" if glyph else emoji
        self._nav_colors[idx] = color
        row = tk.Frame(self.middle_content, bg=self.sidebar_bg)
        row.pack(fill=tk.X, padx=(12, 16), pady=0)

        btn = ModernButton(
            row,
            text=text,
            glyph=glyph,
            glyph_font=icons.font(ModernStyle.NAV_ICON_PX),
            glyph_fg=color,
            command=lambda: self.on_navigate(idx),
            invoke_on_press=True,
            bg=self.sidebar_bg,
            fg=ModernStyle.SIDEBAR_FG,
            canvas_bg=self.sidebar_bg,
            width=self._btn_w_expanded,
            height=self._NAV_BTN_H,
            radius=10,
            font=ModernStyle.FONT_NAV,
            text_anchor="w",
            text_padx=14,
        )
        btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.buttons[idx] = btn

        # Attach tooltip (visible only in collapsed mode)
        tip = _NavTooltip(btn, label, self.sidebar_bg)
        self._tooltips.append(tip)



    def toggle(self) -> None:
        """Collapse/expand the sidebar."""
        self._collapsed = not bool(self._collapsed)

        # Collapsed buttons show just their icon
        abbr = self._nav_short

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
            try: self._toggle_btn.set_text("☰")
            except Exception: pass
            try: self._profile_name_lbl.pack_forget()
            except Exception: pass

            for idx, btn in self.buttons.items():
                try:
                    btn.set_text(abbr.get(idx, ""))
                    btn.set_size(width=self._btn_w_collapsed)
                except Exception:
                    pass

            try: self._exit_btn.configure(text="⏻")
            except Exception: pass

        else:
            # ── Expand ────────────────────────────────────────────────────────
            self.configure(width=self._w_expanded)

            try: self._title_stack.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
            except Exception: pass
            try:
                self._menu_lbl.pack(fill=tk.X)
                # (the fit may have hidden the heading; it hides it again if still short)
                self._nav_header.pack(fill=tk.X, padx=16, pady=(6, 0), before=self._nav_gold_sep)
            except Exception: pass
            try:
                self._summary_card.pack(fill=tk.X, padx=16, pady=(4, 8), before=self._nav_header)
            except Exception: pass
            try:
                self._status_row.pack(fill=tk.X, pady=(6, 0))
            except Exception: pass
            try:
                self._ticker_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 6), after=self._profile_divider)
            except Exception: pass
            try: self._toggle_btn.set_text("☰")
            except Exception: pass
            try: self._profile_name_lbl.pack(side=tk.LEFT, padx=(10, 0))
            except Exception: pass

            for idx, btn in self.buttons.items():
                try:
                    btn.set_text(self._nav_labels.get(idx, ""))
                    btn.set_size(width=self._btn_w_expanded)
                except Exception:
                    pass

            try: self._exit_btn.configure(text="⏻")
            except Exception: pass

        # Re-apply active styling (FIX: use `in` instead of fragile string comparison)
        try:
            if self._active_idx is not None and self._active_idx in self.buttons:
                self.after(50, lambda: self.set_active(self._active_idx))
        except Exception:
            pass

        self._update_scrollbar_visibility()

    _CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "GBP": "£", "JPY": "¥", "CNY": "¥", "EUR": "€"}
    _CURRENCY_ORDER = ["INR", "USD", "GBP", "EUR", "JPY", "CNY"]  # display priority

    def _refresh_summary_card(self):
        """Fetch portfolio totals grouped by currency for the sidebar summary card.

        Called once at startup and again when the dashboard Refresh button
        is clicked (via refresh_sidebar_data).
        """
        from model.database import db_session

        def _work():
            with db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT qty, avg_price, running_pnl, currency FROM holdings WHERE qty > 0")
                by_currency = {}  # {currency: {invested, pnl, count}}
                for row in cur.fetchall():
                    qty = float(row[0] or 0)
                    price = float(row[1] or 0)
                    running_pnl = float(row[2] or 0)
                    currency = str(row[3] or 'INR').strip().upper()

                    entry = by_currency.setdefault(currency, {"invested": 0.0, "pnl": 0.0, "count": 0})
                    entry["invested"] += qty * price
                    entry["pnl"] += running_pnl
                    entry["count"] += 1
            return by_currency

        run_in_background(_work, on_done=self._update_summary_ui,
                          widget=self, name="sidebar-summary")

    def _refresh_status_badge(self):
        """Fetch the holdings count and last price update time in the background."""
        from model.database import db_session
        from datetime import datetime

        def _work():
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
                except ValueError:
                    pass
            return f"{count} active · prices {time_str}"

        run_in_background(
            _work,
            on_done=lambda text: self._update_status_badge_ui(text, ModernStyle.SIDEBAR_MUTED),
            on_error=lambda e: self._update_status_badge_ui("Sync error", ModernStyle.TICKER_DOWN),
            widget=self, name="sidebar-status",
        )

    def _update_summary_ui(self, by_currency: dict):
        """Render per-currency invested values and P&L in the sidebar summary card."""
        _card_bg = ModernStyle.SIDEBAR_BG_ALT

        # Clear previous content
        for w in self._summary_values_frame.winfo_children():
            w.destroy()

        if not by_currency:
            tk.Label(self._summary_values_frame, text="No holdings", bg=_card_bg,
                     fg=ModernStyle.SIDEBAR_MUTED, font=ModernStyle.FONT_SMALL, anchor="w").pack(fill=tk.X)
            return

        # Sort currencies: known ones first in defined order, then alphabetical
        sorted_currencies = sorted(
            by_currency.keys(),
            key=lambda c: (self._CURRENCY_ORDER.index(c) if c in self._CURRENCY_ORDER else 100, c)
        )

        # Render per-currency invested value + P&L paired together
        for i, cur in enumerate(sorted_currencies):
            entry = by_currency[cur]
            sym = self._CURRENCY_SYMBOLS.get(cur, cur + " ")
            inv = entry["invested"]
            pnl = entry["pnl"]

            # Small gap between currency groups (not before the first)
            top_pad = 6 if i > 0 else 0

            # Invested line
            row = tk.Frame(self._summary_values_frame, bg=_card_bg)
            row.pack(fill=tk.X, pady=(top_pad, 0))
            tk.Label(row, text=f"{sym}{inv:,.0f}", bg=_card_bg,
                     fg=ModernStyle.SIDEBAR_FG, font=ModernStyle.FONT_TITLE, anchor="w").pack(side=tk.LEFT)

            # P&L line immediately below its invested value
            pnl_row = tk.Frame(self._summary_values_frame, bg=_card_bg)
            pnl_row.pack(fill=tk.X, pady=(0, 0))
            color = ModernStyle.TICKER_UP if pnl >= 0 else ModernStyle.TICKER_DOWN
            arrow = "▲" if pnl >= 0 else "▼"
            tk.Label(pnl_row, text=f"{arrow} P&L {sym}{abs(pnl):,.0f}", bg=_card_bg,
                     fg=color, font=ModernStyle.FONT_SMALL, anchor="w").pack(side=tk.LEFT)

    def _update_status_badge_ui(self, text, fg):
        self._status_badge.configure(text=text, fg=fg)

    def refresh_sidebar_data(self):
        """Public method: re-fetch sidebar investment & status data.

        Called by the Dashboard refresh button after market data is updated.
        """
        self._refresh_summary_card()
        self._refresh_status_badge()

    def _pulse_step(self):
        """Show the status dot, bright and steady.

        It used to beat once a second, but every change to the dot makes Tk redraw the
        whole window (about 0.07 s on a Retina Mac), which kept the app about 7% busy
        even when idle and made clicks wait behind it.
        """
        try:
            self._pulse_canvas.itemconfig(self._pulse_glow, outline=ModernStyle.TICKER_UP)
            self._pulse_canvas.itemconfig(self._pulse_dot, fill=ModernStyle.TICKER_UP)
        except Exception:
            pass

    def _show_ticker_loading(self):
        """Show the Loading... placeholder before data arrives."""
        for w in self.tickers_container.winfo_children():
            w.destroy()
        lbl = tk.Label(self.tickers_container, text="Loading...", bg=self.sidebar_bg, fg=ModernStyle.SIDEBAR_MUTED, font=ModernStyle.FONT_SMALL)
        lbl.pack(anchor="w")


    def _on_tickers_fetched(self):
        """Called from the ticker thread when prices are ready: hand over to the Tk thread."""
        call_on_ui(lambda: self.winfo_exists() and self._render_tickers())

    def _render_tickers(self):
        """Redraw the ticker labels using cached data."""
        import model.tickers as tck
        from datetime import datetime

        # Show when the prices were actually fetched, not when they were drawn
        fetched = tck.get_fetched_at() if hasattr(tck, "get_fetched_at") else None
        if fetched:
            when = datetime.fromtimestamp(fetched)
            today = when.date() == datetime.now().date()
            # Beside the heading: the time today, else just the day (the tip has both)
            self._ticker_time_lbl.config(text=when.strftime("%H:%M" if today else "%d %b"))
            self._ticker_time_tip.text = "Prices as of " + when.strftime("%H:%M" if today else "%d %b, %H:%M")
        else:
            self._ticker_time_lbl.config(text="—")
            self._ticker_time_tip.text = "Prices not fetched yet"

        if self._collapsed:
            return
        if not self._ticker_frame.winfo_ismapped():
            self._ticker_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 6), after=self._profile_divider)

        data = tck.get_mini_tickers()

        for w in self.tickers_container.winfo_children():
            w.destroy()




        if not data:
            # FIX: show retry button on failure
            err_row = tk.Frame(self.tickers_container, bg=self.sidebar_bg)
            err_row.pack(fill=tk.X)
            lbl = tk.Label(err_row, text="No data", bg=self.sidebar_bg, fg=ModernStyle.SIDEBAR_MUTED, font=ModernStyle.FONT_SMALL)
            lbl.pack(side=tk.LEFT)
            retry_lbl = tk.Label(err_row, text="↺ Retry", bg=self.sidebar_bg, fg=self.accent_primary,
                                 font=ModernStyle.FONT_SMALL_BOLD, cursor="hand2")
            retry_lbl.pack(side=tk.RIGHT)
            retry_lbl.bind("<Button-1>", lambda e: self.refresh_tickers())
            

        else:
            for name, info in data.items():
                row = tk.Frame(self.tickers_container, bg=self.sidebar_bg)
                row.pack(fill=tk.X, pady=0)

                lbl1 = tk.Label(row, text=name, bg=self.sidebar_bg, fg=ModernStyle.SIDEBAR_FG, font=ModernStyle.FONT_TICKER_SYMBOL, padx=0)
                lbl1.pack(side=tk.LEFT)

                pct = info.get("pct", 0.0)
                cp  = info.get("price", 0.0)

                # Use high-contrast colors optimized for the dark sidebar background
                color = ModernStyle.TICKER_UP if pct >= 0 else ModernStyle.TICKER_DOWN
                arrow = "▲" if pct >= 0 else "▼"

                if "/" in name:
                    # Currency pair - keep decimals for precision
                    if "USD" in name:
                        val_str = f"{cp:.2f}"
                    else:
                        val_str = f"{cp:,.3f}"
                else:
                    # Market index - round to whole number (no fractions)
                    val_str = f"{cp:,.0f}"

                lbl2 = tk.Label(row, text=f"{val_str} {arrow}{abs(pct):.1f}%", bg=self.sidebar_bg, fg=color, font=ModernStyle.FONT_TICKER_VALUE, padx=0)
                lbl2.pack(side=tk.RIGHT)



    def refresh_tickers(self):
        """Trigger a fresh background fetch, then re-render. Called by the Dashboard Refresh button."""
        import model.tickers as tck
        self._show_ticker_loading()
        tck.refresh_mini_tickers(callback=self._on_tickers_fetched)

    def _update_scrollbar_visibility(self):
        pass

    def _schedule_fit(self):
        if getattr(self, "_fit_after_id", None):
            self.after_cancel(self._fit_after_id)
        self._fit_after_id = self.after(120, self._fit_to_height)

    def _fit_to_height(self):
        """Keep the sidebar from needing to scroll: if the menu, summary and
        market list don't fit (small window, Large text), hide the logo; show it
        again when there is room."""
        self._fit_after_id = None
        if self._collapsed or not hasattr(self, "_logo_lbl"):
            return
        # Keep the active-page marker beside its button when the menu moves
        # (e.g. the summary card above it filled in after start-up)
        btn = self.buttons.get(self._active_idx)
        if btn is not None:
            self._animate_indicator(btn.master.winfo_y() + btn.winfo_y())
        need = self.middle_content.winfo_reqheight()
        have = self._middle_canvas.winfo_height()
        logo_h = self._logo_container.winfo_reqheight() + 8
        status_h = self._status_row.winfo_reqheight() + 6
        compact_h = len(self.buttons) * (self._NAV_BTN_H - self._NAV_BTN_H_COMPACT)
        logo_on = self._logo_container.winfo_ismapped()
        status_on = self._status_row.winfo_ismapped()
        compact = self._nav_h != self._NAV_BTN_H
        heading_h = self._nav_header.winfo_reqheight() + 6
        heading_on = self._nav_header.winfo_ismapped()
        # Give way in four steps: the logo first, then the "85 active · prices …" line
        # (the status bar at the bottom of the window shows the same), then shorter
        # menu buttons, then the "NAVIGATION" heading (a 1080p screen needs all four).
        # Room comes back in the reverse order. Each change resizes the sidebar,
        # which runs this again.
        if need > have:
            if logo_on:
                self._logo_container.pack_forget()
            elif status_on:
                self._status_row.pack_forget()
            elif not compact:
                self._set_nav_height(self._NAV_BTN_H_COMPACT)
            elif heading_on:
                self._nav_header.pack_forget()
        elif not heading_on and need + heading_h <= have:
            self._nav_header.pack(fill=tk.X, padx=16, pady=(6, 0), before=self._nav_gold_sep)
        elif compact and need + compact_h <= have:
            self._set_nav_height(self._NAV_BTN_H)
        elif not compact and not status_on and need + status_h <= have:
            self._status_row.pack(fill=tk.X, pady=(6, 0))
        elif not compact and status_on and not logo_on and need + logo_h <= have:
            self._logo_container.pack(fill=tk.X, pady=(8, 0), after=self._title_stack.master)

    def _set_nav_height(self, h: int) -> None:
        """Resize every menu button (and the active-page marker) to h pixels."""
        self._nav_h = h
        for btn in self.buttons.values():
            btn.set_size(height=h)
        self._sliding_indicator.coords(self._sliding_indicator_id, 2, 3, 2, h - 3)


class PTrackerApp:
    """Main application controller."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PTracker - Portfolio Tracker")

        # 1. Temporarily hide the window to eliminate the startup visual flash on macOS
        self.root.withdraw()

        # Theme first, so every widget built below gets the right colours and fonts
        ModernStyle.apply_theme(root)
        ModernStyle.improve_treeview_scrolling(root)
        start_ui_dispatcher(root)
        install_row_hover(root)
        self._last_error_toast = 0.0
        root.report_callback_exception = self._report_callback_exception

        # 2. Size: 60% x 80% of the screen, never smaller than what the pages need,
        #    never bigger than the screen. The window can be resized and maximised.
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        target_w = min(int(screen_w * 0.60), screen_w)
        target_h = min(int(screen_h * 0.80), screen_h - 60)
        self.root.resizable(False, False)
        self.root.geometry(f"{target_w}x{target_h}")
        try:
            self.root.update_idletasks()
            center_window(self.root)
        except Exception:
            pass
        self.root.deiconify()

        # Dock icon when running from source (the built .app already has its .icns)
        self._app_icon: tk.PhotoImage | None = None
        if not getattr(sys, 'frozen', False):
            self.root.after(500, self._set_app_icon)

        # Store for cleanup
        atexit.register(lambda: close_all_connections(optimize=False))
        from model import price_worker
        atexit.register(price_worker.shutdown)

        # Initialize database schemas in background so the window opens instantly.
        # Views are not shown until after navigate(0), giving this thread ample time.
        self.app_state = AppState(root)
        self._db_ready = False

        def _init_db_bg():
            try:
                from model.database import initialize_database, ensure_marketdata_schema, ensure_watchlist_schema
                initialize_database()
                ensure_marketdata_schema()
                ensure_watchlist_schema()
            except Exception:
                log.exception("Database set-up failed")
            finally:
                self._db_ready = True
            # The tables for Holdings and Trade History (and pandas) a little later, so they
            # don't slow the first page down; those pages load them at once if opened sooner
            time.sleep(2.5)
            try:
                self.app_state.refresh_data_cache_async()
            except Exception:
                log.exception("Could not start loading the data cache")
            try:
                # An automatic backup every 5 days; the last 5 are kept
                from model.backup import auto_backup_if_due
                made = auto_backup_if_due()
                if made:
                    log.info("Automatic backup saved: %s", made)
            except Exception:
                log.exception("Automatic backup failed")

        threading.Thread(target=_init_db_bg, daemon=True).start()


        # ── Status Bar (Bottom) ──────────────────────────────────────────────
        self.status_bar_frame = tk.Frame(root, bg=ModernStyle.BG_TERTIARY, height=28)
        self.status_bar_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_bar_frame.pack_propagate(False)
        tk.Frame(self.status_bar_frame, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", side=tk.TOP)
        self.status_lbl = tk.Label(
            self.status_bar_frame,
            text="● Starting up...",
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
        self.app_state.sidebar = self.sidebar   # views refresh the sidebar totals/tickers through this

        # Content area
        self.content_frame = ModernFrame(main_frame, bg=ModernStyle.BG_PRIMARY)
        self.content_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # View manager (with app_state)
        self.view_manager = ViewManager(self.content_frame, app_state=self.app_state)

        # Initialize views (import them here to avoid circular imports)
        self._setup_views()

        # Expose app on root window so views can find ViewManager via winfo_toplevel()
        try:
            self.root._ptracker_app = self
        except Exception:
            pass

        # Show the first view once the window (sidebar, status bar) has been drawn,
        # so the app appears straight away instead of after the Dashboard is built.
        self.root.after(50, lambda: self.navigate(0))

        # Start background tasks
        self._start_auto_refresh()
        self.root.after(3000, self._update_status_loop)

    def _update_status_loop(self):
        """Refresh the bottom status bar every 15 s (the work runs in the background)."""
        from model.database import db_session
        from model.engine import get_dashboard_metrics
        from datetime import datetime

        def _work():
            metrics = get_dashboard_metrics(force_refresh=False)
            val = metrics.get('total_value', 0.0)
            with db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT count(1) FROM holdings WHERE qty > 0")
                count = cur.fetchone()[0]
                cur.execute("SELECT max(last_updated) FROM marketdata")
                last_ts = cur.fetchone()[0]

            time_str = "unknown"
            if last_ts:
                try:
                    dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M:%S")
                    diff = int((datetime.now() - dt).total_seconds() / 60)
                    if diff < 1:
                        time_str = "just now"
                    elif diff < 60:
                        time_str = f"{diff} min ago"
                    else:
                        time_str = f"{diff // 60} hrs ago"
                except ValueError:
                    pass
            try:
                from model.engine import get_fx_estimates
                estimated = sorted(get_fx_estimates())
            except Exception:
                estimated = []
            return time_str, count, val, estimated

        def _show(result):
            time_str, count, val, estimated = result
            fx_note = f"   |   ≈ estimated {'/'.join(estimated)} rate" if estimated else ""
            self.status_lbl.config(
                text=f"● Prices updated {time_str}   ·   {count} active holdings   ·   "
                     f"₹{val:,.0f} total value (all currencies, in ₹){fx_note}"
            )

        run_in_background(_work, on_done=_show, widget=self.status_lbl, name="status-bar")
        self._show_market_status()

        # Re-run every 15 seconds
        self.root.after(15000, self._update_status_loop)

    def _show_market_status(self):
        """NSE open/closed, worked out in India time whatever the Mac's time zone (holidays not included)."""
        from datetime import datetime
        try:
            from zoneinfo import ZoneInfo
            now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        except Exception:
            from datetime import timezone, timedelta
            now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        weekday = now_ist.weekday()  # 0=Mon, 6=Sun
        t_min = now_ist.hour * 60 + now_ist.minute
        if weekday < 5 and 555 <= t_min <= 930:  # 9:15 - 15:30
            self._market_status_lbl.config(text="│  ● NSE Open", fg=ModernStyle.SUCCESS)
        elif weekday < 5 and 540 <= t_min < 555:  # 9:00 - 9:15
            self._market_status_lbl.config(text="│  ◐ NSE Pre-Market", fg=ModernStyle.WARNING)
        else:
            self._market_status_lbl.config(text="│  ○ NSE Closed", fg=ModernStyle.TEXT_TERTIARY)

    def _start_auto_refresh(self) -> None:
        def _silent_refresh():
            def _work():
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

            def _update_ui(_result=None):
                # 4. Sidebar tickers and 5. the visible view reload, on the Tk thread
                if hasattr(self, "sidebar"):
                    self.sidebar.refresh_tickers()
                    self.sidebar.refresh_sidebar_data()
                if not hasattr(self, "view_manager"):
                    return
                for name, v in self.view_manager.views.items():
                    try:
                        v._data_loaded = False
                        if self.view_manager.current_view == name and hasattr(v, "load_data"):
                            v.load_data()
                    except Exception:
                        log.exception("Reloading view %s after the price refresh failed", name)

            run_in_background(_work, on_done=_update_ui, name="price-refresh")
            self.root.after(900000, _silent_refresh)

        # Kickoff after 45 seconds (45,000 ms) instead of waiting 15 mins for first run
        self.root.after(45000, _silent_refresh)

    def _set_app_icon(self) -> None:
        """Dock icon when running from source (small pre-sized PNG; the .app uses its .icns)."""
        try:
            icon_path = _asset_path("images", "app_icon_128.png")
            if not icon_path.exists():
                return
            self._app_icon = tk.PhotoImage(file=str(icon_path))
            try:
                self.root.iconphoto(True, self._app_icon)
            except tk.TclError:
                pass
        except Exception:
            log.exception("Could not set the Dock icon")
            self._app_icon = None

    def _report_callback_exception(self, exc, val, tb):
        """An error inside a button, timer or other Tk callback: log it and tell the user once."""
        import time
        log.error("Error in a Tk callback", exc_info=(exc, val, tb))
        now = time.time()
        if now - self._last_error_toast > 5:
            self._last_error_toast = now
            try:
                show_toast(self.root, "Something went wrong. The details are in the log "
                           "(Settings → Show Log).", type="error")
            except Exception:
                pass

    def _setup_views(self):
        """Register all views as lazy import strings — modules are only imported
        the first time a user navigates to that view, not at startup."""
        self.view_manager.register_view('dashboard',     'views.dashboard_view.DashboardView')
        self.view_manager.register_view('holdings',      'views.holdings_view.HoldingsView')
        self.view_manager.register_view('trade_entry',   'views.trade_entry_view.TradeEntryView')
        self.view_manager.register_view('trade_history', 'views.trade_history_view.TradeHistoryView')
        self.view_manager.register_view('settings',      'views.settings_view.SettingsView')
        self.view_manager.register_view('help',          'views.help_view.HelpView')
        self.view_manager.register_view('tax',           'views.tax_report_view.TaxReportView')
        self.view_manager.register_view('broker_report', 'views.broker_report_view.BrokerReportView')
        self.view_manager.register_view('watchlist',     'views.watchlist_view.WatchlistView')
        self.view_manager.register_view('valuation',     'views.valuation_view.ValuationView')
        self.view_manager.register_view('news',          'views.news_view.NewsView')

    VIEW_ORDER = ('dashboard', 'holdings', 'trade_entry', 'trade_history', 'tax', 'broker_report', 'watchlist',
                  'valuation', 'news', 'settings', 'help')   # the sidebar's order

    def navigate_to(self, name: str) -> None:
        """Open a page by name, as its sidebar button does."""
        if name in self.VIEW_ORDER:
            self.navigate(self.VIEW_ORDER.index(name))

    def navigate(self, view_idx: int):
        """Navigate to a view by index."""
        views = self.VIEW_ORDER
        if 0 <= view_idx < len(views):
            try:
                if hasattr(self, "sidebar") and hasattr(self.sidebar, "set_active"):
                    self.sidebar.set_active(view_idx)
                self.view_manager.show_view(views[view_idx])
            except Exception:
                log.exception("Error loading view %s", views[view_idx])
                show_toast(self.root, f"Couldn't open {views[view_idx].replace('_', ' ').title()}. "
                           "The details are in the log.", type="error")

def main():
    """Application entry point."""
    setup_logging()
    _install_macos_openpanel_stderr_filter()

    # Enable High-DPI awareness on Windows before creating the root window
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()
    # The red close button (and ⌘W) hides the window, as Mac apps do; clicking
    # the Dock icon brings it back. ⌘Q and the ⏻ button quit.
    def on_closing():
        root.withdraw()

    def on_reopen():
        root.deiconify()
        root.lift()

    root.protocol("WM_DELETE_WINDOW", on_closing)

    # Handle dock icon click on macOS to restore the window
    try:
        root.createcommand('tk::mac::ReopenApplication', on_reopen)
    except Exception:
        pass

    app = PTrackerApp(root)
    root.bind_all("<Command-w>", lambda _e: on_closing())
    try:
        root.createcommand("tk::mac::Quit", app.sidebar._do_quit)
    except Exception:
        pass
    root.mainloop()

# source .venv/bin/activate
# python3 -m PyInstaller --noconfirm PortfolioTrack.spec
if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()   # the price helper process, in the built app too
    main()
