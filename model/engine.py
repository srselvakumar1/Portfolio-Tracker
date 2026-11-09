
from model.database import db_session
from model.applog import log
from datetime import datetime
from functools import lru_cache
import time
import math
import threading
import concurrent.futures

_bad_dates_logged: set = set()


@lru_cache(maxsize=8192)
def _parse_ymd(text: str) -> datetime:
    """strptime is slow and the same few hundred dates are read thousands of times."""
    return datetime.strptime(text, '%Y-%m-%d')


def _trade_date(date_str, *context):
    """Parse a stored trade date (YYYY-MM-DD). Returns None for a bad date, logged once.

    One malformed date (e.g. "15/01/2024") used to abort the whole holdings
    rebuild, or turn the overall XIRR into 0.00% without any warning.
    """
    try:
        return _parse_ymd(str(date_str))
    except (TypeError, ValueError):
        key = (str(date_str),) + tuple(str(c) for c in context)
        if key not in _bad_dates_logged:
            _bad_dates_logged.add(key)
            from model.applog import log
            log.warning("Skipping a trade with an unreadable date %r %s", date_str, " ".join(map(str, context)))
        return None


def _fast_parse_date(date_str: str) -> datetime:
    """Helper to parse YYYY-MM-DD date strings up to 50x faster than strptime."""
    try:
        return datetime(int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10]))
    except Exception:
        return datetime.strptime(date_str, '%Y-%m-%d')

# ── Trade history materialized calculations (trade_calcs) ───────────────────
_trade_calcs_lock = threading.Lock()
_trade_calcs_built_this_session = False
_trade_calcs_rebuild_inflight = False
_db_write_lock = threading.RLock()


