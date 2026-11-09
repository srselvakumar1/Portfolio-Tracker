#!/usr/bin/env python3
"""Small UI utilities shared across views.

Kept separate to avoid circular imports.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import sys

from model.applog import log


# ── Background work and the Tk thread ─────────────────────────────────────────
# Tkinter is not thread-safe: widgets and Tk variables must only be touched on
# the main thread. Background threads hand their results back with
# call_on_ui() (or run_in_background(), which does it for you); a timer on
# the main thread runs them every 30 ms.

_ui_queue: "queue.SimpleQueue" = queue.SimpleQueue()


def start_ui_dispatcher(root: tk.Misc, interval_ms: int = 30) -> None:
    """Start running queued UI callbacks on the main thread (call once, from main.py)."""
    def _drain():
        try:
            while True:
                fn, args, kwargs = _ui_queue.get_nowait()
                try:
                    fn(*args, **kwargs)
                except Exception:
                    log.exception("UI callback %s failed", getattr(fn, "__qualname__", fn))
        except queue.Empty:
            pass
        try:
            root.after(interval_ms, _drain)
        except tk.TclError:
            pass  # window closed
    root.after(interval_ms, _drain)


def call_on_ui(fn, *args, **kwargs) -> None:
    """Run fn(*args, **kwargs) soon on the Tk main thread. Safe from any thread."""
    _ui_queue.put((fn, args, kwargs))


def _alive(widget) -> bool:
    try:
        return widget is None or bool(widget.winfo_exists())
    except Exception:
        return False


def run_in_background(work, on_done=None, on_error=None, *, widget=None, name: str | None = None) -> threading.Thread:
    """Run work() in a daemon thread, then on_done(result) or on_error(exc) on the Tk thread.

    Read any Tk variables BEFORE calling this and pass the values into `work`.
    If `widget` is given and has been destroyed by the time the work finishes,
    the callbacks are skipped. Errors are always written to the log.
    """
    def _runner():
        try:
            result = work()
        except Exception as e:
            log.exception("Background task %s failed", name or getattr(work, "__qualname__", "work"))
            if on_error:
                call_on_ui(lambda err=e: _alive(widget) and on_error(err))
            return
        if on_done:
            call_on_ui(lambda: _alive(widget) and on_done(result))

    t = threading.Thread(target=_runner, daemon=True, name=name or getattr(work, "__name__", "background"))
    t.start()
    return t


def format_money(val: float, currency: str = "INR") -> str:
    """Format money as e.g. ₹1,234.50 or -₹1,234.50 (minus before the symbol)."""
    symbols = {
        "INR": "₹",
        "JPY": "¥",
        "USD": "$",
        "GBP": "£",
        "CNY": "¥"
    }
    code = (currency or "INR").upper()
    symbol = symbols.get(code, code + " ")
    try:
        v = float(val or 0.0)
    except Exception:
        v = 0.0
    sign = "-" if v < 0 else ""
    return f"{sign}{symbol}{abs(v):,.2f}"

def close_popup(win: tk.Misc) -> None:
    """Close a pop-up at once (the window behind is usable straight away)."""
    try:
        win.grab_release()
    except tk.TclError:
        pass
    try:
        win.destroy()
    except tk.TclError:
        pass


POPUP_MAX_HEIGHT = 0.75   # pop-ups are never taller than this share of the app window


def popup_limits(win: tk.Misc) -> tuple[int, int]:
    """The largest pop-up (width, height): the app window's width less a margin, and 75%
    of its height (the screen stands in before the app window is up)."""
    app = win._root()
    try:
        aw, ah = app.winfo_width(), app.winfo_height()
        if aw <= 1 or ah <= 1:
            raise tk.TclError
    except tk.TclError:
        aw, ah = win.winfo_screenwidth(), win.winfo_screenheight()
    return max(320, aw - 40), max(240, int(ah * POPUP_MAX_HEIGHT))


def place_centered(win: tk.Misc, width: int, height: int, parent: tk.Misc | None = None) -> None:
    """Give a (hidden) pop-up its size, within popup_limits, and centre it on the app
    window (every pop-up, also one opened from another pop-up). `parent` is not used."""
    max_w, max_h = popup_limits(win)
    width, height = min(int(width), max_w), min(int(height), max_h)
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    app = win._root()
    try:
        px, py = app.winfo_rootx(), app.winfo_rooty()
        pw, ph = app.winfo_width(), app.winfo_height()
        if pw <= 1 or ph <= 1:
            raise tk.TclError
    except tk.TclError:
        px, py, pw, ph = 0, 0, sw, sh
    # px, py is the app's content corner; geometry places the window's frame, title bar
    # included: take the title bar off, so frame centres on frame and content on content
    try:
        title_bar = max(0, app.winfo_rooty() - app.winfo_y())
    except tk.TclError:
        title_bar = 0
    x = min(max(0, px + (pw - width) // 2), max(0, sw - width))
    y = min(max(25, py + (ph - height) // 2 - title_bar), max(25, sh - height - 40))
    win.geometry(f"{width}x{height}+{x}+{y}")


def center_window(win: tk.Misc, *, parent: tk.Misc | None = None) -> None:
    """Center a Tk/Toplevel window cleanly, accounting for macOS native structures."""

    try:
        win.update_idletasks()
    except Exception:
        pass

    # Determine the window's target size.
    try:
        width = int(win.winfo_width())
        height = int(win.winfo_height())
        if width <= 1 or height <= 1:
            width = int(win.winfo_reqwidth())
            height = int(win.winfo_reqheight())
    except Exception:
        width, height = 800, 600

    # Determine the reference rect.
    if parent is not None:
        try:
            parent.update_idletasks()
        except Exception:
            pass
        try:
            px = int(parent.winfo_rootx())
            py = int(parent.winfo_rooty())
            pw = int(parent.winfo_width())
            ph = int(parent.winfo_height())
            if pw <= 1 or ph <= 1:
                pw = int(parent.winfo_reqwidth())
                ph = int(parent.winfo_reqheight())
            x = px + (pw // 2) - (width // 2)
            y = py + (ph // 2) - (height // 2)
        except Exception:
            parent = None

    if parent is None:
        try:
            # wm_maxsize accounts for the usable desktop bounds (ignoring Dock/Menu bar)
            max_w, max_h = win.wm_maxsize()
            
            # Use actual screen dimensions for the centering offset baseline
            sw = int(win.winfo_screenwidth())
            sh = int(win.winfo_screenheight())
            
            x = (sw // 2) - (width // 2)
            
            # Adjust vertical alignment slightly upward on macOS to feel visually balanced
            if sys.platform == "darwin":
                y = (max_h // 2) - (height // 2) + 22 # Offset for macOS menu bar thickness
            else:
                y = (sh // 2) - (height // 2)
        except Exception:
            x, y = 50, 50

    # Safe multi-monitor positioning (Removes the broken max(0, x) constraint)
    try:
        win.geometry(f"{width}x{height}+{int(x)}+{int(y)}")
    except Exception:
        pass


def add_treeview_copy_menu(tv) -> None:
    """Attach a right-click context menu to a ttk.Treeview for copying data."""
    try:
        from tkinter import Menu
        
        # We need a reference to the main app clipboard, so we can use tv's master
        app = tv.winfo_toplevel()
        
        menu = Menu(tv, tearoff=0)
        
        def _copy_row():
            try:
                selected_item = tv.selection()[0]
                values = tv.item(selected_item, "values")
                import re
                if values:
                    text = "\t".join(re.sub(r'[₹¥$£,%]', '', str(v)).strip() for v in values)
                    app.clipboard_clear()
                    app.clipboard_append(text)
            except IndexError:
                pass
                
        def _copy_all():
            try:
                import re
                cols = list(tv["columns"])
                lines = ["\t".join(cols)]
                for iid in tv.get_children():
                    vals = tv.item(iid, "values")
                    lines.append("\t".join(re.sub(r'[₹¥$£,%]', '', str(v)).strip() for v in vals))
                text = "\n".join(lines)
                app.clipboard_clear()
                app.clipboard_append(text)
            except Exception:
                pass
                
        menu.add_command(label="📋 Copy Selected Row", command=_copy_row)
        menu.add_command(label="📝 Copy All Rows", command=_copy_all)
        
        def _show_menu(event):
            # Select the row under cursor before showing menu
            iid = tv.identify_row(event.y)
            if iid:
                tv.selection_set(iid)
            from .icons import decorate_menu
            decorate_menu(menu)   # a small coloured icon on each item
            menu.tk_popup(event.x_root, event.y_root)
            
        # Bind right click (Button-2 on Mac, Button-3 on Windows)
        tv.bind("<Button-2>", _show_menu)
        tv.bind("<Button-3>", _show_menu)
    except Exception:
        pass


def format_date(value) -> str:
    """Dates in tables, one style everywhere: 02 Aug 2016 (unreadable values as they are)."""
    from datetime import date, datetime
    if isinstance(value, (date, datetime)):
        return value.strftime("%d %b %Y")
    s = str(value or "").strip()
    for text, fmt in ((s[:10], "%Y-%m-%d"), (s, "%Y-%b-%d")):
        try:
            return datetime.strptime(text, fmt).strftime("%d %b %Y")
        except ValueError:
            pass
    return s


def _sort_key(val):
    """Sort key for a table cell: dates, then numbers, then text; blanks last.

    Handles money (₹1,234 / -₹1,234 / ▼ ₹1.37L / ₹2.1Cr), percentages and
    YYYY-Mon-DD dates. Returning tuples means numbers and text never get
    compared directly, which used to raise TypeError and silently not sort.
    """
    import re
    from datetime import datetime
    s = str(val).strip()
    if not s or s in ("—", "-", "N/A", "n/a", "None"):
        return (3, 0.0, "")
    for fmt in ("%Y-%m-%d", "%Y-%b-%d", "%d-%m-%Y", "%d %b %Y"):
        try:
            return (0, datetime.strptime(s, fmt).timestamp(), "")
        except ValueError:
            pass
    # A number only when the whole cell is one (symbols, %, + and L / Cr / K aside):
    # ids such as "2eab4c68" and symbols such as "7203.T" sort as text
    core = re.sub(r"[₹¥$£€%+▲▼🔻\s]|Rs\.?", "", s.replace("−", "-").replace(",", ""))
    m = re.fullmatch(r"(-?)(\d+(?:\.\d+)?)(Cr|L|[kK])?", core)
    if not m:
        return (2, 0.0, s.lower())
    x = float(m.group(2)) * {"Cr": 1e7, "L": 1e5, "k": 1e3, "K": 1e3}.get(m.group(3) or "", 1.0)
    if m.group(1) or "▼" in s or "🔻" in s:
        x = -x
    return (1, x, "")


def show_skeleton(tv, rows: int = 12) -> None:
    """Soft grey bars in an empty table while it loads, the shape of the rows to come.
    Only an empty table gets them (a reload keeps the rows it shows); the real rows
    replace them, as the table is cleared before it is filled."""
    if tv.get_children():
        return
    from tkinter import font as tkfont, ttk
    from .ui_theme import ModernStyle
    spec = ttk.Style(tv).lookup(str(tv.cget("style") or "Treeview"), "font") or ModernStyle.FONT_TABLE
    try:
        bar_w = max(4, tkfont.Font(font=spec).measure("━"))
    except tk.TclError:
        bar_w = 10
    tv.tag_configure("skeleton", foreground=ModernStyle.INPUT_BORDER)
    cols = list(tv["columns"])
    for i in range(rows):
        values = []
        for j, c in enumerate(cols):
            share = (0.35, 0.7, 0.5, 0.85, 0.6)[(i + 2 * j) % 5]   # varied lengths, like real text
            values.append("━" * max(2, int(int(tv.column(c, "width")) * share / bar_w)))
        tv.insert("", "end", values=values, tags=("skeleton",))


def clear_skeleton(tv) -> None:
    """Remove the loading bars (e.g. when the load failed)."""
    rows = [i for i in tv.get_children() if "skeleton" in tv.item(i, "tags")]
    if rows:
        tv.delete(*rows)


def enhance_table(tv, stripes: tuple | None = ("even", "odd")) -> None:
    """Pop-up tables: a soft highlight under the mouse, and a click on a heading sorts by
    that column (again to reverse; ▲ / ▼ shows which). `stripes` = the row tags of the
    first and second rows, put back in order after a sort; None keeps the rows' colours.
    Call it after the table's own tags are configured (the highlight must come last)."""
    from .ui_theme import ModernStyle
    tv.tag_configure("hover", background=ModernStyle.BG_HOVER)
    state = {"hover": "", "col": None, "reverse": False}
    titles = {c: tv.heading(c, "text") for c in tv["columns"]}

    def _hover(event) -> None:
        iid = tv.identify_row(event.y) if event is not None else ""
        prev = state["hover"]
        if iid == prev:
            return
        if prev and tv.exists(prev):
            tv.item(prev, tags=tuple(t for t in tv.item(prev, "tags") if t != "hover"))
        if iid:
            tv.item(iid, tags=tuple(tv.item(iid, "tags")) + ("hover",))
        state["hover"] = iid
    tv.bind("<Motion>", _hover, add="+")
    tv.bind("<Leave>", lambda _e: _hover(None), add="+")

    def _sort(col) -> None:
        reverse = state["col"] == col and not state["reverse"]
        rows = sorted(((_sort_key(tv.set(k, col)), k) for k in tv.get_children("")),
                      key=lambda r: r[0], reverse=reverse)
        for i, (_key, k) in enumerate(rows):
            tv.move(k, "", i)
            if stripes:
                tags = [t for t in tv.item(k, "tags") if t not in stripes]
                tv.item(k, tags=tuple(tags) + (stripes[i % 2],))
        state["col"], state["reverse"] = col, reverse
        for c, text in titles.items():
            tv.heading(c, text=f"{text} {'▼' if reverse else '▲'}" if c == col else text)
    for c in titles:
        tv.heading(c, command=lambda c=c: _sort(c))

    # When the rows are reloaded they come in their own order: drop the ▲ / ▼
    plain_delete = tv.delete

    def _delete(*items):
        plain_delete(*items)
        if state["col"] is not None and not tv.get_children(""):
            state["col"] = None
            for c, text in titles.items():
                tv.heading(c, text=text)
    tv.delete = _delete


