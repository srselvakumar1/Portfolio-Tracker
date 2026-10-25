"""Add / edit trade dialogs shared by Holdings, the Dashboard and Trade History.

    open_edit_trade_modal(...)       edit one trade (Holdings drill-down)
    open_quick_add_trade_modal(...)  add trades for one symbol (Dashboard Quick Buy / Sell)

Helpers that Trade History's own dialogs use too:
    TradeForm            the two-column form: theme colours, focus rings, BUY/SELL and
                         currency choices, a price label that shows the right symbol
    currency_symbol()    "₹", "¥", "$" ...
    currency_choices()   INR, JPY and every currency your brokers use
    check_trade_fields() typed text -> numbers, or ValueError with a plain-English message
    save_trade_edit()    writes an edit in ONE transaction (moving a trade to another
                         broker is a single UPDATE, so a failure leaves it untouched)
    friendly_error()     turns a database error into a sentence for the status line
"""

import sqlite3
import tkinter as tk
from datetime import date as _date, datetime
from tkinter import messagebox, ttk

from model.applog import log
from model.importer import CURRENCY_SYMBOLS, parse_number, sanity_warnings
from ui.ui_theme import ModernStyle
from ui.ui_utils import center_window, run_in_background, show_toast
from ui.ui_widgets import RoundedBox, ModernButton
from views.base_view import _create_date_input


# ── Helpers ────────────────────────────────────────────────────────────────────
def currency_symbol(code: str) -> str:
    code = (code or "INR").strip().upper()
    return CURRENCY_SYMBOLS.get(code, code)


def broker_currency_map(app_state=None) -> dict:
    """{broker: currency} from the app's cache (one small query the first time)."""
    try:
        if app_state is not None and hasattr(app_state, "get_broker_currencies_cached"):
            return dict(app_state.get_broker_currencies_cached() or {})
        import model.crud as crud
        return dict(crud.get_broker_currencies() or {})
    except Exception:
        log.exception("Could not read the broker currencies")
        return {}


def known_brokers(app_state=None, *extra: str) -> list:
    try:
        if app_state is not None and hasattr(app_state, "get_brokers_cached"):
            names = list(app_state.get_brokers_cached() or [])
        else:
            import model.crud as crud
            names = list(crud.get_all_brokers() or [])
    except Exception:
        log.exception("Could not read the broker list")
        names = []
    names = sorted(set(names))
    for b in extra:
        if b and b not in names:
            names.insert(0, b)
    return names


def currency_choices(app_state=None, *extra: str) -> list:
    """INR, JPY, then any other currency your brokers use (and `extra`)."""
    out = ["INR", "JPY"]
    for c in list(broker_currency_map(app_state).values()) + list(extra):
        c = (c or "").strip().upper()
        if c and c not in out:
            out.append(c)
    return out


def friendly_error(e: Exception, *, broker: str = "", trade_id: str = "") -> str:
    if isinstance(e, sqlite3.IntegrityError):
        if broker:
            return f"{broker} already has a trade with id {trade_id}, so nothing was changed."
        return "A trade with this id already exists, so nothing was changed."
    if isinstance(e, sqlite3.OperationalError) and "locked" in str(e).lower():
        return "The database is busy. Please try again in a moment."
    if isinstance(e, ValueError):
        return str(e)
    return "Something went wrong, so nothing was changed. The details are in the log."


def check_trade_fields(*, broker, date, symbol, trade_type, qty, price, fee, currency,
                       new_trade: bool = False, original_date: str | None = None) -> dict:
    """Validate what was typed. Returns clean values, or raises ValueError (a message for the user).

    A date in the future is refused, except when editing a trade that already had that
    date (so an old typo can still be opened and corrected)."""
    broker = (broker or "").strip()
    if not broker:
        raise ValueError("Please choose a broker.")
    date = (date or "").strip()
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Date must look like 2024-01-15 (year-month-day)")
    if d > _date.today() and date != (original_date or "").strip():
        raise ValueError("The date is in the future.")
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("Please enter the symbol.")
    t_type = (trade_type or "").strip().upper()
    if t_type not in ("BUY", "SELL"):
        raise ValueError("Type must be BUY or SELL.")
    cur = (currency or "INR").strip().upper()
    q, q_err = parse_number(qty)
    if q_err or q <= 0:
        raise ValueError("Quantity must be a number more than 0.")
    if new_trade and cur == "INR" and abs(q - round(q)) > 1e-9:
        raise ValueError("INR quantities must be whole shares.")
    p, p_err = parse_number(price)
    if p_err or p <= 0:
        raise ValueError("Price must be a number more than 0.")
    f, f_err = parse_number(fee)
    if f_err == "missing":
        f = 0.0
    elif f_err or f < 0:
        raise ValueError("Fees must be a number (0 if none).")
    return dict(broker=broker, date=date, symbol=symbol, trade_type=t_type,
                qty=float(q), price=float(p), fee=float(f), currency=cur)


