
from model.database import db_session
from datetime import datetime
import time
import math
import threading
import concurrent.futures

# ── Trade history materialized calculations (trade_calcs) ───────────────────
_trade_calcs_lock = threading.Lock()
_trade_calcs_built_this_session = False
_trade_calcs_rebuild_inflight = False


def rebuild_trade_calcs():
    """Rebuild materialized per-trade running stats into trade_calcs.

    This replaces the expensive per-filter pandas running-state calculation in the
    Trade History view. It reads trades once (chronological) and writes computed
    columns (run_qty, avg_cost, running_pnl) keyed by (broker, trade_id).
    """
    global _trade_calcs_built_this_session

    # Pull all trades once
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT broker, trade_id, date, symbol, type, qty, price, fee FROM trades ORDER BY date ASC"
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
                ac = ((rq * ac) + (q * p) + f) / new_qty
            else:
                ac = 0.0
            rq = new_qty
        else:  # SELL
            # Realized PnL based on current avg cost
            if ac > 0 and q > 0:
                trade_pnl = (p - ac) * q - f
                rz += trade_pnl
            rq = max(0.0, rq - q)
            if rq == 0:
                ac = 0.0

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

def calculate_intrinsic_value(eps: float, growth_rate: float = 0.12, discount_rate: float = 0.10, terminal_multiple: float = 15.0) -> float:
    """Calculates Intrinsic Value using a 5-year DCF snapshot."""
    if eps is None or (isinstance(eps, float) and math.isnan(eps)) or eps <= 0:
        return 0.0

    cash_flows = []
    current_eps = eps
    for _ in range(5):
        current_eps *= (1 + growth_rate)
        cash_flows.append(current_eps)

    terminal_value = cash_flows[-1] * terminal_multiple

    iv = 0.0
    for i, cf in enumerate(cash_flows, start=1):
        iv += cf / ((1 + discount_rate) ** i)

    iv += terminal_value / ((1 + discount_rate) ** 5)
    return round(iv, 2)

def get_iv_signal(current_price: float, iv: float) -> str:
    """Calculates action signal based on Intrinsic Value."""
    if iv <= 0 or current_price <= 0: return "N/A"
    if current_price < (0.70 * iv): return "ACCUMULATE"
    elif current_price > (1.10 * iv): return "REDUCE"
    else: return "HOLD"

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

    for guess in guesses:
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

