#!/usr/bin/env python3
"""Reusable UI widgets (kept separate to avoid circular imports)."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional
from pathlib import Path

from ui_theme import ModernStyle


class ModernEntry(tk.Entry):
    """Custom entry with modern styling, placeholder support, and a subtle border."""

    def __init__(self, parent, placeholder="", numeric_only=False, currency_format=False, **kwargs):
        # Default text color (blue) for input, muted for placeholder
        fg = kwargs.pop("fg", ModernStyle.ACCENT_PRIMARY)
        # Subtle default border — callers can override
        kwargs.setdefault("highlightthickness", 1)
        kwargs.setdefault("highlightbackground", ModernStyle.BORDER_COLOR)
        kwargs.setdefault("highlightcolor", ModernStyle.ACCENT_PRIMARY)
        kwargs.setdefault("relief", tk.FLAT)
        
        self.numeric_only = numeric_only
        self.currency_format = currency_format
        
        if self.numeric_only:
            vcmd = (parent.register(self._validate_numeric), '%P')
            kwargs['validate'] = 'key'
            kwargs['validatecommand'] = vcmd
            
        super().__init__(parent, **kwargs)
        
        self.placeholder = placeholder
        self.default_color = ModernStyle.TEXT_TERTIARY
        self.normal_color = fg
        
        self.bg_color = kwargs.get("bg", ModernStyle.ENTRY_BG)
        self.highlight_color = kwargs.get("highlightcolor", ModernStyle.ACCENT_PRIMARY)
        self.highlight_bg_color = kwargs.get("highlightbackground", ModernStyle.BORDER_COLOR)
        
        if placeholder:
            self.insert(0, placeholder)
            self.config(fg=self.default_color)
        else:
            self.config(fg=self.normal_color)
        
        self.bind('<FocusIn>', self._on_focus_in)
        self.bind('<FocusOut>', self._on_focus_out)
        
    def _validate_numeric(self, P):
        if P == "" or P == self.placeholder:
            return True
        # Allow numbers, optional negative sign at start, and one decimal point
        if P in ('-', '.', '-.'):
            return True
        try:
            # Also allow commas if it's currently formatted
            P_stripped = str(P).replace(',', '')
            float(P_stripped)
            return True
        except ValueError:
            self._shake()
            return False
            
    def _shake(self):
        """Micro-animation: shake widget to indicate error."""
        orig_x = self.winfo_x()
        for offset, delay in zip([2, -2, 2, -2, 0], [10, 30, 50, 70, 90]):
            self.after(delay, lambda o=offset: self.place(x=orig_x + o) if self.place_info() else None)

    def _clear_text(self):
        self.delete(0, tk.END)
        self.focus_set()
        self._on_focus_out()

    def _check_clear_btn(self, event=None):
        pass  # handled by ClearableEntry
    
    def _on_focus_in(self, event=None):
        # 1. Handle Placeholder / Unformatting
        val = self.get()
        if val == self.placeholder:
            self.delete(0, tk.END)
        elif self.currency_format and val:
            # Strip formatting to edit
            self.delete(0, tk.END)
            self.insert(0, val.replace(',', ''))
            
        self.config(fg=self.normal_color)
        self._check_clear_btn()
        
        # 2. Smooth border fading via ui_utils
        try:
            from ui_utils import fade_color_transition
            fade_color_transition(self, self.highlight_bg_color, self.highlight_color, attr='highlightcolor', duration_ms=100)
        except Exception:
            pass
    
    def _on_focus_out(self, event=None):
        val = self.get().strip()
        if not val:
            self.insert(0, self.placeholder)
            self.config(fg=self.default_color)
        elif self.currency_format and val != self.placeholder:
            try:
                # Add thousands separators
                fval = float(val)
                self.delete(0, tk.END)
                self.insert(0, f"{fval:,.2f}")
            except Exception:
                pass
        self._check_clear_btn()
    
    def get_value(self):
        """Get entry value, ignoring placeholder and formatting."""
        val = self.get()
        if val == self.placeholder:
            return ""
        if self.currency_format:
            return val.replace(',', '')
        return val



class ClearableEntry(tk.Frame):
    """Search entry with a visible ✕ clear button that appears when text is present.

    Uses a tk.Frame wrapper so the X label is a true sibling of the entry
    (not a child of tk.Entry, which doesn't render on macOS).
    """

    def __init__(self, parent, placeholder="Search...", on_change=None, **entry_kwargs):
        bg = entry_kwargs.pop("bg", ModernStyle.ENTRY_BG)
        super().__init__(parent, bg=bg, highlightthickness=1,
                         highlightbackground=ModernStyle.BORDER_COLOR,
                         highlightcolor=ModernStyle.ACCENT_PRIMARY)

        self._on_change = on_change
        self._placeholder = placeholder
        self._bg = bg

        # ── inner entry (no border — frame handles it) ──────────────────────
        self.entry = ModernEntry(
            self,
            placeholder=placeholder,
            bg=bg,
            highlightthickness=0,
            bd=0,
            relief=tk.FLAT,
            **entry_kwargs,
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0), pady=4)

        # ── clear button (always present, visibility toggled) ───────────────
        self._clear_lbl = tk.Label(
            self, text="✕",
            fg=ModernStyle.TEXT_TERTIARY, bg=bg,
            font=("Helvetica", 11), cursor="hand2",
            padx=4,
        )
        self._clear_lbl.bind("<Button-1>", self._on_clear)
        # start hidden
        self._clear_lbl.pack_forget()

        # keep X in sync with content
        self.entry.bind("<KeyRelease>", self._sync_clear, add="+")
        self.entry.bind("<FocusIn>",  self._on_focus_in,  add="+")
        self.entry.bind("<FocusOut>", self._on_focus_out, add="+")

    # ── private helpers ────────────────────────────────────────────────────
    def _sync_clear(self, event=None):
        val = self.entry.get_value()
        if val:
            self._clear_lbl.pack(side=tk.RIGHT, padx=(0, 4))
        else:
            self._clear_lbl.pack_forget()
        if self._on_change:
            self._on_change(event)

    def _on_clear(self, event=None):
        self.entry.delete(0, tk.END)
        self.entry._on_focus_out()          # restore placeholder
        self._clear_lbl.pack_forget()
        self.entry.focus_set()
        if self._on_change:
            self._on_change(event)

    def _on_focus_in(self, event=None):
        self.config(highlightcolor=ModernStyle.ACCENT_PRIMARY,
                    highlightbackground=ModernStyle.ACCENT_PRIMARY)

    def _on_focus_out(self, event=None):
        self.config(highlightbackground=ModernStyle.BORDER_COLOR)
        self._sync_clear()

    # ── public API ─────────────────────────────────────────────────────────
    def get(self):
        return self.entry.get_value()

    def delete(self, first, last=None):
        self.entry.delete(first, last)
        self._sync_clear()


class MaterialEntry(tk.Canvas):
    """A premium form input with a floating Material-style label."""
    def __init__(self, parent, placeholder: str, width: int = 20, numeric_only=False, currency_format=False, **kwargs):
        self.bg_color = kwargs.pop("bg", ModernStyle.BG_PRIMARY)
        self.accent_color = kwargs.pop("accent", ModernStyle.ACCENT_PRIMARY)
        
        super().__init__(parent, bg=self.bg_color, highlightthickness=0, width=width*10, height=50, **kwargs)
        
        self.placeholder = placeholder
        self.is_focused = False
        self.has_text = False
        
        # Internal Entry Widget
        self.entry = ModernEntry(
            self, placeholder="",
            numeric_only=numeric_only, currency_format=currency_format,
            bg=self.bg_color, fg=ModernStyle.TEXT_PRIMARY,
            font=ModernStyle.FONT_BODY,
            bd=0, highlightthickness=0, relief=tk.FLAT,
            insertbackground=ModernStyle.TEXT_PRIMARY
        )
        # Link variable if provided
        if "textvariable" in kwargs:
            self.entry.config(textvariable=kwargs["textvariable"])
        
        # Position slightly down to leave room for the floating text
        self.entry_window = self.create_window(0, 24, window=self.entry, anchor="nw", width=width*10)
        
        # Floating Label Text
        self.label_id = self.create_text(
            4, 24,  # Start at same height as entry text
            text=self.placeholder,
            fill=ModernStyle.TEXT_TERTIARY,
            font=ModernStyle.FONT_BODY,
            anchor="nw"
        )
        
        # Underline
        self.line_id = self.create_line(0, 48, width*10, 48, fill=ModernStyle.BORDER_COLOR, width=1)
        
        # Bind events
        self.entry.bind("<FocusIn>", self._on_focus_in, add="+")
        self.entry.bind("<FocusOut>", self._on_focus_out, add="+")
        self.entry.bind("<KeyRelease>", self._check_state, add="+")
        self.bind("<Button-1>", lambda e: self.entry.focus_set())
        
        self.bind("<Configure>", self._on_resize)
        
    def _on_resize(self, event=None):
        w = event.width if event else self.winfo_width()
        self.itemconfig(self.entry_window, width=w)
        self.coords(self.line_id, 0, 48, w, 48)

    def _anim_float(self, target_y: float, target_font: tuple, target_color: str):
        # Extremely simplified animation logic
        current_y = self.coords(self.label_id)[1]
        step_y = (target_y - current_y) / 5.0
        
        def _step(count):
            if count > 5:
                self.itemconfig(self.label_id, font=target_font, fill=target_color)
                self.coords(self.label_id, 4, target_y)
                return
            self.move(self.label_id, 0, step_y)
            self.after(16, _step, count+1)
        _step(1)

    def _on_focus_in(self, event=None):
        self.is_focused = True
        self.itemconfig(self.line_id, fill=self.accent_color, width=2)
        self._sync_label()

    def _on_focus_out(self, event=None):
        self.is_focused = False
        self.itemconfig(self.line_id, fill=ModernStyle.BORDER_COLOR, width=1)
        self._sync_label()

    def _check_state(self, event=None):
        new_state = len(self.entry.get()) > 0
        if new_state != self.has_text:
            self.has_text = new_state
            self._sync_label()

    def _sync_label(self):
        if self.is_focused or self.has_text:
            # Float UP
            color = self.accent_color if self.is_focused else ModernStyle.TEXT_SECONDARY
            self._anim_float(4, ModernStyle.FONT_SMALL_BOLD, color)
        else:
            # Float DOWN
            self._anim_float(24, ModernStyle.FONT_BODY, ModernStyle.TEXT_TERTIARY)
            
    # Proxy core tk.Entry methods
    def get(self): return self.entry.get_value()
    def insert(self, idx, text):
        self.entry.insert(idx, text)
        self._check_state()
    def delete(self, first, last=None):
        self.entry.delete(first, last)
        self._check_state()
    def config(self, **kwargs):
        if 'textvariable' in kwargs:
            self.entry.config(textvariable=kwargs.pop('textvariable'))
        super().config(**kwargs)


class ModernButton(tk.Canvas):
    """Canvas-based button with hover/press effects.

    Works consistently across platforms and allows a more modern look than
    default tk.Button.
    """

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: Optional[Callable[[], None]] = None,
        *,
        icon: tk.PhotoImage | None = None,
        icon_path: str | None = None,
        icon_subsample: int = 1,
        invoke_on_press: bool = False,
        bg: str = ModernStyle.ACCENT_PRIMARY,
        fg: str = ModernStyle.TEXT_ON_ACCENT,
        canvas_bg: Optional[str] = None,
        width: int = 120,
        height: int = 38,
        radius: int = 10,
        font=None,
        text_anchor: str = "c",
        text_padx: int = 14,
        disabled: bool = False,
        **kwargs,
    ):
        if canvas_bg is None:
            try:
                canvas_bg = str(parent.cget("bg"))
            except Exception:
                canvas_bg = ModernStyle.BG_PRIMARY

        super().__init__(
            parent,
            width=width,
            height=height,
            bg=canvas_bg,
            highlightthickness=0,
            bd=0,
            **kwargs,
        )

        self._command = command
        self._text = text
        self._width = width
        self._height = height
        self._radius = max(6, int(radius))
        self._icon = icon if icon is not None else self._try_load_icon(icon_path, icon_subsample)
        self._icon_subsample = max(1, int(icon_subsample))
        self._icon_pad = 10

        self._invoke_on_press = bool(invoke_on_press)

        self._font = font if font is not None else ModernStyle.FONT_SUBHEADING
        self._text_anchor = (text_anchor or "c").lower()
        self._text_padx = max(0, int(text_padx))
        
        self._canvas_bg = canvas_bg

        self._bg_normal = bg
        self._bg_hover = self._lighten_color(bg, 18)
        self._bg_pressed = self._darken_color(bg, 18)
        self._fg = fg

        self._disabled = disabled
        self._is_pressed = False
        self._canvas_ids = {} # Persist IDs to avoid delete("all") overhead.

        # Some macOS/Tk builds occasionally miss `<ButtonRelease-1>` for
        # custom Canvas widgets during immediate UI swaps. To keep navigation
        # feeling snappy and reliable, we also schedule a command invoke on
        # press with a tiny delay, and guard against double-fires.
        self._press_invoke_after_id: str | None = None
        self._reset_after_id: str | None = None
        self._click_invoked: bool = False
        self._hover_suppressed: bool = False
        self._hover_suppress_id: str | None = None

        self._fade_id: str | None = None
        self._current_fill: str = self._bg_normal

        self.configure(cursor="arrow" if disabled else "hand2")
        self._redraw(self._bg_normal)

        if not disabled:
            self._bind_events()

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = disabled
        self.configure(cursor="arrow" if disabled else "hand2")
        if disabled:
            self._unbind_events()
        else:
            self._bind_events()
        self._redraw(self._bg_normal)

    def set_palette(
        self,
        *,
        bg: str | None = None,
        fg: str | None = None,
        hover_bg: str | None = None,
        pressed_bg: str | None = None,
    ) -> None:
        if bg is not None:
            self._bg_normal = bg
            self._bg_hover = self._lighten_color(bg, 18)
            self._bg_pressed = self._darken_color(bg, 18)
        if fg is not None:
            self._fg = fg
        if hover_bg is not None:
            self._bg_hover = hover_bg
        if pressed_bg is not None:
            self._bg_pressed = pressed_bg
        self._redraw(self._bg_normal)

    def set_text(self, text: str) -> None:
        self._text = text
        self._redraw(self._bg_normal)

    def set_size(self, *, width: int | None = None, height: int | None = None) -> None:
        if width is not None:
            self._width = int(width)
            try:
                self.configure(width=self._width)
            except Exception:
                pass
        if height is not None:
            self._height = int(height)
            try:
                self.configure(height=self._height)
            except Exception:
                pass
        self._redraw(self._bg_normal)

    def _bind_events(self) -> None:
        self.bind("<Enter>", self._on_hover)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _unbind_events(self) -> None:
        self.unbind("<Enter>")
        self.unbind("<Leave>")
        self.unbind("<Button-1>")
        self.unbind("<ButtonRelease-1>")

        # Cancel any pending callbacks.
        try:
            if self._press_invoke_after_id:
                self.after_cancel(self._press_invoke_after_id)
        except Exception:
            pass
        self._press_invoke_after_id = None
        try:
            if self._reset_after_id:
                self.after_cancel(self._reset_after_id)
        except Exception:
            pass
    def _cancel_fade(self) -> None:
        if self._fade_id:
            try:
                self.after_cancel(self._fade_id)
            except Exception:
                pass
            self._fade_id = None

    def _fade_to_color(self, target_color: str, step: float = 0.0) -> None:
        if self._disabled:
            return
            
        # Ensure we always start cleanly without stack overflows
        self._cancel_fade()
        
        # Don't fade active transparent fallbacks if they are identical
        if self._current_fill == "transparent" and target_color == "transparent":
            return
            
        def _anim(s=step):
            if s >= 1.0:
                self._current_fill = target_color
                self._update_surface(target_color)
                self._fade_id = None
                return
            
            blended = self._blend(self._current_fill, target_color, s)
            self._update_surface(blended)
            
            # Smooth ease-out logic
            s += 0.2
            self._fade_id = self.after(16, lambda: _anim(s))
            
        # Start the loop
        _anim()

    def _update_surface(self, fill: str) -> None:
        """Fast path to just update surface colers without redrawing everything."""
        if "surface" in self._canvas_ids:
            ids = self._canvas_ids["surface"]
            if isinstance(ids, (list, tuple)):
                for i in ids: 
                    self.itemconfig(i, fill=fill, outline=fill)

    def _redraw(self, fill: str) -> None:
        self._current_fill = fill
        # Surface fill logic
        if self._disabled:
            fill = self._blend(fill, ModernStyle.BG_PRIMARY, 0.55)
        text_fill = ModernStyle.TEXT_TERTIARY if self._disabled else self._fg

        # ── INITIAL BUILD ─────────────────────────────────────────────────────
        if not self._canvas_ids:
            self.delete("all")
            
            # Shadow (subtle)
            shadow_alpha = 0.08
            shadow_color = self._blend("#000000", self._canvas_bg, shadow_alpha)
            self._canvas_ids["shadow"] = self._rounded_rect(2, 3, self._width - 1, self._height - 1, self._radius, fill=shadow_color)
            
            # Primary surface
            self._canvas_ids["surface"] = self._rounded_rect(1, 1, self._width - 2, self._height - 2, self._radius, fill=fill)
            
            # Content (Text/Icon)
            if self._icon is not None:
                if not str(self._text or "").strip():
                    self._canvas_ids["icon"] = self.create_image(self._width // 2, self._height // 2, image=self._icon)
                else:
                    x_icon = self._icon_pad + (self._icon.width() // 2)
                    self._canvas_ids["icon"] = self.create_image(x_icon, self._height // 2, image=self._icon)
                    self._canvas_ids["text"] = self.create_text(
                        x_icon + (self._icon.width() // 2) + self._icon_pad,
                        self._height // 2,
                        text=self._text, font=self._font, fill=text_fill, anchor="w",
                    )
            else:
                tx, ty, ta = (self._text_padx, self._height // 2, "w") if self._text_anchor in {"w", "west", "left"} else (self._width // 2, self._height // 2, "c")
                self._canvas_ids["text"] = self.create_text(tx, ty, text=self._text, font=self._font, fill=text_fill, anchor=ta)
            return

        # ── COLOR UPDATE ─────────────────────────────────────────────────────
        # Only update colors, do not destroy/recreate. This is orders of magnitude
        # faster on macOS and prevents main thread starvation.
        if "surface" in self._canvas_ids:
            # We must update all components of the custom rounded rect group
            ids = self._canvas_ids["surface"]
            if isinstance(ids, (list, tuple)):
                for i in ids: self.itemconfig(i, fill=fill, outline=fill)
        
        if "text" in self._canvas_ids:
            self.itemconfig(self._canvas_ids["text"], fill=text_fill)

    @staticmethod
    def _try_load_icon(icon_path: str | None, icon_subsample: int) -> tk.PhotoImage | None:
        if not icon_path:
            return None
        try:
            p = Path(icon_path)
            if not p.is_absolute():
                p = Path(__file__).resolve().parent / p
            if not p.exists():
                return None
            img = tk.PhotoImage(file=str(p))
            s = max(1, int(icon_subsample))
            if s > 1:
                img = img.subsample(s, s)
            return img
        except Exception:
            return None

    def _rounded_rect(self, x1: int, y1: int, x2: int, y2: int, r: int, *, fill: str) -> list[int]:
        ids = []
        # corners 
        ids.append(self.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, fill=fill, outline=fill))
        ids.append(self.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, fill=fill, outline=fill))
        ids.append(self.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, fill=fill, outline=fill))
        ids.append(self.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, fill=fill, outline=fill))
        # center + edges
        ids.append(self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=""))
        ids.append(self.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=""))
        return ids

    def _on_hover(self, event=None):
        # On macOS, <Enter> events can flood the loop and block background thread UI updates.
        # If we just clicked or the button is meant to be quiet, skip the expensive redraw.
        if self._hover_suppressed or self._disabled:
            return
        if not self._is_pressed:
            self._fade_to_color(self._bg_hover)

    def _on_leave(self, event=None):
        if not self._is_pressed:
            self._fade_to_color(self._bg_normal)

    def _on_press(self, event=None):
        self._is_pressed = True
        self._click_invoked = False

        # Cancel any previous click timers.
        try:
            if self._press_invoke_after_id:
                self.after_cancel(self._press_invoke_after_id)
        except Exception:
            pass
        self._press_invoke_after_id = None
        try:
            if self._reset_after_id:
                self.after_cancel(self._reset_after_id)
        except Exception:
            pass
        self._reset_after_id = None
        
        self._cancel_fade()
        self._update_surface(self._bg_pressed)

        # Schedule an invoke shortly after press. This fixes cases where
        # `<ButtonRelease-1>` is not delivered (observed on macOS with
        # immediate view swaps).
        if self._invoke_on_press and self._command:
            try:
                self._press_invoke_after_id = self.after(35, self._invoke_from_press)
            except Exception:
                self._press_invoke_after_id = None

    def _invoke_from_press(self) -> None:
        self._press_invoke_after_id = None
        if self._disabled or self._click_invoked or not self._is_pressed or not self._command:
            return

        self._click_invoked = True
        # Suppress hover redraws for 600ms so deferred after(0,...) UI callbacks can run.
        self._suppress_hover()
        
        def _execute_and_flush():
            try:
                if self._command: self._command()
            finally:
                try: self.update_idletasks()
                except Exception: pass

        try:
            self.after(0, _execute_and_flush)
        except Exception:
            _execute_and_flush()

        # If the release event never arrives, auto-reset visuals so the button
        # doesn't look stuck.
        try:
            self._reset_after_id = self.after(220, self._auto_reset_if_stuck)
        except Exception:
            self._reset_after_id = None

    def _auto_reset_if_stuck(self) -> None:
        self._reset_after_id = None
        if not self._is_pressed:
            return
        self._is_pressed = False
        
        self._redraw(self._bg_normal)

    def _on_release(self, event=None):
        was_pressed = self._is_pressed
        self._is_pressed = False

        # If a press-invoke is pending, cancel it now.
        try:
            if self._press_invoke_after_id:
                self.after_cancel(self._press_invoke_after_id)
        except Exception:
            pass
        self._press_invoke_after_id = None

        # Cancel any auto-reset timer.
        try:
            if self._reset_after_id:
                self.after_cancel(self._reset_after_id)
        except Exception:
            pass
        self._reset_after_id = None
        
        self._redraw(self._bg_hover)
        if was_pressed and self._command and not self._click_invoked:
            self._click_invoked = True
            # Suppress hover redraws for 600ms so deferred after(0,...) UI callbacks can run.
            self._suppress_hover()
            
            def _execute_and_flush():
                try:
                    if self._command: self._command()
                finally:
                    try: self.update_idletasks()
                    except Exception: pass

            try:
                # Use a small positive delay to ensure the OS has handled the 'switch'
                # but use after(10,...) to be as immediate as possible without being stravable.
                self.after(10, _execute_and_flush)
            except Exception:
                _execute_and_flush()

    def _suppress_hover(self) -> None:
        """Suppress hover redraws for 600ms to let deferred callbacks execute."""
        self._hover_suppressed = True
        try:
            if self._hover_suppress_id:
                self.after_cancel(self._hover_suppress_id)
        except Exception:
            pass
        try:
            self._hover_suppress_id = self.after(600, self._unsuppress_hover)
        except Exception:
            self._hover_suppressed = False

    def _unsuppress_hover(self) -> None:
        self._hover_suppress_id = None
        self._hover_suppressed = False

    @staticmethod
    def _lighten_color(color: str, amount: int) -> str:
        try:
            c = color.lstrip("#")
            r = min(255, int(c[0:2], 16) + amount)
            g = min(255, int(c[2:4], 16) + amount)
            b = min(255, int(c[4:6], 16) + amount)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return color

    @staticmethod
    def _darken_color(color: str, amount: int) -> str:
        try:
            c = color.lstrip("#")
            r = max(0, int(c[0:2], 16) - amount)
            g = max(0, int(c[2:4], 16) - amount)
            b = max(0, int(c[4:6], 16) - amount)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return color

    @staticmethod
    def _blend(fg_hex: str, bg_hex: str, alpha: float) -> str:
        """Alpha blend fg over bg (both #RRGGBB)."""
        alpha = max(0.0, min(1.0, float(alpha)))
        f = fg_hex.lstrip("#")
        b = bg_hex.lstrip("#")
        fr, fg, fb = int(f[0:2], 16), int(f[2:4], 16), int(f[4:6], 16)
        br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
        r = int((fr * alpha) + (br * (1 - alpha)))
        g = int((fg * alpha) + (bg * (1 - alpha)))
        bl = int((fb * alpha) + (bb * (1 - alpha)))
        return f"#{r:02x}{g:02x}{bl:02x}"


class DatePicker(tk.Frame):
    """Modern calendar date picker widget."""

    def __init__(self, parent, on_date_selected=None, **kwargs):
        super().__init__(parent, bg=ModernStyle.BG_SECONDARY, **kwargs)
        self.on_date_selected = on_date_selected
        
        from datetime import datetime, timedelta
        import calendar as cal_module
        
        self.selected_date = datetime.now()
        
        # Header with month navigation
        header = tk.Frame(self, bg=ModernStyle.BG_SECONDARY)
        header.pack(fill=tk.X, padx=8, pady=8)
        
        tk.Button(
            header, text="◀", font=ModernStyle.FONT_BODY_BOLD,
            bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT,
            relief=tk.FLAT, bd=0, padx=6, pady=2,
            command=self._prev_month
        ).pack(side=tk.LEFT)
        
        self.month_label = tk.Label(
            header, font=ModernStyle.FONT_SUBHEADING,
            bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY
        )
        self.month_label.pack(side=tk.LEFT, expand=True)
        
        tk.Button(
            header, text="▶", font=ModernStyle.FONT_BODY_BOLD,
            bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT,
            relief=tk.FLAT, bd=0, padx=6, pady=2,
            command=self._next_month
        ).pack(side=tk.LEFT)
        
        # Weekday labels
        weekdays = tk.Frame(self, bg=ModernStyle.BG_SECONDARY)
        weekdays.pack(fill=tk.X, padx=4, pady=(0, 4))
        for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            tk.Label(
                weekdays, text=day, font=ModernStyle.FONT_TINY_BOLD,
                bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_SECONDARY,
                width=4, pady=4
            ).pack(side=tk.LEFT, padx=1)
        
        # Calendar grid
        self.grid_frame = tk.Frame(self, bg=ModernStyle.BG_SECONDARY)
        self.grid_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        
        self.day_buttons = []
        self._update_calendar()
    
    def _prev_month(self):
        from datetime import timedelta
        self.selected_date = (self.selected_date.replace(day=1) - timedelta(days=1)).replace(day=1)
        self._update_calendar()
    
    def _next_month(self):
        from datetime import timedelta
        last_day = (self.selected_date.replace(day=1) - timedelta(days=1)).day if self.selected_date.month == 1 else (self.selected_date.replace(day=1) + timedelta(days=32)).replace(day=1).day
        self.selected_date = (self.selected_date.replace(day=1) + timedelta(days=32)).replace(day=1)
        self._update_calendar()
    
    def _update_calendar(self):
        import calendar as cal_module
        from datetime import datetime
        
        # Update header
        self.month_label.config(text=self.selected_date.strftime("%B %Y"))
        
        # Clear grid completely
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.day_buttons = []
        
        # Get calendar for this month
        month_cal = cal_module.monthcalendar(self.selected_date.year, self.selected_date.month)
        
        for week in month_cal:
            week_frame = tk.Frame(self.grid_frame, bg=ModernStyle.BG_SECONDARY)
            week_frame.pack(fill=tk.X)
            
            for day in week:
                if day == 0:
                    tk.Label(week_frame, text="", bg=ModernStyle.BG_SECONDARY, width=4).pack(side=tk.LEFT, padx=1, pady=2)
                else:
                    is_today = (
                        day == datetime.now().day and
                        self.selected_date.month == datetime.now().month and
                        self.selected_date.year == datetime.now().year
                    )
                    
                    btn = tk.Button(
                        week_frame, text=str(day), font=ModernStyle.FONT_TINY,
                        bg=ModernStyle.ACCENT_PRIMARY if is_today else ModernStyle.BG_PRIMARY,
                        fg=ModernStyle.TEXT_ON_ACCENT if is_today else ModernStyle.TEXT_PRIMARY,
                        relief=tk.FLAT, bd=0, width=4, padx=0, pady=2,
                        command=lambda d=day: self._select_day(d)
                    )
                    btn.pack(side=tk.LEFT, padx=1, pady=2)
                    self.day_buttons.append(btn)
    
    def _select_day(self, day):
        from datetime import datetime
        selected = self.selected_date.replace(day=day)
        if self.on_date_selected:
            self.on_date_selected(selected.date())
        # Don't close here; let parent handle it


class DatePickerButton(tk.Frame):
    """Button that opens a date picker popup."""
    
    def __init__(self, parent, on_date_selected=None, initial_date=None, **kwargs):
        bg = kwargs.pop("bg", ModernStyle.BG_PRIMARY)
        super().__init__(parent, bg=bg, **kwargs)
        self.on_date_selected = on_date_selected
        self.selected_date = initial_date if initial_date else None
        self.popup = None
        
        # Display frame
        display = tk.Frame(self, bg=ModernStyle.BG_SECONDARY, highlightbackground=ModernStyle.BORDER_COLOR, highlightthickness=1)
        display.pack(fill=tk.X, padx=0, pady=0)
        
        self.date_label = tk.Label(
            display, text=self.selected_date.strftime("%Y-%m-%d") if self.selected_date else "Select Date",
            font=ModernStyle.FONT_SMALL,
            bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_PRIMARY,
            padx=8, pady=6
        )
        self.date_label.pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        tk.Button(
            display, text="📅", font=ModernStyle.FONT_BODY,
            bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.ACCENT_PRIMARY,
            relief=tk.FLAT, bd=0, padx=6, pady=4,
            command=self._open_picker
        ).pack(side=tk.RIGHT)
    
    def _open_picker(self):
        if self.popup is None or not self.popup.winfo_exists():
            self.popup = tk.Toplevel(self)
            self.popup.title("Select Date")
            ModernStyle.style_modal(self.popup)
            
            # Position the popup below the button
            x = self.winfo_rootx()
            y = self.winfo_rooty() + self.winfo_height()
            self.popup.geometry(f"280x320+{x}+{y}")
            self.popup.resizable(False, False)
            
            # Try to make it look like a dropdown without OS chrome if possible
            try:
                if sys.platform == "win32":
                    self.popup.overrideredirect(True)
                elif sys.platform == "darwin":
                    self.popup.wm_attributes("-type", "dropdown")
                else:
                    self.popup.wm_attributes("-type", "popup_menu")
            except Exception:
                pass
            
            # Configure popup style
            self.popup.configure(bg=ModernStyle.BG_SECONDARY)
            
            picker = DatePicker(self.popup, on_date_selected=self._on_date_selected)
            picker.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
            
            # Buttons
            btn_frame = tk.Frame(self.popup, bg=ModernStyle.BG_SECONDARY)
            btn_frame.pack(fill=tk.X, padx=4, pady=4)
            
            tk.Button(
                btn_frame, text="OK", font=ModernStyle.FONT_BODY,
                bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT,
                relief=tk.FLAT, bd=0, padx=12, pady=6,
                command=self.popup.destroy
            ).pack(side=tk.RIGHT, padx=2)
            
            tk.Button(
                btn_frame, text="Cancel", font=ModernStyle.FONT_BODY,
                bg=ModernStyle.ACCENT_SECONDARY, fg=ModernStyle.TEXT_ON_ACCENT,
                relief=tk.FLAT, bd=0, padx=12, pady=6,
                command=self.popup.destroy
            ).pack(side=tk.RIGHT, padx=2)
            
            # Focus handling for closing
            self.popup.focus_set()
    
    def _on_date_selected(self, date):
        self.selected_date = date
        self.date_label.config(text=date.strftime("%Y-%m-%d"))
        if self.on_date_selected:
            self.on_date_selected(date)
    
    def get_date(self):
        return self.selected_date
    
    def set_date(self, date):
        self.selected_date = date
        if date:
            self.date_label.config(text=date.strftime("%Y-%m-%d"))

class PremiumModal(tk.Toplevel):
    """
    A unified base class for all popup modals.
    Provides standard window styling, centering, and a clean light/modern aesthetic.
    """
    def __init__(self, parent, title: str, geometry: str = "500x520", icon: str = "✨"):
        super().__init__(parent)
        self.title(f"{title}")
        self.configure(bg=ModernStyle.BG_PRIMARY)
        self.resizable(False, False)
        self.geometry(geometry)
        
        # Apply global option_add defaults for this window's widgets
        try:
            ModernStyle.style_modal(self)
        except Exception:
            pass
        
        try:
            self.transient(parent.winfo_toplevel())
            self.grab_set()
        except Exception:
            pass
            
        try:
            from ui_utils import center_window
            center_window(self, parent=parent.winfo_toplevel())
        except Exception:
            pass
            
        # ── Premium header with accent gradient bar ──
        self.header = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        self.header.pack(fill="x")

        # Thin accent gradient bar at very top
        tk.Frame(self.header, bg=ModernStyle.ACCENT_PRIMARY, height=3).pack(fill="x")

        self.inner_hdr = tk.Frame(self.header, bg=ModernStyle.BG_PRIMARY)
        self.inner_hdr.pack(fill="x", padx=28, pady=(18, 16))

        # Left block: icon + title
        if icon:
            tk.Label(
                self.inner_hdr, text=icon, bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_PRIMARY,
                font=ModernStyle.FONT_MODAL_ICON
            ).pack(side="left", padx=(0, 12))

        self.title_col = tk.Frame(self.inner_hdr, bg=ModernStyle.BG_PRIMARY)
        self.title_col.pack(side="left", fill="y")
        self.title_lbl = tk.Label(
            self.title_col, text=title,
            bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_PRIMARY,
            font=ModernStyle.FONT_SECTION_LABEL
        )
        self.title_lbl.pack(anchor="w")
        
        # Area for child classes to put chips/badges under the title.
        self.chips_row = tk.Frame(self.title_col, bg=ModernStyle.BG_PRIMARY)
        self.chips_row.pack(anchor="w", pady=(4, 0))

        # ── Scrolling content card (Main Body) ──
        self.body_card = tk.Frame(self, bg=ModernStyle.BG_SECONDARY, highlightbackground=ModernStyle.BORDER_COLOR, highlightthickness=1)
        self.body_card.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        # Accent separator under header
        tk.Frame(self.body_card, bg=ModernStyle.ACCENT_PRIMARY, height=2).pack(fill="x")
        
        self.content_frame = tk.Frame(self.body_card, bg=ModernStyle.BG_SECONDARY)
        self.content_frame.pack(fill="both", expand=True, padx=24, pady=(20, 8))
        self.content_frame.grid_columnconfigure(0, weight=1)

        # ── Footer / Actions Area ──
        self.status_lbl = tk.Label(
            self.body_card, text="", bg=ModernStyle.BG_SECONDARY, fg=ModernStyle.TEXT_SECONDARY,
            font=ModernStyle.FONT_ITALIC, anchor="w"
        )
        self.status_lbl.pack(anchor="w", padx=24, pady=(0, 8), fill="x")
        
        # Divider before buttons
        tk.Frame(self.body_card, bg=ModernStyle.BORDER_COLOR, height=1).pack(fill="x", padx=20, pady=(0, 12))

        self.actions_frame = tk.Frame(self.body_card, bg=ModernStyle.BG_SECONDARY)
        self.actions_frame.pack(fill="x", padx=24, pady=(0, 20))

    def set_status(self, text: str, is_error: bool = False):
        color = ModernStyle.ERROR if is_error else ModernStyle.TEXT_TERTIARY
        self.status_lbl.configure(text=text, fg=color)
        
    def add_chip(self, emoji: str, text: str, bg_color: str = ModernStyle.ACCENT_PRIMARY_PALE, fg_color: str = ModernStyle.ACCENT_PRIMARY, font: tuple = None):
        if font is None:
            font = ModernStyle.FONT_SMALL_BOLD
        chip = tk.Frame(self.chips_row, bg=bg_color, highlightthickness=1, highlightbackground=fg_color)
        chip.pack(side="left", padx=(0, 6))
        tk.Label(
            chip, text=f"{emoji} {text}", bg=bg_color, fg=fg_color,
            font=font,
            padx=8, pady=2
        ).pack()

class LoadingOverlay(tk.Frame):
    """
    A unified, non-blocking loading overlay to provide feedback during data fetching.
    """
    def __init__(self, parent, text: str = "Loading..."):
        super().__init__(parent, bg=ModernStyle.BG_PRIMARY)
        self.text = text
        self._build()
        
    def _build(self):
        # A simple centered message
        container = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        container.place(relx=0.5, rely=0.5, anchor="center")
        
        tk.Label(
            container, text="⏳", bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.ACCENT_PRIMARY,
            font=ModernStyle.FONT_LOADING_ICON
        ).pack(pady=(0, 10))
        
        self.lbl = tk.Label(
            container, text=self.text, bg=ModernStyle.BG_PRIMARY, fg=ModernStyle.TEXT_SECONDARY,
            font=ModernStyle.FONT_ITALIC_MD
        )
        self.lbl.pack()
        
    def show(self):
        self.lift()
        self.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        
    def hide(self):
        self.place_forget()
        
    def set_text(self, text: str):
        self.lbl.configure(text=text)

class ModernToggle(tk.Canvas):
    """Modern rounded toggle switch."""
    def __init__(self, parent, variable, on_value=True, off_value=False, command=None, 
                 width=44, height=24, bg=ModernStyle.BG_PRIMARY, **kwargs):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, bd=0, **kwargs)
        self.variable = variable
        self.on_value = on_value
        self.off_value = off_value
        self.command = command
        self._width_px = width
        self._height_px = height
        self._r = height // 2
        
        self.bind("<Button-1>", self.toggle)
        
        # Draw base
        self._bg_id = self._rounded_rect(2, 2, self._width_px - 2, self._height_px - 2, self._r - 2, fill=ModernStyle.SLATE_700)
        self._knob_id = self.create_oval(4, 4, self._height_px - 4, self._height_px - 4, fill="#FFFFFF", outline="")
        
        self._animating = False
        self._knob_pos = 4
        self.update_visual()
        
        if self.variable is not None:
            # Trace variable if possible
            try:
                self.variable.trace_add("write", lambda *args: self.update_visual())
            except Exception:
                pass

    def _rounded_rect(self, x1, y1, x2, y2, r, fill):
        ids = []
        ids.append(self.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, fill=fill, outline=fill))
        ids.append(self.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, fill=fill, outline=fill))
        ids.append(self.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, fill=fill, outline=fill))
        ids.append(self.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, fill=fill, outline=fill))
        ids.append(self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=""))
        ids.append(self.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=""))
        return ids

    def toggle(self, event=None):
        if self._animating: return
        val = self.variable.get()
        new_val = self.off_value if val == self.on_value else self.on_value
        if self.variable:
            try:
                self.variable.set(new_val)
            except Exception:
                pass
        self._animate(new_val == self.on_value)
        if self.command:
            self.command()
            
    def update_visual(self):
        try:
            is_on = (self.variable.get() == self.on_value)
            target_x = self._width_px - self._height_px + 4 if is_on else 4
            self.coords(self._knob_id, target_x, 4, target_x + self._height_px - 8, self._height_px - 4)
            self._knob_pos = target_x
            
            fill_color = ModernStyle.SUCCESS if is_on else ModernStyle.SLATE_700
            for i in self._bg_id:
                self.itemconfig(i, fill=fill_color, outline=fill_color)
        except Exception:
            pass
            
    def _animate(self, is_on):
        self._animating = True
        target_x = self._width_px - self._height_px + 4 if is_on else 4
        fill_color = ModernStyle.SUCCESS if is_on else ModernStyle.SLATE_700
        
        # Color change immediately
        for i in self._bg_id:
            self.itemconfig(i, fill=fill_color, outline=fill_color)
            
        def step():
            dist = target_x - self._knob_pos
            if abs(dist) < 1:
                self.coords(self._knob_id, target_x, 4, target_x + self._height_px - 8, self._height_px - 4)
                self._knob_pos = target_x
                self._animating = False
                return
            
            self._knob_pos += dist * 0.4 # ease out
            self.coords(self._knob_id, self._knob_pos, 4, self._knob_pos + self._height_px - 8, self._height_px - 4)
            self.after(16, step)
            
        step()

