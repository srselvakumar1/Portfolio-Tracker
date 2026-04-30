import tkinter as tk
from tkinter import ttk, messagebox
import threading

from ui_theme import ModernStyle
from ui_widgets import ModernButton
from ui_utils import center_window
from views.base_view import _create_date_input

def open_edit_trade_modal(parent: tk.Widget, reload_cb, broker: str, trade_id: str, date: str, symbol: str, trade_type: str, qty: str, price: str, fee: str, app_state=None) -> None:
    if not broker or not trade_id:
        messagebox.showerror("Edit Trade", "Missing broker/trade id for this row.")
        return

    win = tk.Toplevel(parent)
    win.title("✏️ Edit Trade")
    ModernStyle.style_modal(win)
    win.configure(bg=ModernStyle.BG_PRIMARY)
    win.resizable(False, False)
    win.geometry("600x540")
    try:
        win.transient(parent.winfo_toplevel())
        win.grab_set()
    except Exception:
        pass

    try:
        center_window(win, parent=parent.winfo_toplevel())
    except Exception:
        pass

    tk.Frame(win, bg=ModernStyle.ACCENT_PRIMARY, height=4).pack(fill="x")
    header = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
    header.pack(fill="x", padx=28, pady=(18, 0))

    tk.Label(
        header, text=symbol.upper() if symbol else "Edit Trade",
        bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.ACCENT_PRIMARY,
        font=ModernStyle.FONT_SYMBOL_LARGE,
    ).pack(anchor="w")

    tk.Label(
        header, text=f"✏️  Editing Trade  ·  {trade_id}",
        bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY,
        font=ModernStyle.FONT_BODY,
    ).pack(anchor="w", pady=(2, 12))

    tk.Frame(win, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=20)

    card = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
    card.pack(fill="both", expand=True, padx=24, pady=16)

    form = tk.Frame(card, bg=ModernStyle.BG_PRIMARY)
    form.pack(fill="x")
    for i in range(2):
        form.grid_columnconfigure(i, weight=1)

    BG = ModernStyle.BG_PRIMARY
    BORDER = "#E2E8F0"
    FG = "#0F172A"

    def _label(text, r, c):
        tk.Label(form, text=text, bg=BG, fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_BODY_BOLD).grid(row=r * 2, column=c, sticky="w", pady=(10 if r > 0 else 0, 4), padx=(0, 12 if c == 0 else 0))

    def _entry_widget(r, c, var, *, is_date=False):
        wrap = tk.Frame(form, bg=BORDER, padx=1, pady=1)
        wrap.grid(row=r * 2 + 1, column=c, sticky="ew", pady=(0, 4), padx=(0, 12 if c == 0 else 0))
        if is_date:
            ent = _create_date_input(wrap, var)
            ent.pack(fill="both", expand=True)
        else:
            ent = tk.Entry(wrap, textvariable=var, bg="#F8FAFC", fg=FG, font=ModernStyle.FONT_TABLE, relief=tk.FLAT, insertbackground=ModernStyle.ACCENT_PRIMARY, highlightthickness=0)
            ent.bind("<FocusIn>", lambda e: [wrap.configure(bg=ModernStyle.ACCENT_PRIMARY), ent.configure(bg="#FFFFFF")])
            ent.bind("<FocusOut>", lambda e: [wrap.configure(bg=BORDER), ent.configure(bg="#F8FAFC")])
            ent.pack(fill="both", expand=True, ipady=6, padx=8)
        return ent

    _edit_broker_var = tk.StringVar(value=(broker or "").strip())
    _edit_date_var   = tk.StringVar(value=(date or "").strip())
    _edit_symbol_var = tk.StringVar(value=(symbol or "").strip().upper())
    _edit_type_var   = tk.StringVar(value=(trade_type or "BUY").strip().upper())
    _edit_qty_var    = tk.StringVar(value=str(qty).replace(",", "").replace("₹", "").strip())
    _edit_price_var  = tk.StringVar(value=str(price).replace(",", "").replace("₹", "").strip())
    _edit_fee_var    = tk.StringVar(value=str(fee).replace(",", "").replace("₹", "").strip())

    _label("👑  Broker", 0, 0)
    broker_wrap = tk.Frame(form, bg=BORDER, padx=1, pady=1)
    broker_wrap.grid(row=1, column=0, sticky="ew", pady=(0, 4), padx=(0, 12))
    try:
        import model.crud as _crud
        known_brokers = sorted(set(_crud.get_all_brokers()))
    except Exception:
        known_brokers = []
    if broker and broker not in known_brokers:
        known_brokers.insert(0, broker)
    broker_cb = ttk.Combobox(broker_wrap, textvariable=_edit_broker_var, values=known_brokers, font=ModernStyle.FONT_TABLE, state="normal")
    broker_cb.pack(fill="both", expand=True, ipady=4, padx=4)

    _label("📅  Trade Date", 0, 1)
    _entry_widget(0, 1, _edit_date_var, is_date=True)

    _label("💎  Symbol", 1, 0)
    _entry_widget(1, 0, _edit_symbol_var)
    _label("📊  Quantity", 1, 1)
    _entry_widget(1, 1, _edit_qty_var)

    _label("💰  Price (₹)", 2, 0)
    _entry_widget(2, 0, _edit_price_var)
    _label("💸  Fees (₹)", 2, 1)
    _entry_widget(2, 1, _edit_fee_var)

    type_lbl_frame = tk.Frame(form, bg=BG)
    type_lbl_frame.grid(row=6, column=0, columnspan=2, sticky="w", pady=(12, 4))
    tk.Label(type_lbl_frame, text="🌲  Trade Type", bg=BG, fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_BODY_BOLD).pack(side="left")

    type_row = tk.Frame(form, bg=BG)
    type_row.grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 10))

    for val, color in [("BUY", "#059669"), ("SELL", "#DC2626")]:
        tk.Radiobutton(type_row, text=val, variable=_edit_type_var, value=val, bg=BG, fg=color, font=ModernStyle.FONT_TABLE_BOLD, selectcolor=BG, activebackground=BG).pack(side="left", padx=(0, 24))

    tk.Frame(win, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=24, pady=(4, 0))
    status = tk.Label(win, text="", bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_ITALIC, anchor="w")
    status.pack(anchor="w", padx=28, pady=(8, 4), fill="x")

    actions = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
    actions.pack(fill="x", padx=24, pady=(0, 20))

    def _save():
        try:
            b = (_edit_broker_var.get() or "").strip()
            if not b: raise ValueError("Broker required")
            d = _edit_date_var.get() or ""
            sym = (_edit_symbol_var.get() or "").strip().upper()
            if not sym: raise ValueError("Symbol required")
            tt = _edit_type_var.get()
            q = float((_edit_qty_var.get() or "0").replace(",", ""))
            p = float((_edit_price_var.get() or "0").replace(",", ""))
            f = float((_edit_fee_var.get() or "0").replace(",", ""))
            if q <= 0: raise ValueError("Qty must be > 0")
            if p <= 0: raise ValueError("Price must be > 0")
        except Exception as e:
            status.configure(text=str(e), fg=ModernStyle.ERROR)
            return

        rename_all = False
        if sym != symbol:
            rename_all = messagebox.askyesno("Rename Symbol", f"Do you want to rename ALL trades for '{symbol}' under broker '{broker}' to '{sym}'?", parent=win)

        status.configure(text="Updating…", fg=ModernStyle.TEXT_TERTIARY)

        def _bg():
            err = None
            try:
                import model.crud as crud
                from model.engine import rebuild_holdings
                from model.database import db_session

                if rename_all:
                    with db_session() as conn:
                        conn.execute("UPDATE trades SET symbol = ? WHERE broker = ? AND symbol = ?", (sym, broker, symbol))

                if b != broker:
                    crud.delete_trade(broker, trade_id)
                    crud.add_trade(b, d, sym, tt, q, p, f, trade_id)
                else:
                    crud.update_trade(b, trade_id, d, sym, tt, q, p, f)
                
                try: rebuild_holdings()
                except Exception: pass
                
                try:
                    if app_state and hasattr(app_state, "refresh_data_cache"):
                        app_state.refresh_data_cache()
                except Exception: pass
            except Exception as e:
                err = str(e)

            def _done():
                if err:
                    status.configure(text=f"Update failed: {err}", fg=ModernStyle.ERROR)
                    return
                win.destroy()
                if reload_cb: reload_cb()

            parent.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    ModernButton(actions, text="✓ Update Trade", command=_save, bg=ModernStyle.ACCENT_PRIMARY, fg="#ffffff", canvas_bg=ModernStyle.BG_PRIMARY, width=160, height=42, radius=8, font=ModernStyle.FONT_SUBHEADING).pack(side="right")
    ModernButton(actions, text="✕ Cancel", command=win.destroy, bg=ModernStyle.TEXT_TERTIARY, fg="#ffffff", canvas_bg=ModernStyle.BG_PRIMARY, width=120, height=42, radius=8, font=ModernStyle.FONT_SUBHEADING).pack(side="right", padx=(0, 12))
