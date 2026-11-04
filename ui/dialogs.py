"""Themed alert and question boxes, used instead of the standard Mac ones (which ignore
the app's colours, fonts and dark mode).

Same names and arguments as tkinter.messagebox / simpledialog.askstring, so a call
only changes its prefix: dialogs.askyesno(title, message, parent=...).
"""
import re
import tkinter as tk

from ui.ui_theme import ModernStyle as S
from ui.ui_utils import place_centered
from ui.ui_widgets import RoundedBox, action_button, icon_tile, secondary_button

# A question about deleting or wiping something gets a red icon and a red Yes button
_DANGER = re.compile(r"\b(delete|remove|wipe|erase|discard)\b", re.I)

# kind → (Lucide icon, emoji if the icon font is missing, icon colour, tile colour)
_KINDS = {
    "error": ("circle-x", "❌", lambda: S.ERROR, lambda: S.ERROR_PALE),
    "warning": ("triangle-alert", "⚠️", lambda: S.WARNING, lambda: S.WARNING_PALE),
    "info": ("info", "ℹ️", lambda: S.TEXT_ACCENT, lambda: S.ACCENT_PRIMARY_PALE),
    "question": ("circle-help", "❓", lambda: S.TEXT_ACCENT, lambda: S.ACCENT_PRIMARY_PALE),
    "danger": ("trash-2", "🗑️", lambda: S.ERROR, lambda: S.ERROR_PALE),
}


def _owner(parent):
    if parent is not None:
        try:
            return parent.winfo_toplevel()
        except tk.TclError:
            pass
    return tk._default_root


def _show(kind: str, title: str, message: str, parent=None, buttons=(("OK", "ok", "primary"),),
          entry_value: str | None = None):
    """Show the box and wait. buttons = (label, value, style) from left to right; style is
    "soft", "primary" or "danger". Enter presses the last button; Esc or closing the
    window gives the first button's value (with an entry, OK gives the typed text)."""
    owner = _owner(parent)
    bg = S.BG_SECONDARY
    win = tk.Toplevel(owner)
    win.withdraw()
    win.title(title or "")
    S.style_modal(win)
    win.configure(bg=bg)
    win.resizable(False, False)

    body = tk.Frame(win, bg=bg)
    body.pack(fill="both", expand=True, padx=24, pady=(22, 18))
    top = tk.Frame(body, bg=bg)
    top.pack(fill="x")
    name, emoji, color, pale = _KINDS.get(kind, _KINDS["info"])
    icon_tile(top, name, emoji, color(), pale(), size=44).pack(side="left", anchor="n")
    words = tk.Frame(top, bg=bg)
    words.pack(side="left", fill="x", expand=True, padx=(14, 0))
    tk.Label(words, text=title or "", fg=S.TEXT_PRIMARY, bg=bg, font=S.FONT_TITLE, anchor="w",
             justify="left", wraplength=380).pack(fill="x")
    if message:
        tk.Label(words, text=message, fg=S.TEXT_SECONDARY, bg=bg, font=S.FONT_BODY, anchor="w",
                 justify="left", wraplength=380).pack(fill="x", pady=(4, 0))

    entry = None
    if entry_value is not None:
        box = RoundedBox(words)
        box.pack(fill="x", pady=(12, 0))
        entry = tk.Entry(box, bg=S.ENTRY_BG, fg=S.TEXT_PRIMARY, font=S.FONT_INPUT, relief=tk.FLAT, bd=0,
                         highlightthickness=0, insertbackground=S.ACCENT_PRIMARY)
        entry.insert(0, entry_value)
        entry.pack(fill="x", ipady=8, padx=10)
        box.watch(entry)

    result = {"value": buttons[0][1]}

    def _close(value):
        if entry is not None and value is not None:
            value = entry.get()
        result["value"] = value
        try:
            win.grab_release()
        except tk.TclError:
            pass
        win.destroy()

    row = tk.Frame(body, bg=bg)
    row.pack(fill="x", pady=(20, 0))
    for label, value, style in reversed(buttons):
        if style == "soft":   # No / Cancel: the soft grey every Cancel / Close shares
            btn = secondary_button(row, label, lambda v=value: _close(v), width=96, canvas_bg=bg)
        else:
            btn = action_button(row, label, lambda v=value: _close(v), width=96, canvas_bg=bg,
                                kind="danger" if style == "danger" else "primary")
        btn.pack(side="right", padx=(10, 0))

    win.protocol("WM_DELETE_WINDOW", lambda: _close(buttons[0][1]))
    win.bind("<Escape>", lambda _e: _close(buttons[0][1]))
    win.bind("<Return>", lambda _e: _close(buttons[-1][1]))
    win.bind("<KP_Enter>", lambda _e: _close(buttons[-1][1]))

    win.update_idletasks()
    place_centered(win, max(440, win.winfo_reqwidth()), win.winfo_reqheight())   # a steady width; on the app
    win.deiconify()
    try:
        win.transient(owner)
        win.grab_set()
    except tk.TclError:
        pass
    win.lift()
    (entry or win).focus_force()
    win.wait_window()
    return result["value"]


def askyesno(title, message, parent=None, **_kw) -> bool:
    kind = "danger" if _DANGER.search(f"{title} {message}") else "question"
    return bool(_show(kind, title, message, parent,
                      buttons=(("No", False, "soft"), ("Yes", True, "danger" if kind == "danger" else "primary"))))


def showerror(title, message, parent=None, **_kw) -> str:
    return _show("error", title, message, parent)


def showwarning(title, message, parent=None, **_kw) -> str:
    return _show("warning", title, message, parent)


def showinfo(title, message, parent=None, **_kw) -> str:
    return _show("info", title, message, parent)


def askstring(title, prompt, parent=None, initialvalue: str | None = None, **_kw) -> str | None:
    """The typed text, or None when cancelled."""
    return _show("question", title, prompt, parent, entry_value=initialvalue or "",
                 buttons=(("Cancel", None, "soft"), ("OK", "", "primary")))