def _gain_sign(text) -> int:
    """+1 for a gain ("▲ ₹1,234", "+2.5%", "₹80"), -1 for a loss ("▼ 3.1%", "-₹5"), 0 otherwise."""
    t = str(text).strip()
    if t[:1] in ("▲", "▼"):   # the usual case
        return 1 if t[0] == "▲" else -1
    start = next((i for i, ch in enumerate(t) if ch.isdigit()), None)
    if start is None:
        return 0
    head = t[:start]
    if "▼" in head or "-" in head or "−" in head or "(" in head:
        return -1
    if "▲" in head or "+" in head:
        return 1
    digits = "".join(ch for ch in t[start:] if ch.isdigit() or ch == ".")
    try:
        return 1 if float(digits or 0) > 0 else 0
    except ValueError:
        return 0


def color_gain_loss(tv, cols, items=None, *, rows=None) -> None:
    """Green text for gains and red for losses in the given columns, cell by cell (the rest
    of each row keeps its colours). Call after filling the table; Tk without cell tags: no colours.
    rows: the just-inserted rows as (iid, values), which saves reading every cell back."""
    from .ui_theme import ModernStyle
    tv.tag_configure("gain_cell", foreground=ModernStyle.SUCCESS)
    tv.tag_configure("loss_cell", foreground=ModernStyle.ERROR)
    columns = list(tv["columns"])
    cols = [(c, columns.index(c)) for c in cols if c in columns]
    if rows is None:
        rows = [(iid, tv.item(iid, "values")) for iid in (tv.get_children("") if items is None else items)]
        clear = [(iid, c) for iid, _v in rows for c, _i in cols]   # rows shown before may carry old colours
    else:
        clear = []
    gains, losses = [], []
    for iid, values in rows:
        for col, i in cols:
            sign = _gain_sign(values[i]) if i < len(values) else 0
            if sign > 0:
                gains.append((iid, col))
            elif sign < 0:
                losses.append((iid, col))
    try:
        for tag, tagged in (("gain_cell", gains), ("loss_cell", losses)):
            if clear:
                tv.tk.call(tv._w, "tag", "cell", "remove", tag, clear)
            if tagged:   # one Tcl list in a single string: much faster than a Python list of pairs
                tv.tk.call(tv._w, "tag", "cell", "add", tag, " ".join(f"{{{i} {{{c}}}}}" for i, c in tagged))
    except tk.TclError:
        pass


