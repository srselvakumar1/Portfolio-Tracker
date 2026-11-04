#!/usr/bin/env python3
"""Central UI theme tokens and ttk styling for PTracker.

HOW TO USE:
    from ui.ui_theme import ModernStyle

    tk.Label(..., font=ModernStyle.FONT_BODY, fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_SECONDARY)

    # Apply global ttk theme at app startup (call once from main.py)
    ModernStyle.apply_theme(root)

THEMES:
    The palette is picked ONCE, when this module is imported, from the saved
    settings (Settings → Appearance): Light, Dark, or Match macOS. Colours are
    read when widgets are built, so a change applies after a restart.

    Use the ROLE names below, never hex literals, so both themes work:
      Surfaces   BG_PRIMARY (window), BG_SECONDARY (cards), BG_TERTIARY (filter
                 bars, alt rows), ENTRY_BG, BG_HOVER, BORDER_COLOR, DIVIDER_COLOR
      Text       TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY (hints),
                 TEXT_ACCENT (blue text/links), TEXT_PURPLE
      Gain/loss  SUCCESS, ERROR, WARNING, INFO = coloured TEXT and small marks
                 (P&L numbers, arrows, badges' text)
      Fills      ACCENT_PRIMARY, SUCCESS_FILL, ERROR_FILL, WARNING_FILL,
                 INFO_FILL, PURPLE_FILL, NEUTRAL_FILL (Cancel/Close) =
                 solid button/badge backgrounds; put TEXT_ON_ACCENT (white) on them
      Tints      SUCCESS_PALE, ERROR_PALE, WARNING_PALE, INFO_PALE,
                 ACCENT_PRIMARY_PALE, ACCENT_PURPLE_PALE = soft backgrounds for
                 chips and highlighted rows; KPI_TINT_* for KPI cards
      Tables     TABLE_HEADER_BG/FG/HOVER, TABLE_ROW_ALT/GAIN/LOSS, TABLE_SELECTED_BG/FG
      Header     HEADER_GRAD_START/END (RGB tuples), HEADER_FG, HEADER_SUBTLE_FG
      Sidebar    SIDEBAR_* (the sidebar is dark in both themes)
"""

from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from tkinter import ttk

from model.app_settings import load_settings

# ──────────────────────────────────────────────────────────────────────────────
# PALETTES
# Text colours meet WCAG AA (4.5:1) on BG_PRIMARY, BG_SECONDARY, BG_TERTIARY and
# the KPI tints; white TEXT_ON_ACCENT meets it on every *_FILL colour.
# ──────────────────────────────────────────────────────────────────────────────
_SLATE = {
    50: "#F8FAFC", 100: "#F1F5F9", 200: "#E2E8F0", 300: "#CBD5E1", 400: "#94A3B8",
    500: "#64748B", 600: "#475569", 700: "#334155", 800: "#1E293B", 900: "#0F172A",
}

_COMMON = {
    # Solid fills: identical in both themes, always with white text
    "ACCENT_PRIMARY": "#2563EB",
    "SUCCESS_FILL":   "#15803D",
    "ERROR_FILL":     "#B91C1C",
    "WARNING_FILL":   "#B45309",
    "INFO_FILL":      "#0E7490",
    "PURPLE_FILL":    "#7E22CE",
    "NEUTRAL_FILL":   "#475569",
    "TEXT_ON_ACCENT": "#FFFFFF",

    "BRAND_GOLD":     "#D4AF37",

    # Sidebar (dark in both themes)
    "SIDEBAR_BG":       "#1E293B",
    "SIDEBAR_BG_ALT":   "#253347",   # summary card
    "SIDEBAR_HOVER":    "#334155",
    "SIDEBAR_PRESSED":  "#475569",
    "SIDEBAR_ACTIVE_BG": "#334155",
    "SIDEBAR_BORDER":   "#0F172A",
    "SIDEBAR_FG":       "#E2E8F0",
    "SIDEBAR_MUTED":    "#94A3B8",
    "SIDEBAR_HINT":     "#FDE68A",   # "last updated" line
    "TICKER_UP":        "#4ADE80",
    "TICKER_DOWN":      "#F87171",
    "QUIT_BG":          "#2A1B24",
    "QUIT_BG_HOVER":    "#451A24",
    "QUIT_FG":          "#FCA5A5",
    "QUIT_FG_HOVER":    "#FECACA",

    # Gradient header text (white on the indigo→pink banner)
    "HEADER_FG":        "#FFFFFF",
    "HEADER_SUBTLE_FG": "#E0E7FF",
    "HEADER_WARN_FG":   "#FDE68A",   # light amber warnings on the banner
}

