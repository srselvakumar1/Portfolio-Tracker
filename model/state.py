import tkinter as tk
from typing import Any, Dict

from model.data_cache import DataCache

class AppState:
    """Central state manager for PTracker application."""

    def __init__(self, root: tk.Tk):
        self.root: tk.Tk = root

        # View State Storage (prevents data loss when switching tabs)
        self.trade_history_state: Dict[str, Any] = {}

        # Lightweight caches (to keep sidebar navigation snappy)
        # - Broker list is used by Settings + Trade Entry and can be reused to
        #   avoid repeated SQLite reads on each view mount.
        self.brokers_cache: list[str] | None = None
        self.brokers_cache_version: int = 0

        # In-memory dataset cache (holdings/trades pre-joined)
        self.data_cache = DataCache()

    def get_brokers_cached(self, *, force_refresh: bool = False) -> list[str]:
        """Return broker list, using an in-memory cache when possible."""
        if force_refresh or self.brokers_cache is None:
            import model.crud as crud
            self.brokers_cache = crud.get_all_brokers()
            self.brokers_cache_version += 1
        return self.brokers_cache

    def init_data_cache(self) -> None:
        """Initial load of all datasets into memory (blocking)."""
        self.data_cache.refresh_from_db()
        # Keep brokers cache aligned with DB too
        try:
            self.get_brokers_cached(force_refresh=True)
        except Exception:
            pass

    def refresh_data_cache(self) -> None:
        """Reload datasets into memory (blocking)."""
        self.data_cache.refresh_from_db()
        try:
            self.get_brokers_cached(force_refresh=True)
        except Exception:
            pass

    def refresh_data_cache_async(self) -> None:
        """Reload datasets in a daemon thread (non-blocking)."""
        import threading

        def _bg():
            try:
                self.refresh_data_cache()
            except Exception:
                pass

        threading.Thread(target=_bg, daemon=True).start()