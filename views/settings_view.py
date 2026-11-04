"""
Settings view for TKinter-based PTracker application.
"""

import tkinter as tk
from tkinter import filedialog
from ui import dialogs
import threading
import csv
import os
import subprocess
import sys
from datetime import datetime

from views.base_view import BaseView
from model.applog import log
from ui import icons
from ui.ui_theme import ModernStyle
from ui.ui_widgets import Pill, rounded_combobox, RoundedBox, ModernButton, ModernCard, ModernEntry, action_button, header_button
from ui.ui_utils import call_on_ui

class _StatusLine(tk.Label):
    """A status message that takes no room while it is empty.

    holder (the label itself, or the row it sits in) is packed with pack_opts
    when a message is set and unpacked when the text is cleared.
    """

    def __init__(self, master, pack_opts: dict, holder=None, on_change=None, **kw):
        super().__init__(master, **kw)
        self._holder = holder or self
        self._pack_opts = pack_opts
        self._on_change = on_change   # called when the line appears or goes (the card must resize)

    def configure(self, cnf=None, **kw):
        result = super().configure(cnf, **kw)
        if "text" in kw:
            shown = bool(self._holder.winfo_manager())
            if kw["text"] and not shown:
                self._holder.pack(**self._pack_opts)
            elif not kw["text"] and shown:
                self._holder.pack_forget()
            else:
                return result
            if self._on_change:
                self._on_change()
        return result

    config = configure