def _fetch_single_ticker(yf_sym: str, orig_sym: str, now: str):
    """Fetches a single ticker's data from yfinance. Runs isolated in a thread.

    Skips the redundant fast_info call — ticker.info already contains all needed fields.
    """
    try:
        import yfinance as yf
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

        previous_close = 0.0
        try:
            val = float(ticker.fast_info.previous_close)
            if not math.isnan(val): previous_close = val
        except Exception:
            pass
        if previous_close <= 0.0:
            previous_close = float(full_info.get('previousClose', 0.0) or
                                   full_info.get('regularMarketPreviousClose', current_price) or current_price)

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
            except Exception:
                pass

        eps = float(full_info.get('trailingEps', 0.0) or 0.0)
        iv = calculate_intrinsic_value(eps)
        signal = get_iv_signal(current_price, iv)

        mkt_row = (
            orig_sym, current_price, previous_close,
            float(full_info.get('fiftyTwoWeekLow', 0.0) or 0.0),
            float(full_info.get('fiftyTwoWeekHigh', 0.0) or 0.0),
            float(full_info.get('trailingPE', 0.0) or 0.0),
            eps,
            float(full_info.get('priceToBook', 0.0) or 0.0),
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

        return mkt_row, asset_row

    except Exception:
        # Return a safe blank record so the app doesn't crash on this symbol
        mkt_row = (orig_sym, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, '', '', '', now)
        asset_row = (orig_sym, 0.0, "N/A", 0.0, 0.0, 0.0, now)
        return mkt_row, asset_row

def fetch_and_update_market_data(symbols: list):
    """
    Fetches real-time data from yfinance concurrently to prevent UI freezing.
    Writes to the database in one lightning-fast bulk transaction.
    """
    if not symbols: return

    # Schema guard: ensure all target columns exist before we attempt to persist.
    # This does NOT fetch anything; it only allows refreshed data to be stored.
    try:
        from model.database import ensure_marketdata_schema
        ensure_marketdata_schema()
    except Exception:
        pass

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    yf_symbols = [s + ".NS" if not s.endswith(('.NS', '.BO')) else s for s in symbols]

    marketdata_records = []
    assets_records = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        futures = {executor.submit(_fetch_single_ticker, yf_sym, orig_sym, now): orig_sym 
                   for yf_sym, orig_sym in zip(yf_symbols, symbols)}

        try:
            # We remove the total timeout here to allow large batches to finish.
            # Individual futures still time out via future.result(_YFINANCE_TIMEOUT) below.
            for future in concurrent.futures.as_completed(futures):
                try:
                    m_row, a_row = future.result(timeout=_YFINANCE_TIMEOUT)
                    marketdata_records.append(m_row)
                    assets_records.append(a_row)
                    if future in futures: del futures[future]
                except Exception:
                    sym = futures.get(future, "Unknown")
                    marketdata_records.append((sym, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, '', '', '', now))
                    assets_records.append((sym, 0.0, "N/A", 0.0, 0.0, 0.0, now))
                    if future in futures: del futures[future]
        except Exception as e:
            # Catch unexpected loop failures (like KeyboardInterrupt)
            pass

        # Cleanup: capture any symbols that were totally missed/interrupted
        for f, sym in futures.items():
            if not any(r[0] == sym for r in marketdata_records):
                marketdata_records.append((sym, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, '', '', '', now))
                assets_records.append((sym, 0.0, "N/A", 0.0, 0.0, 0.0, now))

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
    with db_session() as conn:
        cursor = conn.cursor()

        # Fetch market prices as a simple dict — no pandas needed
        cursor.execute("SELECT symbol, current_price FROM marketdata")
        prices = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("SELECT broker, trade_id, date, symbol, type, qty, price, fee FROM trades ORDER BY date ASC")

        holdings_dict = {}

        for broker, trade_id, date_str, symbol, t_type, qty, price, fee in cursor.fetchall():
            key = (broker, symbol)
            qty = float(qty)
            price = float(price)
            fee = float(fee or 0.0)

            if key not in holdings_dict:
                holdings_dict[key] = {'qty': 0.0, 'cost': 0.0, 'realized_pnl': 0.0, 'cfs': [], 'earliest_date': date_str, 'total_fees': 0.0}

            h = holdings_dict[key]

            trade_date = datetime.strptime(date_str, '%Y-%m-%d')
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

            if data['qty'] > 0 or data['realized_pnl'] != 0 or data['total_fees'] > 0:
                avg_price = data['cost'] / data['qty'] if data['qty'] > 0 else 0.0

                if data['qty'] > 0 and len(data['cfs']) > 0:
                    current_price = prices.get(symbol) or prices.get(symbol + ".NS") or prices.get(symbol + ".BO") or 0.0
                    
                    # Core Fix: If the API failed and price is literally 0.0, fallback to cost basis
                    # so we don't artificially wipe out the entire value of the holdings.
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
                            years = (now - start_dt).days / 365.25
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

            records_to_insert.append((broker, symbol, data['qty'], avg_price, data['realized_pnl'], running_pnl, xirr_val, cagr_val, data['earliest_date'], data['total_fees']))


        # Rebuild holdings table
        cursor2 = conn.cursor()
        cursor2.execute("DELETE FROM holdings")
        cursor2.executemany('''
            INSERT INTO holdings (broker, symbol, qty, avg_price, realized_pnl, running_pnl, xirr, cagr, earliest_date, total_fees)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', records_to_insert)

    # After rebuilding holdings, also update and save dashboard metrics
    new_metrics = get_dashboard_metrics(force_refresh=True)
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

def calculate_overall_xirr(conn=None, broker_filter: str | None = None) -> float:
    """Calculate true XIRR for overall portfolio or specific broker from all trades.
    
    Collects all cash flows (BUY = negative, SELL = positive) and adds terminal 
    value as final cash flow. Uses Newton-Raphson solver for actual XIRR.
    """
    if conn is None:
        with db_session() as conn:
            return calculate_overall_xirr(conn=conn, broker_filter=broker_filter)
    
    try:
        cursor = conn.cursor()
        
        # Build WHERE clause for broker filter if provided
        where_clause = ""
        params = []
        if broker_filter:
            where_clause = "WHERE broker = ?"
            params = [broker_filter]
        
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
            WHERE h.qty > 0 OR h.running_pnl != 0
        '''
        if broker_filter:
            query_holdings += " AND h.broker = ?"
            cursor.execute(query_holdings, [broker_filter])
        else:
            cursor.execute(query_holdings)
        
        holdings_row = cursor.fetchone()
        current_val = holdings_row[0] or 0.0 if holdings_row else 0.0
        
        # Convert trades to cash flows
        cashflows = []
        for trade in trades:
            date_str, trade_type, qty, price, fee = trade
            trade_date = datetime.strptime(date_str, '%Y-%m-%d')
            
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
        
    except Exception as e:
        pass
        return 0.0


def get_dashboard_metrics(force_refresh: bool = False) -> dict:
    """Retrieve dashboard metrics (cached unless force_refresh=True)."""
    # 1. Check in-memory cache (thread-safe read)
    with _cache_lock:
        # "Calculate once" policy: keep cached metrics until explicitly invalidated
        # (e.g., after rebuild_holdings or manual market refresh).
        if not force_refresh and _metrics_cache["data"] is not None:
            return _metrics_cache["data"]

    # 2. Check DB stored metrics if not forcing a recalc
    if not force_refresh:
        stored = get_stored_dashboard_metrics()
        if stored:
            with _cache_lock:
                _metrics_cache["data"], _metrics_cache["ts"] = stored, time.time()
            return stored

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                SUM(h.qty * h.avg_price),
                SUM(h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)),
                SUM(h.running_pnl),
                SUM(CASE WHEN h.realized_pnl < 0 THEN h.realized_pnl ELSE 0 END),
                SUM(CASE WHEN ((h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)) - (h.qty * h.avg_price)) < 0 
                         THEN ((h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)) - (h.qty * h.avg_price)) ELSE 0 END),
                MIN(h.earliest_date)
            FROM holdings h
            LEFT JOIN marketdata m ON h.symbol = m.symbol
            WHERE h.qty > 0 OR h.running_pnl != 0
        ''')
        row = cursor.fetchone()

        invested, current_val = row[0] or 0.0, row[1] or 0.0
        overall_pnl = row[2] or 0.0
        overall_loss = row[3] or 0.0
        unrealized_loss = row[4] or 0.0
        earliest_date = row[5]

        unrealized_pnl = current_val - invested
        realized_pnl = overall_pnl - unrealized_pnl
        realized_loss = overall_loss

        # Calculate true XIRR from all trades (not simple ROI)
        overall_xirr = calculate_overall_xirr(conn)

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
        "overall_xirr": overall_xirr, "overall_cagr": overall_cagr
    }
    with _cache_lock:
        _metrics_cache["data"], _metrics_cache["ts"] = result, time.time()
    return result

def get_metrics_by_broker() -> dict:
    # "Calculate once" policy: keep cached broker metrics until explicitly invalidated.
    with _cache_lock:
        if _broker_metrics_cache["data"] is not None:
            return _broker_metrics_cache["data"]

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT h.broker, SUM(h.qty * h.avg_price), SUM(h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)),
                   SUM(h.running_pnl), SUM(CASE WHEN h.realized_pnl < 0 THEN h.realized_pnl ELSE 0 END),
                   SUM(CASE WHEN ((h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)) - (h.qty * h.avg_price)) < 0 
                            THEN ((h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)) - (h.qty * h.avg_price)) ELSE 0 END),
                   MIN(h.earliest_date)
            FROM holdings h
            LEFT JOIN marketdata m ON h.symbol = m.symbol
            WHERE h.qty > 0 OR h.running_pnl != 0
            GROUP BY h.broker
        ''')
        rows = cursor.fetchall()

        broker_metrics = {}
        for row in rows:
            broker = row[0]
            invested, current_val = row[1] or 0.0, row[2] or 0.0
            overall_pnl, overall_loss = row[3] or 0.0, row[4] or 0.0
            unrealized_loss = row[5] or 0.0
            earliest_date = row[6]

            unrealized_pnl = current_val - invested
            realized_pnl = overall_pnl - unrealized_pnl
            # Calculate true XIRR per broker based on all trades for that broker
            overall_xirr = calculate_overall_xirr(conn, broker_filter=broker)

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

            broker_metrics[broker] = {
                "total_invested": invested, "total_value": current_val,
                "overall_pnl": overall_pnl, "unrealized_pnl": unrealized_pnl,
                "realized_pnl": realized_pnl, "realized_loss": overall_loss, "unrealized_loss": unrealized_loss,
                "overall_xirr": overall_xirr, "overall_cagr": overall_cagr
            }

    with _cache_lock:
        _broker_metrics_cache["data"], _broker_metrics_cache["ts"] = broker_metrics, time.time()
    return broker_metrics

