"""Lucide line icons (ISC licence, assets/fonts) drawn with the bundled icon font.

The font is registered for this process only, so Tk draws the icons as text:
crisp on Retina screens and coloured like any label.
"""
import ctypes
import ctypes.util
import json
import logging
import re
import sys
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

FAMILY = "lucide"


def _fonts_dir() -> Path:
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "assets" / "fonts"


@lru_cache(maxsize=1)
def available() -> bool:
    """Register the icon font once; False where that is not possible (then callers use emoji)."""
    path = _fonts_dir() / "lucide.ttf"
    try:
        if not path.exists():
            return False
        if sys.platform == "darwin":
            cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
            ct = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreText"))
            cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
            cf.CFURLCreateFromFileSystemRepresentation.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
            ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
            raw = str(path).encode()
            url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
            if not url:
                return False
            try:
                return bool(ct.CTFontManagerRegisterFontsForURL(url, 1, None))   # 1 = this process only
            finally:
                cf.CFRelease(url)
        if sys.platform == "win32":
            return ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0) > 0   # 0x10 = private
    except Exception:
        log.warning("Could not load the icon font %s", path, exc_info=True)
    return False


@lru_cache(maxsize=1)
def _codepoints() -> dict:
    with open(_fonts_dir() / "lucide-codepoints.json", encoding="utf-8") as fh:
        return json.load(fh)


def glyph(name: str) -> str:
    """The character for a Lucide icon name, or "" when the icon font is unavailable."""
    if not available():
        return ""
    try:
        return chr(_codepoints()[name])
    except (OSError, ValueError, KeyError):
        log.warning("Unknown Lucide icon %r", name, exc_info=True)
        return ""


def font(px: int) -> tuple:
    """A Tk font that draws icons px pixels wide (a negative size means pixels)."""
    return (FAMILY, -max(1, int(px)))


# ── Pictures (menus show images, not fonts) ──────────────────────────────────
_EMOJI = re.compile(r"[☀-➿\U0001F300-\U0001FAFF️]+\s*")
_IMAGES: dict = {}


def image(name: str, color: str, size: int = 16):
    """A Lucide icon as a small colour picture (drawn 4x larger and scaled down, so it is
    smooth); None when the icon font or Pillow is unavailable."""
    import tkinter as tk
    key = (name, color, size, id(tk._default_root))
    if key not in _IMAGES:
        photo = None
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageTk
            code = _codepoints().get(name)
            if code is not None:
                big = size * 4
                font = ImageFont.truetype(str(_fonts_dir() / "lucide.ttf"), big)
                img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
                ImageDraw.Draw(img).text((big // 2, big // 2), chr(code), font=font, fill=color, anchor="mm")
                photo = ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))
        except Exception:
            log.warning("Could not draw the icon %r", name, exc_info=True)
        _IMAGES[key] = photo
    return _IMAGES[key]


# Words in a menu item → (Lucide icon, colour); the first match wins
_MENU_ICONS = (
    ("delete", "trash-2", "#DC2626"), ("remove", "trash-2", "#DC2626"),
    ("copy all", "clipboard-list", "#4F46E5"), ("copy", "copy", "#2563EB"),
    ("view trades", "history", "#0D9488"), ("add", "circle-plus", "#16A34A"),
    ("edit", "pencil", "#D97706"), ("choose columns", "columns-3", "#7C3AED"),
    ("show all", "eye", "#0284C7"), ("back to", "rotate-ccw", "#64748B"),
)


def decorate_menu(menu) -> None:
    """Give each command in a right-click menu a small coloured Lucide icon, chosen by its
    words, in place of the emoji its label had."""
    end = menu.index("end")
    if end is None:
        return
    for i in range(end + 1):
        if menu.type(i) != "command":
            continue
        label = _EMOJI.sub("", menu.entrycget(i, "label")).strip()
        low = label.lower()
        match = next(((name, color) for words, name, color in _MENU_ICONS if words in low), None)
        picture = image(*match) if match else None
        if picture is not None:
            menu.entryconfigure(i, label=label, image=picture, compound="left")
        else:
            menu.entryconfigure(i, label=label)