def color_buy_sell(tv, sides, cols=("Type", "Qty", "Price")) -> None:
    """Green for buys and red for sells, in the given columns only (the rest of each row stays
    plain). sides: (iid, is_buy) pairs for just-inserted rows; is_buy None = neither."""
    from .ui_theme import ModernStyle
    tv.tag_configure("gain_cell", foreground=ModernStyle.SUCCESS)   # the same tags as gains / losses
    tv.tag_configure("loss_cell", foreground=ModernStyle.ERROR)
    present = set(tv["columns"])
    cols = [c for c in cols if c in present]
    buys, sells = [], []
    for iid, is_buy in sides:
        if is_buy is not None:
            (buys if is_buy else sells).extend(f"{{{iid} {{{c}}}}}" for c in cols)
    try:
        for tag, cells in (("gain_cell", buys), ("loss_cell", sells)):
            if cells:
                tv.tk.call(tv._w, "tag", "cell", "add", tag, " ".join(cells))
    except tk.TclError:
        pass


_SIGNAL_WORDS = (("strong buy", "gain_cell"), ("accumulate", "gain_cell"), ("reduce", "loss_cell"),
                 ("avoid", "loss_cell"), ("sell", "loss_cell"), ("hold", "hold_cell"), ("wait", "hold_cell"))


