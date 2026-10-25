#!/usr/bin/env python3
"""Reusable UI widgets (kept separate to avoid circular imports)."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional
from pathlib import Path

from .ui_theme import ModernStyle


class ModernEntry(tk.Entry):
    """Custom entry with modern styling, placeholder support, and a subtle border."""

    def __init__(self, parent, placeholder="", numeric_only=False, currency_format=False, **kwargs):
        # Default text color (blue) for input, muted for placeholder
        fg = kwargs.pop("fg", ModernStyle.TEXT_ACCENT)
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
        
        self.config(fg=self.normal_color)

        # The placeholder is a grey label drawn inside the entry, NOT text in the
        # entry: inserted text also landed in the textvariable, so a hint such as
        # "SYMBOL *" could be saved as if the user had typed it.
        self._ph_label = None
        if placeholder:
            self._ph_label = tk.Label(self, text=placeholder, fg=self.default_color,
                                      bg=self.bg_color, font=self.cget("font"), anchor="w", padx=2)
            self._ph_label.bind("<Button-1>", lambda e: self.focus_set())
            tv = kwargs.get("textvariable")
            if tv is not None:
                try:
                    tv.trace_add("write", lambda *a: self._update_placeholder())
                except Exception:
                    pass
            self.bind('<KeyRelease>', lambda e: self._update_placeholder(), add="+")
            self.after_idle(self._update_placeholder)

        self.bind('<FocusIn>', self._on_focus_in, add="+")
        self.bind('<FocusOut>', self._on_focus_out, add="+")

    def _update_placeholder(self) -> None:
        if self._ph_label is None:
            return
        try:
            show = not self.get() and self.focus_get() is not self
        except (tk.TclError, KeyError):
            show = not self.get()
        if show and not self._ph_label.winfo_ismapped():
            self._ph_label.place(x=2, rely=0.5, anchor="w")
        elif not show and self._ph_label.winfo_ismapped():
            self._ph_label.place_forget()
        
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
        # 1. Hide the placeholder / remove formatting for editing
        if self._ph_label is not None:
            self._ph_label.place_forget()
        val = self.get()
        if self.currency_format and val:
            # Strip formatting to edit
            self.delete(0, tk.END)
            self.insert(0, val.replace(',', ''))
            
        self.config(fg=self.normal_color)
        self._check_clear_btn()
        
        # 2. Smooth border fading via ui_utils
        try:
            from .ui_utils import fade_color_transition
            fade_color_transition(self, self.highlight_bg_color, self.highlight_color, attr='highlightcolor', duration_ms=100)
        except Exception:
            pass
    
    def _on_focus_out(self, event=None):
        val = self.get().strip()
        if not val:
            self._update_placeholder()
        elif self.currency_format:
            try:
                # Add thousands separators
                fval = float(val)
                self.delete(0, tk.END)
                self.insert(0, f"{fval:,.2f}")
            except Exception:
                pass
        self._check_clear_btn()
    
    def get_value(self):
        """Get entry value, without thousands separators when currency-formatted."""
        val = self.get()
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
            font=ModernStyle.FONT_SMALL, cursor="hand2",
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
        variant: str = "solid",
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

        # Secondary actions can be "soft": a pale tint of their colour with darker
        # coloured text, so each page has one solid main button.
        soft_hover = None
        if variant == "soft":
            accent = bg
            bg = self._blend(accent, canvas_bg, 0.13)
            soft_hover = self._blend(accent, canvas_bg, 0.24)
            fg = self._blend("#000000", accent, 0.22)   # a shade darker: readable on the tint

        self._bg_normal = bg
        self._bg_hover = soft_hover or self._lighten_color(bg, 18)
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

    def destroy(self) -> None:
        try:
            if self._press_invoke_after_id:
                self.after_cancel(self._press_invoke_after_id)
            if self._reset_after_id:
                self.after_cancel(self._reset_after_id)
            if self._hover_suppress_id:
                self.after_cancel(self._hover_suppress_id)
            self._cancel_fade()
        except Exception:
            pass
        super().destroy()

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
        self._cancel_fade()
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

    def set_font(self, font) -> None:
        self._font = font
        if "text" in self._canvas_ids:
            self.itemconfig(self._canvas_ids["text"], font=self._font)

    def set_canvas_bg(self, color: str) -> None:
        self._canvas_bg = color
        self.config(bg=color)
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
        # Rebuild the shape at the new size (recolouring alone left clipped,
        # square corners on the collapsed sidebar buttons)
        self._canvas_ids = {}
        self._redraw(self._bg_normal)

    def _bind_events(self) -> None:
        # Bound once, with add="+" so other bindings on the button (tooltips) survive.
        # While disabled, the handlers simply ignore the events. (Re-binding without
        # add="+" on every enable used to wipe the sidebar tooltips on each page switch.)
        if getattr(self, "_events_bound", False):
            return
        self._events_bound = True
        self.bind("<Enter>", self._on_hover, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<Button-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")

    def _unbind_events(self) -> None:
        """Called when the button is disabled: stop anything still pending."""
        self._is_pressed = False
        self._cancel_fade()

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
            # A plain grey button with readable grey text (a faded colour fill
            # with tertiary text was unreadable)
            fill = ModernStyle.BG_TERTIARY
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
            self.itemconfig(self._canvas_ids["text"], fill=text_fill, text=self._text)

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
        if self._disabled:
            return
        if not self._is_pressed:
            self._fade_to_color(self._bg_normal)

    def _on_press(self, event=None):
        if self._disabled:
            return
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
        if self._disabled:
            self._is_pressed = False
            return
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
        # Only a release over the button counts as a click (drag away to cancel)
        inside = True
        if event is not None:
            inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        if was_pressed and inside and self._command and not self._click_invoked:
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
        """Hover colour: lighter, or a little darker for near-white buttons
        (lightening white changes nothing, so their hover was invisible)."""
        try:
            c = color.lstrip("#")
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            if min(r, g, b) > 230:
                d = max(8, amount // 2)
                return f"#{max(0, r - d):02x}{max(0, g - d):02x}{max(0, b - d):02x}"
            return f"#{min(255, r + amount):02x}{min(255, g + amount):02x}{min(255, b + amount):02x}"
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
        """Alpha blend fg over bg (both #RRGGBB). A named colour (e.g. a macOS
        system colour inherited from the parent) can't be blended: return bg."""
        alpha = max(0.0, min(1.0, float(alpha)))
        f = str(fg_hex).lstrip("#")
        b = str(bg_hex).lstrip("#")
        try:
            fr, fg, fb = int(f[0:2], 16), int(f[2:4], 16), int(f[4:6], 16)
            br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
        except ValueError:
            return bg_hex if len(b) == 6 else fg_hex
        r = int((fr * alpha) + (br * (1 - alpha)))
        g = int((fg * alpha) + (bg * (1 - alpha)))
        bl = int((fb * alpha) + (bb * (1 - alpha)))
        return f"#{r:02x}{g:02x}{bl:02x}"