LIGHT = {
    **_COMMON,
    "NAME": "light",
    "BG_PRIMARY":   "#F8FAFC",
    "BG_SECONDARY": "#FFFFFF",
    "BG_TERTIARY":  "#F1F5F9",
    "ENTRY_BG":     "#FFFFFF",
    "BG_HOVER":     "#EEF2F7",
    "BORDER_COLOR": "#E5E7EB",
    "INPUT_BORDER": "#CBD5E1",   # around text inputs: clearly visible on white cards
    "DIVIDER_COLOR": "#E2E8F0",

    "TEXT_PRIMARY":   "#0F172A",
    "TEXT_SECONDARY": "#475569",
    "TEXT_TERTIARY":  "#5B6B80",
    "TEXT_ACCENT":    "#1D4ED8",
    "TEXT_PURPLE":    "#7E22CE",

    "SUCCESS": "#15803D",
    "ERROR":   "#B91C1C",
    "WARNING": "#B45309",
    "INFO":    "#0E7490",

    "SUCCESS_PALE": "#DCFCE7",
    "ERROR_PALE":   "#FEE2E2",
    "WARNING_PALE": "#FEF3C7",
    "INFO_PALE":    "#CFFAFE",
    "ACCENT_PRIMARY_PALE": "#DBEAFE",
    "ACCENT_PURPLE_PALE":  "#EDE9FE",
    "ACCENT_PURPLE":       "#9333EA",

    "KPI_TINT_BLUE":   "#EFF6FF",
    "KPI_TINT_GREEN":  "#F0FDF4",
    "KPI_TINT_RED":    "#FEF2F2",
    "KPI_TINT_AMBER":  "#FFFBEB",
    "KPI_TINT_PURPLE": "#F5F3FF",
    "KPI_TINT_TEAL":   "#ECFEFF",

    "TABLE_HEADER_BG":    "#D0CDF2",   # every table's heading row: a lavender tint of the page header's indigo
    "TABLE_HEADER_FG":    "#312E81",
    "TABLE_HEADER_HOVER": "#BDB9EC",
    "TABLE_ROW_ALT":      "#F4F6F9",   # zebra stripes: visible on white, lighter than the hover
    "TABLE_ROW_GAIN":     "#F3FEF7",   # Holdings rows in profit / at a loss: a third-strength pale
    "TABLE_ROW_LOSS":     "#FFF5F5",
    "TABLE_SELECTED_BG":  "#2563EB",
    "TABLE_SELECTED_FG":  "#FFFFFF",

    "HEADER_GRAD_START": (67, 56, 202),   # #4338CA indigo
    "HEADER_GRAD_MID":   (124, 58, 237),  # #7C3AED violet
    "HEADER_GRAD_END":   (190, 24, 93),   # #BE185D pink (white text stays 6:1)
}

DARK = {
    **_COMMON,
    "NAME": "dark",
    "BG_PRIMARY":   "#0B1220",
    "BG_SECONDARY": "#131C2E",
    "BG_TERTIARY":  "#1B2640",
    "ENTRY_BG":     "#0F1A2C",
    "BG_HOVER":     "#1E2A45",
    "BORDER_COLOR": "#26344F",
    "INPUT_BORDER": "#3B4D70",
    "DIVIDER_COLOR": "#22304A",

    "TEXT_PRIMARY":   "#E5E9F0",
    "TEXT_SECONDARY": "#C3CCD9",
    "TEXT_TERTIARY":  "#94A3B8",
    "TEXT_ACCENT":    "#93C5FD",
    "TEXT_PURPLE":    "#C4B5FD",

    "SUCCESS": "#4ADE80",
    "ERROR":   "#F87171",
    "WARNING": "#FBBF24",
    "INFO":    "#22D3EE",

    "SUCCESS_PALE": "#0F2E1F",
    "ERROR_PALE":   "#3A1518",
    "WARNING_PALE": "#33260A",
    "INFO_PALE":    "#0B2B33",
    "ACCENT_PRIMARY_PALE": "#172A4D",
    "ACCENT_PURPLE_PALE":  "#261B47",
    "ACCENT_PURPLE":       "#A78BFA",

    "KPI_TINT_BLUE":   "#14213D",
    "KPI_TINT_GREEN":  "#0F2A1E",
    "KPI_TINT_RED":    "#2E1519",
    "KPI_TINT_AMBER":  "#2B220E",
    "KPI_TINT_PURPLE": "#211A3D",
    "KPI_TINT_TEAL":   "#0C2730",

    "TABLE_HEADER_BG":    "#292974",
    "TABLE_HEADER_FG":    "#C7D2FE",
    "TABLE_HEADER_HOVER": "#2D2B84",
    "TABLE_ROW_ALT":      "#18233A",   # zebra stripes: a shade lighter than the card, below the hover
    "TABLE_ROW_GAIN":     "#122229",
    "TABLE_ROW_LOSS":     "#211A26",
    "TABLE_SELECTED_BG":  "#2563EB",
    "TABLE_SELECTED_FG":  "#FFFFFF",

    "SIDEBAR_BG":       "#111827",
    "SIDEBAR_BG_ALT":   "#1B2537",
    "SIDEBAR_BORDER":   "#05080F",

    "HEADER_GRAD_START": (49, 46, 129),   # #312E81
    "HEADER_GRAD_MID":   (76, 29, 149),   # #4C1D95
    "HEADER_GRAD_END":   (131, 24, 67),   # #831843
}