def color_signals(tv, col: str = "Signal", items=None) -> None:
    """Signals in traffic-light colours, in that column only: Accumulate / Strong Buy green,
    Hold / Wait amber, Reduce / Avoid red. Call after filling the table."""
    from .ui_theme import ModernStyle
    tv.tag_configure("gain_cell", foreground=ModernStyle.SUCCESS)
    tv.tag_configure("loss_cell", foreground=ModernStyle.ERROR)
    tv.tag_configure("hold_cell", foreground=ModernStyle.WARNING)
    if col not in tv["columns"]:
        return
    iids = list(tv.get_children("") if items is None else items)
    cells = {"gain_cell": [], "loss_cell": [], "hold_cell": []}
    for iid in iids:
        text = str(tv.set(iid, col)).lower()
        tag = next((t for word, t in _SIGNAL_WORDS if word in text), None)
        if tag:
            cells[tag].append(f"{{{iid} {{{col}}}}}")
    clear = " ".join(f"{{{iid} {{{col}}}}}" for iid in iids)   # rows shown before may carry old colours
    try:
        for tag, tagged in cells.items():
            if clear:
                tv.tk.call(tv._w, "tag", "cell", "remove", tag, clear)
            if tagged:
                tv.tk.call(tv._w, "tag", "cell", "add", tag, " ".join(tagged))
    except tk.TclError:
        pass