class GradientHeader(tk.Canvas):
    """A reusable banner with the theme's indigo-to-pink gradient background.
    Supports a title, subtitle, and an optional right-aligned widget container.
    """
    _BANDS = 64  # colour bands; smooth enough, and far fewer items than 1 per 4 px

    def __init__(self, parent, title: str, subtitle: str, height: int = 75, right_widget_func=None, **kwargs):
        super().__init__(parent, bg=ModernStyle.BG_PRIMARY, highlightthickness=0, height=height, **kwargs)
        self.height = height

        self.grad_start = ModernStyle.HEADER_GRAD_START
        self.grad_end = ModernStyle.HEADER_GRAD_END

        self.right_frame = None
        self._drawn_size = None
        self._sync_after_id = None

        # Draw Title & Subtitle directly on the canvas for true 100% transparent background
        self.title_id = self.create_text(
            20, max(22, int(height * 0.3)),
            text=title,
            fill=ModernStyle.HEADER_FG,
            font=ModernStyle.FONT_PAGE_TITLE if height >= 75 else ModernStyle.FONT_SECTION_LABEL,
            anchor="w",
            tags="header_content"
        )
        if subtitle:
            self.subtitle_id = self.create_text(
                20, max(48, int(height * 0.68)),
                text=subtitle,
                fill=ModernStyle.HEADER_SUBTLE_FG,
                font=ModernStyle.FONT_BODY if height >= 75 else ModernStyle.FONT_SMALL,
                anchor="w",
                tags="header_content"
            )

        self.bind("<Configure>", self._draw_header_gradient)

        if right_widget_func:
            self.right_frame = tk.Frame(self, bg=self._color_at(1.0))
            right_widget_func(self.right_frame)
            self.create_window(
                0, int(height / 2), window=self.right_frame, anchor="e", tags=("header_content", "right_hdr")
            )

    def set_title(self, text: str):
        self.itemconfig(self.title_id, text=text)

    def set_subtitle(self, text: str):
        if hasattr(self, 'subtitle_id'):
            self.itemconfig(self.subtitle_id, text=text)

    def _color_at(self, t: float) -> str:
        """Gradient colour at position t (0 = left edge, 1 = right edge)."""
        t = max(0.0, min(1.0, t))
        mid = getattr(ModernStyle, "HEADER_GRAD_MID", None)
        if mid:  # three stops: indigo → violet → pink, like the Dashboard
            a_, b2, t = (self.grad_start, mid, t * 2) if t < 0.5 else (mid, self.grad_end, t * 2 - 1)
        else:
            a_, b2 = self.grad_start, self.grad_end
        r, g, b = (int(a + (b_ - a) * t) for a, b_ in zip(a_, b2))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _draw_header_gradient(self, event=None):
        w = event.width if event else self.winfo_width()
        h = event.height if event else self.winfo_height()
        if w < 10 or (w, h) == self._drawn_size:
            return  # Tk sends many <Configure> events with the same size
        self._drawn_size = (w, h)

        self.delete("gradient")
        steps = self._BANDS
        for i in range(steps):
            x0 = int(i * w / steps)
            x1 = int((i + 1) * w / steps) + 1
            self.create_rectangle(x0, 0, x1, h, fill=self._color_at(i / (steps - 1)),
                                  outline="", tags="gradient")
        # Rounded corners: paint the page colour outside a 14 px quarter circle
        import math
        r = 14
        for ox, oy, sx, sy in ((0, 0, 1, 1), (w, 0, -1, 1), (0, h, 1, -1), (w, h, -1, -1)):
            pts = [(ox, oy)] + [(ox + sx * (r - r * math.cos(math.radians(d))),
                                 oy + sy * (r - r * math.sin(math.radians(d)))) for d in range(0, 91, 10)]
            self.create_polygon(*pts, fill=str(self.cget("bg")), outline="", tags="gradient")

        if self.right_frame:
            # Re-position right frame to right edge, then match its widgets' backgrounds
            # to the gradient once the layout has settled (only the last resize counts).
            self.coords("right_hdr", w - 20, int(h / 2))
            if self._sync_after_id:
                self.after_cancel(self._sync_after_id)
            self._sync_after_id = self.after(60, lambda: self._sync_right_bg(w))

        self.tag_raise("header_content")

    def _sync_right_bg(self, w: int) -> None:
        self._sync_after_id = None

        def _sync(widget):
            try:
                if getattr(widget, '_ignore_sync_bg', False):
                    return
                # Exact gradient colour at the widget's horizontal centre
                w_x = widget.winfo_rootx() - self.winfo_rootx() + (widget.winfo_width() / 2)
                t = (w - 70) / max(1, w) if (w_x < 0 or widget.winfo_width() <= 1) else w_x / max(1, w)
                local_color = self._color_at(t)

                if hasattr(widget, 'sync_gradient_bg'):
                    widget.sync_gradient_bg(local_color)
                elif widget.__class__.__name__ == 'ModernButton':
                    if hasattr(widget, 'set_canvas_bg'):
                        widget.set_canvas_bg(local_color)
                elif widget.__class__.__name__ not in ['ttk.Combobox', 'ModernDropdown']:
                    if widget.cget("bg") != local_color:
                        widget.config(bg=local_color)
            except tk.TclError:
                pass

            if not hasattr(widget, 'sync_gradient_bg'):
                for child in widget.winfo_children():
                    _sync(child)

        if self.right_frame is not None and self.right_frame.winfo_exists():
            _sync(self.right_frame)