def _spread_buttons(row: tk.Frame, buttons: list, gap: int = 6) -> None:
    """Make the buttons share the row's full width: equal widths when there is room,
    otherwise each stays wide enough for its text."""
    import tkinter.font as tkfont
    natural = [tkfont.Font(font=b._font).measure(b._text) + 2 * b._text_padx + 8 for b in buttons]
    for b, w in zip(buttons, natural):
        b.set_size(width=w)

    def _fit(e):
        room = e.width - gap * (len(buttons) - 1)
        if room // len(buttons) >= max(natural):
            widths = [room // len(buttons)] * len(buttons)
        else:
            extra = max(0, (room - sum(natural)) // len(buttons))
            widths = [w + extra for w in natural]
        for b, w in zip(buttons, widths):
            b.set_size(width=w)
    row.bind("<Configure>", _fit, add="+")


def _fit_to_text(btn) -> None:
    """Make a ModernButton just wide enough for its text (fixed widths clip longer words)."""
    import tkinter.font as tkfont
    btn.set_size(width=tkfont.Font(font=btn._font).measure(btn._text) + 2 * btn._text_padx + 8)


def _wrap_to_width(label: tk.Label) -> None:
    """Wrap the label's text at its own width, so it uses the whole card."""
    label.bind("<Configure>", lambda e: label.configure(wraplength=max(200, e.width - 4)), add="+")


class SettingsView(BaseView):
    """Application settings and configuration."""
    
    def build(self):
        """Build Settings with Flet-equivalent cards (broker management + danger zone)."""
        self._data_loaded = False
        self._broker_trade_counts = {}

        self.add_gradient_header(
            self,
            "⚙️ Settings",
            "Configure application preferences and data management."
        )

        # Main content area: two equal columns, sized to fit the window without scrolling
        content = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        content.pack(fill="both", expand=True, padx=20, pady=(2, 10))
        content.grid_columnconfigure(0, weight=1, uniform="settings_col")
        content.grid_columnconfigure(1, weight=1, uniform="settings_col")
        content.grid_rowconfigure(0, weight=1)

        left_col = tk.Frame(content, bg=ModernStyle.BG_PRIMARY)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self._left_col = left_col
        self._cards = []
        content.bind("<Configure>", self._schedule_row_fit, add="+")   # text re-wraps when the width changes
        self._row_applied = (0, 0)   # extra px per broker row and per statistics row (see _fit_rows)
        left_col.bind("<Configure>", self._schedule_row_fit, add="+")

        right_col = tk.Frame(content, bg=ModernStyle.BG_PRIMARY)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(7, 0))

        def _card(parent, title: str, icon: tuple, grow: bool = True):
            """A card headed by a strong coloured band across its width (as the Dashboard's
            tables), with its icon and title in white; the .head row (band coloured, so use its
            bg, white text and header_button) takes buttons or notes on the right of the title.
            icon = (Lucide name, emoji, band colour, pale tint (unused), title colour (unused)).

            Cards share out the column's spare height (grow=False: stay compact), so both
            columns end level; inside, parts packed with expand=True spread evenly.
            """
            frame = ModernCard(parent, bg=ModernStyle.BG_SECONDARY, highlight_color=ModernStyle.BG_SECONDARY, shadow=True, highlight_thickness=1, radius=ModernStyle.RADIUS_CARD,
                               canvas_bg=ModernStyle.BG_PRIMARY, shrink=True, expand_height=True)
            frame.pack(fill="both" if grow else "x", expand=grow, pady=4)
            self._cards.append(frame)
            name, _emoji, strong, _pale, _color = icon
            ink = ModernStyle.TEXT_ON_ACCENT
            band = tk.Frame(frame.content, bg=strong)
            band.pack(fill="x", pady=(0, 6))
            frame.tint_top(strong, band)   # the band's colour reaches the card's rounded edges
            head = tk.Frame(band, bg=strong)
            head.pack(fill="x", padx=(6, 12), pady=3)
            Pill(head, text=title, icon=name, fill=strong, fg=ink, font=ModernStyle.FONT_CARD_TITLE,
                 height=32).pack(side="left")   # as tall as header_button: every band the same height
            inner = tk.Frame(frame.content, bg=ModernStyle.BG_SECONDARY)
            inner.pack(fill="both", expand=True, padx=12, pady=(0, 9))
            inner.head = head
            return inner

        # -------------- LEFT COLUMN --------------
        
        # 1. Broker Management
        broker = _card(left_col, "Broker Management", ("landmark", "🏦", ModernStyle.ACCENT_PRIMARY, ModernStyle.ACCENT_PRIMARY_PALE, ModernStyle.TEXT_ACCENT),
                       grow=False)   # the statistics get the spare room
        
        self.broker_count_label = tk.Label(broker.head, text="Loading brokers…", fg=ModernStyle.TEXT_ON_ACCENT, bg=broker.head["bg"], font=ModernStyle.FONT_SMALL)
        self.broker_count_label.pack(side="right")
        
        # Add Broker Row
        add_frame = tk.Frame(broker, bg=ModernStyle.BG_SECONDARY)
        add_frame.pack(fill="x", pady=4)
        add_frame.grid_columnconfigure(0, weight=1)
        add_frame.grid_columnconfigure(1, weight=0)
        add_frame.grid_columnconfigure(2, weight=0)
        
        
        self.new_broker_var = tk.StringVar(value="")
        self.new_broker_currency_var = tk.StringVar(value="INR")
        
        box = RoundedBox(add_frame)
        entry = ModernEntry(box, textvariable=self.new_broker_var, font=ModernStyle.FONT_INPUT, placeholder="New broker name",
                            highlightthickness=0, bg=ModernStyle.ENTRY_BG)
        entry.pack(fill="x", ipady=5, padx=8)
        box.watch(entry)
        box.grid(row=1, column=0, sticky="ew", padx=(0, 6))

        curr_box, curr_cb = rounded_combobox(add_frame, textvariable=self.new_broker_currency_var,
                                             values=["INR", "JPY"], width=6, state="readonly")
        curr_box.grid(row=1, column=1, sticky="w", padx=(0, 6))
        
        btn_frame = tk.Frame(add_frame, bg=ModernStyle.BG_SECONDARY)
        btn_frame.grid(row=1, column=2, sticky="e", pady=(0,0))
        add_btn = action_button(btn_frame, "+ Add", self._add_broker_inline, kind="success", size="sm",
                                canvas_bg=ModernStyle.BG_SECONDARY)
        _fit_to_text(add_btn)
        add_btn.pack()
        
        # Suggestions
        sug_frame = tk.Frame(broker, bg=ModernStyle.BG_SECONDARY)
        sug_frame.pack(fill="x", pady=(0, 4))
        tk.Label(sug_frame, text="Suggestions:", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TINY).pack(side="left")
        
        for sug in ["Kite", "Upstox", "ICICI Direct", "Angel"]:
            btn = tk.Label(sug_frame, text=f" {sug} ", fg=ModernStyle.TEXT_ACCENT, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TINY, cursor="hand2")
            btn.pack(side="left", padx=4)
            btn.bind("<Button-1>", lambda e, s=sug: self.new_broker_var.set(s))
            btn.bind("<Enter>", lambda e, b=btn: b.config(fg=ModernStyle.TEXT_PRIMARY))
            btn.bind("<Leave>", lambda e, b=btn: b.config(fg=ModernStyle.TEXT_ACCENT))

        # Broker List Frame
        list_container = tk.Frame(broker, bg=ModernStyle.BG_SECONDARY, highlightthickness=1, highlightbackground=ModernStyle.BORDER_COLOR)
        list_container.pack(fill="x", pady=(4, 0))
        self.broker_status = _StatusLine(broker, dict(anchor="w", pady=(0, 2), before=list_container), on_change=self._schedule_row_fit,
                                         text="", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL)
        
        self.inline_broker_frame = tk.Frame(list_container, bg=ModernStyle.BG_SECONDARY)
        self.inline_broker_frame.pack(fill="x", padx=4, pady=4)

        # 2. Database Statistics
        stats = _card(left_col, "Database Statistics", ("database", "📊", ModernStyle.INFO_FILL, ModernStyle.INFO_PALE, ModernStyle.INFO))

        # Summary tiles over the table; _fit_rows hides them when the window is too short
        from ui.ui_utils import ToolTip
        tile_bg = ModernStyle.BG_TERTIARY
        self._stats_tiles = tk.Frame(stats, bg=ModernStyle.BG_SECONDARY)
        self._stats_tiles.pack(fill="x", pady=(0, 8))
        self._stat_tile_vals, self._stat_tile_tips = {}, {}
        tile_specs = (("records", "rows-3", "🧮", "Records", ModernStyle.TEXT_ACCENT),
                      ("size", "hard-drive", "💽", "File size", ModernStyle.INFO),
                      ("backup", "archive", "💾", "Last backup", ModernStyle.SUCCESS),
                      ("prices", "refresh-cw", "💹", "Prices", ModernStyle.TEXT_PURPLE))
        for col, (key, icon, emoji, title, color) in enumerate(tile_specs):
            self._stats_tiles.grid_columnconfigure(col, weight=1, uniform="stat_tiles")
            tile = RoundedBox(self._stats_tiles, fill=tile_bg, border=tile_bg, padx=5, pady=5)
            tile.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col < len(tile_specs) - 1 else 0)
            top = tk.Frame(tile, bg=tile_bg)
            top.pack(fill="x", padx=10, pady=(8, 0))
            glyph = icons.glyph(icon)
            tk.Label(top, text=glyph or emoji, fg=color, bg=tile_bg,
                     font=icons.font(14) if glyph else ModernStyle.FONT_SMALL).pack(side="left", padx=(0, 5))
            tk.Label(top, text=title, fg=ModernStyle.TEXT_SECONDARY, bg=tile_bg,
                     font=ModernStyle.FONT_SMALL_BOLD).pack(side="left")
            val = tk.Label(tile, text="—", fg=color, bg=tile_bg, font=ModernStyle.FONT_HEADING, anchor="w")
            val.pack(fill="x", padx=10, pady=(2, 8))
            self._stat_tile_vals[key] = val
            self._stat_tile_tips[key] = ToolTip(tile, "")

        self.stats_frame = tk.Frame(stats, bg=ModernStyle.BG_SECONDARY)
        self.stats_frame.pack(fill="both", expand=True)
        
        self.stats_loading_label = tk.Label(self.stats_frame, text="Loading statistics...", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY)
        self.stats_loading_label.pack(anchor="w")

        self.db_file_label = tk.Label(stats, text="", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY,
                                      font=ModernStyle.FONT_SMALL, anchor="w", justify="left")
        self.db_file_label.pack(fill="x", pady=(4, 0))

        self._db_file_tip = ToolTip(self.db_file_label, "")
        clear_btn = header_button(stats.head, "Clear Cache", self._clear_cache, icon="eraser")
        clear_btn.pack(side="right")
        ToolTip(clear_btn, "The cache keeps filtering fast. Clear it if figures look out of date.")
        header_button(stats.head, "↻ Refresh", self._refresh_database_stats).pack(side="right", padx=(0, 6))



        # -------------- RIGHT COLUMN --------------
        
        # 4. Appearance
        appearance = _card(right_col, "Appearance", ("palette", "🎨", ModernStyle.PURPLE_FILL, ModernStyle.ACCENT_PURPLE_PALE, ModernStyle.TEXT_PURPLE))
        from model.app_settings import load_settings
        saved = load_settings()
        self._appearance_buttons = {}

        def _choice_row(title, key, options):
            group = tk.Frame(appearance, bg=ModernStyle.BG_SECONDARY)
            group.pack(fill="x", expand=True, pady=(2, 6))
            tk.Label(group, text=title, fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
                     font=ModernStyle.FONT_SMALL_BOLD).pack(anchor="w", pady=(0, 4))
            row = tk.Frame(group, bg=ModernStyle.BG_SECONDARY)
            row.pack(fill="x")
            buttons = []
            for i, (value, label) in enumerate(options):
                btn = ModernButton(row, text=label, command=lambda k=key, v=value: self._choose_appearance(k, v),
                                   canvas_bg=ModernStyle.BG_SECONDARY, height=32, radius=14,   # a pill, like every choice
                                   font=ModernStyle.FONT_SMALL_BOLD)
                btn.pack(side="left", padx=(0 if i == 0 else 6, 0))
                self._appearance_buttons[(key, value)] = btn
                buttons.append(btn)
            _spread_buttons(row, buttons)
            self._paint_appearance(key, saved.get(key))

        _choice_row("Theme", "theme", [("light", "☀️ Light"), ("dark", "🌙 Dark"), ("system", "🖥 Match macOS")])
        _choice_row("Text size", "text_size", [("small", "Small"), ("normal", "Normal"), ("large", "Large"), ("xlarge", "Extra large")])

        restart_row = tk.Frame(appearance, bg=ModernStyle.BG_SECONDARY)
        self.appearance_status = _StatusLine(restart_row, dict(anchor="w", fill="x"), holder=restart_row, on_change=self._schedule_row_fit,
                                             text="", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
                                             font=ModernStyle.FONT_SMALL, wraplength=230, justify="left")
        self.appearance_status.pack(side="left")
        self._restart_btn = action_button(restart_row, "Restart Now", self._restart_app, size="sm",
                                          icon="rotate-cw", canvas_bg=ModernStyle.BG_SECONDARY)
        # shown once a choice differs from what this run is using

        # 3. Backup & Export
        backup = _card(right_col, "Data Backup & Export", ("hard-drive-download", "💾", ModernStyle.SUCCESS_FILL, ModernStyle.SUCCESS_PALE,
                                                         ModernStyle.SUCCESS))
        backup_text = tk.Label(
            backup,
            text="Saved automatically every 5 days (the last 5 are kept), "
                 "and before every delete, wipe, import or restore.",
            fg=ModernStyle.TEXT_SECONDARY,
            bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_BODY,
            wraplength=400,
            justify="left",
            anchor="w",
        )
        backup_text.pack(fill="x", expand=True, pady=(0, 4))
        _wrap_to_width(backup_text)
        self.backup_info = tk.Label(backup, text="Last backup: checking…", fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY_BOLD)
        self.backup_info.pack(anchor="w", expand=True, pady=(0, 6))

        backup_btns = tk.Frame(backup, bg=ModernStyle.BG_SECONDARY)
        backup_btns.pack(fill="x", expand=True)
        b1 = action_button(backup_btns, "Back Up Now", self._backup_now, icon="database-backup",
                           canvas_bg=ModernStyle.BG_SECONDARY)
        b1.pack(side="left")
        b2 = action_button(backup_btns, "Restore…", self._restore_backup, soft=True, icon="archive-restore",
                           canvas_bg=ModernStyle.BG_SECONDARY)
        b2.pack(side="left", padx=(8, 0))
        b3 = action_button(backup_btns, "Show Backups", self._show_backups, soft=True, icon="folder-open",
                           canvas_bg=ModernStyle.BG_SECONDARY)
        b3.pack(side="left", padx=(8, 0))
        _spread_buttons(backup_btns, [b1, b2, b3], gap=8)

        header_button(backup.head, "Export Trades (CSV)", self._export_trades_csv, icon="file-down").pack(side="right")

        self.backup_status = _StatusLine(backup, dict(anchor="w", pady=(6, 0)), on_change=self._schedule_row_fit,
                                         text="", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL, wraplength=400, justify="left")

        # 6. About
        about = _card(right_col, "About", ("info", "ℹ️", ModernStyle.WARNING_FILL, ModernStyle.WARNING_PALE, ModernStyle.WARNING))
        from model.applog import LOG_PATH
        about_text = tk.Label(about, text=f"PTracker · Portfolio Tracker · problems go to the log:\n{LOG_PATH.replace(os.path.expanduser('~'), '~')}",
                              fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY,
                              justify="left", wraplength=400, anchor="w")
        about_text.pack(fill="x", expand=True)
        _wrap_to_width(about_text)
        header_button(about.head, "Show Log", self._show_log, icon="scroll-text").pack(side="right")

        # 7. Danger Zone
        danger = _card(right_col, "Danger Zone", ("triangle-alert", "⚠️", ModernStyle.ERROR_FILL, ModernStyle.ERROR_PALE, ModernStyle.ERROR))
        danger_group = tk.Frame(danger, bg=ModernStyle.BG_SECONDARY)
        danger_group.pack(fill="x", expand=True)
        tk.Label(danger_group, text="Wipe Portfolio Data", fg=ModernStyle.ERROR, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SUBHEADING).pack(anchor="w")
        danger_text = tk.Label(
            danger_group,
            text="Deletes all trades, market data and holdings (brokers are kept). "
                 "A backup is saved first, so Restore… above can undo it.",
            fg=ModernStyle.TEXT_SECONDARY,
            bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_BODY,
            wraplength=400,
            justify="left",
            anchor="w",
        )
        danger_text.pack(fill="x", pady=(2, 0))
        _wrap_to_width(danger_text)
        # solid white with red text: it stands out on the red band
        header_button(danger.head, "Delete All Data", self._wipe_all_data, main=True, icon="trash-2").pack(side="right")
        self.danger_status = _StatusLine(danger, dict(anchor="w", pady=(6, 0)), on_change=self._schedule_row_fit,
                                         text="", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL, wraplength=400, justify="left")

    def on_show(self):
        super().on_show()
        self._refresh_backup_info()

    def load_data(self):
        if getattr(self, "_data_loaded", False):
            return
        self._data_loaded = True
        self._reload_brokers()
        self._refresh_database_stats()

    def _get_broker_trade_counts(self) -> dict:
        """Get count of trades for each broker."""
        try:
            from model.database import db_session
            with db_session() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT broker, COUNT(*) as count FROM trades GROUP BY broker")
                return {row[0]: row[1] for row in cursor.fetchall()}
        except Exception:
            return {}

    def _reload_brokers(self) -> None:
        """Reload broker list and update count label."""
        try:
            import model.crud as crud
            from ui.broker_logos import ordered
            brokers = ordered(crud.get_all_brokers())   # Bahee-Kite, ICICI, Upstox, … everywhere
            self._broker_trade_counts = self._get_broker_trade_counts()
        except Exception:
            brokers = []
        
        count = len(brokers)
        if count == 0:
            self.broker_count_label.config(text="No brokers configured", fg=ModernStyle.TEXT_ON_ACCENT)
        else:
            total_trades = sum(self._broker_trade_counts.values())
            self.broker_count_label.config(text=f"{count} broker{'s' if count != 1 else ''} · {total_trades:,} trades", fg=ModernStyle.TEXT_ON_ACCENT)
            
        self._refresh_inline_broker_list(brokers)

    def _add_broker_inline(self) -> None:
        name = (self.new_broker_var.get() or "").strip().upper()
        currency = (self.new_broker_currency_var.get() or "INR").strip().upper()
        if not name:
            self.broker_status.config(text="Enter a broker name", fg=ModernStyle.ERROR)
            return
        try:
            import model.crud as crud
            existing = [b.upper() for b in crud.get_all_brokers()]
            if name in existing:
                self.broker_status.config(text=f"'{name}' already exists", fg=ModernStyle.ERROR)
                return
            crud.add_broker(name, currency)
            try:
                if self.app_state and hasattr(self.app_state, "get_brokers_cached"):
                    self.app_state.get_brokers_cached(force_refresh=True)
                if self.app_state and hasattr(self.app_state, "get_broker_currencies_cached"):
                    self.app_state.get_broker_currencies_cached(force_refresh=True)
            except Exception:
                pass
            self.new_broker_var.set("")
            self.broker_status.config(text=f"Broker '{name}' added ✓", fg=ModernStyle.SUCCESS)
            self._reload_brokers()
        except Exception as e:
            log.exception("Adding broker %r failed", name)
            msg = ("That broker already exists." if "UNIQUE" in str(e).upper()
                   else "Couldn't add the broker. Details are in the log (Show Log).")
            self.broker_status.config(text=msg, fg=ModernStyle.ERROR)

    def _refresh_inline_broker_list(self, brokers: list) -> None:
        """Refresh broker list in the settings view."""
        if not hasattr(self, 'inline_broker_frame'):
            return
        
        for w in self.inline_broker_frame.winfo_children():
            w.destroy()
        
        if not brokers:
            tk.Label(self.inline_broker_frame, text="📭 No brokers yet. Add one above!", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY).pack(anchor="w", padx=4, pady=8)
            return
        
        # Grid based table header
        header_bg = ModernStyle.ACCENT_PRIMARY
        header_fg = ModernStyle.TEXT_ON_ACCENT
        header_row = tk.Frame(self.inline_broker_frame, bg=header_bg)
        header_row.pack(fill="x", pady=(2, 4))
        
        tk.Label(header_row, text="#", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, width=3, anchor="center").pack(side="left", pady=2)
        tk.Label(header_row, text="Broker Name", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, anchor="w").pack(side="left", padx=8, expand=True, fill="x", pady=2)
        tk.Label(header_row, text="Action", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, width=8, anchor="center").pack(side="right", padx=6, pady=2)
        tk.Label(header_row, text="Currency", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, width=8, anchor="center").pack(side="right", padx=6, pady=2)
        tk.Label(header_row, text="Trades", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, width=6, anchor="e").pack(side="right", padx=6, pady=2)

        # Fetch currencies to display
        import model.crud as crud
        broker_currencies = crud.get_broker_currencies()

        row_num = 1
        self._broker_rows = []
        self._row_applied = (0, self._row_applied[1])   # new rows start without extra height
        for name in brokers:
            row_bg = ModernStyle.BG_PRIMARY if row_num % 2 != 0 else ModernStyle.BG_SECONDARY
            row = tk.Frame(self.inline_broker_frame, bg=row_bg, highlightbackground=ModernStyle.BORDER_COLOR, highlightthickness=0)
            row.pack(fill="x", pady=0, padx=0)
            self._broker_rows.append(row)
            
            trade_count = self._broker_trade_counts.get(name, 0)
            current_curr = broker_currencies.get(name, "INR")
            
            tk.Label(row, text=str(row_num), fg=ModernStyle.TEXT_PRIMARY, bg=row_bg, font=ModernStyle.FONT_BODY, pady=0, bd=0, width=3, anchor="center").pack(side="left", pady=0)
            from ui.broker_logos import logo
            tk.Label(row, text=f"  {name}", image=logo(name, 20), compound="left", fg=ModernStyle.TEXT_PRIMARY,
                     bg=row_bg, font=ModernStyle.FONT_BODY, pady=0, bd=0, anchor="w").pack(side="left", padx=8, expand=True, fill="x", pady=0)
            
            # Soft, so the one solid red button on the page stays "Delete All Data"
            del_btn = ModernButton(row, text="Delete", command=lambda n=name: self._delete_broker_inline(n),
                                   bg=ModernStyle.ERROR_FILL, fg=ModernStyle.TEXT_ON_ACCENT, variant="soft",
                                   canvas_bg=row_bg, height=24, radius=10, font=ModernStyle.FONT_SMALL_BOLD,
                                   text_padx=8)
            _fit_to_text(del_btn)
            del_btn.pack(side="right", padx=6, pady=0)
            
            # Currency display for existing broker
            tk.Label(row, text=current_curr, fg=ModernStyle.TEXT_ACCENT, bg=row_bg, font=ModernStyle.FONT_TINY_BOLD, pady=0, bd=0, width=8, anchor="center").pack(side="right", padx=6, pady=0)
            
            tk.Label(row, text=f"{trade_count:,}", fg=ModernStyle.TEXT_PRIMARY, bg=row_bg, font=ModernStyle.FONT_BODY, pady=0, bd=0, width=6, anchor="e").pack(side="right", padx=6, pady=0)
            
            row_num += 1
        self._schedule_row_fit()


    def _delete_broker_inline(self, name: str) -> None:
        """Delete broker and refresh."""
        count = self._broker_trade_counts.get(name, 0)
        if not dialogs.askyesno(
            "Delete Broker",
            f"Delete broker '{name}' and its {count:,} trade{'s' if count != 1 else ''}?\n\n"
            "Its holdings are deleted too. A backup is saved first, "
            "so you can undo this from Settings (Restore…).",
        ):
            return

        def _bg():
            try:
                from model.backup import safety_backup
                safety_backup("delete-broker")
            except Exception as e:
                msg = f"Couldn't save a backup first, so nothing was deleted. ({e})"
                call_on_ui(lambda m=msg: self.broker_status.config(text=m, fg=ModernStyle.ERROR))
                return
            try:
                import model.crud as crud
                crud.delete_broker(name)
                try:
                    from model.engine import rebuild_holdings
                    rebuild_holdings()
                except Exception:
                    pass
                try:
                    if self.app_state and hasattr(self.app_state, "refresh_data_cache"):
                        self.app_state.refresh_data_cache()
                except Exception:
                    pass
                call_on_ui(lambda: (self._reload_brokers(), self._refresh_backup_info(), self.broker_status.config(text=f"Broker '{name}' deleted ✓ (a backup was saved first)", fg=ModernStyle.SUCCESS)))
            except Exception as e:
                err = str(e)
                call_on_ui(lambda e=err: self.broker_status.config(text=f"Delete failed: {e}", fg=ModernStyle.ERROR))
        
        threading.Thread(target=_bg, daemon=True).start()
    
    def _clear_cache(self):
        try:
            if self.app_state and hasattr(self.app_state, "refresh_data_cache"):
                self.app_state.refresh_data_cache()
        except Exception:
            pass
        self.broker_status.config(text="Cache refreshed")

    def _wipe_all_data(self) -> None:
        answer = dialogs.askstring(
            "Delete All Data",
            "This deletes ALL trades, market data and holdings. Brokers are kept.\n"
            "A backup is saved first, so you can undo this from Settings (Restore…).\n\n"
            "Type DELETE to confirm:",
            parent=self.winfo_toplevel(),
        )
        if answer is None:
            return
        if answer.strip().upper() != "DELETE":
            self.danger_status.config(text="Nothing was deleted (you didn't type DELETE).", fg=ModernStyle.TEXT_SECONDARY)
            return

        self.danger_status.config(text="Saving a backup, then deleting…", fg=ModernStyle.TEXT_SECONDARY)

        def _bg():
            try:
                from model.backup import safety_backup
                safety_backup("wipe")
            except Exception as e:
                msg = f"Couldn't save a backup first, so nothing was deleted. ({e})"
                call_on_ui(lambda m=msg: self.danger_status.config(text=m, fg=ModernStyle.ERROR))
                return
            try:
                import model.crud as crud
                crud.wipe_all_data()
                try:
                    from model.engine import rebuild_holdings
                    rebuild_holdings()
                except Exception:
                    pass
                try:
                    if self.app_state and hasattr(self.app_state, "refresh_data_cache"):
                        self.app_state.refresh_data_cache()
                except Exception:
                    pass
                call_on_ui(lambda: (
                    self.danger_status.config(text="All data deleted ✓. A backup was saved first.", fg=ModernStyle.SUCCESS),
                    self._reload_brokers(),
                    self._refresh_database_stats(),
                    self._refresh_backup_info(),
                    self._invalidate_other_views(),
                ))
            except Exception as e:
                err = str(e)
                call_on_ui(lambda e=err: self.danger_status.config(text=f"Delete failed: {e}", fg=ModernStyle.ERROR))

        threading.Thread(target=_bg, daemon=True).start()

    # ── Appearance ─────────────────────────────────────────────────────────────

    def _paint_appearance(self, key: str, selected) -> None:
        for (k, v), btn in self._appearance_buttons.items():
            if k != key:
                continue
            if v == selected:
                btn.set_palette(bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT)
            else:
                btn.set_palette(bg=ModernStyle.BG_TERTIARY, fg=ModernStyle.TEXT_PRIMARY)

    def _choose_appearance(self, key: str, value: str) -> None:
        from model.app_settings import save_settings
        try:
            settings = save_settings({key: value})
        except OSError as e:
            self.appearance_status.config(text=f"Couldn't save the setting: {e}", fg=ModernStyle.ERROR)
            return
        self._paint_appearance(key, value)
        running = {"theme": ModernStyle.THEME_CHOICE, "text_size": getattr(ModernStyle, "TEXT_SIZE_CHOICE", {0.96: "small", 1.0: "normal", 1.12: "large", 1.25: "xlarge"}.get(ModernStyle.TEXT_SCALE, "normal"))}
        changed = any(settings.get(k) != v for k, v in running.items())
        if changed:
            self.appearance_status.config(text="Restart PTracker to apply this.", fg=ModernStyle.TEXT_SECONDARY)
            self._restart_btn.pack(side="right")
        else:
            self.appearance_status.config(text="")
            self._restart_btn.pack_forget()

    def _restart_app(self) -> None:
        """Start a fresh copy of PTracker, then close this one."""
        from model.database import close_all_connections
        try:
            if getattr(sys, "frozen", False):
                # .../PTracker.app/Contents/MacOS/<exe>  →  .../PTracker.app
                bundle = os.path.abspath(os.path.join(os.path.dirname(sys.executable), "..", ".."))
                subprocess.Popen(["open", "-n", bundle])
            else:
                subprocess.Popen([sys.executable] + sys.argv)
        except Exception as e:
            self.appearance_status.config(text=f"Couldn't restart: {e}. Please quit and open PTracker again.", fg=ModernStyle.ERROR)
            return
        try:
            close_all_connections()
        except Exception:
            pass
        self.winfo_toplevel().destroy()

    def _show_log(self) -> None:
        from model.applog import LOG_PATH
        try:
            if not os.path.exists(LOG_PATH):
                self.backup_status.config(text="The log is empty: nothing has gone wrong yet.", fg=ModernStyle.TEXT_SECONDARY)
                return
            if sys.platform == "darwin":
                subprocess.run(["open", LOG_PATH], check=False)
            elif sys.platform == "win32":
                os.startfile(LOG_PATH)
            else:
                subprocess.run(["xdg-open", LOG_PATH], check=False)
        except Exception as e:
            self.backup_status.config(text=f"Couldn't open the log: {e}", fg=ModernStyle.ERROR)

    # ── Backups ────────────────────────────────────────────────────────────────

    def _refresh_backup_info(self) -> None:
        """Show when the newest backup was made and how many are kept."""
        try:
            from model.backup import list_backups
            backups = list_backups()
            if backups:
                newest = backups[0]["when"].strftime("%d %b %Y, %H:%M")
                text = f"Last backup: {newest}  •  {len(backups)} kept"
            else:
                text = "No backups yet. Click Back Up Now to make one."
            self.backup_info.config(text=text, fg=ModernStyle.TEXT_PRIMARY)
        except Exception as e:
            self.backup_info.config(text=f"Backups unavailable: {e}", fg=ModernStyle.ERROR)

    def _backup_now(self) -> None:
        self.backup_status.config(text="Saving a backup…", fg=ModernStyle.TEXT_SECONDARY)

        def _bg():
            try:
                from model.backup import create_backup
                path = create_backup("manual")
                msg, color = f"Backup saved ✓  {os.path.basename(path)}", ModernStyle.SUCCESS
            except Exception as e:
                msg, color = f"Backup failed: {e}", ModernStyle.ERROR
            call_on_ui(lambda: (self.backup_status.config(text=msg, fg=color), self._refresh_backup_info()))

        threading.Thread(target=_bg, daemon=True).start()

    def _show_backups(self) -> None:
        """Open the Backups folder in Finder (or the system file browser)."""
        try:
            from model.backup import backup_dir
            folder = backup_dir()
            if sys.platform == "darwin":
                subprocess.run(["open", folder], check=False)
            elif sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.run(["xdg-open", folder], check=False)
        except Exception as e:
            self.backup_status.config(text=f"Couldn't open the Backups folder: {e}", fg=ModernStyle.ERROR)

    def _restore_backup(self) -> None:
        """Let the user pick a backup file and put its data back."""
        from model import backup as bk
        top = self.winfo_toplevel()
        try:
            start_dir = bk.backup_dir()
        except Exception:
            start_dir = None
        path = filedialog.askopenfilename(
            title="Choose a backup to restore",
            initialdir=start_dir,
            filetypes=[("PTracker backups", "*.db"), ("All files", "*.*")],
            parent=top,
        )
        if not path:
            return
        try:
            info = bk.describe_backup(path)
        except ValueError as e:
            dialogs.showerror("Restore Backup", str(e), parent=top)
            return

        saved = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d %b %Y, %H:%M")
        span = f"\nTrades dated {info['first_date']} to {info['last_date']}." if info["trades"] else ""
        if not dialogs.askyesno(
            "Restore Backup",
            f"Replace your current data with this backup?\n\n"
            f"{os.path.basename(path)}\n"
            f"Saved {saved}: {info['trades']:,} trades, {info['brokers']} brokers.{span}\n\n"
            "Your current data is backed up first, so you can switch back.",
            parent=top,
        ):
            return

        self.backup_status.config(text="Restoring… this takes a few seconds.", fg=ModernStyle.TEXT_SECONDARY)

        def _bg():
            err = None
            warn = None
            undo_path = ""
            try:
                undo_path = bk.restore_backup(path)
            except Exception as e:
                err = str(e)
            if not err:
                # The backup may come from an older version: bring the schema up to
                # date, then recalculate holdings and caches from its trades.
                try:
                    from model.database import initialize_database, ensure_marketdata_schema, ensure_watchlist_schema
                    initialize_database()
                    ensure_marketdata_schema()
                    ensure_watchlist_schema()
                    from model.engine import rebuild_holdings, invalidate_all_caches
                    rebuild_holdings()
                    invalidate_all_caches()
                    if self.app_state and hasattr(self.app_state, "refresh_data_cache"):
                        self.app_state.refresh_data_cache()
                except Exception as e:
                    warn = str(e)

            def _done():
                if err:
                    self.backup_status.config(text=f"Restore failed, nothing was changed: {err}", fg=ModernStyle.ERROR)
                    return
                undo_name = os.path.basename(undo_path)
                if warn:
                    self.backup_status.config(text=f"Restored, but recalculating holdings failed: {warn}. Your previous data is in {undo_name}.", fg=ModernStyle.WARNING)
                else:
                    self.backup_status.config(text=f"Restored ✓  Your previous data was saved as {undo_name}.", fg=ModernStyle.SUCCESS)
                self._reload_brokers()
                self._refresh_database_stats()
                self._refresh_backup_info()
                self._invalidate_other_views()

            call_on_ui(_done)

        threading.Thread(target=_bg, daemon=True).start()

    def _invalidate_other_views(self) -> None:
        """Make every other page reload its data the next time it is shown."""
        try:
            app = getattr(self.winfo_toplevel(), "_ptracker_app", None)
            if app is None:
                return
            for view in app.view_manager.views.values():
                if view is not self and hasattr(view, "_data_loaded"):
                    view._data_loaded = False
            app.sidebar.refresh_sidebar_data()
        except Exception:
            pass



    def _export_trades_csv(self):
        """Export trades data to a CSV file."""
        try:
            filename = filedialog.asksaveasfilename(
                title="Export Trades",
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                initialfile="trades_backup.csv"
            )
            if not filename:
                return

            import model.crud as crud
            trades = crud.get_all_trades_for_export()
            
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["broker", "trade_id", "date", "symbol", "type", "qty", "price", "fee", "currency"])
                writer.writerows(trades)
            
            self.backup_status.config(text=f"Exported {len(trades)} trades ✓", fg=ModernStyle.SUCCESS)
        except Exception:
            log.exception("Trade export failed")
            self.backup_status.config(text="Couldn't export the trades. Check the folder can be written to; "
                                           "details are in the log.", fg=ModernStyle.ERROR)

    def _refresh_database_stats(self):
        """Refresh the database statistics UI."""
        def _bg():
            try:
                import model.crud as crud
                from model.database import db_session
                stats = crud.get_all_table_stats()
                status = self._table_status(stats)
                with db_session() as conn:
                    prices_at = conn.execute("SELECT MAX(last_updated) FROM marketdata").fetchone()[0]
                call_on_ui(lambda: self._render_stats(stats, status, prices_at))
            except Exception:
                log.exception("Reading database statistics failed")
                call_on_ui(lambda: self.stats_loading_label.config(
                    text="Couldn't read the database statistics. Details are in the log.", fg=ModernStyle.ERROR))
        
        if hasattr(self, 'stats_loading_label'):
             self.stats_loading_label.config(text="Refreshing...", fg=ModernStyle.TEXT_SECONDARY)
             
        for child in self.stats_frame.winfo_children():
            if child != self.stats_loading_label:
                child.destroy()
        self.stats_loading_label.pack(anchor="w")

        threading.Thread(target=_bg, daemon=True).start()

    _ROW_GROW = {"broker": 12, "stats": 12}   # most px a table row may grow, so rows never look stretched

    def _schedule_row_fit(self, _e=None):
        if getattr(self, "_row_fit_id", None):
            self.after_cancel(self._row_fit_id)
        self._row_fit_id = self.after(60, self._fit_rows)

    def _fit_rows(self):
        """Share the left column's spare height between the broker and statistics rows.

        The summary tiles show only when they fit. Rows grow together, each up to its
        cap in _ROW_GROW; any space beyond that is split above and below the table."""
        self._row_fit_id = None
        # A stretched card's inside has a fixed height, so it isn't told when its content
        # grows or shrinks: bring every card's size up to date by hand
        self._sync_cards()
        brows = [w for w in getattr(self, "_broker_rows", []) if w.winfo_exists()]
        table = getattr(self, "_stats_table", None)
        nats = getattr(self, "_stats_nat", []) if table is not None and table.winfo_exists() else []
        nb, ns = len(brows), len(nats)
        eb0, es0 = self._row_applied
        need = sum(int(c.cget("height")) + 8 for c in self._cards if c.master is self._left_col) - nb * eb0 - ns * es0
        spare = self._left_col.winfo_height() - need
        tiles = self._stats_tiles
        tiles_on = bool(tiles.winfo_manager())
        if tiles_on and spare < 0 or not tiles_on and spare >= tiles.winfo_reqheight() + 8:
            if tiles_on:
                tiles.pack_forget()
            else:
                tiles.pack(fill="x", pady=(0, 8), before=self.stats_frame)
            self._sync_cards_settled(then=self._schedule_row_fit)   # measure again at the new size
            return
        eb = es = 0
        if spare > 0 and nb + ns:
            cb, cs = self._ROW_GROW["broker"], self._ROW_GROW["stats"]
            step = spare // (nb + ns)
            if step <= cb:
                eb = es = step
            else:
                eb = cb
                es = min(cs, (spare - nb * cb) // max(ns, 1))
        eb -= eb % 2   # ipady adds its value above and below
        if (eb, es) == (eb0, es0):
            return
        for row in brows:
            row.pack_configure(ipady=eb // 2)
        for r, nat in enumerate(nats, start=1):
            table.grid_rowconfigure(r, minsize=nat + es)
        self._row_applied = (eb, es)
        self._sync_cards_settled(then=self._schedule_row_fit)

    def _sync_cards(self):
        for card in getattr(self, "_cards", []):
            if card.winfo_exists():
                card._sync_size()

    def _sync_cards_settled(self, last=None, steady=0, tries=20, then=None):
        """Sync the cards a few times, an idle pass apart, until their content sizes have
        stopped changing (a new row size climbs through the nested frames one level per pass),
        then call `then` (the row fit checks its measurement on the settled page)."""
        now = [c.content.winfo_reqheight() for c in self._cards if c.winfo_exists()]
        self._sync_cards()
        steady = steady + 1 if now == last else 0
        if steady < 3 and tries:
            self.after_idle(lambda: self.after(20, lambda: self._sync_cards_settled(now, steady, tries - 1, then)))
        elif then:
            then()

    # Key tables first, with friendlier names
    _TABLE_NAMES = {"trades": "Trades", "holdings": "Holdings", "marketdata": "Market data", "trade_calcs": "Trade calcs",
                    "brokers": "Brokers", "watchlist": "Watchlist", "assets": "Assets", "dashboard_metrics": "Dashboard"}

    @staticmethod
    def _table_status(counts: dict) -> dict:
        """A short (text, tone) status per table; a query that fails just leaves that table blank."""
        from model.database import db_session

        def day(text):        # "2016-08-02" -> "02 Aug 2016"
            try:
                return datetime.strptime(str(text)[:10], "%Y-%m-%d").strftime("%d %b %Y")
            except ValueError:
                return str(text)

        def month(text):      # "2016-08-02" -> "Aug 2016"
            try:
                return datetime.strptime(str(text)[:10], "%Y-%m-%d").strftime("%b %Y")
            except ValueError:
                return str(text)

        def stamp(text):      # "2026-10-22 21:28:16" -> "22 Oct 21:28" (this year) or "22 Oct 2025"
            try:
                when = datetime.strptime(str(text)[:16], "%Y-%m-%d %H:%M")
            except ValueError:
                return day(text)
            return when.strftime("%d %b %H:%M" if when.year == datetime.now().year else "%d %b %Y")

        queries = {
            "trades": ("SELECT MIN(date), MAX(date), SUM(date > date('now', 'localtime')) FROM trades",
                       lambda r: ((f"⚠ {r[2]:,} dated in the future", "warn") if r[2]
                                  else (f"{month(r[0])} – {month(r[1])}", None)) if r[0] else None),
            "holdings": ("SELECT COUNT(*) FROM holdings WHERE qty > 0.0001",
                         lambda r: (f"{r[0]:,} open now", None)),
            "marketdata": ("SELECT MAX(last_updated), SUM(current_price IS NULL OR current_price = 0) FROM marketdata",
                           lambda r: (f"{stamp(r[0])} · {r[1]:,} no price" if r[1] else stamp(r[0]),
                                      "warn" if r[1] else None) if r[0] else None),
            "trade_calcs": ("SELECT MAX(calc_ts) FROM trade_calcs",
                            lambda r: (("✓ one per trade", "good")
                                       if counts.get("trade_calcs") == counts.get("trades")
                                       else (f"⚠ trades have {counts.get('trades', 0):,}", "warn"))),
            "brokers": ("SELECT currency, COUNT(*) FROM brokers GROUP BY currency ORDER BY COUNT(*) DESC", None),
            "watchlist": ("SELECT MAX(added_on) FROM watchlist",
                          lambda r: (f"latest {day(r[0])}", None) if r[0] else None),
            "assets": ("SELECT MAX(last_updated) FROM assets",
                       lambda r: (stamp(r[0]), None) if r[0] else None),
            "dashboard_metrics": ("SELECT MAX(last_updated) FROM dashboard_metrics",
                                  lambda r: (stamp(r[0]), None) if r[0] else None),
        }
        out = {}
        with db_session() as conn:
            for name, (sql, make) in queries.items():
                if name not in counts:
                    continue
                try:
                    if make is None:   # brokers: "5 INR · 2 JPY"
                        out[name] = (" · ".join(f"{n} {cur}" for cur, n in conn.execute(sql).fetchall()), None)
                    else:
                        result = make(conn.execute(sql).fetchone())
                        if result:
                            out[name] = result
                except Exception:
                    log.debug("No status for table %s", name, exc_info=True)
        return out

    def _fill_stat_tiles(self, stats: dict, size_text: str, path: str, prices_at) -> None:
        """Records, file size, last backup and price time, with details in each tile's tooltip."""
        def when(dt):
            return dt.strftime("%d %b %H:%M" if dt.year == datetime.now().year else "%d %b %Y")

        vals, tips = self._stat_tile_vals, self._stat_tile_tips
        vals["records"].config(text=f"{sum(stats.values()):,}" if stats else "—")
        tips["records"].text = f"Rows in all {len(stats)} tables together"
        vals["size"].config(text=size_text)
        tips["size"].text = path
        try:
            from model.backup import list_backups
            backups = list_backups()
        except Exception:
            log.debug("Backups unavailable", exc_info=True)
            backups = []
        if backups:
            vals["backup"].config(text=when(backups[0]["when"]))
            tips["backup"].text = f"Newest of {len(backups)} backups kept"
        else:
            vals["backup"].config(text="None yet")
            tips["backup"].text = "Click Back Up Now to make one"
        try:
            vals["prices"].config(text=when(datetime.strptime(str(prices_at)[:16], "%Y-%m-%d %H:%M")))
            tips["prices"].text = "When market prices were last fetched"
        except ValueError:
            vals["prices"].config(text="—")
            tips["prices"].text = "Prices not fetched yet"

    def _render_stats(self, stats: dict, status: dict | None = None, prices_at=None):
        """Render the stats dict into the summary tiles and the statistics table."""
        self.stats_loading_label.pack_forget()
        # Which file these numbers come from (running from source uses a different one)
        import model.database as database
        path = database.DB_PATH or ""
        try:
            size = os.path.getsize(path) + (os.path.getsize(path + "-wal") if os.path.exists(path + "-wal") else 0)
            size_text = f"{size / 1048576:.1f} MB" if size >= 1048576 else f"{size / 1024:.0f} KB"
        except OSError:
            size_text = "size unknown"
        short = os.path.join("…", *path.split(os.sep)[-3:])   # e.g. …/PTracker/… — one line; the tip has it all
        self.db_file_label.config(text=f"📁 Data file: {short} · {size_text}")
        self._db_file_tip.text = path
        self._fill_stat_tiles(stats, size_text, path, prices_at)
        for child in self.stats_frame.winfo_children():
            if child != self.stats_loading_label:
                child.destroy()
        
        if not stats:
            tk.Label(self.stats_frame, text="No data found.", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY).pack(anchor="w")
            return
            
        # One row per table: name, records and a short status; rows share the card's spare height
        table = tk.Frame(self.stats_frame, bg=ModernStyle.BG_SECONDARY)
        table.pack(fill="x", expand=True)   # spare height splits evenly above and below
        table.grid_columnconfigure(0, weight=1)   # spare width shared by the name and status columns
        table.grid_columnconfigure(2, weight=1)
        self._stats_table, self._stats_nat = table, []
        self._row_applied = (self._row_applied[0], 0)
        head_bg, head_fg = ModernStyle.ACCENT_PRIMARY, ModernStyle.TEXT_ON_ACCENT
        for col, (text, anchor) in enumerate((("Table", "w"), ("Records", "e"), ("Status", "w"))):
            tk.Label(table, text=text, fg=head_fg, bg=head_bg, font=ModernStyle.FONT_TINY_BOLD, anchor=anchor,
                     padx=8, pady=2).grid(row=0, column=col, sticky="nsew")
        tone_fg = {"good": ModernStyle.SUCCESS, "warn": ModernStyle.WARNING}
        order = [t for t in self._TABLE_NAMES if t in stats] + sorted(t for t in stats if t not in self._TABLE_NAMES)
        for r, name in enumerate(order, start=1):
            row_bg = ModernStyle.BG_PRIMARY if r % 2 else ModernStyle.BG_SECONDARY
            note, tone = (status or {}).get(name, ("", None))
            cells = ((self._TABLE_NAMES.get(name, name), ModernStyle.FONT_BODY, ModernStyle.TEXT_PRIMARY, "w"),
                     (f"{stats[name]:,}", ModernStyle.FONT_BODY, ModernStyle.TEXT_PRIMARY, "e"),
                     (note, ModernStyle.FONT_SMALL, tone_fg.get(tone, ModernStyle.TEXT_SECONDARY), "w"))
            labels = [tk.Label(table, text=text, fg=fg, bg=row_bg, font=font, anchor=anchor, padx=8, pady=0)
                      for text, font, fg, anchor in cells]
            for col, label in enumerate(labels):
                label.grid(row=r, column=col, sticky="nsew")
            self._stats_nat.append(max(label.winfo_reqheight() for label in labels))
        self._schedule_row_fit()