def color_book_cells(tv, col: str) -> None:
    """Red text for a book value shown in place of a fair value ("₹832.40 (B)"): a
    loss-making company's net assets a share, not a fair price. Call after filling the table."""
    from .ui_theme import ModernStyle
    tv.tag_configure("book_cell", foreground=ModernStyle.ERROR)
    if col not in tv["columns"]:
        return
    iids = list(tv.get_children(""))
    book = [f"{{{iid} {{{col}}}}}" for iid in iids if str(tv.set(iid, col)).endswith("(B)")]
    clear = " ".join(f"{{{iid} {{{col}}}}}" for iid in iids)   # rows shown before may carry old colours
    try:
        if clear:
            tv.tk.call(tv._w, "tag", "cell", "remove", "book_cell", clear)
        if book:
            tv.tk.call(tv._w, "tag", "cell", "add", "book_cell", " ".join(book))
    except tk.TclError:
        pass


def treeview_sort_column(tv, col: str, reverse: bool) -> None:
    """Sort a ttk.Treeview clicking on its header, dealing with numeric and text values."""

    try:
        l = [(tv.set(k, col), k) for k in tv.get_children('')]
        l.sort(key=lambda t: _sort_key(t[0]), reverse=reverse)

        # Rearrange items in sorted positions
        for index, (val, k) in enumerate(l):
            tv.move(k, '', index)

        # Reverse sort direction for next click
        tv.heading(col, command=lambda: treeview_sort_column(tv, col, not reverse))

        # Optionally apply group-based zebra striping
        try:
            current_group_val = None
            current_stripe = "odd" # Start with white
            
            for item in tv.get_children(''):
                val_str = str(tv.set(item, col))
                if val_str != current_group_val:
                    current_group_val = val_str
                    current_stripe = "even" if current_stripe == "odd" else "odd"
                
                tags = tv.item(item, 'tags')
                # Filter out old odd/even tags
                tags = [t for t in tags if t not in ('odd', 'even')]
                # Re-apply
                tags.append(current_stripe)
                tv.item(item, tags=tags)
        except Exception:
            pass

    except Exception:
        log.exception("Sorting column %s failed", col)

