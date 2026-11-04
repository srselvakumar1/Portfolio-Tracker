import tkinter as tk
from abc import ABC, abstractmethod
import sys

from ui.ui_theme import ModernStyle

def _create_date_input(parent: tk.Misc, text_var: tk.StringVar, ipady: int = 5) -> tk.Widget:
    """Date input: custom popup date picker widget (ipady sets the box height)."""
    from datetime import datetime as _DT
    from ui.ui_widgets import PopupDatePicker

    def _parse(text):
        """The date in any of the usual ways of writing it, or None."""
        for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %y"):
            try:
                return _DT.strptime(text.strip(), fmt)
            except ValueError:
                pass
        return None

    init_dt = _parse(text_var.get()) or _DT.now()
    text_var.set(init_dt.strftime("%Y-%m-%d"))

    # The box shows "27 Oct 2026"; text_var keeps YYYY-MM-DD for the rest of the app.
    shown_var = tk.StringVar(value=init_dt.strftime("%d %b %Y"))

    def _from_box(*_):
        dt = _parse(shown_var.get())
        value = dt.strftime("%Y-%m-%d") if dt else shown_var.get().strip()   # bad text → the form's own check
        if text_var.get() != value:
            text_var.set(value)

    def _to_box(*_):
        dt = _parse(text_var.get())
        if dt and _parse(shown_var.get()) != dt:   # leave half-typed text alone
            shown_var.set(dt.strftime("%d %b %Y"))

    shown_var.trace_add("write", _from_box)
    trace_id = text_var.trace_add("write", _to_box)

    from ui.ui_widgets import RoundedBox
    container = RoundedBox(parent)   # one rounded box holds the date and the 📅 button
    container.bind("<Destroy>", lambda e: e.widget is container and text_var.trace_remove("write", trace_id), add="+")

    # Text entry for the date
    entry = tk.Entry(
        container, textvariable=shown_var, width=11,
        font=ModernStyle.FONT_INPUT, bg=ModernStyle.ENTRY_BG,
        fg=ModernStyle.TEXT_PRIMARY, relief=tk.FLAT, bd=0, highlightthickness=0,
        insertbackground=ModernStyle.TEXT_ACCENT
    )
    entry.pack(side="left", fill="both", expand=True, ipady=ipady, padx=(8, 0))   # fills a stretched box
    container.watch(entry)

    def _tidy(_e=None):   # "5 jan 2024" → "05 Jan 2024" when leaving the box
        dt = _parse(shown_var.get())
        if dt:
            shown_var.set(dt.strftime("%d %b %Y"))
    entry.bind("<FocusOut>", _tidy, add="+")

    def _open_picker():
        top = parent.winfo_toplevel()
        PopupDatePicker(top, text_var)

    # Calendar icon (a Label: a Mac tk.Button ignores colours and showed a grey block)
    from ui import icons
    glyph = icons.glyph("calendar-days")
    btn = tk.Label(
        container, text=glyph or "📅", font=icons.font(18) if glyph else ModernStyle.FONT_BODY,
        bg=ModernStyle.ENTRY_BG, fg=ModernStyle.TEXT_ACCENT, bd=0, padx=10, cursor="hand2",
    )
    btn.bind("<Button-1>", lambda _e: _open_picker())
    btn.bind("<Enter>", lambda _e: btn.configure(fg=ModernStyle.ACCENT_PRIMARY))
    btn.bind("<Leave>", lambda _e: btn.configure(fg=ModernStyle.TEXT_ACCENT))
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
        self._page_header, self._page_subtitle = header, subtitle

        return header   # (no gold divider: the rounded banner stands on its own)

    def go_to(self, page: str) -> None:
        """Open another page (e.g. "trade_entry"), as the sidebar does."""
        app = getattr(self.winfo_toplevel(), "_ptracker_app", None)
        if app is not None:
            app.navigate_to(page)

    def set_header_summary(self, text: str) -> None:
        """A live one-line summary under the page title, e.g. "18 holdings · worth ₹12.3 L".
        Empty text brings the page's own subtitle back."""
        header = getattr(self, "_page_header", None)
        if header is not None:
            try:
                header.set_subtitle(text or self._page_subtitle)
            except tk.TclError:
                pass

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