class ModernDropdown(tk.Frame):
    """Custom dropdown using a canvas button and a borderless Toplevel."""
    def __init__(self, parent, textvariable=None, values=None, width=160, height=36, font=None, command=None, bg=ModernStyle.BG_SECONDARY, list_bg=ModernStyle.BG_SECONDARY, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)
        self.textvariable = textvariable
        self.values = values or []
        self.command = command
        self._width_px = width
        self._height_px = height
        self.list_bg = list_bg
        
        # The button that looks like a dropdown
        self.btn = ModernButton(
            self, text=self.textvariable.get() if self.textvariable else "Select...",
            bg=bg, fg=ModernStyle.TEXT_PRIMARY,
            width=width, height=height, radius=6,
            text_anchor="w", text_padx=12,
            command=self._toggle_popup,
            font=font or ModernStyle.FONT_BODY,
            canvas_bg=bg
        )
        self.btn.pack(fill=tk.BOTH, expand=True)
        
        # Add a little chevron
        self.chevron = tk.Label(self.btn, text="▼", bg=bg, fg=ModernStyle.TEXT_TERTIARY, font=ModernStyle.FONT_TINY)
        self.chevron.place(relx=1.0, rely=0.5, anchor="e", x=-10)
        
        # Update text when variable changes
        if self.textvariable is not None:
            try:
                self.textvariable.trace_add("write", self._on_var_change)
            except Exception:
                pass
                
        self.popup = None

    def _on_var_change(self, *args):
        if self.textvariable is not None:
             val = self.textvariable.get()
             self.btn.set_text(val)
             
    def configure_values(self, values):
        self.values = values
             
    def _toggle_popup(self):
        import sys
        if self.popup and self.popup.winfo_exists():
            self.popup.destroy()
            self.popup = None
            return
            
        self.popup = tk.Toplevel(self)
        ModernStyle.style_modal(self.popup)
        self.popup.config(bg=ModernStyle.BORDER_COLOR)
        try:
            if sys.platform == "win32":
                self.popup.overrideredirect(True)
            elif sys.platform == "darwin":
                self.popup.wm_attributes("-type", "dropdown")
            else:
                 self.popup.overrideredirect(True)
        except Exception:
            pass
            
        self.update_idletasks()
        x = self.btn.winfo_rootx()
        y = self.btn.winfo_rooty() + self.btn.winfo_height() + 2
        w = max(self.btn.winfo_width(), 100)
        h_popup = min(200, len(self.values)*30 + 4)
        self.popup.geometry(f"{w}x{h_popup}+{x}+{y}")
        
        listbox_frame = tk.Frame(self.popup, bg=self.list_bg, padx=1, pady=1)
        listbox_frame.pack(fill=tk.BOTH, expand=True)

        listbox = tk.Listbox(
            listbox_frame, bg=self.list_bg, fg=ModernStyle.TEXT_PRIMARY,
            selectbackground=ModernStyle.ACCENT_PRIMARY_PALE,
            selectforeground=ModernStyle.ACCENT_PRIMARY,
            font=ModernStyle.FONT_BODY,
            relief=tk.FLAT, bd=0, highlightthickness=0,
            activestyle="none"
        )
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        from tkinter import ttk
        scrollbar = ttk.Scrollbar(listbox_frame, orient="vertical", command=listbox.yview)
        if len(self.values)*30 > 200:
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.config(yscrollcommand=scrollbar.set)
        
        for val in self.values:
            listbox.insert(tk.END, val)
            
        def _on_select(event):
            try:
                sel = listbox.curselection()
                if sel:
                    val = listbox.get(sel[0])
                    if self.textvariable:
                        self.textvariable.set(val)
                    if self.command:
                        self.command(event)
                self.popup.destroy()
                self.popup = None
            except Exception:
                pass
                
        def _on_focus_out(event):
            if self.popup and self.popup.winfo_exists():
                # Give a small delay so click events process
                self.popup.after(150, lambda: self.popup.destroy() if self.popup else None)
                
        listbox.bind("<<ListboxSelect>>", _on_select)
        self.popup.bind("<FocusOut>", _on_focus_out)
        self.popup.focus_set()

