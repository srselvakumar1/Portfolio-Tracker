"""
Settings view for TKinter-based PTracker application.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import csv

from views.base_view import BaseView
from ui_theme import ModernStyle
from ui_widgets import ModernButton, ModernCard, ModernEntry
from ui_utils import center_window

class SettingsView(BaseView):
    """Application settings and configuration."""
    
    def build(self):
        """Build Settings with Flet-equivalent cards (broker management + danger zone)."""
        self._data_loaded = False
        self._broker_trade_counts = {}

        header_frame = tk.Frame(self, bg=ModernStyle.BG_PRIMARY, height=60)
        header_frame.pack(fill="x", padx=15, pady=(15, 10))
        tk.Label(header_frame, text="⚙️ Settings", fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_PRIMARY, font=ModernStyle.FONT_TITLE).pack(anchor="w")
        tk.Label(header_frame, text="Configuration and broker management", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_PRIMARY, font=ModernStyle.FONT_BODY).pack(anchor="w")

        # Accent divider
        tk.Frame(self, bg="#D4AF37", height=1).pack(fill="x", padx=15, pady=(10, 10))

        # Main content area using a 2-column layout to avoid vertical scroll
        content = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        content.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        left_col = tk.Frame(content, bg=ModernStyle.BG_PRIMARY)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 7))

        right_col = tk.Frame(content, bg=ModernStyle.BG_PRIMARY)
        right_col.pack(side="right", fill="both", expand=True, padx=(7, 0))

        def _card(parent, title: str):
            frame = ModernCard(parent, bg=ModernStyle.BG_SECONDARY, highlight_color=ModernStyle.BORDER_COLOR, highlight_thickness=1, radius=10, canvas_bg=ModernStyle.BG_PRIMARY)
            frame.pack(fill="x", pady=6)
            tk.Label(frame.content, text=title, fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SUBHEADING).pack(anchor="w", padx=12, pady=(8, 4))
            inner = tk.Frame(frame.content, bg=ModernStyle.BG_SECONDARY)
            inner.pack(fill="both", expand=True, padx=12, pady=(0, 10))
            return inner

        # -------------- LEFT COLUMN --------------

        # Broker Management
        broker = _card(left_col, "🏦 Broker Management")
        button_row = tk.Frame(broker, bg=ModernStyle.BG_SECONDARY)
        button_row.pack(fill="x", pady=(0, 6))
        
        self.broker_count_label = tk.Label(broker, text="Loading brokers…", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL)
        self.broker_count_label.pack(anchor="w", pady=(0, 8))
        
        ModernButton(button_row, text="Open Broker Manager", command=self._open_broker_manager, bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=140, height=36).pack(side="left", padx=(0, 6))
        ModernButton(button_row, text="Quick Add", command=self._quick_add_broker_dialog, bg=ModernStyle.ACCENT_SECONDARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=90, height=36).pack(side="left")
        
        self.broker_status = tk.Label(broker, text="", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL)
        self.broker_status.pack(anchor="w", pady=(6, 0))

        # Backup & Export
        backup = _card(left_col, "💾 Data Backup & Export")
        tk.Label(backup, text="Export trades data to a CSV file.", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY).pack(anchor="w", pady=(0, 8))
        ModernButton(backup, text="Export Trades (CSV)", command=self._export_trades_csv, bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=150, height=36).pack(anchor="w")
        
        self.backup_status = tk.Label(backup, text="", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL)
        self.backup_status.pack(anchor="w", pady=(6, 0))

        # Danger Zone
        danger = _card(left_col, "⚠️ Danger Zone")
        tk.Label(danger, text="Wipe Portfolio Data", fg=ModernStyle.ERROR, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SUBHEADING).pack(anchor="w")
        tk.Label(
            danger,
            text="Permanently deletes all trades, market data, and holdings.\nBrokers are kept.",
            fg=ModernStyle.TEXT_SECONDARY,
            bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_BODY,
            wraplength=350,
            justify="left",
        ).pack(anchor="w", pady=(4, 10))
        ModernButton(danger, text="Delete All Data", command=self._wipe_all_data, bg=ModernStyle.ERROR, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=150, height=38).pack(anchor="w")

        # About
        about = _card(left_col, "ℹ️ About")
        tk.Label(about, text="PTracker (Tkinter Edition)\nLight theme for readability", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY).pack(anchor="w")

        # -------------- RIGHT COLUMN --------------
        
        # Database Statistics
        stats = _card(right_col, "📊 Database Statistics")
        self.stats_frame = tk.Frame(stats, bg=ModernStyle.BG_SECONDARY)
        self.stats_frame.pack(fill="x", pady=(0, 8))
        
        self.stats_loading_label = tk.Label(self.stats_frame, text="Loading statistics...", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY)
        self.stats_loading_label.pack(anchor="w")

        ModernButton(stats, text="Refresh Stats", command=self._refresh_database_stats, bg=ModernStyle.ACCENT_SECONDARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=110, height=32).pack(anchor="w")

        # Theme
        theme = _card(right_col, "🎨 Theme")
        try:
            current_theme = ttk.Style().theme_use()
        except Exception:
            current_theme = "(unknown)"
        tk.Label(theme, text=f"Light Mode (Currently Enabled) • ttk: {current_theme}", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY).pack(anchor="w")
        try:
            names = ", ".join(ttk.Style().theme_names())
        except Exception:
            names = "(unavailable)"
        tk.Label(theme, text=f"Available ttk themes: {names}", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL, wraplength=350, justify="left").pack(anchor="w", pady=(4, 0))

        # Data Cache
        cache = _card(right_col, "⚡ Data Cache")
        tk.Label(cache, text="Cache is enabled for fast filtering", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY).pack(anchor="w")
        ModernButton(cache, text="Clear Cache", command=self._clear_cache, bg=ModernStyle.ACCENT_TERTIARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=130, height=36).pack(anchor="w", pady=(8, 0))

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

    def _open_broker_manager(self) -> None:
        """Open broker management modal window."""
        modal = tk.Toplevel(self)
        modal.title("Broker Manager")
        ModernStyle.style_modal(modal)
        modal.configure(bg=ModernStyle.BG_PRIMARY)
        modal.geometry("600x500")
        modal.resizable(True, True)
        
        try:
            center_window(modal, parent=self.winfo_toplevel())
        except Exception:
            pass
        
        try:
            modal.transient(self.winfo_toplevel())
            modal.grab_set()
        except Exception:
            pass
        
        # Header
        header = tk.Frame(modal, bg=ModernStyle.BG_PRIMARY)
        header.pack(fill="x", padx=15, pady=(15, 10))
        tk.Label(header, text="🏦 Broker Management", fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_PRIMARY, font=ModernStyle.FONT_MODAL_TITLE).pack(anchor="w")
        tk.Label(header, text="Add, view, and manage brokers", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_PRIMARY, font=ModernStyle.FONT_BODY).pack(anchor="w")
        
        # Add broker section
        add_card = ModernCard(modal, bg=ModernStyle.BG_SECONDARY, highlight_color=ModernStyle.BORDER_COLOR, highlight_thickness=1, radius=10, canvas_bg=ModernStyle.BG_PRIMARY)
        add_card.pack(fill="x", padx=15, pady=10)
        tk.Label(add_card.content, text="Add New Broker", fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SUBHEADING).pack(anchor="w", padx=12, pady=(10, 6))
        
        inner = tk.Frame(add_card.content, bg=ModernStyle.BG_SECONDARY)
        inner.pack(fill="x", padx=12, pady=(0, 12))
        inner.grid_columnconfigure(0, weight=1)
        
        new_broker_var = tk.StringVar(value="")
        entry = tk.Entry(inner, textvariable=new_broker_var, bg=ModernStyle.ENTRY_BG, fg=ModernStyle.TEXT_PRIMARY, font=ModernStyle.FONT_BODY, relief=tk.FLAT)
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        
        status_label = tk.Label(inner, text="", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TINY)
        status_label.grid(row=1, column=0, sticky="w", pady=(4, 0))
        
        def _add():
            name = (new_broker_var.get() or "").strip().upper()
            if not name:
                status_label.config(text="Enter a broker name", fg=ModernStyle.ERROR)
                return
            try:
                import model.crud as crud
                existing = [b.upper() for b in crud.get_all_brokers()]
                if name in existing:
                    status_label.config(text=f"Broker '{name}' already exists", fg=ModernStyle.ERROR)
                    return
                crud.add_broker(name)
                try:
                    if self.app_state and hasattr(self.app_state, "get_brokers_cached"):
                        self.app_state.get_brokers_cached(force_refresh=True)
                except Exception:
                    pass
                new_broker_var.set("")
                status_label.config(text=f"Broker '{name}' added ✓", fg=ModernStyle.SUCCESS)
                self.broker_status.config(text=f"Broker '{name}' added ✓")
                self._reload_brokers()
                self._refresh_broker_list(modal)
                entry.focus()
            except Exception as e:
                status_label.config(text=f"Error: {str(e)[:40]}", fg=ModernStyle.ERROR)
        
        ModernButton(inner, text="Add", command=_add, bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=60, height=32).grid(row=0, column=1, sticky="e")
        
        # Broker list section
        list_label = tk.Label(modal, text="Active Brokers", fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_PRIMARY, font=ModernStyle.FONT_SUBHEADING)
        list_label.pack(anchor="w", padx=15, pady=(10, 6))
        
        # Scrollable broker list
        list_canvas = tk.Canvas(modal, bg=ModernStyle.BG_PRIMARY, highlightthickness=0)
        list_scroll = ttk.Scrollbar(modal, orient="vertical", command=list_canvas.yview)
        list_canvas.configure(yscrollcommand=list_scroll.set)
        list_canvas.pack(side="left", fill="both", expand=True, padx=15, pady=(0, 15))
        list_scroll.pack(side="right", fill="y", pady=(0, 15))
        
        broker_list_frame = tk.Frame(list_canvas, bg=ModernStyle.BG_PRIMARY)
        list_cid = list_canvas.create_window((0, 0), window=broker_list_frame, anchor="nw")
        
        def _on_broker_list_cfg(_e=None):
            list_canvas.configure(scrollregion=list_canvas.bbox("all"))
            list_canvas.itemconfigure(list_cid, width=list_canvas.winfo_width() - 20)
        
        broker_list_frame.bind("<Configure>", _on_broker_list_cfg)
        list_canvas.bind("<Configure>", _on_broker_list_cfg)
        
        self.modal_broker_frame = broker_list_frame
        self.modal_list_canvas = list_canvas
        self._refresh_broker_list(modal)
        
        # Close button
        footer = tk.Frame(modal, bg=ModernStyle.BG_PRIMARY)
        footer.pack(fill="x", padx=15, pady=(0, 15))
        ModernButton(footer, text="Close", command=modal.destroy, bg=ModernStyle.ACCENT_TERTIARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_PRIMARY, width=80, height=32).pack(anchor="e")
    
    def _refresh_broker_list(self, modal) -> None:
        """Refresh broker list in modal."""
        if not hasattr(self, 'modal_broker_frame'):
            return
        
        try:
            import model.crud as crud
            brokers = crud.get_all_brokers()
        except Exception:
            brokers = []
        
        for w in self.modal_broker_frame.winfo_children():
            w.destroy()
        
        if not brokers:
            tk.Label(self.modal_broker_frame, text="📭 No brokers yet. Add one above!", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_PRIMARY, font=ModernStyle.FONT_BODY).pack(anchor="w", padx=4, pady=8)
            return
        
        for i, name in enumerate(brokers):
            # Broker row with pill style
            row = tk.Frame(self.modal_broker_frame, bg=ModernStyle.BG_SECONDARY, highlightbackground="#DBEAFE", highlightthickness=1)
            row.pack(fill="x", pady=3, padx=2)
            
            trade_count = self._broker_trade_counts.get(name, 0)
            info_text = f"📊 {name}  •  {trade_count} trade{'s' if trade_count != 1 else ''}"
            tk.Label(row, text=info_text, fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY).pack(side="left", padx=12, pady=8, expand=True, fill="x")
            
            ModernButton(row, text="Delete", command=lambda n=name: self._delete_broker_from_modal(n, modal), bg=ModernStyle.ERROR, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=70, height=28).pack(side="right", padx=4, pady=4)
    
    def _delete_broker_from_modal(self, name: str, modal) -> None:
        """Delete broker and refresh modal."""
        if not messagebox.askyesno("Delete Broker", f"Delete broker '{name}'?\n\nAll its trades and holdings will be deleted."):
            return
        
        def _bg():
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
                self.after(0, lambda: (self._reload_brokers(), self._refresh_broker_list(modal), self.broker_status.config(text=f"Broker '{name}' deleted ✓")))
            except Exception as e:
                err = str(e)
                self.after(0, lambda e=err: self.broker_status.config(text=f"Delete failed: {e}"))
        
        threading.Thread(target=_bg, daemon=True).start()
    
    def _quick_add_broker_dialog(self) -> None:
        """Quick add broker with suggested names."""
        dlg = tk.Toplevel(self)
        dlg.title("Quick Add Broker")
        ModernStyle.style_modal(dlg)
        dlg.configure(bg=ModernStyle.BG_PRIMARY)
        dlg.geometry("400x200")
        dlg.resizable(False, False)
        
        try:
            center_window(dlg, parent=self.winfo_toplevel())
        except Exception:
            pass
        
        try:
            dlg.transient(self.winfo_toplevel())
            dlg.grab_set()
        except Exception:
            pass
        
        card = tk.Frame(dlg, bg=ModernStyle.BG_SECONDARY)
        card.pack(fill="both", expand=True, padx=12, pady=12)
        
        tk.Label(card, text="Broker Name", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_SMALL).pack(anchor="w", padx=12, pady=(10, 4))
        
        broker_var = tk.StringVar(value="")
        entry = tk.Entry(card, textvariable=broker_var, bg=ModernStyle.ENTRY_BG, fg=ModernStyle.TEXT_PRIMARY, font=ModernStyle.FONT_BODY, relief=tk.FLAT)
        entry.pack(fill="x", padx=12, pady=(0, 8))
        entry.focus()
        
        # Suggested brokers
        suggested_frame = tk.Frame(card, bg=ModernStyle.BG_SECONDARY)
        suggested_frame.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(suggested_frame, text="Suggested:", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TINY).pack(anchor="w")
        
        suggested = ["Kite", "Upstox", "ICICI Direct", "Angel", "Broker"]
        suggested_row = tk.Frame(card, bg=ModernStyle.BG_SECONDARY)
        suggested_row.pack(fill="x", padx=12, pady=(0, 12))
        
        for sug in suggested[:3]:
            tk.Button(suggested_row, text=sug, command=lambda s=sug: broker_var.set(s), bg=ModernStyle.ACCENT_TERTIARY, fg=ModernStyle.TEXT_ON_ACCENT, relief=tk.FLAT, pady=2, padx=6, font=ModernStyle.FONT_TINY).pack(side="left", padx=2)
        
        status = tk.Label(card, text="", fg=ModernStyle.TEXT_TERTIARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TINY)
        status.pack(anchor="w", padx=12, pady=(0, 8))
        
        def _add():
            name = (broker_var.get() or "").strip().upper()
            if not name:
                status.config(text="Enter a broker name", fg=ModernStyle.ERROR)
                return
            try:
                import model.crud as crud
                existing = [b.upper() for b in crud.get_all_brokers()]
                if name in existing:
                    status.config(text=f"'{name}' already exists", fg=ModernStyle.ERROR)
                    return
                crud.add_broker(name)
                try:
                    if self.app_state and hasattr(self.app_state, "get_brokers_cached"):
                        self.app_state.get_brokers_cached(force_refresh=True)
                except Exception:
                    pass
                self.broker_status.config(text=f"Broker '{name}' added ✓")
                self._reload_brokers()
                dlg.destroy()
            except Exception as e:
                status.config(text=f"Error: {str(e)[:30]}", fg=ModernStyle.ERROR)
        
        btn_row = tk.Frame(card, bg=ModernStyle.BG_SECONDARY)
        btn_row.pack(fill="x", padx=12, pady=(0, 12))
        
        ModernButton(btn_row, text="Cancel", command=dlg.destroy, bg=ModernStyle.ACCENT_TERTIARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=70, height=32).pack(side="right", padx=2)
        ModernButton(btn_row, text="Add", command=_add, bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT, canvas_bg=ModernStyle.BG_SECONDARY, width=70, height=32).pack(side="right", padx=(0, 2))
    
    def _clear_cache(self):
        try:
            if self.app_state and hasattr(self.app_state, "refresh_data_cache"):
                self.app_state.refresh_data_cache()
        except Exception:
            pass
        self.broker_status.config(text="Cache refreshed")

    def _wipe_all_data(self) -> None:
        if not messagebox.askyesno("Wipe All Data", "Are you absolutely sure?\n\nThis will delete ALL trades, market data, and holdings.\nBrokers are NOT deleted."):
            return

        self.broker_status.config(text="Wiping data…")

        def _bg():
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
                self.after(0, lambda: (self.broker_status.config(text="All data wiped ✓"), self._reload_brokers()))
            except Exception as e:
                err = str(e)
                self.after(0, lambda e=err: self.broker_status.config(text=f"Wipe failed: {e}"))

        threading.Thread(target=_bg, daemon=True).start()



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
                writer.writerow(["broker", "trade_id", "date", "symbol", "type", "qty", "price", "fee"])
                writer.writerows(trades)
            
            self.backup_status.config(text=f"Exported {len(trades)} trades ✓", fg=ModernStyle.SUCCESS)
        except Exception as e:
            self.backup_status.config(text=f"Export failed: {str(e)[:40]}", fg=ModernStyle.ERROR)

    def _refresh_database_stats(self):
        """Refresh the database statistics UI."""
        def _bg():
            try:
                import model.crud as crud
                stats = crud.get_all_table_stats()
                self.after(0, lambda: self._render_stats(stats))
            except Exception as e:
                self.after(0, lambda: self.stats_loading_label.config(text=f"Error: {str(e)[:40]}", fg=ModernStyle.ERROR))
        
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
            
        row = 0
        for table, count in sorted(stats.items()):
            table_row = tk.Frame(self.stats_frame, bg=ModernStyle.BG_SECONDARY)
            table_row.pack(fill="x", pady=2)
            
            tk.Label(table_row, text=f"• {table}", fg=ModernStyle.TEXT_PRIMARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_BODY).pack(side="left")
            tk.Label(table_row, text=f"{count} rows", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_SECONDARY, font=ModernStyle.FONT_TINY_BOLD).pack(side="right")
            row += 1