def show_toast(parent: tk.Misc, message: str, type: str = "success") -> None:
    """Show a non-blocking toast notification that fades out."""
    try:
        from .ui_theme import ModernStyle
        
        toast = tk.Toplevel(parent)
        toast.overrideredirect(True)
        # Keep on top
        try:
            toast.attributes('-topmost', True)
        except Exception:
            pass
            
        from . import icons
        accent, fill, icon_name, emoji = {
            "success": (ModernStyle.SUCCESS, ModernStyle.SUCCESS_FILL, "circle-check", "✅"),
            "warning": (ModernStyle.WARNING, ModernStyle.WARNING_FILL, "triangle-alert", "⚠"),
            "info": (ModernStyle.TEXT_ACCENT, ModernStyle.ACCENT_PRIMARY, "info", "ℹ️"),
        }.get(type, (ModernStyle.ERROR, ModernStyle.ERROR_FILL, "circle-x", "⚠"))
        card_bg = ModernStyle.BG_SECONDARY

        # A white card with rounded corners (the Mac lets the window around it be see-through),
        # a coloured bar and icon on the left, and the message in the normal text colour
        rounded = sys.platform == "darwin"
        if rounded:
            try:
                toast.wm_attributes("-transparent", True)
                toast.configure(bg="systemTransparent")
            except tk.TclError:
                rounded = False
        canvas = tk.Canvas(toast, bg="systemTransparent" if rounded else card_bg, highlightthickness=0, bd=0)
        canvas.pack()
        glyph = icons.glyph(icon_name)
        left = 28
        gid = canvas.create_text(left, 0, text=glyph or emoji, fill=accent, anchor="w",
                                 font=icons.font(20) if glyph else ModernStyle.FONT_BODY)
        gw = (canvas.bbox(gid) or (0, 0, 20, 0))[2] - left
        tid = canvas.create_text(left + gw + 10, 0, text=message, fill=ModernStyle.TEXT_PRIMARY, anchor="w",
                                 font=ModernStyle.FONT_BODY_BOLD, width=420, justify="left")
        tb = canvas.bbox(tid) or (0, 0, 200, 20)
        th = max(tb[3] - tb[1], 24) + 2 * 14
        tw = tb[2] + 20
        canvas.coords(gid, left, th // 2)
        canvas.coords(tid, left + gw + 10, th // 2)
        r, e, b = (ModernStyle.RADIUS_CARD if rounded else 0), tw - 1, th - 1
        if r:
            card = canvas.create_polygon(r, 0, r, 0, e - r, 0, e - r, 0, e, 0, e, r, e, r, e, b - r, e, b - r, e, b,
                                         e - r, b, e - r, b, r, b, r, b, 0, b, 0, b - r, 0, b - r, 0, r, 0, r, 0, 0,
                                         smooth=True, fill=card_bg, outline=ModernStyle.BORDER_COLOR)
        else:
            card = canvas.create_rectangle(0, 0, e, b, fill=card_bg, outline=ModernStyle.BORDER_COLOR)
        canvas.tag_lower(card)
        canvas.create_line(14, 12, 14, th - 12, fill=fill, width=ModernStyle.ACCENT_BAR, capstyle="round")
        canvas.configure(width=tw, height=th)

        # Position bottom right of parent
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            x = px + pw - tw - 30
            y = py + ph - th - 30
            toast.geometry(f"+{x}+{y}")
        except Exception:
            pass
            
        # Optional fade out for macOS/Windows
        def fade():
            try:
                alpha = toast.attributes("-alpha")
                if alpha > 0.1:
                    toast.attributes("-alpha", alpha - 0.1)
                    toast.after(50, fade)
                else:
                    toast.destroy()
            except Exception:
                toast.destroy()
                
        # Start fade after 2.5 seconds
        toast.after(2500, fade)
        
    except Exception:
        log.exception("Toast failed")

def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    try:
        h = hex_str.lstrip('#')
        if len(h) == 3:
            h = ''.join(c + c for c in h)
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4)) # type: ignore
    except Exception:
        return (0, 0, 0)