class ModernCard(tk.Canvas):
    """A card layout with actual rounded corners."""
    def __init__(self, parent, width=0, height=0, radius=12, bg=ModernStyle.BG_SECONDARY,
                 highlight_color=ModernStyle.BORDER_COLOR, highlight_thickness=1,
                 canvas_bg=ModernStyle.BG_PRIMARY, expand_height=False, **kwargs):
        super().__init__(parent, width=width, height=height, bg=canvas_bg, highlightthickness=0, bd=0, **kwargs)
        self.radius = radius
        self.bg_color = bg
        self.highlight_color = highlight_color
        self.highlight_thickness = highlight_thickness
        self._explicit_width = width    # 0 = auto-size from content
        self._explicit_height = height  # 0 = auto-size from content
        self._expand_height = expand_height  # True = let geometry manager control height

        self.bind("<Configure>", self._on_resize)

        self.content = tk.Frame(self, bg=bg)
        self.content_id = self.create_window(self.highlight_thickness, self.highlight_thickness, window=self.content, anchor="nw")
        self._bg_items = []
        self._sync_pending = False  # debounce flag prevents event-loop cascade
        self._hover_active = False
        self._original_highlight = highlight_color
        # Sync canvas size whenever inner content changes or card first appears
        self.content.bind("<Configure>", self._sync_size)
        self.bind("<Map>", self._sync_size)
        # Hover lift effect
        self.bind("<Enter>", self._on_card_enter)
        self.bind("<Leave>", self._on_card_leave)
        self.content.bind("<Enter>", self._on_card_enter)
        self.content.bind("<Leave>", self._on_card_leave)

    def _on_card_enter(self, event=None):
        if self._hover_active:
            return
        self._hover_active = True
        self.highlight_color = ModernStyle.ACCENT_PRIMARY
        self._on_resize()

    def _on_card_leave(self, event=None):
        # Only reset if the mouse actually left the card entirely
        try:
            mx = self.winfo_pointerx() - self.winfo_rootx()
            my = self.winfo_pointery() - self.winfo_rooty()
            if 0 <= mx <= self.winfo_width() and 0 <= my <= self.winfo_height():
                return
        except Exception:
            pass
        self._hover_active = False
        self.highlight_color = self._original_highlight
        self._on_resize()

    def _sync_size(self, event=None):
        """Grow canvas to fit content perfectly. Executed synchronously to avoid macOS event loop sleeping bugs."""
        t = self.highlight_thickness
        req_w = self.content.winfo_reqwidth() + 2 * t
        req_h = self.content.winfo_reqheight() + 2 * t
        kw = {}
        # Only grow — never shrink. Geometry manager handles stretching.
        if self._explicit_width == 0 and self.winfo_width() < req_w:
            kw["width"] = req_w
        if not self._expand_height and self._explicit_height == 0 and self.winfo_height() < req_h:
            kw["height"] = req_h
            
        if kw:
            self.config(**kw)

    def _on_resize(self, event=None):
        w = getattr(event, "width", self.winfo_width()) if event else self.winfo_width()
        h = getattr(event, "height", self.winfo_height()) if event else self.winfo_height()
        if w < 10 or h < 10:
            return
        for i in self._bg_items:
            self.delete(i)
        self._bg_items = self._rounded_rect(
            self.highlight_thickness, self.highlight_thickness,
            w - self.highlight_thickness - 1, h - self.highlight_thickness - 1,
            self.radius, fill=self.bg_color, outline=self.highlight_color, width=self.highlight_thickness
        )
        for i in self._bg_items:
            self.tag_lower(i)
        t = self.highlight_thickness
        item_kw = {"width": max(1, w - 2 * t)}
        if self._expand_height:
            item_kw["height"] = max(1, h - 2 * t)
        self.itemconfig(self.content_id, **item_kw)
        
    def _rounded_rect(self, x1, y1, x2, y2, r, fill, outline, width):
        ids = []
        if r > 0:
            ids.append(self.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, fill=fill, outline=outline, width=width))
            ids.append(self.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, fill=fill, outline=outline, width=width))
            ids.append(self.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, fill=fill, outline=outline, width=width))
            ids.append(self.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, fill=fill, outline=outline, width=width))
            
            if width > 0:
                ids.append(self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill))
                ids.append(self.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill))
                
                # Draw the actual straight borders
                ids.append(self.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=width))
                ids.append(self.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=width))
                ids.append(self.create_line(x1, y1 + r, x1, y2 - r, fill=outline, width=width))
                ids.append(self.create_line(x2, y1 + r, x2, y2 - r, fill=outline, width=width))
            else:
                ids.append(self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=""))
                ids.append(self.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=""))
        else:
            ids.append(self.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=width))
        return ids

