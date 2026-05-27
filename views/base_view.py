import tkinter as tk
from tkinter import ttk
from abc import ABC, abstractmethod
import sys
from datetime import datetime

from ui_theme import ModernStyle

from ui_widgets import ModernButton
from ui_utils import center_window

def _create_date_input(parent: tk.Misc, text_var: tk.StringVar) -> tk.Widget:
    try:
        from tkcalendar import DateEntry
        from datetime import datetime

        # Guarantee a valid initial date before creating the widget
        current = text_var.get().strip()
        try:
            init_dt = datetime.strptime(current, "%Y-%m-%d")
        except Exception:
            init_dt = datetime.now()
            text_var.set(init_dt.strftime("%Y-%m-%d"))

        w = DateEntry(
            parent,
            textvariable=text_var,
            date_pattern="yyyy-mm-dd",
            width=12,
            state="normal",
            font=ModernStyle.FONT_BODY,
            foreground="white",
            background="#009668",
            borderwidth=2,
            relief=tk.SOLID,
            # Calendar popup colours
            headersforeground="#4D88EC",
            headersbackground="#DBEAFE",
            selectforeground="white",
            selectbackground="#FF6B6B",
            normalforeground="#000000",
            normalbackground="#F0F0F0",
            weekendforeground="#E5E5E5",
            weekendbackground="#FF0000",
            disabledbackground="#D3D3D3",
            disabledforeground="#A9A9A9",
            cursor="hand2",
        )
        try:
            w.set_date(init_dt)
        except Exception:
            pass
        
        def _on_selected(event=None):
            val = w.get()
            if val:  # guard against empty intermediate events
                text_var.set(val)

        w.bind("<<DateEntrySelected>>", _on_selected)

        return w

    except Exception as e:
        return tk.Entry(
            parent,
            textvariable=text_var,
            bg=ModernStyle.ENTRY_BG,
            fg=ModernStyle.TEXT_PRIMARY,
            font=ModernStyle.FONT_BODY,
            relief=tk.FLAT,
            width=12,
        )

def _enable_canvas_mousewheel(canvas: tk.Canvas, *, include_widget: tk.Widget | None = None) -> None:
    def _wheel(event):
        try:
            if sys.platform == "darwin":
                # On macOS, delta is already small; invert sign for natural scroll.
                delta = int(-1 * event.delta)
                step = 1 if delta > 0 else -1
            else:
                # Windows typically reports 120 per notch.
                step = int(-1 * (event.delta / 120))
            if step:
                canvas.yview_scroll(step, "units")
        except Exception:
            return

    def _wheel_linux_up(_event):
        try:
            canvas.yview_scroll(-1, "units")
        except Exception:
            return

    def _wheel_linux_down(_event):
        try:
            canvas.yview_scroll(1, "units")
        except Exception:
            return

    def _bind_all(_e=None):
        try:
            canvas.bind_all("<MouseWheel>", _wheel)
            canvas.bind_all("<Button-4>", _wheel_linux_up)
            canvas.bind_all("<Button-5>", _wheel_linux_down)
        except Exception:
            pass

    def _unbind_all(_e=None):
        try:
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")
        except Exception:
            pass

    # Bind on both the canvas and its content container so entering any child
    # widget still activates scrolling.
    try:
        canvas.bind("<Enter>", _bind_all)
        canvas.bind("<Leave>", _unbind_all)
    except Exception:
        pass

    if include_widget is not None:
        try:
            include_widget.bind("<Enter>", _bind_all)
            include_widget.bind("<Leave>", _unbind_all)
        except Exception:
            pass


