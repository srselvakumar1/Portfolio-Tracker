"""Price downloads in a helper process.

yfinance and the libraries it loads (pandas, a web-page parser, an HTTP client) take
about a second of pure Python work to load, and reading their answers is Python work
too. In a thread of the app that work takes turns with the window (only one thread
runs Python at a time), so the app hitched while prices came in. A helper process does
it on another processor core; the app only receives the finished rows.

One helper is started on first use and kept for later refreshes; it ends with the app.
"""
import multiprocessing
import sys
import threading
import types

from model.applog import log

_pool = None
_lock = threading.Lock()


def _get_pool():
    global _pool
    with _lock:
        if _pool is None:
            ctx = multiprocessing.get_context("spawn")   # a fresh interpreter (safe with Tk and threads)
            # A new process normally re-runs the app's start script first; the helper needs
            # nothing from it, so it is shown a blank one (faster, and safe however the app was started)
            main = sys.modules.get("__main__")
            sys.modules["__main__"] = types.ModuleType("__main__")
            try:
                _pool = ctx.Pool(processes=1)             # a daemon: it cannot outlive the app
            finally:
                if main is not None:
                    sys.modules["__main__"] = main
            log.info("Price helper process started")
        return _pool


def run(func, *args, timeout: float | None = None):
    """func(*args) in the helper process; its result, or the error it raised.
    func must be a module-level function (it is looked up by name in the helper)."""
    return _get_pool().apply_async(func, args).get(timeout)


def shutdown() -> None:
    """Stop the helper (at exit)."""
    global _pool
    with _lock:
        if _pool is not None:
            try:
                _pool.terminate()
            except Exception:
                pass
            _pool = None