class ModernSegmentedControl(tk.Frame):
    """
    A segmented control (button group) for mutually exclusive options.
    Replaces radio buttons with a modern pill-like horizontal layout.
    """
    def __init__(self, parent, options, variable=None, command=None, 
                 bg=ModernStyle.BG_SECONDARY, 
                 fg=ModernStyle.TEXT_SECONDARY,
                 active_bg=ModernStyle.ACCENT_PRIMARY,
                 active_fg=ModernStyle.TEXT_ON_ACCENT,
                 font=ModernStyle.FONT_BODY,
                 container_bg=ModernStyle.BG_PRIMARY,
                 height=32, **kwargs):
        super().__init__(parent, bg=container_bg, **kwargs)
        
        self.options = options
        self.variable = variable if variable else tk.StringVar(value=options[0])
        self.command = command
        
        self._bg = bg
        self._fg = fg
        self._active_bg = active_bg
        self._active_fg = active_fg
        
        self._buttons = {}
        
        # Inner frame to hold buttons
        self.inner = tk.Frame(self, bg=container_bg)
        self.inner.pack(fill=tk.BOTH, expand=True)
        
        for i, opt in enumerate(options):
            # Create a frame for each button
            btn_frame = tk.Frame(self.inner, bg=bg, height=height)
            # Apply padding on the right, except for the last item
            pad_right = 4 if i < len(options) - 1 else 0
            btn_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, pad_right))
            
            # The actual clickable label
            lbl = tk.Label(
                btn_frame, text=opt, font=font, 
                bg=bg, fg=fg, cursor="hand2", padx=16
            )
            lbl.pack(fill=tk.BOTH, expand=True)
            
            # Bindings
            lbl.bind("<Button-1>", lambda e, v=opt: self._select(v))
            
            self._buttons[opt] = (btn_frame, lbl)
            
        # Initial state setup
        if self.variable:
            self.variable.trace_add("write", self._on_var_changed)
            self._update_ui()
            
    def _select(self, value):
        if self.variable:
            self.variable.set(value)
            
    def _on_var_changed(self, *args):
        self._update_ui()
        if self.command:
            self.command()
            
    def _update_ui(self):
        selected = self.variable.get()
        for opt, (frame, lbl) in self._buttons.items():
            if opt == selected:
                frame.config(bg=self._active_bg)
                lbl.config(bg=self._active_bg, fg=self._active_fg)
            else:
                frame.config(bg=self._bg)
                lbl.config(bg=self._bg, fg=self._fg)