class BaseView(tk.Frame, ABC):
    """Abstract base class for all application views."""
    
    def __init__(self, parent, app_state=None, **kwargs):
        super().__init__(parent, bg=ModernStyle.BG_PRIMARY, **kwargs)
        self.app_state = app_state
        self._is_active = False
        self._data_loaded = False
        
        # Subclasses should override build() to create UI
        self.build()
    
    @abstractmethod
    def build(self):
        """Build the view UI. Override in subclasses."""
        pass
    
    def add_gradient_header(self, container, title: str, subtitle: str, right_widget_func=None, show_divider: bool = True):
        """Add a dynamic gradient header banner to the view.
        
        Args:
            container: The parent frame/canvas to pack the header into.
            title: The main title text.
            subtitle: The subtitle text.
            right_widget_func: A callable that takes a parent frame and returns a widget to place on the right.
        """
        header_canvas = tk.Canvas(
            container, bg=ModernStyle.BG_PRIMARY, highlightthickness=0, height=75
        )
        header_canvas.pack(fill="x", padx=20, pady=(6, 4))

        # Gradient colors: deep blue → teal
        grad_start = (30, 58, 138)   # #1E3A8A
        grad_end   = (13, 148, 136)  # #0D9488

        right_frame = None
        def _draw_header_gradient(event=None):
            w = event.width if event else header_canvas.winfo_width()
            h = event.height if event else header_canvas.winfo_height()
            if w < 10:
                return
            header_canvas.delete("gradient")
            steps = max(1, w // 4)  # ~1 rect per 4px for performance
            for i in range(steps):
                t = i / max(1, steps - 1)
                r = int(grad_start[0] + (grad_end[0] - grad_start[0]) * t)
                g = int(grad_start[1] + (grad_end[1] - grad_start[1]) * t)
                b = int(grad_start[2] + (grad_end[2] - grad_start[2]) * t)
                color = f"#{r:02x}{g:02x}{b:02x}"
                x0 = int(i * w / steps)
                x1 = int((i + 1) * w / steps) + 1
                header_canvas.create_rectangle(x0, 0, x1, h, fill=color, outline="", tags="gradient")
                
            if right_frame:
                t_right = max(0, min(1, (w - 70) / max(1, w)))
                r = int(grad_start[0] + (grad_end[0] - grad_start[0]) * t_right)
                g = int(grad_start[1] + (grad_end[1] - grad_start[1]) * t_right)
                b = int(grad_start[2] + (grad_end[2] - grad_start[2]) * t_right)
                right_color = f"#{r:02x}{g:02x}{b:02x}"
                try:
                    right_frame.config(bg=right_color)
                    for child in right_frame.winfo_children():
                        try:
                            child.config(bg=right_color)
                        except Exception:
                            pass
                except Exception:
                    pass

            header_canvas.tag_raise("header_content")

        header_canvas.bind("<Configure>", lambda e: None) # handled later

        # Title
        lbl_title = tk.Label(
            header_canvas,
            text=title,
            fg="#FFFFFF",
            bg="#1E3A8A",
            font=ModernStyle.FONT_PAGE_TITLE,
        )
        header_canvas.create_window(
            20, 20, window=lbl_title, anchor="w", tags="header_content"
        )

        # Subtitle
        lbl_subtitle = tk.Label(
            header_canvas,
            text=subtitle,
            fg="#94A3B8",
            bg="#1E3A8A",
            font=ModernStyle.FONT_BODY,
        )
        header_canvas.create_window(
            20, 45, window=lbl_subtitle, anchor="w", tags="header_content"
        )

        if right_widget_func:
            right_frame = tk.Frame(header_canvas, bg="#0D9488")
            right_widget_func(right_frame)
            header_canvas.create_window(
                0, 37, window=right_frame, anchor="e", tags=("header_content", "right_hdr")
            )

        def _reposition_right(event=None):
            w = event.width if event else header_canvas.winfo_width()
            if w > 10 and right_frame:
                header_canvas.coords("right_hdr", w - 20, 37)
                
        header_canvas.bind("<Configure>", lambda e: (_draw_header_gradient(e), _reposition_right(e)), add="+")
        
        # Thin accent divider under header
        if show_divider:
            tk.Frame(container, bg=ModernStyle.BRAND_GOLD, height=2).pack(
                fill="x", padx=20, pady=(4, 0)
            )
        return header_canvas

    def show(self) -> None:
        """Called when view becomes visible. Override to refresh data."""
        self._is_active = True
        if not self._data_loaded:
            self.load_data()
    
    def on_show(self):
        """Called when view becomes visible. Override to refresh data."""
        self._is_active = True
        if not self._data_loaded:
            self.load_data()
    
    def on_hide(self):
        """Called when view becomes hidden."""
        self._is_active = False
    
    def load_data(self):
        """Load data for this view. Override in subclasses."""
        self._data_loaded = True
    
    def refresh(self):
        """Refresh view data."""
        self.load_data()