def confirm_unusual(parent, qty: float, price: float, currency: str, last_price=None) -> bool:
    """Ask "Are you sure?" when a trade looks unusually large. True = go ahead."""
    reasons = sanity_warnings(qty, price, currency, last_price)
    if not reasons:
        return True
    return messagebox.askyesno(
        "Please check this trade",
        "\n".join(reasons) + "\n\nSave it anyway?",
        parent=parent,
    )


def save_trade_edit(*, broker_old: str, trade_id: str, symbol_old: str, values: dict,
                    rename_all: bool = False) -> None:
    """Write an edited trade. Everything happens in one transaction: if any part fails
    (for example the new broker already has this trade id) nothing is changed."""
    from model.database import db_session

    v = values
    with db_session() as conn:
        if rename_all:
            conn.execute("UPDATE trades SET symbol = ? WHERE broker = ? AND symbol = ?",
                         (v["symbol"], broker_old, symbol_old))
        cur = conn.execute(
            "UPDATE trades SET broker = ?, date = ?, symbol = ?, type = ?, qty = ?, price = ?, fee = ?, currency = ? "
            "WHERE broker = ? AND trade_id = ?",
            (v["broker"], v["date"], v["symbol"], v["trade_type"], v["qty"], v["price"], v["fee"],
             v["currency"], broker_old, trade_id),
        )
        if cur.rowcount == 0:
            raise ValueError("This trade isn't in the database any more (was it deleted?).")


STALE_WARNING = ("The trade was saved, but your holdings couldn't be recalculated. "
                 "Press ⟳ Refresh, or restart the app, to update them.")


def refresh_after_change(app_state=None) -> str | None:
    """Rebuild holdings and the in-memory data after trades changed (run in a worker).

    Returns None when all went well, else a message for show_stale_warning() (the
    details are in the log)."""
    ok = True
    try:
        from model.engine import rebuild_holdings
        rebuild_holdings()
    except Exception:
        ok = False
        log.exception("Rebuilding holdings after a trade change failed")
    try:
        if app_state is not None and hasattr(app_state, "refresh_data_cache"):
            app_state.refresh_data_cache()
    except Exception:
        ok = False
        log.exception("Refreshing the data cache after a trade change failed")
    return None if ok else STALE_WARNING


def show_stale_warning(parent, warning) -> None:
    """Tk thread: tell the user when refresh_after_change() reported a problem."""
    if warning:
        try:
            show_toast(parent.winfo_toplevel(), warning, type="warning")
        except tk.TclError:
            pass


