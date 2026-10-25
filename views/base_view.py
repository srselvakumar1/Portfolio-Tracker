import tkinter as tk
from abc import ABC, abstractmethod
import sys

from ui.ui_theme import ModernStyle

def _create_date_input(parent: tk.Misc, text_var: tk.StringVar) -> tk.Widget:
    """Date input: custom popup date picker widget."""
    from datetime import datetime as _DT
    from ui.ui_widgets import PopupDatePicker

    current = text_var.get().strip()
    try:
        init_dt = _DT.strptime(current, "%Y-%m-%d")
    except Exception:
        init_dt = _DT.now()
        text_var.set(init_dt.strftime("%Y-%m-%d"))

    from ui.ui_widgets import RoundedBox
    container = RoundedBox(parent)   # one rounded box holds the date and the 📅 button

    # Text entry for the date
    entry = tk.Entry(
        container, textvariable=text_var, width=11,
        font=ModernStyle.FONT_INPUT, bg=ModernStyle.ENTRY_BG,
        fg=ModernStyle.TEXT_PRIMARY, relief=tk.FLAT, bd=0, highlightthickness=0,
        insertbackground=ModernStyle.TEXT_ACCENT
    )
    entry.pack(side="left", fill="both", expand=True, ipady=5, padx=(8, 0))   # fills a stretched box
    container.watch(entry)
    
    def _open_picker():
        top = parent.winfo_toplevel()
        PopupDatePicker(top, text_var)

    # Calendar button
    btn = tk.Button(
        container, text="📅", font=ModernStyle.FONT_BODY,
        bg=ModernStyle.ENTRY_BG, fg=ModernStyle.TEXT_ACCENT,
        activebackground=ModernStyle.ENTRY_BG, highlightthickness=0,
        relief=tk.FLAT, bd=0, padx=6, pady=0,
        cursor="hand2", command=_open_picker
    )
    btn.pack(side="left", fill="y")

    return container



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
        """Add a dynamic gradient header banner to the view using GradientHeader.
        
        Args:
            container: The parent frame/canvas to pack the header into.
            title: The main title text.
            subtitle: The subtitle text.
            right_widget_func: A callable that takes a parent frame and returns a widget to place on the right.
        """
        import re
        from ui.ui_widgets import GradientHeader
        # No emoji in titles: the clean title reads better on the gradient
        title = re.sub(r"^[^\w(]+", "", title).strip() or title
        header = GradientHeader(container, title=title, subtitle=subtitle, right_widget_func=right_widget_func)
        header.pack(fill="x", padx=20, pady=(6, 4))
        
        return header   # (no gold divider: the rounded banner stands on its own)

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


