"""Broker logos (assets/images/brokers) and the order brokers are listed in.

A logo file is the broker's name in lower case: "Bahee-Kite" → bahee-kite.png.
Brokers without a logo get a coloured circle with their first letter.
"""
import sys
import tkinter as tk
from pathlib import Path

# The order brokers are shown in everywhere (lists, drop-downs); others follow A–Z
BROKER_ORDER = ("bahee-kite", "icici", "upstox", "tanaka", "nomura", "selva-kite", "mithun-kite")

_IMAGES: dict = {}


def _dir() -> Path:
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "assets" / "images" / "brokers"


def key(broker) -> str:
    return str(broker or "").strip().lower()


def sort_key(broker) -> tuple:
    k = key(broker)
    return (BROKER_ORDER.index(k), "") if k in BROKER_ORDER else (len(BROKER_ORDER), k)


def ordered(brokers) -> list:
    """The brokers in the preferred order ("All" stays first)."""
    brokers = list(brokers or [])
    head = [b for b in brokers if str(b) == "All"]
    return head + sorted((b for b in brokers if str(b) != "All"), key=sort_key)


def logo(broker, size: int = 20):
    """The broker's logo as a Tk image of size × size pixels (cached), or None for "All"."""
    k = key(broker)
    if not k or k == "all":
        return None
    root = tk._default_root
    cache_key = (k, size, id(root))
    if cache_key in _IMAGES:
        return _IMAGES[cache_key]
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageTk
        path = _dir() / f"{k}.png"
        if path.exists():
            im = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
        else:   # no logo yet: a soft circle with the first letter
            big = size * 4
            im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.ellipse((0, 0, big - 1, big - 1), fill=(99, 102, 241, 255))
            try:
                f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", int(big * 0.55))
            except OSError:
                f = ImageFont.load_default()
            d.text((big / 2, big / 2), k[:1].upper(), font=f, fill=(255, 255, 255, 255), anchor="mm")
            im = im.resize((size, size), Image.LANCZOS)
        img = ImageTk.PhotoImage(im, master=root)
    except Exception:
        img = None
    _IMAGES[cache_key] = img
    return img


# ── Tables ────────────────────────────────────────────────────────────────────
# A Tk table (ttk.Treeview) can show pictures only in its first, "tree" column. So that
# column becomes a narrow "Src" column with each row's broker logo; the "#" and Broker
# columns stay as they are. The pictures are shared, so it costs nothing.

def logo_column(tv, num_col: str, broker_col: str) -> None:
    """Add the "Src" column of broker logos in front (call show_logos after filling).
    num_col: rows without a number there (group titles, totals) get no logo."""
    from tkinter import ttk
    style = str(tv.cget("style") or "Treeview")
    if style == "Treeview":   # its own style, so only this table changes
        style = "Logo.Treeview"
        tv.configure(style=style)
    # Just the logo, centred (no expand arrow, no text)
    ttk.Style(tv).layout(f"{style}.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
        ("Treeitem.image", {"sticky": ""})]})])
    tv.configure(show=("tree", "headings"))
    tv.heading("#0", text="Src", anchor="center")
    tv.column("#0", width=36, minwidth=36, stretch=False, anchor="center")
    tv._logo_cols = (num_col, broker_col)


def show_logos(tv, items=None) -> None:
    """Put each row's broker logo in the "Src" column (all top-level rows by default).
    Rows without a number (group titles, totals) get none."""
    cols = getattr(tv, "_logo_cols", None)
    if not cols:
        return
    num_col, broker_col = cols
    for iid in (tv.get_children("") if items is None else items):
        num = str(tv.set(iid, num_col)).strip()
        name = str(tv.set(iid, broker_col)).split(",")[0].split(" +")[0].strip()
        img = logo(name, 18) if num and num != "-" else None
        tv.item(iid, text="", image=img or "")
