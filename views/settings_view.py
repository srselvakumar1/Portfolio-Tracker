"""
Settings view for TKinter-based PTracker application.
"""

import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog
import threading
import csv
import os
import subprocess
import sys
from datetime import datetime

from views.base_view import BaseView
from model.applog import log
from ui.ui_theme import ModernStyle
from ui.ui_widgets import rounded_combobox, RoundedBox, ModernButton, ModernCard, ModernEntry
from ui.ui_utils import call_on_ui

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

        # Main content area using a 2-column layout to avoid vertical scroll
        content = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        content.pack(fill="both", expand=True, padx=20, pady=(4, 16))

        left_col = tk.Frame(content, bg=ModernStyle.BG_PRIMARY)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 7))

        right_col = tk.Frame(content, bg=ModernStyle.BG_PRIMARY)
        right_col.pack(side="right", fill="both", expand=True, padx=(7, 0))

        def _card(parent, title: str):
            frame = ModernCard(parent, bg=ModernStyle.BG_SECONDARY, highlight_color=ModernStyle.BG_SECONDARY, shadow=True, highlight_thickness=1, radius=10, canvas_bg=ModernStyle.BG_PRIMARY)
            frame.pack(fill="x", pady=6)
            tk.Label(frame.content, text=title, fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SUBHEADING).pack(anchor="w", padx=12, pady=(8, 4))
            inner = tk.Frame(frame.content, bg=ModernStyle.BG_SECONDARY)
            inner.pack(fill="both", expand=True, padx=12, pady=(0, 10))
            return inner

        # -------------- LEFT COLUMN --------------
        
        # 1. Broker Management
        broker = _card(left_col, "🏦 Broker Management")
        
        self.broker_count_label = tk.Label(broker, text="Loading brokers…", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL)
        self.broker_count_label.pack(anchor="w", pady=(0, 4))
        
        # Add Broker Row
        add_frame = tk.Frame(broker, bg=ModernStyle.BG_SECONDARY)
        add_frame.pack(fill="x", pady=4)
        add_frame.grid_columnconfigure(0, weight=1)
        add_frame.grid_columnconfigure(1, weight=0)
        add_frame.grid_columnconfigure(2, weight=0)
        
        tk.Label(add_frame, text="Broker Name", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TINY).grid(row=0, column=0, sticky="w", padx=(0, 6))
        tk.Label(add_frame, text="Currency", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TINY).grid(row=0, column=1, sticky="w", padx=(0, 6))
        
        self.new_broker_var = tk.StringVar(value="")
        self.new_broker_currency_var = tk.StringVar(value="INR")
        
        box = RoundedBox(add_frame)
        entry = ModernEntry(box, textvariable=self.new_broker_var, font=ModernStyle.FONT_INPUT,
                            highlightthickness=0, bg=ModernStyle.ENTRY_BG)
        entry.pack(fill="x", ipady=5, padx=8)
        box.watch(entry)
        box.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        
        import tkinter.ttk as ttk
        curr_box, curr_cb = rounded_combobox(add_frame, textvariable=self.new_broker_currency_var,
                                             values=["INR", "JPY", "USD"], width=6, state="readonly")
        curr_box.grid(row=1, column=1, sticky="w", padx=(0, 6))
        
        btn_frame = tk.Frame(add_frame, bg=ModernStyle.BG_SECONDARY)
        btn_frame.grid(row=1, column=2, sticky="e", pady=(0,0))
        ModernButton(btn_frame, text="Add", command=self._add_broker_inline, bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=60, height=32).pack()
        
        # Suggestions
        sug_frame = tk.Frame(broker, bg=ModernStyle.BG_SECONDARY)
        sug_frame.pack(fill="x", pady=(0, 8))
        tk.Label(sug_frame, text="Suggestions:", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TINY).pack(side="left")
        
        for sug in ["Kite", "Upstox", "ICICI Direct", "Angel"]:
            btn = tk.Label(sug_frame, text=f" {sug} ", fg=ModernStyle.TEXT_ACCENT, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TINY, cursor="hand2")
            btn.pack(side="left", padx=4)
            btn.bind("<Button-1>", lambda e, s=sug: self.new_broker_var.set(s))
            btn.bind("<Enter>", lambda e, b=btn: b.config(fg=ModernStyle.TEXT_PRIMARY))
            btn.bind("<Leave>", lambda e, b=btn: b.config(fg=ModernStyle.TEXT_ACCENT))

        self.broker_status = tk.Label(broker, text="", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL)
        self.broker_status.pack(anchor="w", pady=(2, 4))
        
        # Broker List Frame
        list_container = tk.Frame(broker, bg=ModernStyle.BG_SECONDARY, highlightthickness=1, highlightbackground=ModernStyle.BORDER_COLOR)
        list_container.pack(fill="x", pady=(4, 0))
        
        self.inline_broker_frame = tk.Frame(list_container, bg=ModernStyle.BG_SECONDARY)
        self.inline_broker_frame.pack(fill="x", padx=4, pady=4)

        # 2. Database Statistics
        stats = _card(left_col, "📊 Database Statistics")
        self.stats_frame = tk.Frame(stats, bg=ModernStyle.BG_SECONDARY)
        self.stats_frame.pack(fill="x", pady=(0, 8))
        
        self.stats_loading_label = tk.Label(self.stats_frame, text="Loading statistics...", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY)
        self.stats_loading_label.pack(anchor="w")

        ModernButton(stats, text="Refresh Stats", variant="soft", command=self._refresh_database_stats, bg=ModernStyle.ACCENT_SECONDARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=140, height=32).pack(anchor="w")



        # -------------- RIGHT COLUMN --------------
        
        # 4. Appearance
        appearance = _card(right_col, "🎨 Appearance")
        from model.app_settings import load_settings
        saved = load_settings()
        self._appearance_buttons = {}

        def _choice_row(title, key, options):
            tk.Label(appearance, text=title, fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
                     font=ModernStyle.FONT_SMALL_BOLD).pack(anchor="w", pady=(2, 4))
            row = tk.Frame(appearance, bg=ModernStyle.BG_SECONDARY)
            row.pack(anchor="w", pady=(0, 8))
            for value, label in options:
                btn = ModernButton(row, text=label, command=lambda k=key, v=value: self._choose_appearance(k, v),
                                   canvas_bg=ModernStyle.BG_SECONDARY, width=118, height=32,
                                   font=ModernStyle.FONT_SMALL_BOLD)
                btn.pack(side="left", padx=(0, 6))
                self._appearance_buttons[(key, value)] = btn
            self._paint_appearance(key, saved.get(key))

        _choice_row("Theme", "theme", [("light", "☀️ Light"), ("dark", "🌙 Dark"), ("system", "🖥 Match macOS")])
        _choice_row("Text size", "text_size", [("normal", "Normal"), ("large", "Large"), ("xlarge", "Extra large")])

        restart_row = tk.Frame(appearance, bg=ModernStyle.BG_SECONDARY)
        restart_row.pack(anchor="w", fill="x")
        self.appearance_status = tk.Label(restart_row, text="", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY,
                                          font=ModernStyle.FONT_SMALL, wraplength=230, justify="left")
        self.appearance_status.pack(side="left")
        self._restart_btn = ModernButton(restart_row, text="Restart Now", command=self._restart_app,
                                         bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT,
                                         canvas_bg=ModernStyle.BG_SECONDARY, width=120, height=32)
        # shown once a choice differs from what this run is using

        # 5. Data Cache
        cache = _card(right_col, "⚡ Data Cache")
        tk.Label(cache, text="Cache is enabled for fast filtering", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY).pack(anchor="w")
        ModernButton(cache, text="Clear Cache", variant="soft", command=self._clear_cache, bg=ModernStyle.ACCENT_TERTIARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=140, height=36).pack(anchor="w", pady=(8, 0))

        # 3. Backup & Export
        backup = _card(right_col, "💾 Data Backup & Export")
        tk.Label(
            backup,
            text="Your data is backed up automatically once a day (the last 30 are kept), "
                 "and again before every delete, wipe, import or restore.",
            fg=ModernStyle.TEXT_SECONDARY,
            bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_BODY,
            wraplength=350,
            justify="left",
        ).pack(anchor="w", pady=(0, 4))
        self.backup_info = tk.Label(backup, text="Last backup: checking…", fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY_BOLD)
        self.backup_info.pack(anchor="w", pady=(0, 8))

        backup_btns = tk.Frame(backup, bg=ModernStyle.BG_SECONDARY)
        backup_btns.pack(anchor="w")
        ModernButton(backup_btns, text="Back Up Now", command=self._backup_now, bg=ModernStyle.ACCENT_SECONDARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=130, height=36).pack(side="left")
        ModernButton(backup_btns, text="Restore…", variant="soft", command=self._restore_backup, bg=ModernStyle.ACCENT_TERTIARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=110, height=36).pack(side="left", padx=(8, 0))
        ModernButton(backup_btns, text="Show Backups", variant="soft", command=self._show_backups, bg=ModernStyle.NEUTRAL_FILL, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=130, height=36).pack(side="left", padx=(8, 0))

        ModernButton(backup, text="Export Trades (CSV)", command=self._export_trades_csv, bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=200, height=36).pack(anchor="w", pady=(10, 0))

        self.backup_status = tk.Label(backup, text="", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL, wraplength=350, justify="left")
        self.backup_status.pack(anchor="w", pady=(6, 0))

        # 6. About
        about = _card(right_col, "ℹ️ About")
        from model.applog import LOG_PATH
        tk.Label(about, text=f"PTracker · Portfolio Tracker\nProblems are written to the log:\n{LOG_PATH.replace(os.path.expanduser('~'), '~')}",
                 fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY,
                 justify="left", wraplength=350).pack(anchor="w")
        ModernButton(about, text="Show Log", command=self._show_log, bg=ModernStyle.NEUTRAL_FILL, fg=ModernStyle.TEXT_ON_ACCENT,
                     canvas_bg=ModernStyle.BG_SECONDARY, width=110, height=32).pack(anchor="w", pady=(8, 0))

        # 7. Danger Zone
        danger = _card(right_col, "⚠️ Danger Zone")
        tk.Label(danger, text="Wipe Portfolio Data", fg=ModernStyle.ERROR, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SUBHEADING).pack(anchor="w")
        tk.Label(
            danger,
            text="Deletes all trades, market data, and holdings. Brokers are kept.\nA backup is saved first, so you can undo this with Restore… above.",
            fg=ModernStyle.TEXT_SECONDARY,
            bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_BODY,
            wraplength=350,
            justify="left",
        ).pack(anchor="w", pady=(4, 10))
        ModernButton(danger, text="Delete All Data", command=self._wipe_all_data, bg=ModernStyle.ERROR_FILL, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=170, height=38).pack(anchor="w")
        self.danger_status = tk.Label(danger, text="", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL, wraplength=350, justify="left")
        self.danger_status.pack(anchor="w", pady=(6, 0))

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
            brokers = crud.get_all_brokers()
            self._broker_trade_counts = self._get_broker_trade_counts()
        except Exception:
            brokers = []
        
        count = len(brokers)
        if count == 0:
            self.broker_count_label.config(text="No brokers configured", fg=ModernStyle.TEXT_TERTIARY)
        else:
            total_trades = sum(self._broker_trade_counts.values())
            self.broker_count_label.config(text=f"📊 {count} broker{'s' if count != 1 else ''} • {total_trades} total trades", fg=ModernStyle.TEXT_SECONDARY)
            
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
        
        tk.Label(header_row, text="#", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, width=3, anchor="center").pack(side="left", pady=4)
        tk.Label(header_row, text="Broker Name", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, anchor="w").pack(side="left", padx=8, expand=True, fill="x", pady=4)
        tk.Label(header_row, text="Action", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, width=8, anchor="center").pack(side="right", padx=6, pady=4)
        tk.Label(header_row, text="Currency", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, width=8, anchor="center").pack(side="right", padx=6, pady=4)
        tk.Label(header_row, text="Trades", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, width=6, anchor="e").pack(side="right", padx=6, pady=4)

        # Fetch currencies to display
        import model.crud as crud
        broker_currencies = crud.get_broker_currencies()

        row_num = 1
        for name in brokers:
            row_bg = ModernStyle.BG_PRIMARY if row_num % 2 != 0 else ModernStyle.BG_SECONDARY
            row = tk.Frame(self.inline_broker_frame, bg=row_bg, highlightbackground=ModernStyle.BORDER_COLOR, highlightthickness=0)
            row.pack(fill="x", pady=1, padx=0)
            
            trade_count = self._broker_trade_counts.get(name, 0)
            current_curr = broker_currencies.get(name, "INR")
            
            tk.Label(row, text=str(row_num), fg=ModernStyle.TEXT_PRIMARY, bg=row_bg, font=ModernStyle.FONT_BODY, width=3, anchor="center").pack(side="left", pady=4)
            tk.Label(row, text=name, fg=ModernStyle.TEXT_PRIMARY, bg=row_bg, font=ModernStyle.FONT_BODY, anchor="w").pack(side="left", padx=8, expand=True, fill="x", pady=4)
            
            ModernButton(row, text="Delete", command=lambda n=name: self._delete_broker_inline(n), bg=ModernStyle.ERROR_FILL, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=row_bg, width=60, height=26).pack(side="right", padx=6, pady=4)
            
            # Currency display for existing broker
            tk.Label(row, text=current_curr, fg=ModernStyle.TEXT_ACCENT, bg=row_bg, font=ModernStyle.FONT_TINY_BOLD, width=8, anchor="center").pack(side="right", padx=6, pady=4)
            
            tk.Label(row, text=str(trade_count), fg=ModernStyle.TEXT_PRIMARY, bg=row_bg, font=ModernStyle.FONT_BODY, width=6, anchor="e").pack(side="right", padx=6, pady=4)
            
            row_num += 1


    def _delete_broker_inline(self, name: str) -> None:
        """Delete broker and refresh."""
        count = self._broker_trade_counts.get(name, 0)
        if not messagebox.askyesno(
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
        answer = simpledialog.askstring(
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
        running = {"theme": ModernStyle.THEME_CHOICE, "text_size": {1.0: "normal", 1.12: "large", 1.25: "xlarge"}.get(ModernStyle.TEXT_SCALE, "normal")}
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
            messagebox.showerror("Restore Backup", str(e), parent=top)
            return

        saved = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%d %b %Y, %H:%M")
        span = f"\nTrades dated {info['first_date']} to {info['last_date']}." if info["trades"] else ""
        if not messagebox.askyesno(
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
                stats = crud.get_all_table_stats()
                call_on_ui(lambda: self._render_stats(stats))
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

    def _render_stats(self, stats: dict):
        """Render the stats dict into the statistics frame."""
        self.stats_loading_label.pack_forget()
        for child in self.stats_frame.winfo_children():
            if child != self.stats_loading_label:
                child.destroy()
        
        if not stats:
            tk.Label(self.stats_frame, text="No data found.", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY).pack(anchor="w")
            return
            
        row_num = 1
        
        # Grid based table for Stats
        header_bg = ModernStyle.ACCENT_PRIMARY
        header_fg = ModernStyle.TEXT_ON_ACCENT
        header_row = tk.Frame(self.stats_frame, bg=header_bg)
        header_row.pack(fill="x", pady=(4, 4))
        
        tk.Label(header_row, text="#", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, width=3, anchor="center").pack(side="left", pady=4)
        tk.Label(header_row, text="Table Name", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, anchor="w").pack(side="left", padx=8, expand=True, fill="x", pady=4)
        tk.Label(header_row, text="Records", fg=header_fg, bg=header_bg, font=ModernStyle.FONT_TINY_BOLD, width=8, anchor="e").pack(side="right", padx=8, pady=4)
        
        row_num = 1
        for table, count in sorted(stats.items()):
            row_bg = ModernStyle.BG_PRIMARY if row_num % 2 != 0 else ModernStyle.BG_SECONDARY
            row_frame = tk.Frame(self.stats_frame, bg=row_bg)
            row_frame.pack(fill="x", pady=1)
            
            tk.Label(row_frame, text=str(row_num), fg=ModernStyle.TEXT_PRIMARY, bg=row_bg, font=ModernStyle.FONT_BODY, width=3, anchor="center").pack(side="left", pady=4)
            tk.Label(row_frame, text=table, fg=ModernStyle.TEXT_PRIMARY, bg=row_bg, font=ModernStyle.FONT_BODY, anchor="w").pack(side="left", padx=8, expand=True, fill="x", pady=4)
            tk.Label(row_frame, text=f"{count:,}", fg=ModernStyle.TEXT_PRIMARY, bg=row_bg, font=ModernStyle.FONT_BODY, width=8, anchor="e").pack(side="right", padx=8, pady=4)
            row_num += 1