TEXT_SCALES = {"small": 0.96, "normal": 1.0, "large": 1.12, "xlarge": 1.25}


def _macos_is_dark() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                             capture_output=True, text=True, timeout=2)
        return "dark" in out.stdout.lower()
    except Exception:
        return False


_SETTINGS = load_settings()
_THEME_CHOICE = _SETTINGS.get("theme", "light")
_PALETTE = DARK if (_THEME_CHOICE == "dark" or (_THEME_CHOICE == "system" and _macos_is_dark())) else LIGHT
_SCALE = TEXT_SCALES.get(_SETTINGS.get("text_size", "normal"), 1.0)

_FAMILY = (
    "Segoe UI" if sys.platform == "win32"
    else ("Helvetica" if sys.platform == "darwin" else "Ubuntu")   # clean, with even-width digits
)
# The macOS system font (SF Pro) by its own name: asking for "SF Pro Display" gives the
# same font, but Tk first searched every installed font for it (0.15 s at each start)
_NAV_FAMILY = ".AppleSystemUIFont" if sys.platform == "darwin" else _FAMILY


def _calibri() -> str:
    """Calibri (the Dashboard's KPI card titles). On a Mac it comes with Microsoft Office,
    which keeps it to itself, so the app loads it from Word or Excel for its own use only
    (nothing is installed). Without Office: the app's usual font."""
    if sys.platform == "win32":
        return "Calibri"
    if sys.platform != "darwin":
        return _FAMILY
    from pathlib import Path
    home = Path.home()
    if any((d / "Calibri.ttf").exists() for d in (home / "Library/Fonts", Path("/Library/Fonts"))):
        return "Calibri"   # installed for every app
    try:
        import ctypes
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        ct = ctypes.CDLL("/System/Library/Frameworks/CoreText.framework/CoreText")
        cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
        cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
        ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
        ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        for app in ("Word", "Excel", "PowerPoint", "Outlook"):
            path = Path(f"/Applications/Microsoft {app}.app/Contents/Resources/DFonts/Calibri.ttf")
            if path.exists():
                raw = str(path).encode()
                url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
                if url and ct.CTFontManagerRegisterFontsForURL(url, 1, None):   # 1 = this app only
                    return "Calibri"
    except Exception:
        pass
    return _FAMILY


_KPI_FAMILY = _calibri()


def _f(size: int, *style: str) -> tuple:
    """A font tuple in the app's family, scaled by the Text Size setting."""
    return (_FAMILY, max(1, round(size * _SCALE)), *style)