# ── The form ───────────────────────────────────────────────────────────────────
class TradeForm:
    """A two-column grid of labelled inputs in the theme colours.

    Labels go on grid row r*2 and their input on r*2+1. `accent` colours the focus ring.
    """

    def __init__(self, parent, *, accent=None):
        self.bg = ModernStyle.BG_PRIMARY
        self.accent = accent or ModernStyle.ACCENT_PRIMARY
        self.frame = tk.Frame(parent, bg=self.bg)
        for i in range(2):
            self.frame.grid_columnconfigure(i, weight=1, uniform="tf")
        self.price_label = None
        self.fee_label = None

    def label(self, text, r, c):
        lbl = tk.Label(self.frame, text=text, bg=self.bg, fg=ModernStyle.TEXT_SECONDARY,
                       font=ModernStyle.FONT_BODY_BOLD)
        lbl.grid(row=r * 2, column=c, sticky="w", pady=(10 if r > 0 else 0, 4), padx=(0, 12 if c == 0 else 0))
        return lbl

    def _wrap(self, r, c, plain: bool = False):
        # Rounded bordered box; a date input brings its own box, so it gets a plain frame
        wrap = tk.Frame(self.frame, bg=self.bg) if plain else RoundedBox(self.frame)
        wrap.grid(row=r * 2 + 1, column=c, sticky="ew", pady=(0, 4), padx=(0, 12 if c == 0 else 0))
        return wrap

    def entry(self, r, c, var, *, is_date=False):
        wrap = self._wrap(r, c, plain=is_date)
        if is_date:
            ent = _create_date_input(wrap, var)
            ent.pack(fill="both", expand=True)
            return ent
        ent = tk.Entry(wrap, textvariable=var, bg=ModernStyle.ENTRY_BG, fg=ModernStyle.TEXT_PRIMARY,
                       font=ModernStyle.FONT_TABLE, relief=tk.FLAT, highlightthickness=0,
                       insertbackground=self.accent)
        ent.bind("<FocusIn>", lambda e, w=wrap: w.configure(bg=self.accent))
        ent.bind("<FocusOut>", lambda e, w=wrap: w.configure(bg=ModernStyle.BORDER_COLOR))
        ent.pack(fill="both", expand=True, ipady=5, padx=8)
        return ent

    def broker_box(self, r, c, var, brokers):
        wrap = self._wrap(r, c)
        cb = ttk.Combobox(wrap, textvariable=var, values=brokers, font=ModernStyle.FONT_INPUT, state="normal",
                          style="Boxed.TCombobox")
        cb.pack(fill="both", expand=True, ipady=4, padx=4, pady=1)
        wrap.watch(cb)
        return cb

    def money_labels(self, price_rc, fee_rc, currency_var):
        """Price / Fees labels whose symbol follows the currency choice."""
        self.price_label = self.label("", *price_rc)
        self.fee_label = self.label("", *fee_rc) if fee_rc else None

        def _sync(*_):
            sym = currency_symbol(currency_var.get())
            try:
                self.price_label.configure(text=f"💰  Price ({sym})")
                if self.fee_label is not None:
                    self.fee_label.configure(text=f"💸  Fees ({sym})")
            except tk.TclError:
                pass
        currency_var.trace_add("write", _sync)
        _sync()

    def choice_rows(self, grid_row, type_var, currency_var, currencies):
        """'Trade Type' + 'Currency' captions on grid_row and the radio buttons below."""
        bg = self.bg
        cap = tk.Frame(self.frame, bg=bg)
        cap.grid(row=grid_row, column=0, columnspan=2, sticky="w", pady=(12, 4))
        tk.Label(cap, text="🚦  Trade Type", bg=bg, fg=ModernStyle.TEXT_SECONDARY,
                 font=ModernStyle.FONT_BODY_BOLD).pack(side="left")
        tk.Frame(cap, width=16, bg=bg).pack(side="left")
        tk.Label(cap, text="💱  Currency", bg=bg, fg=ModernStyle.TEXT_SECONDARY,
                 font=ModernStyle.FONT_BODY_BOLD).pack(side="left")

        row = tk.Frame(self.frame, bg=bg)
        row.grid(row=grid_row + 1, column=0, columnspan=2, sticky="w", pady=(0, 10))
        for val, color in (("BUY", ModernStyle.SUCCESS), ("SELL", ModernStyle.ERROR)):
            tk.Radiobutton(row, text=val, variable=type_var, value=val, bg=bg, fg=color,
                           activebackground=bg, activeforeground=color, selectcolor=bg,
                           font=ModernStyle.FONT_TABLE_BOLD).pack(side="left", padx=(0, 20))
        tk.Frame(row, bg=ModernStyle.DIVIDER_COLOR, width=2, height=20).pack(side="left", padx=12)
        for val in currencies:
            tk.Radiobutton(row, text=val, variable=currency_var, value=val, bg=bg, fg=ModernStyle.TEXT_ACCENT,
                           activebackground=bg, activeforeground=ModernStyle.TEXT_ACCENT, selectcolor=bg,
                           font=ModernStyle.FONT_TABLE_BOLD).pack(side="left", padx=(0, 16))
        return row


