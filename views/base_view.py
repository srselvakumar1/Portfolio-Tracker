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