def rebuild_trade_calcs():
    """Rebuild materialized per-trade running stats into trade_calcs.

    This replaces the expensive per-filter pandas running-state calculation in the
    Trade History view. It reads trades once (chronological) and writes computed
    columns (run_qty, avg_cost, running_pnl) keyed by (broker, trade_id).
    """
    global _trade_calcs_built_this_session

    # Pull all trades once
    with _db_write_lock:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT broker, trade_id, date, symbol, type, qty, price, fee FROM trades ORDER BY date ASC, type ASC, trade_id ASC"
            )
            rows = cur.fetchall()

            # Map current prices (DB only; no network)
            cur.execute("SELECT symbol, current_price FROM marketdata")
            prices = {r[0]: float(r[1] or 0.0) for r in cur.fetchall()}

    if not rows:
        with db_session() as conn:
            conn.execute("DELETE FROM trade_calcs")
        with _trade_calcs_lock:
            _trade_calcs_built_this_session = True
        return

    # Per (broker, symbol) running state
    running_qty: dict[tuple[str, str], float] = {}
    avg_cost: dict[tuple[str, str], float] = {}
    realized: dict[tuple[str, str], float] = {}

    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = []

    for broker, trade_id, date_s, symbol, ttype, qty, price, fee in rows:
        key = (str(broker), str(symbol))
        ttype_u = str(ttype).upper()
        q = float(qty or 0.0)
        p = float(price or 0.0)
        f = float(fee or 0.0)

        rq = running_qty.get(key, 0.0)
        ac = avg_cost.get(key, 0.0)
        rz = realized.get(key, 0.0)

        trade_pnl = 0.0
        if ttype_u == "BUY":
            new_qty = rq + q
            if new_qty != 0:
                ac = ((rq * ac) + (q * p)) / new_qty
            else:
                ac = 0.0
            rq = new_qty
        else:  # SELL
            # Realized PnL based on current avg cost (fee deducted for net per-trade P&L)
            if ac > 0 and q > 0:
                trade_pnl = (p - ac) * q - f
                rz += trade_pnl
            rq = rq - q
            if rq <= 0:
                ac = 0.0
                if rq < 0:
                    rq = 0.0  # No short positions in delivery equity

        running_qty[key] = rq
        avg_cost[key] = ac
        realized[key] = rz

        current_price = float(prices.get(symbol) or ac or 0.0)
        unrealized = (current_price - ac) * rq if rq > 0 else 0.0
        r_pnl = rz + unrealized

        out.append((str(broker), str(trade_id), str(symbol), str(date_s), float(rq), float(ac), float(r_pnl), float(trade_pnl), now_ts))

    with db_session() as conn:
        cur = conn.cursor()
        # Replace table in one go (fast enough for typical desktop DB sizes)
        cur.execute("DELETE FROM trade_calcs")
        cur.executemany(
            """
            INSERT OR REPLACE INTO trade_calcs
            (broker, trade_id, symbol, date, run_qty, avg_cost, running_pnl, trade_pnl, calc_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            out,
        )

    with _trade_calcs_lock:
        _trade_calcs_built_this_session = True


def rebuild_trade_calcs_if_needed():
    """Build trade_calcs once per app start if missing/empty."""
    global _trade_calcs_built_this_session
    with _trade_calcs_lock:
        if _trade_calcs_built_this_session:
            return

    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM trade_calcs LIMIT 1")
            has_data = cur.fetchone() is not None
        if has_data:
            with _trade_calcs_lock:
                _trade_calcs_built_this_session = True
            return
    except Exception:
        # If table doesn't exist (older DB), initialize_database() should have created it.
        pass

    rebuild_trade_calcs()


def schedule_rebuild_trade_calcs():
    """Rebuild trade_calcs in a daemon thread (non-blocking)."""
    global _trade_calcs_rebuild_inflight
    with _trade_calcs_lock:
        if _trade_calcs_rebuild_inflight:
            return
        _trade_calcs_rebuild_inflight = True

    def _bg():
        global _trade_calcs_rebuild_inflight
        try:
            rebuild_trade_calcs()
        finally:
            with _trade_calcs_lock:
                _trade_calcs_rebuild_inflight = False

    threading.Thread(target=_bg, daemon=True).start()

# ── Thread-safe caches with proper locking ────────────────────────────────────
_cache_lock = threading.Lock()
_metrics_cache: dict = {"data": None, "ts": 0.0}
_performers_cache: dict = {"data": None, "ts": 0.0}
_insights_cache: dict = {"data": None, "ts": 0.0}
_harvesting_cache: dict = {"data": None, "ts": 0.0}
_broker_metrics_cache: dict = {"data": None, "ts": 0.0}

def _invalidate_metrics_cache():
    with _cache_lock:
        _metrics_cache["data"] = None
        _metrics_cache["ts"] = 0.0

def _invalidate_performers_cache():
    with _cache_lock:
        _performers_cache["data"] = None
        _performers_cache["ts"] = 0.0

def _invalidate_insights_cache():
    with _cache_lock:
        _insights_cache["data"] = None
        _insights_cache["ts"] = 0.0

def _invalidate_harvesting_cache():
    with _cache_lock:
        _harvesting_cache["data"] = None
        _harvesting_cache["ts"] = 0.0

def _invalidate_broker_metrics_cache():
    with _cache_lock:
        _broker_metrics_cache["data"] = None
        _broker_metrics_cache["ts"] = 0.0

def is_nav_priced(symbol) -> bool:
    """A mutual fund: priced once a day (its NAV, published after the market closes), so
    its latest change is yesterday's, not today's. Today's P&L leaves these out. Yahoo
    codes them "0P…" (e.g. 0P0000XVU2.BO)."""
    return str(symbol or "").strip().upper().startswith("0P")


def invalidate_all_caches():
    """Invalidate all UI caches when data changes."""
    with _cache_lock:
        for c in (_metrics_cache, _performers_cache, _insights_cache,
                  _harvesting_cache, _broker_metrics_cache):
            c["data"] = None
            c["ts"] = 0.0

def save_dashboard_metrics(metrics: dict):
    """Persists dashboard metrics to the database."""
    with db_session() as conn:
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        records = [(k, v, now) for k, v in metrics.items() if isinstance(v, (int, float))]
        cursor.executemany("INSERT OR REPLACE INTO dashboard_metrics (metric_key, metric_value, last_updated) VALUES (?, ?, ?)", records)

def get_stored_dashboard_metrics() -> dict | None:
    """Retrieves cached dashboard metrics from the database."""
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT metric_key, metric_value FROM dashboard_metrics")
        rows = cursor.fetchall()
        if not rows: return None
        return {row[0]: row[1] for row in rows}

# ── Exchange rate in-memory cache ─────────────────────────────────────────────
_fx_cache: dict[str, float] = {}
_fx_cache_ts: float = 0.0
_FX_CACHE_TTL = 60.0  # seconds
_fx_estimated: set[str] = set()   # currencies currently using a built-in guess


def get_fx_estimates() -> set[str]:
    """Currencies whose rate to INR is a built-in guess because no rate has been fetched yet.

    Screens that convert currencies should say "≈ estimated rate" when this is not empty.
    """
    return set(_fx_estimated)

def _warm_fx_cache() -> None:
    """Pre-load all exchange rates in a single DB query."""
    global _fx_cache_ts
    try:
        with db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT symbol, current_price, previous_close FROM marketdata WHERE symbol LIKE '%=X'")
            for sym, cp, pc in cur.fetchall():
                rate = float(cp) if cp and float(cp) > 0 else float(pc or 0)
                if rate > 0:
                    # Extract currency code from e.g. "JPYINR=X" → "JPY"
                    code = sym.replace("INR=X", "").strip()
                    if code:
                        _fx_cache[code] = rate
                        _fx_estimated.discard(code)
        _fx_cache["INR"] = 1.0
        _fx_cache_ts = time.time()
    except Exception:
        pass

def get_exchange_rate(currency: str) -> float:
    """Gets the latest exchange rate to INR from marketdata table.

    Uses an in-memory cache (60s TTL) to avoid per-row DB round-trips
    in hot loops like dashboard metrics and data cache summaries.
    """
    if currency == "INR":
        return 1.0

    # Return cached value if fresh
    now = time.time()
    if now - _fx_cache_ts < _FX_CACHE_TTL and currency in _fx_cache:
        return _fx_cache[currency]

    # Cache is stale or miss — warm it from DB in one query
    if now - _fx_cache_ts >= _FX_CACHE_TTL:
        _warm_fx_cache()
        if currency in _fx_cache:
            return _fx_cache[currency]

    # Single-currency fallback (cache was just warmed but this currency wasn't found)
    ticker = f"{currency}INR=X"
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT current_price, previous_close FROM marketdata WHERE symbol = ?", (ticker,))
            row = cursor.fetchone()
            if row:
                rate = float(row[0]) if row[0] and float(row[0]) > 0 else float(row[1] or 0)
                if rate > 0:
                    _fx_cache[currency] = rate
                    _fx_estimated.discard(currency)
                    return rate
    except Exception:
        pass

    # Built-in guesses, used only until a real rate has been fetched; flagged so
    # the screens can show "≈ estimated rate" instead of presenting them as exact.
    fallbacks = {"JPY": 0.55, "USD": 83.5, "GBP": 105.0, "CNY": 11.5}
    if currency in fallbacks:
        _fx_estimated.add(currency)
    return fallbacks.get(currency, 1.0)

def is_placeholder_eps(eps, pe, price) -> bool:
    """True when EPS looks like a stand-in for missing earnings rather than a real figure:
    exactly 1.00, with a P/E equal to the share price (price ÷ 1). Such a P/E, and any
    fair value worked out from that EPS, are meaningless.  Values may be text like '₹1.00'."""
    import re

    def num(v):
        try:
            return float(re.sub(r"[^0-9.\-]", "", str(v)) or "nan")
        except ValueError:
            return float("nan")

    e, p, c = num(eps), num(pe), num(price)
    if not (e == e and p == p and c == c) or c <= 0:   # any value missing (NaN)
        return False
    return abs(e - 1.0) < 0.005 and abs(p - c) <= 0.005 * c


# Fair values and BUY / HOLD / REDUCE / SELL signals come from model/valuation.py
# (one set of rules for every page); the company figures from model/fundamentals.py.

# Only passed between _fetch_single_ticker() and fetch_and_update_market_data(), never
# stored: "this stock has no positive earnings", so its old P/E is cleared
NO_EARNINGS = "NO_EARNINGS"


def calculate_trade_fees(trade_type: str, qty: float, price: float, is_delivery: bool = True) -> float:
    """
    Calculates total fees for Indian equity delivery trades.

    Breakdown (NSE / SEBI statutory rates — verified April 2026):
    ┌─────────────────────┬──────────────────────────────────────────────────┐
    │ Component           │ Rate                                             │
    ├─────────────────────┼──────────────────────────────────────────────────┤
    │ Brokerage           │ Flat ₹1 per order (generic; Zerodha = ₹0)       │
    │ STT                 │ 0.1% of turnover (both BUY and SELL)             │
    │ Exchange Txn Chg    │ ₹2.97/lakh = 0.00297% (NSE CM, Oct 2024 rev.)   │
    │ SEBI Turnover Fee   │ ₹10 per crore = 0.0001%                         │
    │ Stamp Duty          │ 0.015% of turnover (BUY side only)               │
    │ DP Charges          │ ₹13 + 18% GST = ₹15.34/scrip (SELL only)        │
    │ GST                 │ 18% on (Brokerage + Txn Charges + SEBI Fee)      │
    │ IPFT (not included) │ ₹0.01/crore — negligible, omitted               │
    └─────────────────────┴──────────────────────────────────────────────────┘
    """
    trade_type = trade_type.upper()
    turnover = qty * price

    # 1. Brokerage: flat ₹1 per order (conservative generic default)
    brokerage = 1.0

    # 2. STT: 0.1% on both BUY and SELL (delivery)
    stt = turnover * 0.001

    # 3. NSE Exchange Transaction charges: ₹2.97 per lakh = 0.00297%
    transaction_charges = turnover * 0.0000297

    # 4. SEBI Turnover Fee: ₹10 per crore = 0.0001%
    sebi_charges = turnover * 0.000001

    # 5. Stamp duty: 0.015% on BUY side only (uniform nationwide)
    stamp_duty = turnover * 0.00015 if trade_type == 'BUY' else 0.0

    # 6. DP charges: ₹13.00 + 18% GST = ₹15.34, on SELL only (delivery)
    dp_charges = 0.0
    if trade_type == 'SELL' and is_delivery:
        dp_charges = round(13.00 * 1.18, 2)  # ₹15.34

    # 7. GST: 18% on (Brokerage + Transaction Charges + SEBI Charges)
    gst = (brokerage + transaction_charges + sebi_charges) * 0.18

    total_fees = brokerage + stt + transaction_charges + sebi_charges + stamp_duty + dp_charges + gst
    return round(total_fees, 2)

def calculate_xirr(cashflows, guesses=None, max_iter=100, tol=1e-4) -> float:
    """Calculates internal rate of return using Newton-Raphson.

    Precomputes date fractions once instead of recalculating per iteration.
    """
    if guesses is None:
        guesses = [0.1, 0.0, -0.5, -0.9, 0.5]
    if not cashflows: return 0.0

    cashflows = sorted(cashflows, key=lambda x: x[0])
    amounts = [cf[1] for cf in cashflows]

    if min(amounts) >= 0 or max(amounts) <= 0:
        return 0.0

    # Precompute day fractions once — these are constants across all iterations
    base_date = cashflows[0][0]
    day_fracs = [(cf[0] - base_date).days / 365.25 for cf in cashflows]

    import time
    for guess in guesses:
        # Yield GIL so the Tkinter main thread stays responsive!
        time.sleep(0.001)
        rate = guess
        for _ in range(max_iter):
            if rate <= -0.999: rate = -0.999
            if rate > 100.0: rate = 100.0
            try:
                v = 0.0
                deriv = 0.0
                base = 1 + rate
                for amt, df in zip(amounts, day_fracs):
                    discount = base ** df
                    v += amt / discount
                    deriv -= df * amt / (discount * base)

                if abs(v) < tol: return round(rate * 100, 2)
                if deriv == 0: break
                rate -= v / deriv
            except (OverflowError, ZeroDivisionError):
                break
    return 0.0

# ── Parallel Network Fetching Logic ──────────────────────────────────────────

_YFINANCE_TIMEOUT = 10  # seconds per future result

def _fetch_single_ticker(yf_sym: str, orig_sym: str, now: str, want_history: bool = False):
    """Fetches a single ticker's data from yfinance. Runs isolated in a thread.

    Returns (market row, asset row, company figures for model/valuation.py or None).
    With want_history the yearly figures are fetched too (two more requests).
    """
    try:
        import yfinance as yf
        import logging
        logging.getLogger('yfinance').setLevel(logging.CRITICAL)

        ticker = yf.Ticker(yf_sym)
        full_info = ticker.info

        current_price = 0.0
        try:
            val = float(ticker.fast_info.last_price)
            if not math.isnan(val): current_price = val
        except Exception:
            pass
        if current_price <= 0.0:
            current_price = float(full_info.get('currentPrice', 0.0) or
                                  full_info.get('regularMarketPrice', 0.0) or 0.0)

        # The previous close as Yahoo quotes it (its "Previous Close", which its change is
        # measured from). fast_info works one out from the daily history instead, which misses
        # special sessions such as Diwali's Muhurat trading, so "today" was measured from two
        # sessions back (TATASTEEL showed a gain on a day it fell).
        previous_close = 0.0
        for key in ('regularMarketPreviousClose', 'previousClose'):
            try:
                val = float(full_info.get(key) or 0.0)
            except (TypeError, ValueError):
                continue
            if val > 0.0 and not math.isnan(val):
                previous_close = val
                break
        if previous_close <= 0.0:
            try:
                val = float(ticker.fast_info.previous_close)
                if not math.isnan(val): previous_close = val
            except Exception:
                pass
        if previous_close <= 0.0:
            previous_close = current_price

        # Fallback to .BO if .NS fails to yield a price
        if current_price == 0.0 and not yf_sym.endswith('.BO'):
            try:
                bo = yf.Ticker(orig_sym + '.BO')
                bo_info = bo.info
                current_price = float(bo_info.get('currentPrice', 0.0) or
                                      bo_info.get('regularMarketPrice', 0.0) or 0.0)
                previous_close = float(bo_info.get('previousClose', 0.0) or
                                       bo_info.get('regularMarketPreviousClose', current_price) or current_price)
                if current_price > 0:
                    full_info = bo_info
                    ticker = bo
            except Exception:
                pass

        raw_eps = full_info.get('trailingEps')
        eps = float(raw_eps or 0.0)
        pe = float(full_info.get('trailingPE', 0.0) or 0.0)
        placeholder = is_placeholder_eps(eps, pe, current_price)
        if placeholder:
            eps = pe = 0.0   # no real earnings figure: store "unknown", not 1.00
        # The fair value and signal are worked out after saving (model/valuation.py).
        # NO_EARNINGS only tells the save to clear an old P/E: a loss is a real answer.
        iv, signal = 0.0, "N/A"
        if current_price > 0 and (placeholder or (isinstance(raw_eps, (int, float)) and raw_eps <= 0)):
            signal = NO_EARNINGS

        inputs = None
        if current_price > 0:
            try:
                from model.fundamentals import extract_inputs
                inputs = extract_inputs(orig_sym, full_info, ticker, want_history=want_history, now=now)
            except Exception:
                log.debug("Company figures for %s failed", orig_sym, exc_info=True)

        mkt_row = (
            orig_sym, current_price, previous_close,
            float(full_info.get('fiftyTwoWeekLow', 0.0) or 0.0),
            float(full_info.get('fiftyTwoWeekHigh', 0.0) or 0.0),
            pe,
            eps,
            float(full_info.get('priceToBook', 0.0) or 0.0),
            # Stored in Yahoo's own units; the Dashboard converts them for display:
            # roe = fraction (0.25 = 25%), the "roce" column holds Return on ASSETS (a fraction,
            # Yahoo has no ROCE), debt_to_equity = percent (45.0 = 0.45×)
            float(full_info.get('returnOnEquity', 0.0) or 0.0),
            float(full_info.get('returnOnAssets', 0.0) or 0.0),
            float(full_info.get('debtToEquity', 0.0) or 0.0),
            float(full_info.get('dividendYield', 0.0) or 0.0),
            full_info.get('longBusinessSummary') or full_info.get('longName') or '',
            full_info.get('longName') or full_info.get('shortName') or '',
            full_info.get('sector') or '',
            now
        )

        asset_row = (
            orig_sym, iv, signal,
            float((full_info.get('heldPercentInsiders') or 0.0) * 100),
            float((full_info.get('heldPercentInstitutions') or 0.0) * 100),
            0.0, now
        )

        return mkt_row, asset_row, inputs

    except Exception:
        # Return a safe blank record so the app doesn't crash on this symbol
        mkt_row = (orig_sym, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, '', '', '', now)
        asset_row = (orig_sym, 0.0, "N/A", 0.0, 0.0, 0.0, now)
        return mkt_row, asset_row, None

def fetch_market_rows(pairs: list, now: str, need_history=None) -> list:
    """(market row, asset row, company figures) for each (Yahoo symbol, symbol). Runs in the
    price helper process (or, if it can't start, in a thread of the app). Symbols in
    need_history also get their yearly figures."""
    need_history = set(need_history or ())
    blank = lambda sym: ((sym, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, '', '', '', now),
                         (sym, 0.0, "N/A", 0.0, 0.0, 0.0, now), None)
    rows, done = [], set()
    # 8 workers: enough to overlap network waits without 25 threads competing for the GIL
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_fetch_single_ticker, yf_sym, orig_sym, now, orig_sym in need_history): orig_sym
                   for yf_sym, orig_sym in pairs}
        try:
            # No total timeout, so large batches finish; each answer still has _YFINANCE_TIMEOUT
            for future in concurrent.futures.as_completed(futures):
                sym = futures[future]
                try:
                    rows.append(future.result(timeout=_YFINANCE_TIMEOUT))
                except Exception:
                    rows.append(blank(sym))
                done.add(sym)
        except Exception:
            pass   # unexpected loop failure: the missing symbols get blank rows below
    rows.extend(blank(sym) for sym in futures.values() if sym not in done)
    return rows


def fetch_and_update_market_data(symbols: list):
    """
    Fetches real-time data from yfinance concurrently to prevent UI freezing.
    Writes to the database in one lightning-fast bulk transaction.
    """
    if not symbols: return

    # Ensure exchange rates are fetched whenever market data is fetched
    for currency_ticker in ["JPYINR=X", "USDINR=X", "GBPINR=X", "CNYINR=X"]:
        if currency_ticker not in symbols:
            symbols.append(currency_ticker)

    # Schema guard: ensure all target columns exist before we attempt to persist.
    # This does NOT fetch anything; it only allows refreshed data to be stored.
    try:
        from model.database import ensure_marketdata_schema
        ensure_marketdata_schema()
    except Exception:
        pass

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Yahoo's symbol: as typed when it has a suffix; a 4-digit code is a Tokyo listing
    # ("7203" → "7203.T"); anything else is NSE ("TCS" → "TCS.NS")
    yf_symbols = [s if ('.' in s or '=' in s) else s + ".T" if (len(s) == 4 and s.isdigit()) else s + ".NS"
                  for s in symbols]

    pairs = list(zip(yf_symbols, symbols))
    try:   # yearly company figures are fetched at most once a week per company
        from model.fundamentals import needs_history
        need_history = needs_history(symbols)
    except Exception:
        log.warning("Couldn't check which company figures are due", exc_info=True)
        need_history = set()
    try:   # in the helper process, so the window never waits behind yfinance's Python work
        from model import price_worker
        rows = price_worker.run(fetch_market_rows, pairs, now, need_history,
                                timeout=60 + len(pairs) * _YFINANCE_TIMEOUT / 4 + len(need_history) * 2)
    except Exception:
        log.warning("Price helper unavailable: fetching prices in the app instead", exc_info=True)
        rows = fetch_market_rows(pairs, now, need_history)
    marketdata_records = [m for m, _a, _i in rows]
    # Stocks with no positive earnings: store "N/A", then clear their old fair value and P/E below
    no_earnings = [(m[6], m[0]) for m, a, _i in rows if a[2] == NO_EARNINGS]
    assets_records = [(a[0], a[1], "N/A", *a[3:]) if a[2] == NO_EARNINGS else a for _m, a, _i in rows]

    # Write to DB in a fraction of a second
    with db_session() as conn:
        cursor = conn.cursor()

        cursor.executemany('''
            INSERT INTO marketdata
            (symbol, current_price, previous_close, low_52w, high_52w,
             pe_ratio, eps, pb_ratio, roe, roce, debt_to_equity, dividend_yield,
             description, stock_name, sector, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                current_price  = CASE WHEN excluded.current_price > 0 THEN excluded.current_price ELSE marketdata.current_price END,
                previous_close = CASE WHEN excluded.previous_close > 0 THEN excluded.previous_close ELSE marketdata.previous_close END,
                low_52w        = CASE WHEN excluded.low_52w > 0 THEN excluded.low_52w ELSE marketdata.low_52w END,
                high_52w       = CASE WHEN excluded.high_52w > 0 THEN excluded.high_52w ELSE marketdata.high_52w END,
                pe_ratio       = CASE WHEN excluded.pe_ratio > 0 THEN excluded.pe_ratio ELSE marketdata.pe_ratio END,
                eps            = CASE WHEN excluded.eps != 0 THEN excluded.eps ELSE marketdata.eps END,
                pb_ratio       = CASE WHEN excluded.pb_ratio > 0 THEN excluded.pb_ratio ELSE marketdata.pb_ratio END,
                roe            = CASE WHEN excluded.roe != 0 THEN excluded.roe ELSE marketdata.roe END,
                roce           = CASE WHEN excluded.roce != 0 THEN excluded.roce ELSE marketdata.roce END,
                debt_to_equity = CASE WHEN excluded.debt_to_equity >= 0 THEN excluded.debt_to_equity ELSE marketdata.debt_to_equity END,
                dividend_yield = CASE WHEN excluded.dividend_yield >= 0 THEN excluded.dividend_yield ELSE marketdata.dividend_yield END,
                description    = excluded.description,
                sector         = excluded.sector,
                stock_name     = CASE WHEN (marketdata.stock_name IS NULL OR marketdata.stock_name = '' OR marketdata.stock_name = symbol) AND excluded.stock_name != '' THEN excluded.stock_name ELSE marketdata.stock_name END,
                last_updated   = excluded.last_updated
        ''', marketdata_records)

        cursor.executemany('''
            INSERT INTO assets
            (symbol, intrinsic_value, action_signal, promoter_holding, fii_holding, dii_holding, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                intrinsic_value  = CASE WHEN excluded.intrinsic_value > 0 THEN excluded.intrinsic_value ELSE assets.intrinsic_value END,
                action_signal    = CASE WHEN excluded.action_signal != 'N/A' THEN excluded.action_signal ELSE assets.action_signal END,
                promoter_holding = CASE WHEN excluded.promoter_holding > 0 THEN excluded.promoter_holding ELSE assets.promoter_holding END,
                fii_holding      = CASE WHEN excluded.fii_holding > 0 THEN excluded.fii_holding ELSE assets.fii_holding END,
                dii_holding      = CASE WHEN excluded.dii_holding > 0 THEN excluded.dii_holding ELSE assets.dii_holding END,
                last_updated     = excluded.last_updated
        ''', assets_records)

        # The upserts above keep old values when a new one is missing (a failed fetch).
        # A loss is a real answer, so a fair value / P/E / signal from a profitable year goes.
        if no_earnings:
            cursor.executemany("UPDATE marketdata SET eps = ?, pe_ratio = 0 WHERE symbol = ?", no_earnings)
            cursor.executemany("UPDATE assets SET intrinsic_value = 0, action_signal = 'N/A' WHERE symbol = ?",
                               [(sym,) for _eps, sym in no_earnings])

        # Fair value and signal from the shared rules (model/valuation.py), the same ones the
        # Watchlist, Valuation and Dashboard use. A failed download keeps the old values.
        _apply_valuations(conn, rows, now)


def _apply_valuations(conn, rows, now: str) -> None:
    """Save each answered stock's company figures, decide its zone, and store the fair value
    and signal (BUY → ACCUMULATE, HOLD, REDUCE, SELL, no signal → N/A) in assets."""
    from model import fundamentals
    from model.valuation import load_assumptions
    assumptions = load_assumptions()
    updates = []
    for mkt, _asset, inputs in rows:
        sym, price = mkt[0], mkt[1]
        if not inputs or not price or price <= 0 or "=" in sym:
            continue
        try:
            fundamentals.save_inputs(sym, dict(inputs, price=price, price_at=now), conn)
            d = fundamentals.record(sym, price, now, conn, assumptions)
            updates.append((round(d.fair_value, 2) if d.fair_value else 0.0, d.stored_signal, sym))
        except Exception:
            log.warning("Valuing %s failed", sym, exc_info=True)
    if updates:
        conn.executemany("UPDATE assets SET intrinsic_value = ?, action_signal = ? WHERE symbol = ?", updates)


# ── Database Rebuild Logic ───────────────────────────────────────────────────

def rebuild_holdings(*, sync_trade_calcs: bool = True):
    """Recalculates the holdings table based on all trades.
    Uses stored fees from trades - does NOT recalculate fees.
    Fees are only calculated when trades are entered/imported or amended.

    Uses direct cursor iteration instead of loading everything into pandas.
    
    Args:
        sync_trade_calcs: If True, rebuild trade_calcs synchronously (for trade edits).
                          If False, run in background (for startup speed).
    """
    with _db_write_lock:
        with db_session() as conn:
            cursor = conn.cursor()

            # Fetch market prices as a simple dict — no pandas needed
            cursor.execute("SELECT symbol, current_price, previous_close FROM marketdata")
            prices = {row[0]: (float(row[1] or 0.0), float(row[2] or 0.0)) for row in cursor.fetchall()}

            cursor.execute("SELECT broker, trade_id, date, symbol, type, qty, price, fee, currency FROM trades ORDER BY date ASC, type ASC, trade_id ASC")

            holdings_dict = {}

            import time
            for i, (broker, trade_id, date_str, symbol, t_type, qty, price, fee, currency) in enumerate(cursor.fetchall()):
                if i % 1000 == 0:
                    time.sleep(0.001) # Yield GIL for Tkinter responsiveness
                key = (broker, symbol)
                qty = float(qty)
                price = float(price)
                fee = float(fee or 0.0)

                trade_date = _trade_date(date_str, broker, trade_id, symbol)
                if trade_date is None:
                    continue

                if key not in holdings_dict:
                    holdings_dict[key] = {'qty': 0.0, 'cost': 0.0, 'realized_pnl': 0.0, 'cfs': [], 'earliest_date': date_str, 'total_fees': 0.0, 'currency': currency or 'INR'}

                h = holdings_dict[key]

                if date_str < h['earliest_date']:
                    h['earliest_date'] = date_str

                h['total_fees'] += fee

                if t_type == 'BUY':
                    h['qty'] += qty
                    h['cost'] += (qty * price)
                    h['cfs'].append((trade_date, -((qty * price) + fee)))
                elif t_type == 'SELL':
                    avg_price = h['cost'] / h['qty'] if h['qty'] > 0 else 0
                    h['qty'] -= qty
                    h['cost'] -= (qty * avg_price)
                    h['realized_pnl'] += ((price - avg_price) * qty)
                    h['cfs'].append((trade_date, ((qty * price) - fee)))

        now = datetime.now()
        records_to_insert = []

        for (broker, symbol), data in holdings_dict.items():
            avg_price = 0.0
            xirr_val = 0.0
            cagr_val = 0.0
            running_pnl = 0.0

            # If net position is zero or negative (due to intraday sequence, bonus, or rounding), clamp to closed (0.0)
            if data['qty'] <= 0.00001:
                data['qty'] = 0.0
                data['cost'] = 0.0

            if data['qty'] > 0 or data['realized_pnl'] != 0 or data['total_fees'] > 0:
                avg_price = data['cost'] / data['qty'] if data['qty'] > 0 else 0.0

                if data['qty'] > 0 and len(data['cfs']) > 0:
                    p_tuple = prices.get(symbol) or prices.get(symbol + ".NS") or prices.get(symbol + ".BO") or (0.0, 0.0)
                    current_price = p_tuple[0]
                    
                    # Core Fix: If the API failed and price is 0.0, fallback to previous_close
                    if current_price == 0.0:
                        current_price = p_tuple[1]
                    # If still 0.0, fallback to cost basis so we don't artificially wipe out the entire value
                    if current_price == 0.0:
                        current_price = avg_price
                        
                    terminal_value = data['qty'] * float(current_price)
                    
                    # We must ALWAYS compute running_pnl to retain realized_pnl accumulation,
                    # even if the terminal value is technically zero. 
                    unrealized_pnl = (float(current_price) - avg_price) * data['qty']
                    running_pnl = data['realized_pnl'] + unrealized_pnl

                    if terminal_value > 0:
                        # XIRR
                        cfs = data['cfs'] + [(now, terminal_value)]
                        xirr_val = calculate_xirr(cfs)

                        # CAGR
                        try:
                            start_dt = datetime.strptime(data['earliest_date'], '%Y-%m-%d')
                            # Under a year, show the plain return instead of a yearly rate: a few
                            # days' gain raised to the power 365/days gives absurd numbers (e.g. a
                            # fund imported with today's date but an old purchase price)
                            years = max((now - start_dt).days / 365.25, 1.0)
                            if years > 0:
                                invested = data['cost']
                                total_return_val = terminal_value + data['realized_pnl']
                                if invested > 0:
                                    ratio = total_return_val / invested
                                    if ratio > 0:
                                        cagr_val = (ratio ** (1/years) - 1) * 100
                                    else:
                                        cagr_val = -100.0
                        except Exception: pass
                else:
                    running_pnl = data['realized_pnl']

            records_to_insert.append((broker, symbol, max(0.0, data['qty']), avg_price, data['realized_pnl'], running_pnl, xirr_val, cagr_val, data['earliest_date'], data['total_fees'], data['currency']))


        # Rebuild the holdings table in one committed transaction. (This used to run
        # after the session above had closed, so it was only saved when some later
        # call happened to commit, and the table stayed write-locked until then.)
        with db_session() as conn:
            cursor2 = conn.cursor()
            cursor2.execute("DELETE FROM holdings")
            cursor2.executemany('''
                INSERT INTO holdings (broker, symbol, qty, avg_price, realized_pnl, running_pnl, xirr, cagr, earliest_date, total_fees, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', records_to_insert)

    # After rebuilding holdings, also update and save dashboard metrics
    new_metrics = get_dashboard_metrics(force_refresh=True, _rebuild=False)
    save_dashboard_metrics(new_metrics)
    invalidate_all_caches()

    # Keep Trade History precomputed calcs in sync after any trade mutation.
    try:
        if sync_trade_calcs:
            rebuild_trade_calcs()
        else:
            schedule_rebuild_trade_calcs()
    except Exception:
        pass


_holdings_built_this_session = False
_holdings_lock = threading.Lock()
_holdings_rebuild_inflight = False


def rebuild_holdings_on_startup():
    """Rebuild holdings exactly once per app launch.

    This keeps the "calculate once at startup" policy correct even if the user
    added/edited trades in a previous session.
    """
    global _holdings_built_this_session, _holdings_rebuild_inflight
    with _holdings_lock:
        if _holdings_built_this_session or _holdings_rebuild_inflight:
            return
        _holdings_rebuild_inflight = True
    try:
        rebuild_holdings(sync_trade_calcs=False)
    finally:
        with _holdings_lock:
            _holdings_rebuild_inflight = False
            _holdings_built_this_session = True

def rebuild_holdings_if_needed():
    """Skip the expensive startup rebuild if holdings are already populated.

    Holdings are recalculated at startup (best-effort) and on explicit manual
    refresh actions (Holdings/Dashboard). A non-empty holdings table is treated
    as sufficiently warm for startup to avoid blocking the UI.
    """
    global _holdings_built_this_session
    with _holdings_lock:
        if _holdings_built_this_session:
            return
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM holdings LIMIT 1")
            has_data = cursor.fetchone() is not None
            if has_data:
                # Force dashboard metrics to recalculate once per session
                cursor.execute("DELETE FROM dashboard_metrics")
                with _holdings_lock:
                    _holdings_built_this_session = True
                return
    except Exception:
        pass
    rebuild_holdings(sync_trade_calcs=False)
    with _holdings_lock:
        _holdings_built_this_session = True


def rebuild_trade_calcs_on_startup():
    """Rebuild trade_calcs exactly once per app launch."""
    global _trade_calcs_built_this_session, _trade_calcs_rebuild_inflight
    with _trade_calcs_lock:
        if _trade_calcs_built_this_session or _trade_calcs_rebuild_inflight:
            return
        _trade_calcs_rebuild_inflight = True
    try:
        rebuild_trade_calcs()
    finally:
        with _trade_calcs_lock:
            _trade_calcs_rebuild_inflight = False
            _trade_calcs_built_this_session = True


# ── Metric Retrievers ────────────────────────────────────────────────────────

def calculate_overall_xirr(conn=None, broker_filter: str | None = None, currency_filter: str = "All") -> float:
    """Calculate true XIRR for overall portfolio or specific broker from all trades.
    
    Collects all cash flows (BUY = negative, SELL = positive) and adds terminal 
    value as final cash flow. Uses Newton-Raphson solver for actual XIRR.
    """
    if conn is None:
        with db_session() as conn:
            return calculate_overall_xirr(conn=conn, broker_filter=broker_filter, currency_filter=currency_filter)
    
    try:
        cursor = conn.cursor()
        
        # Build WHERE clause for filters
        conditions = []
        params = []
        if broker_filter:
            conditions.append("broker = ?")
            params.append(broker_filter)
        if currency_filter != "All":
            conditions.append("currency = ?")
            params.append(currency_filter.upper())
            
        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        
        # Get all trades for XIRR calculation
        query = f'''
            SELECT date, type, qty, price, fee FROM trades
            {where_clause}
            ORDER BY date ASC
        '''
        cursor.execute(query, params)
        trades = cursor.fetchall()
        
        # Get current holdings value for terminal value
        query_holdings = '''
            SELECT 
                SUM(h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)) as current_val,
                SUM(h.qty * h.avg_price) as invested
            FROM holdings h
            LEFT JOIN marketdata m ON h.symbol = m.symbol
            WHERE (h.qty > 0 OR h.running_pnl != 0)
        '''
        h_params = []
        if broker_filter:
            query_holdings += " AND h.broker = ?"
            h_params.append(broker_filter)
        if currency_filter != "All":
            query_holdings += " AND h.currency = ?"
            h_params.append(currency_filter.upper())
            
        cursor.execute(query_holdings, h_params)
        
        holdings_row = cursor.fetchone()
        current_val = holdings_row[0] or 0.0 if holdings_row else 0.0
        
        # Convert trades to cash flows
        cashflows = []
        import time
        for i, trade in enumerate(trades):
            if i % 1000 == 0:
                time.sleep(0.001) # Yield GIL
            date_str, trade_type, qty, price, fee = trade
            trade_date = _trade_date(date_str)
            if trade_date is None:
                continue
            
            if trade_type == 'BUY':
                # BUY: negative cash flow (money goes out)
                amount = -((qty * price) + fee)
            elif trade_type == 'SELL':
                # SELL: positive cash flow (money comes in)
                amount = (qty * price) - fee
            else:
                continue
            
            cashflows.append((trade_date, amount))
        
        # Add terminal value (current portfolio value) as final cash flow
        if cashflows and current_val > 0:
            cashflows.append((datetime.now(), current_val))
        elif not cashflows:
            return 0.0
        
        # Calculate true XIRR using Newton-Raphson
        return calculate_xirr(cashflows)
        
    except Exception:
        pass
        return 0.0


def get_dashboard_metrics(force_refresh: bool = False, broker_filter: str = None, currency_filter: str = "All", _rebuild: bool = True) -> dict:
    """Calculates high-level metrics for the dashboard KPI cards."""
    # Check if holdings are completely empty. If so, we must rebuild them to show data.
    has_holdings = False
    try:
        with db_session() as conn:
            has_holdings = conn.cursor().execute("SELECT 1 FROM holdings LIMIT 1").fetchone() is not None
    except Exception:
        pass

    if (force_refresh or not has_holdings) and _rebuild:
        # Rebuild holdings best-effort
        try:
            rebuild_holdings(sync_trade_calcs=False)
        except Exception:
            pass

    # 1. Check in-memory cache (thread-safe read)
    with _cache_lock:
        # "Calculate once" policy: keep cached metrics until explicitly invalidated
        # (e.g., after rebuild_holdings or manual market refresh).
        if not force_refresh and _metrics_cache["data"] is not None and _metrics_cache.get("currency") == currency_filter:
            return _metrics_cache["data"]

    # 2. Check DB stored metrics if not forcing a recalc
    if not force_refresh and currency_filter == "All":
        stored = get_stored_dashboard_metrics()
        if stored:
            with _cache_lock:
                _metrics_cache["data"], _metrics_cache["ts"] = stored, time.time()
                _metrics_cache["currency"] = currency_filter
            return stored

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                h.qty,
                h.avg_price,
                COALESCE(NULLIF(m.current_price, 0.0), h.avg_price),
                h.running_pnl,
                h.realized_pnl,
                h.earliest_date,
                h.currency,
                COALESCE(m.previous_close, COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)),
                h.symbol
            FROM holdings h
            LEFT JOIN marketdata m ON h.symbol = m.symbol
            WHERE h.qty > 0 OR h.running_pnl != 0
        ''')
        
        invested = current_val = overall_pnl = overall_loss = unrealized_loss = day_pnl = 0.0
        day_pnl_funds = day_value = 0.0     # funds' last NAV change; the value Today's P&L is on
        closed_realized_pnl = closed_realized_loss = 0.0
        total_realized_pnl = total_realized_loss = 0.0
        earliest_date = None
        
        for row in cursor.fetchall():
            qty = float(row[0] or 0.0)
            avg_price = float(row[1] or 0.0)
            mkt_price = float(row[2] or 0.0)
            running_pnl = float(row[3] or 0.0)
            real_pnl = float(row[4] or 0.0)
            date_str = row[5]
            currency = str(row[6] or 'INR').strip().upper()
            prev_close = float(row[7] or 0.0)
            symbol = row[8]
            
            if currency_filter != "All" and currency != currency_filter.upper():
                continue
                
            rate = 1.0 if currency_filter != "All" else get_exchange_rate(currency)
            
            if qty > 0:
                row_inv = (qty * avg_price) * rate
                row_cur = (qty * mkt_price) * rate
                row_unrealized = row_cur - row_inv
                # no previous close: no change today (not the whole value)
                row_day_pnl = (qty * (mkt_price - prev_close)) * rate if prev_close > 0 else 0.0
                if is_nav_priced(symbol):   # a fund: its latest change is yesterday's NAV
                    day_pnl_funds += row_day_pnl
                    row_day_pnl = 0.0
                else:
                    day_value += row_cur
                if row_unrealized < 0:
                    unrealized_loss += row_unrealized
            else:
                row_inv = 0.0
                row_cur = 0.0
                row_unrealized = 0.0
                row_day_pnl = 0.0
                closed_realized_pnl += real_pnl * rate
                if real_pnl < 0:
                    closed_realized_loss += real_pnl * rate
            
            total_realized_pnl += real_pnl * rate
            if real_pnl < 0:
                total_realized_loss += real_pnl * rate

            invested += row_inv
            current_val += row_cur
            overall_pnl += running_pnl * rate
            day_pnl += row_day_pnl
            
            if real_pnl < 0:
                overall_loss += real_pnl * rate
                
            if earliest_date is None or (date_str and date_str < earliest_date):
                earliest_date = date_str

        unrealized_pnl = current_val - invested
        realized_pnl = total_realized_pnl
        realized_loss = total_realized_loss

        # Calculate true XIRR from all trades (not simple ROI)
        overall_xirr = calculate_overall_xirr(conn, currency_filter=currency_filter)

        overall_cagr = 0.0
        if invested > 0 and earliest_date:
            try:
                days = (datetime.now() - datetime.strptime(earliest_date, '%Y-%m-%d')).days
                years = max(days / 365.25, 0.001)
                total_ret = (invested + overall_pnl) / invested
                if total_ret > 0:
                    overall_cagr = (total_ret ** (1 / years) - 1) * 100
            except Exception:
                pass

    result = {
        "total_invested": invested, "total_value": current_val,
        "overall_pnl": overall_pnl, "unrealized_pnl": unrealized_pnl,
        "realized_pnl": realized_pnl, "realized_loss": realized_loss, "unrealized_loss": unrealized_loss,
        "overall_xirr": overall_xirr, "overall_cagr": overall_cagr, "day_pnl": day_pnl,
        "day_pnl_funds": day_pnl_funds, "day_value": day_value,
    }
    with _cache_lock:
        _metrics_cache["data"], _metrics_cache["ts"] = result, time.time()
        _metrics_cache["currency"] = currency_filter
    return result

def get_metrics_by_broker(currency_filter: str = "All", force_refresh: bool = False) -> dict:
    # "Calculate once" policy: keep cached broker metrics until explicitly invalidated.
    with _cache_lock:
        if not force_refresh and _broker_metrics_cache["data"] is not None and _broker_metrics_cache.get("currency") == currency_filter:
            return _broker_metrics_cache["data"]

    with db_session() as conn:
        cursor = conn.cursor()
        query = '''
            SELECT
                h.broker,
                h.qty,
                h.avg_price,
                COALESCE(NULLIF(m.current_price, 0.0), h.avg_price),
                h.running_pnl,
                h.realized_pnl,
                h.earliest_date,
                h.currency,
                COALESCE(m.previous_close, COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)),
                h.symbol
            FROM holdings h
            LEFT JOIN marketdata m ON h.symbol = m.symbol
            WHERE (h.qty > 0 OR h.running_pnl != 0)
        '''
        params = []
        if currency_filter != "All":
            query += " AND h.currency = ?"
            params.append(currency_filter.upper())
            
        cursor.execute(query, params)
        rows = cursor.fetchall()

        broker_metrics = {}
        for row in rows:
            broker = row[0]
            if broker not in broker_metrics:
                broker_metrics[broker] = {
                    "invested": 0.0, "current_val": 0.0, "overall_pnl": 0.0,
                    "overall_loss": 0.0, "unrealized_loss": 0.0, "day_pnl": 0.0,
                    "total_realized_pnl": 0.0, "total_realized_loss": 0.0,
                    "closed_realized_pnl": 0.0, "closed_realized_loss": 0.0,
                    "earliest_date": None
                }
                
            metrics = broker_metrics[broker]
            qty = float(row[1] or 0.0)
            avg_price = float(row[2] or 0.0)
            mkt_price = float(row[3] or 0.0)
            running_pnl = float(row[4] or 0.0)
            real_pnl = float(row[5] or 0.0)
            date_str = row[6]
            currency = str(row[7] or 'INR').strip().upper()
            prev_close = float(row[8] or 0.0)
            
            rate = 1.0 # Broker metrics are kept in their native currency
            
            if qty > 0:
                row_inv = (qty * avg_price) * rate
                row_cur = (qty * mkt_price) * rate
                row_unrealized = row_cur - row_inv
                row_day_pnl = ((qty * (mkt_price - prev_close)) * rate
                               if prev_close > 0 and not is_nav_priced(row[9]) else 0.0)
                if row_unrealized < 0:
                    metrics["unrealized_loss"] += row_unrealized
            else:
                row_inv = 0.0
                row_cur = 0.0
                row_unrealized = 0.0
                row_day_pnl = 0.0
                metrics["closed_realized_pnl"] += real_pnl * rate
                if real_pnl < 0:
                    metrics["closed_realized_loss"] += real_pnl * rate
            
            metrics["total_realized_pnl"] += real_pnl * rate
            if real_pnl < 0:
                metrics["total_realized_loss"] += real_pnl * rate

            metrics["invested"] += row_inv
            metrics["current_val"] += row_cur
            metrics["overall_pnl"] += running_pnl * rate
            metrics["day_pnl"] += row_day_pnl
            
            if real_pnl < 0:
                metrics["overall_loss"] += real_pnl * rate
                
            if metrics["earliest_date"] is None or (date_str and date_str < metrics["earliest_date"]):
                metrics["earliest_date"] = date_str
            metrics["currency"] = currency

        final_broker_metrics = {}
        for broker, metrics in broker_metrics.items():
            invested, current_val = metrics["invested"], metrics["current_val"]
            overall_pnl = metrics["overall_pnl"]
            unrealized_loss = metrics["unrealized_loss"]
            earliest_date = metrics["earliest_date"]
            currency = metrics.get("currency", "INR")

            unrealized_pnl = current_val - invested
            realized_pnl = metrics["total_realized_pnl"]
            realized_loss = metrics["total_realized_loss"]
            # Calculate true XIRR per broker based on all trades for that broker
            overall_xirr = calculate_overall_xirr(conn, broker_filter=broker, currency_filter=currency)

            overall_cagr = 0.0
            if invested > 0 and earliest_date:
                try:
                    days = (datetime.now() - datetime.strptime(earliest_date, '%Y-%m-%d')).days
                    years = max(days / 365.25, 0.001)
                    total_ret = (invested + overall_pnl) / invested
                    if total_ret > 0:
                        overall_cagr = (total_ret ** (1 / years) - 1) * 100
                except Exception:
                    pass

            final_broker_metrics[broker] = {
                "total_invested": invested, "total_value": current_val,
                "overall_pnl": overall_pnl, "unrealized_pnl": unrealized_pnl,
                "realized_pnl": realized_pnl, "realized_loss": realized_loss, "unrealized_loss": unrealized_loss,
                "closed_realized_pnl": metrics["closed_realized_pnl"],
                "closed_realized_loss": metrics["closed_realized_loss"],
                "overall_xirr": overall_xirr, "overall_cagr": overall_cagr,
                "day_pnl": metrics.get("day_pnl", 0.0),
                "currency": currency
            }

    with _cache_lock:
        _broker_metrics_cache["data"], _broker_metrics_cache["ts"] = final_broker_metrics, time.time()
        _broker_metrics_cache["currency"] = currency_filter
    return final_broker_metrics

def get_top_worst_performers(limit: int = 3, currency_filter: str = "All") -> dict:
    with _cache_lock:
        if _performers_cache["data"] is not None and _performers_cache.get("currency") == currency_filter:
            return _performers_cache["data"]

    with db_session() as conn:
        cursor = conn.cursor()
        query = '''
            SELECT h.symbol, SUM(h.qty), SUM(h.qty * h.avg_price), SUM(h.realized_pnl),
                   MAX(COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)),
                   MAX(COALESCE(m.current_price, 0.0)), MAX(COALESCE(m.previous_close, 0.0))
            FROM holdings h LEFT JOIN marketdata m ON h.symbol = m.symbol
            WHERE h.qty > 0
        '''
        params = []
        if currency_filter != "All":
            query += " AND h.currency = ?"
            params.append(currency_filter.upper())
        query += " GROUP BY h.symbol"
        cursor.execute(query, params)
        rows = cursor.fetchall()

    performers = []
    for row in rows:
        cost, total_pnl = row[2], (row[1] * row[4] - row[2]) + row[3]
        qty, cp = row[1], row[4]
        avg_price = cost / qty if qty > 0 else 0
        live, prev = row[5] or 0.0, row[6] or 0.0
        performers.append({
            "symbol": row[0],
            "pnl": total_pnl,
            "pnl_pct": (total_pnl / cost * 100) if cost > 0 else 0,
            "avg_price": avg_price,
            "current_price": cp,
            "invested": cost,
            # today's price change; None when there is no live price or previous close
            "day_pct": (live / prev - 1) * 100 if live > 0 and prev > 0 else None,
        })

    performers.sort(key=lambda x: x["pnl"], reverse=True)
    if len(performers) >= 2 * limit:
        top = performers[:limit]
        worst = list(reversed(performers[-limit:]))
    else:
        split_idx = (len(performers) + 1) // 2
        top = performers[:split_idx]
        worst = list(reversed(performers[split_idx:]))

    result = {
        "top": top,
        "worst": worst
    }
    with _cache_lock:
        _performers_cache["data"], _performers_cache["ts"] = result, time.time()
        _performers_cache["currency"] = currency_filter
    return result

def get_actionable_insights(limit: int = 10, currency_filter: str = "All") -> list:
    with _cache_lock:
        if _insights_cache["data"] is not None and _insights_cache.get("currency") == currency_filter:
            return _insights_cache["data"]

    with db_session() as conn:
        cursor = conn.cursor()
        query = '''
            SELECT DISTINCT h.symbol, a.action_signal, a.intrinsic_value, m.current_price, h.currency,
                   m.previous_close
            FROM holdings h JOIN assets a ON h.symbol = a.symbol
            LEFT JOIN marketdata m ON h.symbol = m.symbol
            WHERE h.qty > 0 AND a.action_signal IN ('ACCUMULATE', 'REDUCE', 'SELL')
        '''
        params = []
        if currency_filter != "All":
            query += " AND h.currency = ?"
            params.append(currency_filter.upper())

        # SELL (bad news) first, then the biggest gap between fair value and price
        query += (" ORDER BY CASE a.action_signal WHEN 'SELL' THEN 0 ELSE 1 END,"
                  " ABS(a.intrinsic_value - m.current_price) / m.current_price DESC LIMIT ?")
        params.append(limit)
        
        cursor.execute(query, params)
        result = [
            {
                "symbol": r[0],
                "signal": r[1],
                "iv": r[2],
                "current_price": r[3],
                "currency": r[4],
                "previous_close": r[5],     # for the Day Chg column
            }
            for r in cursor.fetchall()
        ]

    # Loss-makers have no fair value: give their book value a share instead ("₹… (B)")
    if any((r["iv"] or 0) <= 0 for r in result):
        try:
            from model import fundamentals
            from model.valuation import canonical
            recs = fundamentals.load_records([r["symbol"] for r in result if (r["iv"] or 0) <= 0])
            for r in result:
                bv = ((recs.get(canonical(r["symbol"])) or {}).get("inputs") or {}).get("bvps")
                if (r["iv"] or 0) <= 0 and isinstance(bv, (int, float)) and bv > 0:
                    r["book"] = float(bv)
        except Exception:
            log.warning("Insights: could not read the book values", exc_info=True)

    with _cache_lock:
        _insights_cache["data"], _insights_cache["ts"] = result, time.time()
        _insights_cache["currency"] = currency_filter
    return result

_ALERT_MIN_UPSIDE = -30.0   # % : skip alerts whose target is more than 30% below the price


def get_watchlist_alerts(currency_filter: str = "All", fill_to: int = 0) -> list:
    """Watchlist stocks in the BUY zone (Accumulate / Strong Buy on the Watchlist), with PE and EPS.

    The zone is worked out now with the shared rules (model/valuation.py), from the
    same figures and price as the Watchlist table, so the two always agree. The
    target is your own target price, else the fair value.

    With fill_to, the list has at most fill_to items (the alerts with the most
    upside), and a shorter list is topped up with the other watchlist stocks
    (never REDUCE / SELL, i.e. never "Avoid") that have the most upside to their
    target; those items carry "watch": True so the Dashboard can show them as "watching".
    """
    from model import fundamentals
    from model.valuation import canonical, country_of, decide, load_assumptions
    
    def _parse_num(val_str) -> float:
        """'₹1,313.2', '¥7030', '$1298.9' (older Auto-Fill values) -> 1313.2 etc."""
        import re
        if not val_str:
            return 0.0
        try:
            return float(re.sub(r"[^0-9.\-]", "", str(val_str)) or 0)
        except ValueError:
            return 0.0
            
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT w.symbol, w.target_price, COALESCE(NULLIF(m.current_price, 0.0), m.previous_close, 0.0) as current_price,
                   COALESCE(NULLIF(m.pe_ratio, 0.0), NULLIF(w.pe_ratio, '0'), NULLIF(w.pe_ratio, '0.0'), w.pe_ratio) as pe_ratio,
                   COALESCE(NULLIF(m.eps, 0.0), NULLIF(w.eps, '0'), NULLIF(w.eps, '0.0'), w.eps) as eps,
                   m.last_updated, w.current_value
            FROM watchlist w
            LEFT JOIN marketdata m ON w.symbol = m.symbol
        ''')
        rows = cursor.fetchall()
        records = fundamentals.load_records([r[0] for r in rows], conn)
        assumptions = load_assumptions()

        alerts, watching = [], []
        for r in rows:
            symbol, target, mkt_price, pe, eps, mkt_date, saved_price = r
            rec = records.get(canonical(symbol)) or {}
            # The same price as the Watchlist table: the newest known price, else the saved one
            current, price_date = fundamentals.best_price((mkt_price, mkt_date), rec.get("inputs"))
            if not current:
                current, price_date = _parse_num(saved_price), None
            d = decide(rec.get("inputs"), current, assumptions, rec.get("state"), price_date)
            is_alert = d.zone == "BUY"
            if not is_alert and (not fill_to or d.zone in ("REDUCE", "SELL")):
                continue

            # The exchange suffix decides the currency (.T = Tokyo)
            currency = "JPY" if country_of(symbol, d.currency) == "JP" else "INR"
            if currency_filter != "All" and currency != currency_filter.upper():
                continue

            # A placeholder EPS (1.00, P/E = price) or a loss: no meaningful P/E
            if is_placeholder_eps(eps, pe, current):
                pe = eps = None
            elif eps not in (None, "", "-") and _parse_num(eps) <= 0:
                pe = None

            # Your own target, else the fair value from the shared rules
            if not target or target <= 0:
                target = d.fair_value or 0.0

            diff = target - current if target > 0 and current > 0 else 0
            # signed: negative when the price is already above the target
            pct = (diff / current) * 100 if current > 0 and target > 0 else 0
            if not is_alert and not (target > 0 and current > 0):
                continue
            # An "Accumulate" whose target is far below today's price contradicts itself
            if is_alert and target > 0 and current > 0 and pct < _ALERT_MIN_UPSIDE:
                continue
            (alerts if is_alert else watching).append({
                "symbol": symbol,
                "target_price": target,
                "current_price": current,
                "pe": pe if pe else "-",
                "eps": eps if eps else "-",
                "diff": diff,
                "pct_below": pct,
                "currency": currency,
                "watch": not is_alert,
            })
        
        if fill_to and len(alerts) > fill_to:
            # Too many for the table: keep the ones with the most upside to their target
            alerts.sort(key=lambda x: -x["pct_below"])
            del alerts[fill_to:]
        alerts.sort(key=lambda x: x["symbol"])
        if len(alerts) < fill_to:
            watching.sort(key=lambda x: -x["pct_below"])
            alerts += watching[:fill_to - len(alerts)]
        return alerts

def get_tax_harvesting_opportunities(min_loss_amount: float = 1000.0, currency_filter: str = "All") -> list:
    # Use parameter-keyed cache so different thresholds don't return wrong data
    with _cache_lock:
        cache_key = _harvesting_cache.get("_key")
        if (_harvesting_cache["data"] is not None and cache_key == min_loss_amount and _harvesting_cache.get("currency") == currency_filter):
            return _harvesting_cache["data"]

    opportunities = []
    with db_session() as conn:
        cursor = conn.cursor()
        # Fetch current prices (with fallback to previous_close)
        cursor.execute("SELECT symbol, COALESCE(NULLIF(current_price, 0.0), previous_close) FROM marketdata")
        prices = {r[0]: float(r[1] or 0.0) for r in cursor.fetchall()}

        # ── Ground-truth net positions from the database ──────────────
        # This catches ghost holdings caused by unmatched sells (intraday
        # sells before buys, cross-broker transfers, import gaps, etc.)
        query_net = '''
            SELECT broker, symbol,
              SUM(CASE WHEN type='BUY' THEN qty ELSE 0 END) -
              SUM(CASE WHEN type='SELL' THEN qty ELSE 0 END)
            FROM trades
        '''
        params_net = []
        if currency_filter != "All":
            query_net += " WHERE currency = ? "
            params_net.append(currency_filter.upper())
        query_net += " GROUP BY broker, symbol"
        cursor.execute(query_net, params_net)
        net_positions = {}
        for broker, symbol, net_qty in cursor.fetchall():
            net_positions[(broker, symbol)] = float(net_qty or 0.0)

        # Fetch all trades for active holdings to build true FIFO lots
        query = "SELECT broker, symbol, type, qty, price, currency FROM trades "
        params = []
        if currency_filter != "All":
            query += "WHERE currency = ? "
            params.append(currency_filter.upper())
        query += "ORDER BY date ASC, type ASC, trade_id ASC"
        
        cursor.execute(query, params)
        
        lots = {} # (broker, symbol) -> list of {'qty', 'price'}
        currencies = {} # (broker, symbol) -> currency
        for broker, symbol, t_type, qty, price, currency in cursor.fetchall():
            qty = float(qty)
            price = float(price)
            key = (broker, symbol)
            currencies[key] = str(currency or "INR").upper()
            
            if key not in lots:
                lots[key] = []
            
            if t_type == 'BUY':
                lots[key].append({'qty': qty, 'price': price})
            elif t_type == 'SELL':
                rem = qty
                while rem > 0 and lots[key]:
                    consume = min(rem, lots[key][0]['qty'])
                    lots[key][0]['qty'] -= consume
                    rem -= consume
                    if lots[key][0]['qty'] <= 1e-6:
                        lots[key].pop(0)
        
        # Solve N+1 query: Fetch all holdings avg_prices in a single query
        cursor.execute("SELECT broker, symbol, avg_price FROM holdings")
        holding_avg_prices = {(row[0], row[1]): float(row[2] or 0.0) for row in cursor.fetchall()}

        # Analyze remaining FIFO lots for unrealized losses
        import time
        for i, ((broker, symbol), remaining_lots) in enumerate(lots.items()):
            if i % 50 == 0:
                time.sleep(0.001) # Yield GIL
            if not remaining_lots:
                continue

            # ── Skip closed / oversold positions ──────────────────────
            # The FIFO tracker can leave "ghost" lots when sell records
            # appear before their matching buys (intraday trade ordering,
            # cross-broker transfers, missing import data).  The net
            # position from the DB is the single source of truth.
            true_net = net_positions.get((broker, symbol), 0.0)
            if true_net <= 0.5:  # effectively zero or negative
                continue
                
            current_price = prices.get(symbol)
            if not current_price:
                # Optimized fallback: fetch from in-memory dict instead of db query
                current_price = holding_avg_prices.get((broker, symbol), 0.0)
                
            if current_price == 0.0:
                continue
                
            loss = 0.0
            loss_qty = 0.0
            cost = 0.0
            
            for lot in remaining_lots:
                if lot['qty'] <= 1e-6:
                    continue
                if lot['price'] > current_price:
                    loss += (lot['price'] - current_price) * lot['qty']
                    loss_qty += lot['qty']
                    cost += lot['price'] * lot['qty']
                    
            if loss >= min_loss_amount:
                avg_loss_price = cost / loss_qty if loss_qty > 0 else 0.0
                opportunities.append({
                    "symbol": symbol,
                    "broker": broker,
                    "qty": loss_qty,
                    "avg_price": avg_loss_price,
                    "current_price": current_price,
                    "unrealized_loss": loss,
                    "currency": currencies.get((broker, symbol), "INR")
                })

    # Sort highest loss first
    opportunities.sort(key=lambda x: x["unrealized_loss"], reverse=True)

    with _cache_lock:
        _harvesting_cache["data"], _harvesting_cache["ts"] = opportunities, time.time()
        _harvesting_cache["_key"] = min_loss_amount
        _harvesting_cache["currency"] = currency_filter
    return opportunities



def get_daily_gainers_losers(limit: int = 10, currency_filter: str = "All") -> tuple[list, list]:
    """
    Returns the top daily gainers and losers from the active portfolio.
    Calculates the % change based on current_price vs previous_close.
    Deduplicates symbols across multiple brokers.
    Returns (top_gainers, top_losers).
    """
    with db_session() as conn:
        cursor = conn.cursor()
        query = '''
            SELECT h.symbol, h.broker, m.current_price, m.previous_close, h.currency
            FROM holdings h
            JOIN marketdata m ON h.symbol = m.symbol
            WHERE h.qty > 0
        '''
        params = []
        if currency_filter != "All":
            query += " AND h.currency = ?"
            params.append(currency_filter.upper())
            
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
    symbol_dict = {}
    for row in rows:
        symbol, broker, cp, pc, currency = row
        if not cp or not pc or pc <= 0:
            continue
        if symbol not in symbol_dict:
            price_change = cp - pc
            pct_change = (price_change / pc) * 100
            symbol_dict[symbol] = {
                "symbol": symbol,
                "brokers": [broker],
                "current_price": cp,
                "prev_close": pc,
                "price_change": price_change,
                "pct_change": pct_change,
                "currency": currency
            }
        else:
            if broker and broker not in symbol_dict[symbol]["brokers"]:
                symbol_dict[symbol]["brokers"].append(broker)
                
    stocks = []
    for item in symbol_dict.values():
        item["broker"] = ", ".join(item["brokers"])
        stocks.append(item)
        
    # Sort for gainers (highest pct_change first)
    gainers = sorted(stocks, key=lambda x: x["pct_change"], reverse=True)
    # Sort for losers (lowest pct_change first)
    losers = sorted(stocks, key=lambda x: x["pct_change"])
    
    # Filter out 0% change or negative from gainers, and 0% change or positive from losers
    top_gainers = [s for s in gainers if s["pct_change"] > 0][:limit]
    top_losers = [s for s in losers if s["pct_change"] < 0][:limit]
    
    return top_gainers, top_losers
