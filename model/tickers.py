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


TICKERS = (('^NSEI', 'NIFTY 50'), ('^N225', 'Nikkei 225'), ('^IXIC', 'NASDAQ'), ('INR=X', 'USD/INR'),
           ('JPY=X', 'USD/JPY'), ('JPYINR=X', 'JPY/INR'))


def _quote(yf, sym):
    """(price, previous close) from Yahoo's own quote, or (None, None)."""
    try:
        info = yf.Ticker(sym).info or {}
    except Exception:
        log.info("Ticker %s: no quote, using the daily history", sym, exc_info=True)
        return None, None
    def pos(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None
    return (pos(info.get("regularMarketPrice")),
            pos(info.get("regularMarketPreviousClose")) or pos(info.get("previousClose")))


def download_tickers() -> dict:
    """{name: {"price", "change", "pct"}} for the sidebar tickers (runs in the price helper).

    The price and the previous close come from Yahoo's own quote, so the change matches what
    Yahoo shows. The daily history (the fallback) misses special sessions such as Diwali's
    Muhurat trading, and closes currencies at a different time, so its "previous close" could
    be two sessions back (NIFTY −0.43% where Yahoo said −0.25%).
    """
    import yfinance as yf
    prices = {sym: _quote(yf, sym) for sym, _n in TICKERS}
    missing = [sym for sym, (cp, pc) in prices.items() if not (cp and pc)]
    if missing:
        try:   # threads=False avoids ThreadPoolExecutor deadlocks inside daemon threads
            data = yf.download(missing, period="7d", progress=False, threads=False)
            for sym in missing:
                closes = data['Close'][sym] if len(missing) > 1 else data['Close']
                series = (closes.iloc[:, 0] if hasattr(closes, "columns") else closes).dropna()
                if len(series) >= 2:
                    prices[sym] = (float(series.iloc[-1]), float(series.iloc[-2]))
                else:
                    log.info("Ticker %s skipped: only %d price points", sym, len(series))
        except Exception:
            log.exception("Could not download the ticker history for %s", missing)
    results = {}
    for sym, name in TICKERS:
        try:
            cp, pc = prices.get(sym) or (None, None)
            if cp and cp > 0 and pc:
                chg = cp - pc
                pct = (chg / pc * 100) if pc > 0 else 0.0
                if sym == 'JPYINR=X':
                    cp *= 100
                    chg *= 100
                results[name] = {"price": cp, "change": chg, "pct": pct}
        except Exception:
            log.exception("Could not read ticker %s", sym)
    return results


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
        results = {}
        try:   # in the price helper process, so the window doesn't wait behind yfinance
            from model import price_worker
            results = price_worker.run(download_tickers, timeout=90)
        except Exception:
            log.warning("Price helper unavailable: fetching tickers in the app instead", exc_info=True)
            try:
                results = download_tickers()
            except Exception:
                log.exception("Ticker download failed")
        with _ticker_lock:
            if results:
                _ticker_cache.update(results)
                _fetched_at = time.time()
                _save_cache()
            _fetching = False
            callbacks = list(_pending_callbacks)
            _pending_callbacks.clear()
        log.info("Tickers refreshed: %d of %d", len(results), len(TICKERS))
        for cb in callbacks:
            try:
                cb()
            except Exception:
                log.exception("Ticker callback failed")

    threading.Thread(target=_fetch, daemon=True, name="tickers").start()
