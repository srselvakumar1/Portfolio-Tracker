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
            menu.tk_popup(event.x_root, event.y_root)
            
        # Bind right click (Button-2 on Mac, Button-3 on Windows)
        tv.bind("<Button-2>", _show_menu)
        tv.bind("<Button-3>", _show_menu)
    except Exception:
        pass


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
    t = s.replace("−", "-").replace(",", "")
    num = re.sub(r"[^\d.\-]", "", t)
    try:
        x = float(num)
    except ValueError:
        return (2, 0.0, s.lower())
    if re.search(r"\dCr\b", t.replace(" ", "")):
        x *= 1e7
    elif re.search(r"\dL\b", t.replace(" ", "")):
        x *= 1e5
    elif re.search(r"\d[kK]\b", t.replace(" ", "")):
        x *= 1e3
    if x > 0 and ("▼" in s or "🔻" in s):
        x = -x
    return (1, x, "")


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
            
        bg_color = {
            "success": ModernStyle.SUCCESS_FILL,
            "warning": ModernStyle.WARNING_FILL,
            "info": ModernStyle.ACCENT_PRIMARY,
        }.get(type, ModernStyle.ERROR_FILL)
        fg_color = ModernStyle.TEXT_ON_ACCENT
        
        frame = tk.Frame(toast, bg=bg_color, highlightbackground=ModernStyle.BORDER_COLOR, highlightthickness=1)
        frame.pack(fill="both", expand=True)
        
        inner = tk.Frame(frame, bg=bg_color, padx=16, pady=10)
        inner.pack(fill="both", expand=True)
        
        icon = {"success": "✅", "info": "ℹ️"}.get(type, "⚠")
        
        msg_lbl = tk.Label(
            inner, 
            text=f"{icon}  {message}", 
            bg=bg_color, 
            fg=fg_color, 
            font=ModernStyle.FONT_BODY_BOLD,
            wraplength=420,
            justify="left",
        )
        msg_lbl.pack()
        
        # Position bottom right of parent
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            
            # Size from the label (inner padding 16x10, 1 px border): no forced redraw
            tw = msg_lbl.winfo_reqwidth() + 2 * 16 + 2
            th = msg_lbl.winfo_reqheight() + 2 * 10 + 2
            
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

def fade_color_transition(widget: tk.Widget, current_color: str, target_color: str, attr: str = "bg", duration_ms: int = 150, steps: int = 10) -> None:
    """Smoothly transition a color attribute of a Tkinter widget."""
    try:
        if not widget.winfo_exists():
            return
            
        start_rgb = _hex_to_rgb(current_color)
        end_rgb = _hex_to_rgb(target_color)
        
        delay = duration_ms // steps
        
        def step_fade(step: int):
            if not widget.winfo_exists():
                return
            if step > steps:
                try:
                    widget.configure(**{attr: target_color})
                except Exception:
                    pass
                return
                
            r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * (step / steps))
            g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * (step / steps))
            b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * (step / steps))
            
            curr_hex = _rgb_to_hex((r, g, b))
            try:
                widget.configure(**{attr: curr_hex})
            except Exception:
                pass
            
            widget.after(delay, step_fade, step + 1)
            
        step_fade(0)
    except Exception:
        pass


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