class PremiumModal(tk.Toplevel):
    """
    A unified base class for all popup modals.
    Provides standard window styling, centering, and a clean light/modern aesthetic.
    """
    def __init__(self, parent, title: str, geometry: str = "500x520", icon: str = "✨", right_widget_func=None):
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
            from .ui_utils import center_window
            center_window(self, parent=parent.winfo_toplevel())
        except Exception:
            pass
            
        # ── Unified Gradient Header ──
        self.header = GradientHeader(self, title=f"{icon}  {title}" if icon else title, subtitle="", height=55, right_widget_func=right_widget_func)
        self.header.pack(fill="x")
        
        # Area for child classes to put chips/badges. We'll use a frame right under the header
        self.chips_row = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        self.chips_row.pack(fill="x", padx=20, pady=(10, 0))
        self.inner_hdr = self.chips_row  # Alias for backward compatibility if anyone attached to inner_hdr

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


class ModernCard(tk.Canvas):
    """A card layout with actual rounded corners."""
    def __init__(self, parent, width=0, height=0, radius=12, bg=ModernStyle.BG_SECONDARY,
                 highlight_color=ModernStyle.BORDER_COLOR, highlight_thickness=1,
                 canvas_bg=ModernStyle.BG_PRIMARY, expand_height=False, shadow=False, **kwargs):
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
        # Inset the content a little more than the border so its square corners
        # sit inside the rounded shape (otherwise the corners and border look square).
        self._inset = max(self.highlight_thickness, int(radius * 0.3) + self.highlight_thickness)
        self.content_id = self.create_window(self._inset, self._inset, window=self.content, anchor="nw")
        self._bg_items = []
        self._shadow = 3 if shadow else 0   # px of soft shadow under the card
        self._shadow_items = []
        self._arc_items = []      # rounded corners: fill + outline
        self._fill_items = []     # straight fill rectangles
        self._edge_items = []     # straight border lines
        self._drawn_size = None
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
        if self._hover_active or self._shadow:   # shadowed cards stay calm on hover
            return
        self._hover_active = True
        self._set_border(ModernStyle.ACCENT_PRIMARY)

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
        self._set_border(self._original_highlight)

    def _set_border(self, color: str) -> None:
        """Recolour the border in place (re-creating the shapes made hover slow)."""
        self.highlight_color = color
        for i in self._arc_items:
            self.itemconfig(i, outline=color)
        for i in self._edge_items:
            self.itemconfig(i, fill=color)
        if self.radius <= 0:
            for i in self._bg_items:
                self.itemconfig(i, outline=color)

    def set_fill(self, color: str) -> None:
        """Change the card's background colour (e.g. a KPI tint) without rebuilding it.

        Only the card shape and its content frame change; widgets inside the
        content frame keep their own backgrounds, so set those too.
        """
        if color == self.bg_color:
            return
        self.bg_color = color
        try:
            self.content.configure(bg=color)
        except tk.TclError:
            pass
        for i in self._arc_items:
            self.itemconfig(i, fill=color)
        for i in self._fill_items:
            self.itemconfig(i, fill=color)
            if self.highlight_thickness > 0:
                self.itemconfig(i, outline=color)
        if self.radius <= 0:
            for i in self._bg_items:
                self.itemconfig(i, fill=color)

    def _sync_size(self, event=None):
        """Grow canvas to fit content perfectly. Executed synchronously to avoid macOS event loop sleeping bugs."""
        t = self.highlight_thickness
        t = self._inset
        req_w = self.content.winfo_reqwidth() + 2 * t
        req_h = self.content.winfo_reqheight() + 2 * t + self._shadow
        kw = {}
        # Only grow — never shrink. Geometry manager handles stretching.
        if self._explicit_width == 0 and self.winfo_width() < req_w:
            kw["width"] = req_w
        if self._explicit_height == 0 and self.winfo_height() < req_h:
            kw["height"] = req_h
            
        if kw:
            self.config(**kw)

    def _on_resize(self, event=None):
        w = getattr(event, "width", self.winfo_width()) if event else self.winfo_width()
        h = getattr(event, "height", self.winfo_height()) if event else self.winfo_height()
        if w < 10 or h < 10 or (w, h) == self._drawn_size:
            return  # Tk sends many <Configure> events with an unchanged size
        self._drawn_size = (w, h)
        for i in self._bg_items + self._shadow_items:
            self.delete(i)
        self._arc_items, self._fill_items, self._edge_items = [], [], []
        sh = self._shadow
        self._shadow_items = []
        if sh:
            t0 = self.highlight_thickness
            col = ModernButton._blend("#000000", str(self.cget("bg")), 0.45 if ModernStyle.IS_DARK else 0.09)
            self._shadow_items = self._rounded_rect(t0 + 1, t0 + sh, w - t0 - 1, h - t0 - 1,
                                                    self.radius, fill=col, outline=col, width=0)
            self._arc_items, self._fill_items, self._edge_items = [], [], []
        self._bg_items = self._rounded_rect(
            self.highlight_thickness, self.highlight_thickness,
            w - self.highlight_thickness - 1, h - self.highlight_thickness - 1 - sh,
            self.radius, fill=self.bg_color, outline=self.highlight_color, width=self.highlight_thickness
        )
        for i in self._bg_items:
            self.tag_lower(i)
        for i in self._shadow_items:
            self.tag_lower(i)
        t = self.highlight_thickness
        t = self._inset
        item_kw = {"width": max(1, w - 2 * t)}
        if self._expand_height:
            item_kw["height"] = max(1, h - 2 * t - sh)
        self.itemconfig(self.content_id, **item_kw)
        
    def _rounded_rect(self, x1, y1, x2, y2, r, fill, outline, width):
        ids = []
        if r > 0:
            arcs = [
                self.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, fill=fill, outline=outline, width=width),
                self.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, fill=fill, outline=outline, width=width),
                self.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, fill=fill, outline=outline, width=width),
                self.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, fill=fill, outline=outline, width=width),
            ]
            self._arc_items.extend(arcs)
            ids.extend(arcs)

            if width > 0:
                rects = [
                    self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill),
                    self.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill),
                ]
                # Draw the actual straight borders
                edges = [
                    self.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=width),
                    self.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=width),
                    self.create_line(x1, y1 + r, x1, y2 - r, fill=outline, width=width),
                    self.create_line(x2, y1 + r, x2, y2 - r, fill=outline, width=width),
                ]
                self._edge_items.extend(edges)
            else:
                rects = [
                    self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=""),
                    self.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=""),
                ]
                edges = []
            self._fill_items.extend(rects)
            ids.extend(rects + edges)
        else:
            ids.append(self.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=width))
        return ids