def follow_broker_currency(broker_var, currency_var, app_state=None) -> None:
    """When a broker is picked, switch the currency to that broker's currency."""
    mapping = broker_currency_map(app_state)
    by_lower = {str(k).lower(): v for k, v in mapping.items()}

    def _sync(*_):
        cur = by_lower.get((broker_var.get() or "").strip().lower())
        if cur and cur.upper() != (currency_var.get() or "").upper():
            currency_var.set(cur.upper())
    broker_var.trace_add("write", _sync)


def make_dialog(parent, title: str, size: str, accent: str):
    """A themed modal window with a coloured top bar."""
    win = tk.Toplevel(parent)
    win.title(title)
    ModernStyle.style_modal(win)
    win.configure(bg=ModernStyle.BG_PRIMARY)
    win.resizable(False, False)
    win.geometry(size)
    try:
        win.transient(parent.winfo_toplevel())
        win.grab_set()
    except Exception:
        pass
    try:
        center_window(win, parent=parent.winfo_toplevel())
    except Exception:
        pass
    tk.Frame(win, bg=accent, height=4).pack(fill="x")
    return win


def dialog_footer(win):
    """Divider, status line and the button row. Returns (status_label, actions_frame)."""
    tk.Frame(win, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=24, pady=(4, 0))
    status = tk.Label(win, text="", bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY,
                      font=ModernStyle.FONT_BODY, anchor="w", justify="left", wraplength=540)
    status.pack(anchor="w", padx=28, pady=(8, 4), fill="x")
    actions = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
    actions.pack(fill="x", padx=24, pady=(0, 18))
    return status, actions


def dialog_button(parent, text, command, fill, width):
    return ModernButton(parent, text=text, command=command, bg=fill, fg=ModernStyle.TEXT_ON_ACCENT,
                        canvas_bg=ModernStyle.BG_PRIMARY, width=width, height=42, radius=8,
                        font=ModernStyle.FONT_SUBHEADING)


def _safe_destroy(win):
    try:
        if win.winfo_exists():
            win.destroy()
    except Exception:
        pass


def number_text(v) -> str:
    """A number for an input box: 17.0 -> "17", "₹1,234.5" -> "1234.5"."""
    s = str(v if v is not None else "").replace(",", "").replace("₹", "").replace("¥", "").replace("$", "").strip()
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f.is_integer() and abs(f) < 1e15 else s