class ModernStyle:
    """Centralized design system for PTracker (light or dark, see THEMES above).

    All fonts, colors, spacing and component dimensions are defined here.
    Views import this class directly — no ad-hoc color strings in view files.
    """

    THEME = _PALETTE["NAME"]          # "light" or "dark" (what is actually shown)
    THEME_CHOICE = _THEME_CHOICE      # what the user picked: light / dark / system
    TEXT_SIZE_CHOICE = _SETTINGS.get("text_size", "normal")
    IS_DARK = THEME == "dark"
    TEXT_SCALE = _SCALE

    FONT_FAMILY = _FAMILY

    # ──────────────────────────────────────────────────────────────
    # TYPOGRAPHIC SCALE (nothing below 12 pt; macOS body text is 13 pt)
    # ──────────────────────────────────────────────────────────────
    FONT_PAGE_TITLE  = _f(28, "bold")   # Dashboard, Holdings, Trade History headers
    FONT_TITLE       = _f(16, "bold")   # Modal titles, drilldown headers
    FONT_HEADING     = _f(14, "bold")   # Filter labels, table section headings
    FONT_SUBHEADING  = _f(13)           # regular: bold is kept for titles and values   # Card sub-labels, tooltip headers
    FONT_DASH_SYMBOL = _f(12)   # Dashboard performer symbol labels

    FONT_BODY        = _f(13)           # Descriptions, subtitles
    FONT_BODY_BOLD   = _f(13, "bold")
    FONT_SMALL       = _f(12)           # Timestamps, hints, metadata
    FONT_SMALL_BOLD  = _f(12, "bold")
    FONT_TINY        = _f(12)           # (same as SMALL: nothing smaller is readable)
    FONT_TABLE       = _f(13)           # Treeview body rows
    FONT_TABLE_BOLD  = _f(13, "bold")   # Treeview headings
    # Stock symbols in the Dashboard tables: bold, two points smaller, so they stand out without
    # looking bigger than their row (Tk has no semi-bold)
    FONT_TABLE_SYMBOL = (_FAMILY, _f(13)[1] - 2, "bold")
    FONT_DASHBOARD_TABLE      = _f(12)
    FONT_DASHBOARD_TABLE_BOLD = _f(12, "bold")
    FONT_REPORT_TABLE         = _f(13)
    FONT_REPORT_TABLE_BOLD    = _f(13, "bold")

    FONT_SYMBOL_LARGE  = _f(20, "bold")
    FONT_DRILLDOWN_SYM = _f(18, "bold")
    FONT_SECTION_LABEL = _f(16, "bold")
    FONT_MODAL_TITLE   = _f(15, "bold")
    FONT_EMPTY_STATE   = _f(22)

    FONT_SIDEBAR_TITLE = _f(18, "bold")
    FONT_SIDEBAR_BADGE = _f(12, "bold")

    FONT_ITALIC_SM     = _f(12, "italic")
    FONT_ITALIC        = _f(12, "italic")
    FONT_ITALIC_MD     = _f(13, "italic")
    FONT_TINY_BOLD     = _f(12, "bold")

    FONT_LOADING_ICON  = _f(22)
    FONT_MODAL_ICON    = _f(20)

    FONT_KPI_VALUE   = _f(20, "bold")
    FONT_KPI_LABEL   = _f(13)
    FONT_KPI_TITLE   = _f(13)   # KPI card titles, in the card's colour (regular, not bold)
    FONT_DASHBOARD_KPI_TITLE = (_KPI_FAMILY, _f(13)[1])   # the Dashboard's KPI card titles: Calibri, regular

    FONT_INPUT       = _f(13)

    # Label roles: the same kind of text looks the same on every page
    FONT_CARD_TITLE  = FONT_HEADING      # card and section titles, in TEXT_PRIMARY
    FONT_FIELD_LABEL = FONT_SMALL_BOLD   # labels of inputs and filters, in TEXT_SECONDARY
    FONT_HINT        = FONT_SMALL        # hints and captions, in TEXT_TERTIARY

    FONT_TICKER_SYMBOL = (_FAMILY, max(1, round(11 * _SCALE) - 1), "bold")   # 10 pt at Small text
    FONT_TICKER_VALUE  = _f(12, "normal")

    # The sidebar menu uses the system font (SF Pro on macOS), bold, like BookingManager
    FONT_NAV         = (_NAV_FAMILY, max(1, round(13 * _SCALE) - 1), "bold")   # 11 pt at Small text
    FONT_NAV_ACTIVE  = FONT_NAV
    NAV_ICON_PX      = round(20 * _SCALE)
    FONT_NAV_SECTION = _f(12)

    FONT_BADGE       = _f(12, "bold")
    FONT_ICON        = _f(13)

    # ──────────────────────────────────────────────────────────────
    # COMPONENT LAYOUT TOKENS
    # ──────────────────────────────────────────────────────────────
    KPI_CARD_HEIGHT          = round(120 * _SCALE)
    RADIUS_CARD              = 16   # corners: cards, panels and pop-up boxes
    RADIUS_BUTTON            = 12   #          standard buttons (pills give their own)
    RADIUS_INPUT             = 10   #          text and drop-down boxes
    RADIUS_HEADER            = 18   #          the page header banners
    ACCENT_BAR               = 2   # coloured bar beside KPI cards and line atop table cards
    CARD_SHADOW              = 2   # soft shadow under cards
    DASH_GRID_CARD_HEIGHT    = round(240 * _SCALE)
    DASH_SECTION_CARD_HEIGHT = round(300 * _SCALE)
    TABLE_ROW_HEIGHT         = round(34 * _SCALE)
    DRILLDOWN_ROW_HEIGHT     = round(30 * _SCALE)
    DASHBOARD_ROW_HEIGHT     = round(27 * _SCALE)   # Dashboard tables (13 pt text)

    NAV_ITEM_PADX        = 14
    NAV_ITEM_PADY        = 10
    NAV_ITEM_OUTER_PADX  = 10

    # Colours are filled in from the active palette right after the class body.
    SLATE_50 = SLATE_100 = SLATE_200 = SLATE_300 = SLATE_400 = None
    SLATE_500 = SLATE_600 = SLATE_700 = SLATE_800 = SLATE_900 = None

    # ──────────────────────────────────────────────────────────────
    # TTK GLOBAL THEME SETUP
    # Called once from main.py on app startup.
    # ──────────────────────────────────────────────────────────────
    @classmethod
    def apply_theme(cls, root: tk.Tk) -> None:
        """Apply the PTracker theme (light or dark) to all ttk and tk widgets.

        Must be called once after the root Tk window is created, before
        building any views. Uses the 'clam' base theme for cross-platform
        consistency.
        """
        style = ttk.Style(root)

        # ── TTK base theme ────────────────────────────────────────────────────
        try:
            themes = set(style.theme_names() or [])
            if "clam" in themes:
                style.theme_use("clam")
            else:
                print(f"Warning: ttk theme 'clam' not available. Available: {sorted(themes)}")
        except Exception as e:
            print(f"Warning: could not set ttk theme to 'clam': {e}")

        # ── TTK Widget Styles ─────────────────────────────────────────────────
        style.configure("TFrame",  background=cls.BG_PRIMARY)
        style.configure("TLabel",  background=cls.BG_PRIMARY, foreground=cls.TEXT_PRIMARY, font=cls.FONT_BODY)
        style.configure("TButton", font=cls.FONT_BODY)

        style.configure(
            "TEntry",
            fieldbackground=cls.ENTRY_BG,
            foreground=cls.TEXT_PRIMARY,
            insertcolor=cls.ACCENT_PRIMARY,
            bordercolor=cls.BORDER_COLOR,
            lightcolor=cls.BORDER_COLOR,
            darkcolor=cls.BORDER_COLOR,
        )

        style.configure(
            "TCombobox",
            fieldbackground=cls.ENTRY_BG,
            foreground=cls.TEXT_PRIMARY,
            background=cls.ENTRY_BG,
            arrowcolor=cls.TEXT_SECONDARY,
            bordercolor=cls.BORDER_COLOR,
            font=cls.FONT_BODY,
        )
        style.map("TCombobox",
            fieldbackground=[("readonly", cls.ENTRY_BG)],
            foreground=[("readonly", cls.TEXT_PRIMARY)],
            selectbackground=[("readonly", cls.ENTRY_BG)],
            selectforeground=[("readonly", cls.TEXT_PRIMARY)],
        )
        # Same height as the other inputs, and the accent border while it has the keyboard
        style.configure("TCombobox", padding=(6, 4))
        style.map("TCombobox", bordercolor=[("focus", cls.ACCENT_PRIMARY)],
                  lightcolor=[("focus", cls.ACCENT_PRIMARY)])
        # Inside a RoundedBox the box draws the border, so the combobox has none
        style.configure("Boxed.TCombobox", bordercolor=cls.ENTRY_BG, lightcolor=cls.ENTRY_BG,
                        darkcolor=cls.ENTRY_BG)
        style.map("Boxed.TCombobox", bordercolor=[("focus", cls.ENTRY_BG)], lightcolor=[("focus", cls.ENTRY_BG)])
        # The drop-down list of a Combobox is a plain Listbox
        root.option_add("*TCombobox*Listbox.background", cls.ENTRY_BG)
        root.option_add("*TCombobox*Listbox.foreground", cls.TEXT_PRIMARY)
        root.option_add("*TCombobox*Listbox.selectBackground", cls.ACCENT_PRIMARY)
        root.option_add("*TCombobox*Listbox.selectForeground", cls.TEXT_ON_ACCENT)
        root.option_add("*TCombobox*Listbox.font", cls.FONT_BODY)

        style.configure(
            "Treeview",
            background=cls.BG_SECONDARY,
            foreground=cls.TEXT_PRIMARY,
            fieldbackground=cls.BG_SECONDARY,
            bordercolor=cls.BORDER_COLOR,
            borderwidth=0,
            rowheight=cls.TABLE_ROW_HEIGHT,
            font=cls.FONT_TABLE,
        )
        style.configure(
            "Treeview.Heading",
            background=cls.TABLE_HEADER_BG,
            foreground=cls.TABLE_HEADER_FG,
            font=cls.FONT_TABLE_BOLD,
            relief="flat",
            borderwidth=0,
        )
        
        # Dashboard-specific treeviews
        style.configure(
            "Drilldown.Treeview",
            font=cls.FONT_DASHBOARD_TABLE,
            rowheight=cls.DRILLDOWN_ROW_HEIGHT
        )
        style.configure(
            "Drilldown.Treeview.Heading",
            font=cls.FONT_DASHBOARD_TABLE_BOLD
        )
        # The Dashboard's four tables: same 13 pt text as the other tables; how many
        # rows show is adjusted at run time so the Dashboard fits the window.
        style.configure("Dashboard.Treeview", font=cls.FONT_TABLE, rowheight=cls.DASHBOARD_ROW_HEIGHT, borderwidth=0)
        # No border of its own: the card edge is the only line under the table
        style.layout("Dashboard.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        # Calm: one light grey heading row in all four Dashboard tables
        style.configure("Dashboard.Treeview.Heading", font=cls.FONT_TABLE_BOLD,
                        background=cls.BG_TERTIARY, foreground=cls.TEXT_PRIMARY)
        style.map("Dashboard.Treeview.Heading", background=[("active", cls.BG_HOVER)],
                  foreground=[("active", cls.TEXT_PRIMARY)])
        try:
            style.map(
                "Treeview.Heading",
                background=[("active", cls.TABLE_HEADER_HOVER)],
                foreground=[("active", cls.TABLE_HEADER_FG)],
            )
        except Exception:
            pass
        style.map(
            "Treeview",
            background=[("selected", cls.TABLE_SELECTED_BG)],
            foreground=[("selected", cls.TABLE_SELECTED_FG)],
        )

        # Fix for Tkinter 8.6.9+ bug where Treeview tags foreground/background are ignored
        def fixed_map(option):
            return [elm for elm in style.map("Treeview", query_opt=option) if elm[:2] != ("!disabled", "!selected")]
        
        style.map("Treeview", foreground=fixed_map("foreground"), background=fixed_map("background"))
        style.map("Drilldown.Treeview", foreground=fixed_map("foreground"), background=fixed_map("background"))
        style.map("Dashboard.Treeview", foreground=fixed_map("foreground"), background=fixed_map("background"))

        style.configure(
            "TLabelframe",
            background=cls.BG_SECONDARY,
            bordercolor=cls.BORDER_COLOR,
            relief="flat",
        )
        style.configure(
            "TLabelframe.Label",
            background=cls.BG_SECONDARY,
            foreground=cls.TEXT_SECONDARY,
            font=cls.FONT_SMALL_BOLD,
        )

        style.configure(
            "TScrollbar",
            background=cls.BORDER_COLOR,
            troughcolor=cls.BG_PRIMARY,
            arrowcolor=cls.TEXT_TERTIARY,
            bordercolor=cls.BG_PRIMARY,
            lightcolor=cls.BORDER_COLOR,
            darkcolor=cls.BORDER_COLOR,
            relief="flat",
            borderwidth=0,
            width=10,
        )
        style.map("TScrollbar", background=[("active", cls.TEXT_TERTIARY)])

        style.configure(
            "TCheckbutton",
            background=cls.BG_PRIMARY,
            foreground=cls.TEXT_PRIMARY,
            font=cls.FONT_BODY,
            focuscolor="",
        )
        style.map("TCheckbutton",
            background=[("active", cls.BG_PRIMARY)],
            foreground=[("active", cls.ACCENT_PRIMARY)],
        )

        style.configure(
            "TRadiobutton",
            background=cls.BG_PRIMARY,
            foreground=cls.TEXT_PRIMARY,
            font=cls.FONT_BODY,
            focuscolor="",
        )
        style.map("TRadiobutton",
            background=[("active", cls.BG_PRIMARY)],
            foreground=[("active", cls.ACCENT_PRIMARY)],
        )

        style.configure(
            "TSpinbox",
            fieldbackground=cls.ENTRY_BG,
            foreground=cls.TEXT_PRIMARY,
            background=cls.BG_PRIMARY,
            arrowcolor=cls.TEXT_SECONDARY,
            bordercolor=cls.BORDER_COLOR,
            font=cls.FONT_BODY,
        )

        style.configure(
            "TScale",
            background=cls.BG_PRIMARY,
            troughcolor=cls.BG_TERTIARY,
            sliderrelief="flat",
        )

        style.configure("TSeparator", background=cls.BORDER_COLOR)

        style.configure(
            "TProgressbar",
            background=cls.ACCENT_PRIMARY,
            troughcolor=cls.BG_TERTIARY,
            bordercolor=cls.BORDER_COLOR,
            relief="flat",
        )

        style.configure(
            "TNotebook",
            background=cls.BG_PRIMARY,
            bordercolor=cls.BORDER_COLOR,
        )
        style.configure(
            "TNotebook.Tab",
            background=cls.BG_TERTIARY,
            foreground=cls.TEXT_SECONDARY,
            font=cls.FONT_SUBHEADING,
            padding=[12, 6],
        )
        style.map("TNotebook.Tab",
            background=[("selected", cls.BG_SECONDARY)],
            foreground=[("selected", cls.ACCENT_PRIMARY)],
        )

        # ── Global tk.* Widget Defaults (option_add) ──────────────────────────
        # Applies to ALL bare tk widgets app-wide — including drilldowns and
        # popups — without touching individual view files.
        p = "60"  # user priority: overrides Tk defaults, yields to explicit kwargs

        root.option_add("*Font",             cls.FONT_BODY,       p)
        root.option_add("*Background",       cls.BG_PRIMARY,      p)
        root.option_add("*Foreground",       cls.TEXT_PRIMARY,    p)

        # Label
        root.option_add("*Label.Font",       cls.FONT_BODY,       p)
        root.option_add("*Label.Background", cls.BG_PRIMARY,      p)
        root.option_add("*Label.Foreground", cls.TEXT_PRIMARY,    p)

        # A steady text cursor in every input: each blink made Tk redraw the window
        # (~0.07 s on a Retina Mac), so a field with the cursor in it kept the app
        # about 17% busy and every click on that page waited behind the blinking
        root.option_add("*insertOffTime", 0, p)

        # Entry
        root.option_add("*Entry.Font",                cls.FONT_BODY,       p)
        root.option_add("*Entry.Background",          cls.ENTRY_BG,        p)
        root.option_add("*Entry.Foreground",          cls.TEXT_PRIMARY,    p)
        root.option_add("*Entry.InsertBackground",    cls.ACCENT_PRIMARY,  p)
        root.option_add("*Entry.HighlightBackground", cls.BORDER_COLOR,    p)
        root.option_add("*Entry.HighlightColor",      cls.ACCENT_PRIMARY,  p)
        root.option_add("*Entry.HighlightThickness",  1,                   p)
        root.option_add("*Entry.Relief",              "flat",              p)
        root.option_add("*Entry.SelectBackground",    cls.ACCENT_PRIMARY,  p)
        root.option_add("*Entry.SelectForeground",    cls.TEXT_ON_ACCENT,  p)

        # Text
        root.option_add("*Text.Font",                cls.FONT_BODY,        p)
        root.option_add("*Text.Background",          cls.ENTRY_BG,         p)
        root.option_add("*Text.Foreground",          cls.TEXT_PRIMARY,     p)
        root.option_add("*Text.InsertBackground",    cls.ACCENT_PRIMARY,   p)
        root.option_add("*Text.HighlightBackground", cls.BORDER_COLOR,     p)
        root.option_add("*Text.HighlightColor",      cls.ACCENT_PRIMARY,   p)
        root.option_add("*Text.HighlightThickness",  1,                    p)
        root.option_add("*Text.Relief",              "flat",               p)
        root.option_add("*Text.SelectBackground",    cls.ACCENT_PRIMARY,   p)
        root.option_add("*Text.SelectForeground",    cls.TEXT_ON_ACCENT,   p)

        # Listbox
        root.option_add("*Listbox.Font",               cls.FONT_BODY,      p)
        root.option_add("*Listbox.Background",         cls.BG_SECONDARY,   p)
        root.option_add("*Listbox.Foreground",         cls.TEXT_PRIMARY,   p)
        root.option_add("*Listbox.SelectBackground",   cls.ACCENT_PRIMARY, p)
        root.option_add("*Listbox.SelectForeground",   cls.TEXT_ON_ACCENT, p)
        root.option_add("*Listbox.HighlightBackground",cls.BORDER_COLOR,   p)
        root.option_add("*Listbox.HighlightColor",     cls.ACCENT_PRIMARY, p)
        root.option_add("*Listbox.HighlightThickness", 1,                  p)
        root.option_add("*Listbox.Relief",             "flat",             p)

        # Button (bare tk.Button — prefer canvas ModernButton)
        root.option_add("*Button.Font",            cls.FONT_BODY,      p)
        root.option_add("*Button.Background",      cls.BG_TERTIARY,    p)
        root.option_add("*Button.Foreground",      cls.TEXT_PRIMARY,   p)
        root.option_add("*Button.ActiveBackground",cls.BORDER_COLOR,   p)
        root.option_add("*Button.ActiveForeground",cls.ACCENT_PRIMARY, p)
        root.option_add("*Button.Relief",          "flat",             p)
        root.option_add("*Button.Cursor",          "hand2",            p)
        root.option_add("*Button.PadX",            10,                 p)
        root.option_add("*Button.PadY",            5,                  p)

        # Checkbutton / Radiobutton
        root.option_add("*Checkbutton.Font",            cls.FONT_BODY,      p)
        root.option_add("*Checkbutton.Background",      cls.BG_PRIMARY,     p)
        root.option_add("*Checkbutton.Foreground",      cls.TEXT_PRIMARY,   p)
        root.option_add("*Checkbutton.ActiveBackground",cls.BG_PRIMARY,     p)
        root.option_add("*Checkbutton.ActiveForeground",cls.ACCENT_PRIMARY, p)
        root.option_add("*Checkbutton.SelectColor",     cls.ACCENT_PRIMARY, p)
        root.option_add("*Radiobutton.Font",            cls.FONT_BODY,      p)
        root.option_add("*Radiobutton.Background",      cls.BG_PRIMARY,     p)
        root.option_add("*Radiobutton.Foreground",      cls.TEXT_PRIMARY,   p)
        root.option_add("*Radiobutton.SelectColor",     cls.ACCENT_PRIMARY, p)

        # Scale
        root.option_add("*Scale.Background",  cls.BG_PRIMARY,   p)
        root.option_add("*Scale.Foreground",  cls.ACCENT_PRIMARY, p)
        root.option_add("*Scale.TroughColor", cls.BG_TERTIARY,   p)

        # Scrollbar — slim and minimal
        root.option_add("*Scrollbar.Background",       cls.BORDER_COLOR, p)
        root.option_add("*Scrollbar.TroughColor",      cls.BG_PRIMARY,   p)
        root.option_add("*Scrollbar.ActiveBackground", cls.TEXT_TERTIARY, p)
        root.option_add("*Scrollbar.Relief",           "flat",           p)
        root.option_add("*Scrollbar.Width",            8,                p)

        # Spinbox
        root.option_add("*Spinbox.Font",      cls.FONT_BODY,  p)
        root.option_add("*Spinbox.Background",cls.ENTRY_BG,   p)
        root.option_add("*Spinbox.Foreground",cls.TEXT_PRIMARY, p)
        root.option_add("*Spinbox.Relief",    "flat",         p)

        # Menu / OptionMenu
        root.option_add("*Menu.Font",            cls.FONT_BODY,      p)
        root.option_add("*Menu.Background",      cls.BG_SECONDARY,   p)
        root.option_add("*Menu.Foreground",      cls.TEXT_PRIMARY,   p)
        root.option_add("*Menu.ActiveBackground",cls.ACCENT_PRIMARY, p)
        root.option_add("*Menu.ActiveForeground",cls.TEXT_ON_ACCENT, p)
        root.option_add("*Menu.Relief",          "flat",             p)
        root.option_add("*Menu.BorderWidth",     1,                  p)

        # Root window
        root.configure(bg=cls.BG_PRIMARY)
        cls.set_window_appearance(root)

    @classmethod
    def set_window_appearance(cls, win) -> None:
        """Make macOS draw this window's own parts (scrollbars, title bar,
        menus) light or dark to match the palette, whatever the system mode is."""
        if sys.platform != "darwin":
            return

        def _apply():
            try:
                win.tk.call("::tk::unsupported::MacWindowStyle", "appearance", win._w,
                            "darkaqua" if cls.IS_DARK else "aqua")
            except Exception:
                pass

        try:
            mapped = win.winfo_ismapped()
        except tk.TclError:
            return
        if mapped:
            _apply()
            return
        # Tk can only set this once the window is on screen (before that it
        # prints "Failed to read appearance name"), so wait for the first <Map>.
        funcid = None

        def _on_map(event):
            if event.widget is win:
                _apply()
                try:
                    win.unbind("<Map>", funcid)
                except tk.TclError:
                    pass
        funcid = win.bind("<Map>", _on_map, add="+")

    @classmethod
    def style_modal(cls, win: tk.Toplevel) -> None:
        """Apply consistent theme to a Toplevel popup or drilldown window.

        Call immediately after creating the Toplevel, before adding widgets::

            modal = tk.Toplevel(root)
            ModernStyle.style_modal(modal)
        """
        win.configure(bg=cls.BG_PRIMARY)
        cls.set_window_appearance(win)
        p = "60"
        try:
            win.option_add("*Font",       cls.FONT_BODY,    p)
            win.option_add("*Background", cls.BG_PRIMARY,   p)
            win.option_add("*Foreground", cls.TEXT_PRIMARY, p)
        except Exception:
            pass


    @staticmethod
    def improve_treeview_scrolling(root: tk.Tk):
        """Makes Treeview scrolling 3x faster and much smoother across OSs."""
        def _on_mousewheel(event):
            widget = event.widget
            # Find the treeview if the event hit a cell
            if not isinstance(widget, ttk.Treeview):
                while widget and not getattr(widget, "yview_scroll", None):
                    widget = widget.master
            if not widget or not isinstance(widget, ttk.Treeview):
                return

            if sys.platform == "darwin":
                delta = int(-1 * event.delta)
                step = 1 if delta > 0 else -1
            else:
                step = int(-1 * (event.delta / 120))
                
            if step != 0:
                widget.yview_scroll(step * 4, "units")
            return "break"

        root.bind_class("Treeview", "<MouseWheel>", _on_mousewheel)
        if sys.platform == "linux":
            root.bind_class("Treeview", "<Button-4>", lambda e: e.widget.yview_scroll(-4, "units") or "break")
            root.bind_class("Treeview", "<Button-5>", lambda e: e.widget.yview_scroll(4, "units") or "break")


# ──────────────────────────────────────────────────────────────────────────────
# Fill in the colours of the active palette
# ──────────────────────────────────────────────────────────────────────────────
for _key, _value in _PALETTE.items():
    if _key != "NAME":
        setattr(ModernStyle, _key, _value)

# Older names, kept so existing code keeps working
ModernStyle.ACCENT_SECONDARY = ModernStyle.SUCCESS_FILL
ModernStyle.ACCENT_TERTIARY = ModernStyle.WARNING_FILL
ModernStyle.ACCENT_RED = ModernStyle.ERROR
ModernStyle.ACCENT_SECONDARY_PALE = ModernStyle.SUCCESS_PALE
ModernStyle.ACCENT_TERTIARY_PALE = ModernStyle.WARNING_PALE
ModernStyle.HEADER_COLOR = ModernStyle.TEXT_ACCENT
# Deprecated: salmon text was unreadable (2.5:1). Use ERROR for text and
# NEUTRAL_FILL for Cancel/Close buttons.
ModernStyle.SALMON = ModernStyle.ERROR

# Raw slate scale. Prefer the role names above. In the dark theme the scale is
# reversed, so any leftover "light surface" uses (SLATE_50/100) stay dark.
for _level, _hex in _SLATE.items():
    _src = _SLATE[{50: 900, 100: 800, 200: 700, 300: 600, 400: 500,
                   500: 400, 600: 300, 700: 200, 800: 100, 900: 50}[_level]] if ModernStyle.IS_DARK else _hex
    setattr(ModernStyle, f"SLATE_{_level}", _src)
