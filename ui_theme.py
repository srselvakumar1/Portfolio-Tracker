#!/usr/bin/env python3
"""Central UI theme tokens and ttk styling for PTracker.

HOW TO USE:
    from ui_theme import ModernStyle

    # Typography
    tk.Label(..., font=ModernStyle.FONT_PAGE_TITLE, fg=ModernStyle.ACCENT_PRIMARY)

    # Colors
    tk.Frame(..., bg=ModernStyle.BG_SECONDARY)

    # Apply global ttk theme at app startup (call once from main.py)
    ModernStyle.apply_theme(root)

DESIGN SYSTEM OVERVIEW:
    ┌─────────────────────────────────────────────────┐
    │  Typographic Scale                              │
    │  FONT_PAGE_TITLE  32pt Bold  → View Headers     │
    │  FONT_TITLE       18pt Bold  → Section Titles   │
    │  FONT_HEADING     14pt Bold  → Card Headings     │
    │  FONT_SUBHEADING  12pt Bold  → Sub-labels        │
    │  FONT_BODY        11pt       → Default text      │
    │  FONT_SMALL       10pt       → Hints/metadata    │
    │  FONT_KPI_VALUE   22pt Bold  → Stat card values  │
    │  FONT_KPI_LABEL   11pt Bold  → Stat card labels  │
    │  FONT_INPUT       15pt Bold  → Search/entry text │
    │  FONT_TICKER      14pt Bold  → Sidebar tickers   │
    │  FONT_BADGE        8pt Bold  → PRO badge etc.    │
    └─────────────────────────────────────────────────┘
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk


class ModernStyle:
    """Centralized light-theme design system for PTracker.

    All fonts, colors, spacing and component dimensions are defined here.
    Views import this class directly — no ad-hoc color strings in view files.
    """

    # ──────────────────────────────────────────────────────────────
    # PLATFORM-AWARE FONT FAMILY
    # Picks the best system font for Windows, macOS, and Linux.
    # ──────────────────────────────────────────────────────────────
    FONT_FAMILY = (
        "Segoe UI" if sys.platform == "win32"
        else ("SF Pro Display" if sys.platform == "darwin"
              else "Ubuntu")
    )

    # ──────────────────────────────────────────────────────────────
    # TYPOGRAPHIC SCALE
    # Use these tokens everywhere instead of inline font tuples.
    # ──────────────────────────────────────────────────────────────

    # View / Page level — used once per view for the main header label
    FONT_PAGE_TITLE  = (FONT_FAMILY, 30, "bold")   # Dashboard, Holdings, Trade History headers

    # Section / card level — used for card titles, section headings
    FONT_TITLE       = (FONT_FAMILY, 18, "bold")   # Modal titles, drilldown headers
    FONT_HEADING     = (FONT_FAMILY, 14, "bold")   # Sidebar nav labels, filter labels, table section headings
    FONT_SUBHEADING  = (FONT_FAMILY, 12, "bold")   # Card sub-labels, tooltip headers

    # Body — default readable text throughout the app
    FONT_BODY        = (FONT_FAMILY, 13)            # Descriptions, subtitles, sidebar subtitles
    FONT_BODY_BOLD   = (FONT_FAMILY, 11, "bold")   # Emphasized body text, inline values in cards
    FONT_SMALL       = (FONT_FAMILY, 10)            # Timestamps, hints, metadata below labels
    FONT_SMALL_BOLD  = (FONT_FAMILY, 10, "bold")   # Small but emphatic: breakdown labels, badge-like text
    FONT_TINY        = (FONT_FAMILY,  9)            # Detail rows, sparkline annotations, footnotes
    FONT_TABLE       = (FONT_FAMILY, 13)            # Treeview / data table body rows
    FONT_TABLE_BOLD  = (FONT_FAMILY, 13, "bold")   # Treeview headings, column headers

    # Special display fonts — used in modals and drilldowns
    FONT_SYMBOL_LARGE  = (FONT_FAMILY, 28, "bold")  # Large symbol name in Add Trade / drilldown modal
    FONT_DRILLDOWN_SYM = (FONT_FAMILY, 24, "bold")  # Valuation modal symbol / top holding name
    FONT_SECTION_LABEL = (FONT_FAMILY, 20, "bold")  # Section headers inside cards / drilldown panels
    FONT_MODAL_TITLE   = (FONT_FAMILY, 16, "bold")  # Modal window titles (Broker Mgmt, Watchlist detail)
    FONT_EMPTY_STATE   = (FONT_FAMILY, 30)           # Large emoji in empty-state overlays

    # Sidebar-specific (dark background, larger for readability)
    FONT_SIDEBAR_TITLE = (FONT_FAMILY, 24, "bold")  # "PTracker" brand title in sidebar header
    FONT_SIDEBAR_BADGE = (FONT_FAMILY, 9, "bold")  # PRO badge text in sidebar header

    # Italic / muted hints
    FONT_ITALIC        = (FONT_FAMILY, 12, "italic") # Italicised helper text / placeholder hints
    FONT_ITALIC_MD     = (FONT_FAMILY, 14, "italic") # Medium italic — LoadingOverlay message text
    FONT_TINY_BOLD     = (FONT_FAMILY, 11, "bold")  # Tiny emphasized labels (calendar day names, row counts)

    # Loading overlay / modal icon
    FONT_LOADING_ICON  = (FONT_FAMILY, 32)           # ⏳ spinner / loading icon in overlay
    FONT_MODAL_ICON    = (FONT_FAMILY, 26)           # Large icon label in PremiumModal header

    # KPI Stats Cards — used in Dashboard, Holdings, Trade History, Tax Report summary bars
    FONT_KPI_VALUE   = (FONT_FAMILY, 26, "bold")   # Large number display (portfolio value, P&L)
    FONT_KPI_LABEL   = (FONT_FAMILY, 14, "bold")   # Small label above/below the KPI value

    # Input Widgets — search boxes in Holdings and Trade History
    FONT_INPUT       = (FONT_FAMILY, 15, "bold")   # Symbol search entry text (blue, high visibility)

    # Sidebar Tickers — Live market prices displayed at the sidebar bottom
    FONT_TICKER      = (FONT_FAMILY, 14, "bold")   # Market index values and change % (Gold/Green)

    # Navigation / Sidebar Labels
    FONT_NAV         = (FONT_FAMILY, 14, "bold")   # Sidebar navigation button labels
    FONT_NAV_SECTION = (FONT_FAMILY, 10, "bold")   # "N A V I G A T I O N" section label

    # Miscellaneous small UI elements
    FONT_BADGE       = (FONT_FAMILY, 10, "bold")   # PRO badge, pill labels
    FONT_ICON        = (FONT_FAMILY, 15)            # Emoji icons inside cards (no bold needed)

    # Alias for convenience — HEADER_COLOR is always the primary accent
    HEADER_COLOR     = "#2563EB"  # Matches ACCENT_PRIMARY below

    # ──────────────────────────────────────────────────────────────
    # BACKGROUND COLORS
    # Three-tier surface system (main → card → sidebar/header).
    # ──────────────────────────────────────────────────────────────
    BG_PRIMARY       = "#F8FAFC"   # App chrome / outer background (Slate 50)
    BG_SECONDARY     = "#FFFFFF"   # Cards, modals, treeview surfaces
    BG_TERTIARY      = "#F1F5F9"   # Sidebar, filter bars, section headers (Slate 100)

    # Entry / input field background
    ENTRY_BG         = "#FFFFFF"   # Same as BG_SECONDARY — clean white input boxes

    # ──────────────────────────────────────────────────────────────
    # ACCENT COLORS (Brand Palette)
    # Primary = Blue, Secondary = Green, Tertiary = Amber
    # ──────────────────────────────────────────────────────────────
    ACCENT_PRIMARY   = "#2563EB"   # Blue 600  — main CTA, active nav, header text
    ACCENT_SECONDARY = "#16A34A"   # Green 600 — success, buy signals, positive P&L
    ACCENT_TERTIARY  = "#D97706"   # Amber 600 — warning, refresh button, filter accents

    # Muted/pale background versions for pills, badges, highlights
    ACCENT_PRIMARY_PALE   = "#DBEAFE"  # Blue 100
    ACCENT_SECONDARY_PALE = "#DCFCE7"  # Green 100
    ACCENT_TERTIARY_PALE  = "#FEF3C7"  # Amber 100
    ACCENT_PURPLE_PALE    = "#E9D5FF"  # Purple 100 — watchlist pill backgrounds
    ACCENT_PURPLE         = "#9333EA"  # Purple 600 — watchlist pill focus border

    # ──────────────────────────────────────────────────────────────
    # TEXT COLORS
    # Three-tier text hierarchy (primary → secondary → muted).
    # ──────────────────────────────────────────────────────────────
    TEXT_PRIMARY     = "#0F172A"   # Slate 900 — main content, headings
    TEXT_SECONDARY   = "#475569"   # Slate 600 — subtitles, descriptions
    TEXT_TERTIARY    = "#64748B"   # Slate 500 — placeholders, hints, muted labels
    TEXT_ON_ACCENT   = "#FFFFFF"   # White — text on colored buttons/active nav items

    # ──────────────────────────────────────────────────────────────
    # BORDERS & DIVIDERS
    # ──────────────────────────────────────────────────────────────
    BORDER_COLOR     = "#E5E7EB"   # Gray 200 — card outlines, treeview lines
    DIVIDER_COLOR    = "#E2E8F0"   # Slate 200 — horizontal dividers, separators

    # ──────────────────────────────────────────────────────────────
    # SEMANTIC COLORS (Status / Signal)
    # Use these consistently for financial data coloring.
    # ──────────────────────────────────────────────────────────────
    SUCCESS          = "#16A34A"   # Green 600 — positive P&L, gains, BUY signals, up arrows
    SUCCESS_PALE     = "#DCFCE7"   # Green 100 — positive P&L background tint
    WARNING          = "#D97706"   # Amber 600 — caution, HOLD signals, moderate risk
    WARNING_PALE     = "#FEF3C7"   # Amber 100 — warning background tint
    ERROR            = "#DC2626"   # Red 600   — losses, SELL/REDUCE signals (use sparingly on dark bg)
    ERROR_PALE       = "#FEE2E2"   # Red 100   — loss background tint
    SALMON           = "#FA8072"   # Salmon    — cancel buttons, close/exit actions (softer than ERROR)
    INFO             = "#0891B2"   # Cyan 600  — informational messages, XIRR/CAGR highlights
    INFO_PALE        = "#CFFAFE"   # Cyan 100  — info background tint

    # Brand accent used on sidebar tickers for negative changes
    # (preferred over ERROR red on dark backgrounds for readability)
    BRAND_GOLD       = "#D4AF37"   # Rich gold — sidebar negative tickers, brand accent divider

    # ──────────────────────────────────────────────────────────────
    # SLATE SCALE (Extended Palette for Dark UI Elements)
    # Used for the sidebar, modal overlays, treeview headings.
    # ──────────────────────────────────────────────────────────────
    SLATE_50  = "#F8FAFC"
    SLATE_100 = "#F1F5F9"
    SLATE_200 = "#E2E8F0"
    SLATE_300 = "#CBD5E1"   # Sidebar nav button text (inactive)
    SLATE_400 = "#94A3B8"
    SLATE_500 = "#64748B"
    SLATE_600 = "#475569"
    SLATE_700 = "#334155"   # Treeview heading hover background
    SLATE_800 = "#1E293B"   # Sidebar nav button background, treeview heading
    SLATE_900 = "#0F172A"   # Sidebar background

    # ──────────────────────────────────────────────────────────────
    # COMPONENT LAYOUT TOKENS
    # Fixed dimensions for consistency across all views.
    # ──────────────────────────────────────────────────────────────

    # Dashboard KPI Cards
    KPI_CARD_HEIGHT         = 118   # Fixed height for all 8 KPI cards
    KPI_ACCENT_BAR_HEIGHT   = 3     # Top colored bar inside each KPI card

    # Dashboard secondary info cards
    DASH_GRID_CARD_HEIGHT   = 240   # Portfolio breakdown / allocation grid cards
    DASH_SECTION_CARD_HEIGHT = 305  # Top performers & sector breakdown cards

    # ──────────────────────────────────────────────────────────────
    # NAVIGATION / SIDEBAR COMPONENT TOKENS
    # Matches the Sidebar class in main.py for consistent look.
    # ──────────────────────────────────────────────────────────────
    NAV_ITEM_BG          = BG_TERTIARY    # Default nav button background
    NAV_ITEM_HOVER_BG    = BG_SECONDARY   # Nav button on hover
    NAV_ITEM_ACTIVE_BG   = ACCENT_PRIMARY # Active / selected nav button
    NAV_ITEM_ACTIVE_FG   = TEXT_ON_ACCENT # Text on active nav button
    NAV_ITEM_FG          = TEXT_PRIMARY   # Text on inactive nav button
    NAV_ITEM_PADX        = 14             # Horizontal padding inside nav buttons
    NAV_ITEM_PADY        = 10             # Vertical padding inside nav buttons
    NAV_ITEM_OUTER_PADX  = 10            # Outer horizontal padding of the nav row

    # ──────────────────────────────────────────────────────────────
    # TTK GLOBAL THEME SETUP
    # Called once from main.py on app startup.
    # ──────────────────────────────────────────────────────────────
    @classmethod
    def apply_theme(cls, root: tk.Tk) -> None:
        """Apply the PTracker light theme to all ttk and tk widgets.

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
        )

        style.configure(
            "Treeview",
            background=cls.BG_SECONDARY,
            foreground=cls.TEXT_PRIMARY,
            fieldbackground=cls.BG_SECONDARY,
            bordercolor=cls.BORDER_COLOR,
            rowheight=32,
            font=(cls.FONT_FAMILY, 11),
        )
        style.configure(
            "Treeview.Heading",
            background=cls.SLATE_800,
            foreground=cls.TEXT_ON_ACCENT,
            font=(cls.FONT_FAMILY, 11, "bold"),
            relief="flat",
        )
        try:
            style.map(
                "Treeview.Heading",
                background=[("active", cls.SLATE_700)],
                foreground=[("active", cls.TEXT_ON_ACCENT)],
            )
        except Exception:
            pass
        style.map(
            "Treeview",
            background=[("selected", cls.ACCENT_PRIMARY)],
            foreground=[("selected", cls.TEXT_ON_ACCENT)],
        )

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
            relief="flat",
            borderwidth=0,
            width=8,
        )
        style.map("TScrollbar", background=[("active", cls.SLATE_400)])

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
        root.option_add("*Scrollbar.ActiveBackground", cls.SLATE_400,    p)
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

    @classmethod
    def style_modal(cls, win: tk.Toplevel) -> None:
        """Apply consistent theme to a Toplevel popup or drilldown window.

        Call immediately after creating the Toplevel, before adding widgets::

            modal = tk.Toplevel(root)
            ModernStyle.style_modal(modal)
        """
        win.configure(bg=cls.BG_PRIMARY)
        p = "60"
        try:
            win.option_add("*Font",       cls.FONT_BODY,    p)
            win.option_add("*Background", cls.BG_PRIMARY,   p)
            win.option_add("*Foreground", cls.TEXT_PRIMARY, p)
        except Exception:
            pass