# ── Edit one trade (Holdings) ─────────────────────────────────────────────────
def open_edit_trade_modal(parent: tk.Widget, reload_cb, broker: str, trade_id: str, date: str, symbol: str,
                          trade_type: str, qty: str, price: str, fee: str, currency: str = "INR",
                          app_state=None) -> None:
    if not broker or not trade_id:
        messagebox.showerror("Edit Trade", "This row has no broker or trade id, so it can't be edited.", parent=parent)
        return

    win = make_dialog(parent, "✏️ Edit Trade", "600x560", ModernStyle.ACCENT_PRIMARY)
    header = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
    header.pack(fill="x", padx=28, pady=(18, 0))
    tk.Label(header, text=symbol.upper() if symbol else "Edit Trade", bg=ModernStyle.BG_PRIMARY,
             fg=ModernStyle.TEXT_ACCENT, font=ModernStyle.FONT_SYMBOL_LARGE).pack(anchor="w")
    tk.Label(header, text=f"✏️  Editing Trade  ·  {trade_id}", bg=ModernStyle.BG_PRIMARY,
             fg=ModernStyle.TEXT_SECONDARY, font=ModernStyle.FONT_BODY).pack(anchor="w", pady=(2, 12))
    tk.Frame(win, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=20)

    card = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
    card.pack(fill="both", expand=True, padx=24, pady=16)

    broker_var = tk.StringVar(value=(broker or "").strip())
    date_var = tk.StringVar(value=(date or "").strip())
    symbol_var = tk.StringVar(value=(symbol or "").strip().upper())
    type_var = tk.StringVar(value=(trade_type or "BUY").strip().upper())
    qty_var = tk.StringVar(value=number_text(qty))
    price_var = tk.StringVar(value=number_text(price))
    fee_var = tk.StringVar(value=number_text(fee))
    currency_var = tk.StringVar(value=(currency or "INR").strip().upper())

    form = TradeForm(card)
    form.frame.pack(fill="x")
    form.label("🏦  Broker", 0, 0)
    form.broker_box(0, 0, broker_var, known_brokers(app_state, broker))
    form.label("📅  Trade Date", 0, 1)
    form.entry(0, 1, date_var, is_date=True)
    form.label("🔠  Symbol", 1, 0)
    form.entry(1, 0, symbol_var)
    form.label("💎  Quantity", 1, 1)
    form.entry(1, 1, qty_var)
    form.money_labels((2, 0), (2, 1), currency_var)
    form.entry(2, 0, price_var)
    form.entry(2, 1, fee_var)
    form.choice_rows(8, type_var, currency_var, currency_choices(app_state, currency_var.get()))

    status, actions = dialog_footer(win)
    saving = [False]

    def _save():
        if saving[0]:
            return
        try:
            values = check_trade_fields(broker=broker_var.get(), date=date_var.get(), symbol=symbol_var.get(),
                                        trade_type=type_var.get(), qty=qty_var.get(), price=price_var.get(),
                                        fee=fee_var.get(), currency=currency_var.get(), original_date=date)
        except ValueError as e:
            status.configure(text=str(e), fg=ModernStyle.ERROR)
            return

        rename_all = False
        if values["symbol"] != (symbol or "").strip().upper():
            rename_all = messagebox.askyesno(
                "Rename Symbol",
                f"Rename ALL trades for '{symbol}' under broker '{broker}' to '{values['symbol']}'?\n\n"
                "Choose No to change only this trade.",
                parent=win)

        saving[0] = True
        save_btn.set_disabled(True)
        status.configure(text="Updating…", fg=ModernStyle.TEXT_SECONDARY)

        def _work():
            save_trade_edit(broker_old=broker, trade_id=trade_id, symbol_old=symbol,
                            values=values, rename_all=rename_all)
            return refresh_after_change(app_state)

        def _done(warning):
            _safe_destroy(win)
            try:
                if reload_cb:
                    reload_cb()
            except Exception:
                log.exception("Reloading after a trade edit failed")
            show_stale_warning(parent, warning)

        def _failed(e):
            saving[0] = False
            try:
                save_btn.set_disabled(False)
                status.configure(text=f"Update failed: {friendly_error(e, broker=values['broker'], trade_id=trade_id)}",
                                 fg=ModernStyle.ERROR)
            except tk.TclError:
                pass

        run_in_background(_work, _done, _failed, name="edit-trade")

    save_btn = dialog_button(actions, "✓ Update Trade", _save, ModernStyle.ACCENT_PRIMARY, 160)
    save_btn.pack(side="right")
    dialog_button(actions, "✕ Cancel", win.destroy, ModernStyle.NEUTRAL_FILL, 120).pack(side="right", padx=(0, 12))