def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return '#{:02x}{:02x}{:02x}'.format(*rgb)

class ToolTip:
    """Lightweight, modern hover tooltip for any Tkinter widget."""

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 400):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.tip_window = None
        self.after_id = None
        self.widget.bind("<Enter>", self.schedule, add="+")
        self.widget.bind("<Leave>", self.hide, add="+")
        self.widget.bind("<ButtonPress>", self.hide, add="+")

    def schedule(self, event=None):
        self.cancel()
        self.after_id = self.widget.after(self.delay_ms, self.show)

    def cancel(self):
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def _anchor(self) -> tuple[int, int]:
        """Screen point the tip hangs from: centred beneath the widget."""
        return (self.widget.winfo_rootx() + self.widget.winfo_width() // 2,
                self.widget.winfo_rooty() + self.widget.winfo_height() + 4)

    def show(self):
        self.hide()
        try:
            from .ui_theme import ModernStyle
            x, y = self._anchor()
            
            self.tip_window = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.attributes("-topmost", True)
            
            # Use same font size, clean padding, and dark slate colors matching design system
            lbl = tk.Label(
                tw, text=self.text,
                bg=ModernStyle.SIDEBAR_BG, fg=ModernStyle.SIDEBAR_FG,
                font=ModernStyle.FONT_SMALL,
                padx=8, pady=4,
                relief="flat",
                highlightbackground=ModernStyle.BORDER_COLOR,
                highlightthickness=1,
                justify="left",
                wraplength=220
            )
            lbl.pack()
            
            # A label knows its requested size straight away; no need to force a
            # redraw of the whole app with update_idletasks()
            w = lbl.winfo_reqwidth()
            h = lbl.winfo_reqheight()
            
            # Center horizontally
            x = x - (w // 2)
            
            tw.wm_geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            self.tip_window = None

    def hide(self, event=None):
        self.cancel()
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None


def install_row_hover(root: tk.Misc) -> None:
    """Highlight the row under the pointer in every table (the Dashboard does its own)."""
    from .ui_theme import ModernStyle

    def _set(tv, row):
        old = getattr(tv, "_hover_row", "")
        if row == old:
            return
        if row and "_sel" in tv.item(row, "tags"):
            row = ""      # a selected row keeps its selection colour
        try:
            if not getattr(tv, "_hover_ready", False):
                tv.tag_configure("hover", background=ModernStyle.BG_HOVER)
                tv._hover_ready = True
            if old and tv.exists(old):
                tv.item(old, tags=[t for t in tv.item(old, "tags") if t != "hover"])
            if row:
                tv.item(row, tags=[*tv.item(row, "tags"), "hover"])
        except tk.TclError:
            row = ""
        tv._hover_row = row

    def _move(e):
        tv = e.widget
        if isinstance(tv, tk.Misc) and not str(tv.cget("style")).startswith("Dashboard"):
            _set(tv, tv.identify_row(e.y) if tv.identify_region(e.x, e.y) in ("cell", "tree") else "")

    def _leave(e):
        if isinstance(e.widget, tk.Misc):
            _set(e.widget, "")

    root.bind_class("Treeview", "<Motion>", _move, add="+")
    root.bind_class("Treeview", "<Leave>", _leave, add="+")

    # Selected rows: white text on the selection blue, whatever colour the row's
    # text normally has (amber, green, red rows were hard to read when selected)
    def _select(e):
        tv = e.widget
        if not isinstance(tv, tk.Misc):
            return
        try:
            if not getattr(tv, "_sel_ready", False):
                tv.tag_configure("_sel", background=ModernStyle.TABLE_SELECTED_BG,
                                 foreground=ModernStyle.TABLE_SELECTED_FG)
                tv._sel_ready = True
            now = set(tv.selection())
            for iid in getattr(tv, "_sel_items", set()) - now:
                if tv.exists(iid):
                    tv.item(iid, tags=[t for t in tv.item(iid, "tags") if t != "_sel"])
            for iid in now:
                tags = [t for t in tv.item(iid, "tags") if t != "hover"]
                if "_sel" not in tags:
                    tv.item(iid, tags=[*tags, "_sel"])
            tv._sel_items = now
        except tk.TclError:
            pass

    root.bind_class("Treeview", "<<TreeviewSelect>>", _select, add="+")

    # Tk gives the tags created first the highest priority, so create "_sel" and
    # "hover" as each table is made: they then win over the row colours (amber,
    # green, stripes) that a page adds afterwards.
    from tkinter import ttk
    if getattr(ttk.Treeview, "_row_tags_first", False):
        return
    _init = ttk.Treeview.__init__

    def _init_with_row_tags(self, *args, **kwargs):
        _init(self, *args, **kwargs)
        try:
            self.tag_configure("_sel", background=ModernStyle.TABLE_SELECTED_BG,
                               foreground=ModernStyle.TABLE_SELECTED_FG)
            self.tag_configure("hover", background=ModernStyle.BG_HOVER)
            self._sel_ready = self._hover_ready = True
        except tk.TclError:
            pass

    ttk.Treeview.__init__ = _init_with_row_tags
    ttk.Treeview._row_tags_first = True


class HeadingTips(ToolTip):
    """Explain a table's columns: hovering a column heading shows what it means.
    `tips` maps column ids to text; columns without an entry show nothing."""

    def __init__(self, tree: tk.Widget, tips: dict, delay_ms: int = 400):
        self.tips = dict(tips)
        self._col = None
        super().__init__(tree, "", delay_ms)
        tree.bind("<Motion>", self._on_motion, add="+")

    def schedule(self, event=None):
        pass  # only headings show a tip; see _on_motion

    def hide(self, event=None):
        if event is not None:
            self._col = None
        super().hide(event)

    def _on_motion(self, event):
        tree = self.widget
        col = None
        try:
            if tree.identify_region(event.x, event.y) == "heading":
                col = tree.column(tree.identify_column(event.x), "id")
        except tk.TclError:
            col = None
        if col == self._col:
            return
        self._col = col
        super().hide()
        if col and self.tips.get(col):
            self.text = self.tips[col]
            self._x = event.x_root
            self.after_id = tree.after(self.delay_ms, self.show)

    def _anchor(self) -> tuple[int, int]:
        return self._x, self.widget.winfo_rooty() + 30