class PopupDatePicker(tk.Toplevel):
    """A custom Date Picker widget that opens exactly where the user clicks."""
    
    def __init__(self, master, target_var: tk.StringVar, on_select=None, **kwargs):
        super().__init__(master, **kwargs)
        self.withdraw()
        self.transient(master)
        
        # Try to make it look like a popup without OS chrome
        import sys
        try:
            if sys.platform == "win32":
                self.overrideredirect(True)
            elif sys.platform == "darwin":
                # Tk 9 ignores "-type dropdown" on macOS (it opened as a normal titled
                # window); a "plain" window has no title bar but still gets clicks and keys.
                try:
                    self.tk.call("::tk::unsupported::MacWindowStyle", "style", self._w, "plain", "none")
                except tk.TclError:
                    self.wm_attributes("-type", "dropdown")
            else:
                self.wm_attributes("-type", "popup_menu")
        except Exception:
            pass

        self.config(bg=ModernStyle.BG_PRIMARY, highlightthickness=1, highlightbackground=ModernStyle.ACCENT_PRIMARY, padx=0, pady=0)
        
        self.target_var = target_var
        self.on_select = on_select
        
        import calendar as _cal
        from datetime import datetime as _DT
        self._cal = _cal
        self._datetime = _DT
        
        # Initialize current date from target_var
        current_val = target_var.get().strip()
        try:
            self.current_date = self._datetime.strptime(current_val, "%Y-%m-%d")
        except Exception:
            self.current_date = self._datetime.now()
            
        self.view_year = self.current_date.year
        self.view_month = self.current_date.month
        
        self._navigating = False  # Guard flag to prevent dismissal during navigation
        
        self._build_ui()
        self._position_popup()
        self.deiconify()
        
        # If a parent dialog holds a grab (modal), steal it so the popup
        # can receive events, and restore it when the popup is destroyed.
        self._prev_grab = None
        try:
            current_grab = self.grab_current()
            if current_grab is not None and current_grab != self:
                self._prev_grab = current_grab
                current_grab.grab_release()
                self.grab_set()
            else:
                self.grab_set()
        except tk.TclError:
            pass
        
        self.focus_set()
        
        # Allow pressing Escape to close
        self.bind("<Escape>", lambda e: self.destroy())
        
        # Close on outside click — only bind on the main window, NOT on self,
        # to avoid dismissing the popup when clicking its own nav buttons.
        self._main_window = self.master.winfo_toplevel()
        self._main_window_bind_id = self._main_window.bind("<Button-1>", self._check_click_outside, add="+")
        
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, event):
        if event.widget == self:
            if hasattr(self, "_main_window") and self._main_window and hasattr(self, "_main_window_bind_id"):
                try:
                    self._main_window.unbind("<Button-1>", self._main_window_bind_id)
                    self._main_window = None
                except Exception:
                    pass
            # Restore the grab to the previous modal dialog
            if hasattr(self, "_prev_grab") and self._prev_grab is not None:
                try:
                    if self._prev_grab.winfo_exists():
                        self._prev_grab.grab_set()
                except Exception:
                    pass
                self._prev_grab = None

    def _check_click_outside(self, event):
        if self._navigating:
            return
        try:
            x, y = self.winfo_rootx(), self.winfo_rooty()
            w, h = self.winfo_width(), self.winfo_height()
        except tk.TclError:
            return  # Widget already destroyed
        if not (x <= event.x_root <= x + w and y <= event.y_root <= y + h):
            self.destroy()

    def _on_focus_out(self, event):
        # Only destroy if the focus out is for the main popup window itself, 
        # and focus is not moving to one of its children.
        # Use after_idle to let focus settle after widget rebuilds.
        if event.widget == self:
            self.after_idle(self._deferred_focus_check)  

    def _deferred_focus_check(self):
        """Check focus after the event loop has settled."""
        if self._navigating:
            return
        try:
            if not self.winfo_exists():
                return
            focus_widget = self.focus_get()
            if focus_widget and (focus_widget == self or str(focus_widget).startswith(str(self))):
                return
        except Exception:
            pass
        self.destroy()
        
    def _position_popup(self):
        self.update_idletasks()
        
        # Track mouse coordinates
        px = self.winfo_pointerx()
        py = self.winfo_pointery()
        
        # Get dimensions
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        
        # Get screen dimensions
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        
        # Edge detection
        x = px
        y = py
        
        if x + w > sw:
            x = sw - w
        if y + h > sh:
            y = sh - h
            
        # Ensure it doesn't go off the top/left edge
        x = max(0, x)
        y = max(0, y)
            
        self.geometry(f"+{x}+{y}")
        
    def _build_ui(self):
        # Header & Navigation
        header_frame = tk.Frame(self, bg=ModernStyle.ACCENT_PRIMARY)
        header_frame.pack(fill=tk.X, pady=(0, 4), ipadx=4, ipady=4)
        
        # Helper for custom label-buttons (macOS safe)
        def make_nav_btn(parent, text, cmd, side):
            lbl = tk.Label(
                parent, text=text, font=ModernStyle.FONT_BODY_BOLD,
                bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT,
                cursor="hand2", padx=4, pady=2
            )
            def _on_click(e, _cmd=cmd):
                _cmd()
                return "break"  # Prevent event propagation
            lbl.bind("<Button-1>", _on_click)
            lbl.bind("<Enter>", lambda e: lbl.config(bg=ModernStyle.ACCENT_PRIMARY_PALE, fg=ModernStyle.ACCENT_PRIMARY))
            lbl.bind("<Leave>", lambda e: lbl.config(bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT))
            lbl.pack(side=side, padx=1)
            return lbl
        
        make_nav_btn(header_frame, "«", self._prev_year, tk.LEFT)
        make_nav_btn(header_frame, "‹", self._prev_month, tk.LEFT)
        
        self.lbl_month = tk.Label(header_frame, bg=ModernStyle.ACCENT_PRIMARY, fg=ModernStyle.TEXT_ON_ACCENT, font=ModernStyle.FONT_SMALL_BOLD)
        self.lbl_month.pack(side=tk.LEFT, expand=True)
        
        make_nav_btn(header_frame, "›", self._next_month, tk.RIGHT)
        make_nav_btn(header_frame, "»", self._next_year, tk.RIGHT)
        
        # Weekday Labels
        days_frame = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        days_frame.pack(fill=tk.X, padx=6)
        
        for i, d in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            is_weekend = i >= 5
            lbl = tk.Label(
                days_frame, text=d, bg=ModernStyle.BG_PRIMARY, 
                fg=ModernStyle.ACCENT_TERTIARY if is_weekend else ModernStyle.TEXT_SECONDARY, 
                font=ModernStyle.FONT_TINY_BOLD if is_weekend else ModernStyle.FONT_TINY,
                width=3
            )
            lbl.grid(row=0, column=i, pady=(2, 2))
            days_frame.columnconfigure(i, weight=1)
            
        # Dynamic Calendar Grid
        self.grid_frame = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        self.grid_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        
        self._build_grid()
        
    def _prev_year(self):
        self._navigating = True
        self.view_year -= 1
        self._build_grid()
        self.after_idle(self._clear_navigating)
        
    def _next_year(self):
        self._navigating = True
        self.view_year += 1
        self._build_grid()
        self.after_idle(self._clear_navigating)
        
    def _prev_month(self):
        self._navigating = True
        if self.view_month == 1:
            self.view_month = 12
            self.view_year -= 1
        else:
            self.view_month -= 1
        self._build_grid()
        self.after_idle(self._clear_navigating)
        
    def _next_month(self):
        self._navigating = True
        if self.view_month == 12:
            self.view_month = 1
            self.view_year += 1
        else:
            self.view_month += 1
        self._build_grid()
        self.after_idle(self._clear_navigating)
    
    def _clear_navigating(self):
        """Reset the navigation guard and reclaim focus after grid rebuild."""
        try:
            if self.winfo_exists():
                self.focus_set()
                self._navigating = False
        except tk.TclError:
            pass
        
    def _build_grid(self):
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
            
        dt = self._datetime(self.view_year, self.view_month, 1)
        self.lbl_month.config(text=dt.strftime("%B %Y"))
        
        weeks = self._cal.monthcalendar(self.view_year, self.view_month)
        for r, week in enumerate(weeks):
            self.grid_frame.rowconfigure(r, weight=1)
            for c, day in enumerate(week):
                self.grid_frame.columnconfigure(c, weight=1)
                if day > 0:
                    is_selected = (
                        day == self.current_date.day and 
                        self.view_month == self.current_date.month and 
                        self.view_year == self.current_date.year
                    )
                    
                    is_today = (
                        day == self._datetime.now().day and 
                        self.view_month == self._datetime.now().month and 
                        self.view_year == self._datetime.now().year
                    )
                    
                    is_weekend = c >= 5
                    
                    if is_selected:
                        bg = ModernStyle.ACCENT_PRIMARY
                        fg = ModernStyle.TEXT_ON_ACCENT
                        hover_bg = ModernStyle.ACCENT_PRIMARY
                    elif is_today:
                        bg = ModernStyle.ACCENT_PRIMARY_PALE
                        fg = ModernStyle.TEXT_ACCENT
                        hover_bg = ModernStyle.ACCENT_PRIMARY
                    else:
                        bg = ModernStyle.BG_PRIMARY
                        fg = ModernStyle.WARNING if is_weekend else ModernStyle.TEXT_PRIMARY
                        hover_bg = ModernStyle.BG_SECONDARY
                        
                    btn = tk.Label(
                        self.grid_frame, text=str(day), 
                        font=ModernStyle.FONT_SMALL_BOLD if is_today or is_selected else ModernStyle.FONT_TINY,
                        bg=bg, fg=fg, cursor="hand2"
                    )
                    btn.bind("<Button-1>", lambda e, d=day: self._select_day(d))
                    # Square button via uniform padding, slightly smaller
                    btn.grid(row=r, column=c, padx=0, pady=0, sticky="nsew", ipadx=0, ipady=1)
                    
                    # Hover effects for unselected days
                    if not is_selected and not is_today:
                        _bg, _hbg = bg, hover_bg
                        btn.bind("<Enter>", lambda e, b=btn, hb=_hbg: b.config(bg=hb))
                        btn.bind("<Leave>", lambda e, b=btn, ob=_bg: b.config(bg=ob))
                    elif is_today and not is_selected:
                        # accent hover for today
                        _bg, _hbg = bg, hover_bg
                        btn.bind("<Enter>", lambda e, b=btn, hb=_hbg: b.config(bg=hb, fg=ModernStyle.TEXT_ON_ACCENT))
                        btn.bind("<Leave>", lambda e, b=btn, ob=_bg, of=fg: b.config(bg=ob, fg=of))
                else:
                    # Empty space for days outside the month
                    spacer = tk.Frame(self.grid_frame, bg=ModernStyle.BG_PRIMARY)
                    spacer.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
                    
    def _select_day(self, day):
        # Format the selected date
        val = f"{self.view_year:04d}-{self.view_month:02d}-{day:02d}"
        
        # Update the injected tk.StringVar
        self.target_var.set(val)
        
        # Optionally trigger an on_select callback
        if self.on_select:
            self.on_select()
            
        # Destroy the CTkToplevel (tk.Toplevel) window
        self.destroy()