# ── Quick add (Dashboard) ─────────────────────────────────────────────────────
def open_quick_add_trade_modal(parent, reload_cb, symbol="", broker="", stock_name="", keep_open=False,
                               app_state=None, trade_type="BUY", currency="INR") -> None:
    accent = ModernStyle.ACCENT_PRIMARY if keep_open else ModernStyle.SUCCESS_FILL
    win = make_dialog(parent, "➕ Add Trade & Continue" if keep_open else "+ Add Trade",
                      "600x600" if keep_open else "600x580", accent)
    header = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
    header.pack(fill="x", padx=28, pady=(16, 0))
    tk.Label(header, text=symbol, bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_ACCENT,
             font=ModernStyle.FONT_SYMBOL_LARGE).pack(anchor="w")
    tk.Label(header, text=stock_name or "", bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY,
             font=ModernStyle.FONT_SUBHEADING).pack(anchor="w", pady=(0, 8))
    tk.Label(header, text="➕  Quick Add Trade • Continue Mode" if keep_open else "➕  Quick Add Trade",
             bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY,
             font=ModernStyle.FONT_BODY).pack(anchor="w", pady=(0, 10))
    tk.Frame(win, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=20)

    card = tk.Frame(win, bg=ModernStyle.BG_PRIMARY)
    card.pack(fill="both", expand=True, padx=24, pady=12)

    broker_var = tk.StringVar(value=broker)
    date_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
    type_var = tk.StringVar(value=(trade_type or "BUY").upper())
    qty_var, price_var, fee_var = tk.StringVar(value=""), tk.StringVar(value=""), tk.StringVar(value="0.0")
    currency_var = tk.StringVar(value=(currency or "INR").upper())

    form = TradeForm(card, accent=ModernStyle.SUCCESS_FILL)
    form.frame.pack(fill="x")
    form.label("🏦  Broker", 0, 0)
    form.broker_box(0, 0, broker_var, known_brokers(app_state, broker))
    form.label("📅  Date", 0, 1)
    form.entry(0, 1, date_var, is_date=True)
    form.label("💎  Quantity", 1, 0)
    qty_entry = form.entry(1, 0, qty_var)
    form.money_labels((1, 1), (2, 0), currency_var)
    form.entry(1, 1, price_var)
    form.entry(2, 0, fee_var)
    form.choice_rows(6, type_var, currency_var, currency_choices(app_state, currency_var.get()))
    follow_broker_currency(broker_var, currency_var, app_state)

    status_lbl, act = dialog_footer(win)
    save_count = [0]
    saving = [False]
    count_lbl = tk.Label(act, text="", bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_ACCENT,
                         font=ModernStyle.FONT_BODY_BOLD)
    count_lbl.pack(side="left")

    def _set_busy(busy: bool):
        saving[0] = busy
        for b in (add_btn, cont_btn):
            try:
                b.set_disabled(busy)
            except tk.TclError:
                pass

    def _do_save(close_after: bool):
        if saving[0]:
            return
        try:
            values = check_trade_fields(broker=broker_var.get(), date=date_var.get(), symbol=symbol,
                                        trade_type=type_var.get(), qty=qty_var.get(), price=price_var.get(),
                                        fee=fee_var.get(), currency=currency_var.get(), new_trade=True)
        except ValueError as ex:
            status_lbl.configure(text=str(ex), fg=ModernStyle.ERROR)
            return
        if not confirm_unusual(win, values["qty"], values["price"], values["currency"]):
            return
        _set_busy(True)
        status_lbl.configure(text="Saving…", fg=ModernStyle.TEXT_SECONDARY)

        def _work():
            import uuid
            import model.crud as crud
            v = values
            crud.add_trade(v["broker"], v["date"], v["symbol"], v["trade_type"], v["qty"], v["price"], v["fee"],
                           str(uuid.uuid4())[:8], currency=v["currency"])
            return refresh_after_change(app_state)

        def _done(warning):
            try:
                if reload_cb:
                    reload_cb()
            except Exception:
                log.exception("Reloading after a quick add failed")
            show_stale_warning(parent, warning)
            if close_after:
                _safe_destroy(win)
                return
            if not win.winfo_exists():
                return
            _set_busy(False)
            save_count[0] += 1
            n = save_count[0]
            status_lbl.configure(text=f"✅ Trade saved!  ({n} trade{'s' if n != 1 else ''} added this session)",
                                 fg=ModernStyle.SUCCESS)
            count_lbl.configure(text=f"📌 {n} added")
            qty_var.set("")
            price_var.set("")
            fee_var.set("0.0")
            try:
                qty_entry.focus_set()
            except tk.TclError:
                pass

        def _failed(e):
            try:
                _set_busy(False)
                status_lbl.configure(text=f"Save failed: {friendly_error(e)}", fg=ModernStyle.ERROR)
            except tk.TclError:
                pass

        run_in_background(_work, _done, _failed, name="quick-add-trade")

    add_btn = dialog_button(act, "✓ Add Trade", lambda: _do_save(True), ModernStyle.SUCCESS_FILL, 150)
    add_btn.pack(side="right")
    cont_btn = dialog_button(act, "⟳ Add & Continue", lambda: _do_save(False), ModernStyle.ACCENT_PRIMARY, 165)
    cont_btn.pack(side="right", padx=(0, 10))
    dialog_button(act, "✕ Cancel", win.destroy, ModernStyle.NEUTRAL_FILL, 110).pack(side="right", padx=(0, 10))
