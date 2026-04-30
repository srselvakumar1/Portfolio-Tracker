#!/usr/bin/env python3
"""Small UI utilities shared across views.

Kept separate to avoid circular imports.
"""

from __future__ import annotations

import tkinter as tk


def center_window(win: tk.Misc, *, parent: tk.Misc | None = None) -> None:
    """Center a Tk/Toplevel window.

    If parent is provided, centers relative to the parent window.
    Otherwise centers on screen.
    """

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
            sw = int(win.winfo_screenwidth())
            sh = int(win.winfo_screenheight())
            x = (sw // 2) - (width // 2)
            y = (sh // 2) - (height // 2)
        except Exception:
            x, y = 50, 50

    # Clamp to visible screen area (basic safety).
    try:
        x = max(0, int(x))
        y = max(0, int(y))
    except Exception:
        x, y = 0, 0

    try:
        win.geometry(f"{width}x{height}+{x}+{y}")
    except Exception:
        pass


def add_treeview_copy_menu(tv) -> None:
    """Attach a right-click context menu to a ttk.Treeview for copying data."""
    try:
        from tkinter import Menu
        from tkinter import ttk
        
        # We need a reference to the main app clipboard, so we can use tv's master
        app = tv.winfo_toplevel()
        
        menu = Menu(tv, tearoff=0)
        
        def _copy_row():
            try:
                selected_item = tv.selection()[0]
                values = tv.item(selected_item, "values")
                if values:
                    text = "\t".join(str(v).replace("₹", "").replace(",", "").replace("%", "").strip() for v in values)
                    app.clipboard_clear()
                    app.clipboard_append(text)
            except IndexError:
                pass
                
        def _copy_all():
            try:
                cols = list(tv["columns"])
                lines = ["\t".join(cols)]
                for iid in tv.get_children():
                    vals = tv.item(iid, "values")
                    lines.append("\t".join(str(v).replace("₹", "").replace(",", "").replace("%", "").strip() for v in vals))
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


def treeview_sort_column(tv, col: str, reverse: bool) -> None:
    """Sort a ttk.Treeview clicking on its header, dealing with numeric and text values."""

    try:
        # Get all children (since we may have items not fully loaded, though usually they are)
        # We also need to get the values to sort by.
        l = [(tv.set(k, col), k) for k in tv.get_children('')]

        def convert(val):
            # Try parsing as float for numeric sorting
            try:
                # Remove currency, percentage, commas, and other non-numeric symbols
                v = str(val).replace('₹', '').replace('%', '').replace(',', '').strip()
                if not v or v in ("—", "-", "N/A"):
                    return float('-inf') if not reverse else float('inf')
                return float(v)
            except ValueError:
                # Fallback: case-insensitive string sorting
                return str(val).lower()

        l.sort(key=lambda t: convert(t[0]), reverse=reverse)

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

    except Exception as e:
        print(f"Sort Error on {col}: {e}")

def show_toast(parent: tk.Misc, message: str, type: str = "success") -> None:
    """Show a non-blocking toast notification that fades out."""
    try:
        from ui_theme import ModernStyle
        
        toast = tk.Toplevel(parent)
        toast.overrideredirect(True)
        # Keep on top
        try:
            toast.attributes('-topmost', True)
        except Exception:
            pass
            
        bg_color = ModernStyle.SUCCESS if type == "success" else ModernStyle.ERROR
        fg_color = ModernStyle.TEXT_ON_ACCENT
        
        frame = tk.Frame(toast, bg=bg_color, highlightbackground=ModernStyle.BORDER_COLOR, highlightthickness=1)
        frame.pack(fill="both", expand=True)
        
        inner = tk.Frame(frame, bg=bg_color, padx=16, pady=10)
        inner.pack(fill="both", expand=True)
        
        icon = "✅" if type == "success" else "⚠"
        
        tk.Label(
            inner, 
            text=f"{icon}  {message}", 
            bg=bg_color, 
            fg=fg_color, 
            font=(ModernStyle.FONT_FAMILY, 11, "bold")
        ).pack()
        
        # Position bottom right of parent
        parent.update_idletasks()
        try:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            
            toast.update_idletasks()
            tw = toast.winfo_reqwidth()
            th = toast.winfo_reqheight()
            
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
        
    except Exception as e:
        print(f"Toast error: {e}")

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