def get_top_worst_performers(limit: int = 3) -> dict:
    with _cache_lock:
        if _performers_cache["data"] is not None:
            return _performers_cache["data"]

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT h.symbol, SUM(h.qty), SUM(h.qty * h.avg_price), SUM(h.realized_pnl),
                   MAX(COALESCE(NULLIF(m.current_price, 0.0), h.avg_price))
            FROM holdings h LEFT JOIN marketdata m ON h.symbol = m.symbol
            WHERE h.qty > 0 GROUP BY h.symbol
        ''')
        rows = cursor.fetchall()

    performers = []
    for row in rows:
        cost, total_pnl = row[2], (row[1] * row[4] - row[2]) + row[3]
        performers.append({"symbol": row[0], "pnl": total_pnl, "pnl_pct": (total_pnl / cost * 100) if cost > 0 else 0})

    performers.sort(key=lambda x: x["pnl"], reverse=True)
    result = {
        "top": performers[:limit],
        "worst": list(reversed(performers[-limit:])) if performers else []
    }
    with _cache_lock:
        _performers_cache["data"], _performers_cache["ts"] = result, time.time()
    return result

def get_actionable_insights(limit: int = 10) -> list:
    with _cache_lock:
        if _insights_cache["data"] is not None:
            return _insights_cache["data"]

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DISTINCT h.symbol, a.action_signal, a.intrinsic_value, m.current_price
            FROM holdings h JOIN assets a ON h.symbol = a.symbol
            LEFT JOIN marketdata m ON h.symbol = m.symbol
            WHERE h.qty > 0 AND a.action_signal IN ('ACCUMULATE', 'REDUCE')
            ORDER BY ABS(a.intrinsic_value - m.current_price) / m.current_price DESC LIMIT ?
        ''', (limit,))
        result = [{"symbol": r[0], "signal": r[1], "iv": r[2], "current_price": r[3]} for r in cursor.fetchall()]

    with _cache_lock:
        _insights_cache["data"], _insights_cache["ts"] = result, time.time()
    return result

def get_tax_harvesting_opportunities(min_loss_amount: float = 1000.0) -> list:
    # Use parameter-keyed cache so different thresholds don't return wrong data
    with _cache_lock:
        cache_key = _harvesting_cache.get("_key")
        if (_harvesting_cache["data"] is not None and cache_key == min_loss_amount):
            return _harvesting_cache["data"]

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT h.symbol, h.broker, h.qty, h.avg_price, m.current_price,
                   (h.qty * h.avg_price) - (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)) as unrealized_loss
            FROM holdings h LEFT JOIN marketdata m ON h.symbol = m.symbol
            WHERE h.qty > 0 AND (h.qty * h.avg_price) - (h.qty * COALESCE(NULLIF(m.current_price, 0.0), h.avg_price)) >= ?
            ORDER BY unrealized_loss DESC
        ''', (min_loss_amount,))
        result = [{"symbol": r[0], "broker": r[1], "qty": r[2], "avg_price": r[3], "current_price": r[4], "unrealized_loss": r[5]} for r in cursor.fetchall()]

    with _cache_lock:
        _harvesting_cache["data"], _harvesting_cache["ts"] = result, time.time()
        _harvesting_cache["_key"] = min_loss_amount
    return result


