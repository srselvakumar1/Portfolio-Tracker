"""Sidebar market tickers (NIFTY 50, Nikkei, NASDAQ and currency pairs).

Prices are fetched in a background thread and cached in
~/.ptracker_tickers_cache.json together with the time they were fetched,
so the sidebar can say "Prices as of 10:42" and stale prices are never
presented as live.
"""

import json
import os
import threading
import time

from model.applog import log

CACHE_FILE = os.path.expanduser("~/.ptracker_tickers_cache.json")

_ticker_cache = {}
_fetched_at = None          # epoch seconds of the last successful fetch
_ticker_lock = threading.Lock()
_fetching = False
_pending_callbacks = []     # callers waiting for the fetch that is already running


def _load_cache():
    global _ticker_cache, _fetched_at
    if not os.path.exists(CACHE_FILE):
        return
    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        log.warning("Ticker cache %s is unreadable; ignoring it", CACHE_FILE)
        return
    if isinstance(data, dict) and "tickers" in data:
        _ticker_cache = data.get("tickers") or {}
        _fetched_at = data.get("fetched_at")
    elif isinstance(data, dict):
        _ticker_cache = data   # old format: tickers only, fetch time unknown


_load_cache()


def get_mini_tickers():
    with _ticker_lock:
        return dict(_ticker_cache)


def get_fetched_at():
    """When the cached prices were fetched (epoch seconds), or None if unknown."""
    with _ticker_lock:
        return _fetched_at


def _save_cache():
    tmp = CACHE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({"fetched_at": _fetched_at, "tickers": _ticker_cache}, f)
        os.replace(tmp, CACHE_FILE)   # atomic: a crash can't leave half a file
    except OSError:
        log.exception("Could not save the ticker cache")


def refresh_mini_tickers(callback=None):
    """Fetch the sidebar tickers in the background; call `callback()` (from that thread) when done.

    If a fetch is already running, the callback is queued and called when it finishes.
    """
    global _fetching
    with _ticker_lock:
        if callback:
            _pending_callbacks.append(callback)
        if _fetching:
            return
        _fetching = True

    def _fetch():
        global _fetching, _fetched_at
        symbols = ['^NSEI', '^N225', '^IXIC', 'INR=X', 'JPY=X', 'JPYINR=X']
        names = ['NIFTY 50', 'Nikkei 225', 'NASDAQ', 'USD/INR', 'USD/JPY', 'JPY/INR']
        results = {}

        try:
            import yfinance as yf
            # threads=False avoids ThreadPoolExecutor deadlocks inside daemon threads
            data = yf.download(symbols, period="7d", progress=False, threads=False)

            for sym, name in zip(symbols, names):
                try:
                    series = data['Close'][sym].dropna()
                    if len(series) >= 2:
                        cp = float(series.iloc[-1])
                        pc = float(series.iloc[-2])

                        if cp > 0:
                            chg = cp - pc
                            pct = (chg / pc * 100) if pc > 0 else 0.0

                            if sym == 'JPYINR=X':
                                cp *= 100
                                chg *= 100

                            results[name] = {"price": cp, "change": chg, "pct": pct}
                    else:
                        log.info("Ticker %s skipped: only %d price points", sym, len(series))
                except Exception:
                    log.exception("Could not read ticker %s", sym)
        except Exception:
            log.exception("Ticker download failed")
        finally:
            with _ticker_lock:
                if results:
                    _ticker_cache.update(results)
                    _fetched_at = time.time()
                    _save_cache()
                _fetching = False
                callbacks = list(_pending_callbacks)
                _pending_callbacks.clear()
            log.info("Tickers refreshed: %d of %d", len(results), len(symbols))
            for cb in callbacks:
                try:
                    cb()
                except Exception:
                    log.exception("Ticker callback failed")

    threading.Thread(target=_fetch, daemon=True, name="tickers").start()
