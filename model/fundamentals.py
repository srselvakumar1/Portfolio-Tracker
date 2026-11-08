"""Company figures for the valuation rules (model/valuation.py).

They are fetched from Yahoo Finance (in background threads or the price helper
only) and kept in a "fundamentals" table keyed by the canonical symbol ("INFY"
for INFY, INFY.NS and INFY.BO). Holdings, Watchlist, Valuation and the Dashboard
therefore all value a company from the same numbers.

* Latest figures (EPS, book value, ROE, cash flow, debt, dividend, analyst
  target) come from the quote info on every price refresh.
* Yearly figures (EPS and revenue for the last 4 years, and the P/E at each
  year end) need two more requests, so they are fetched at most once a week
  per company (HISTORY_MAX_AGE_DAYS).
* "state" remembers the last fair value and quality result between refreshes,
  for the SELL rules (fair value cut, quality check newly failed).

The table is created here (CREATE TABLE IF NOT EXISTS) the first time it is used.
"""
from __future__ import annotations

import json
import math
from contextlib import contextmanager
from datetime import datetime

from model.applog import log
from model.valuation import canonical, decide, load_assumptions, next_state

HISTORY_MAX_AGE_DAYS = 7

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS fundamentals (
        symbol            TEXT PRIMARY KEY,
        inputs            TEXT NOT NULL DEFAULT '{}',
        inputs_updated_at TEXT DEFAULT '',
        state             TEXT NOT NULL DEFAULT '{}',
        updated_at        TEXT DEFAULT ''
    )
"""
_schema_ready: set = set()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


# ── Reading Yahoo's answers (no database) ─────────────────────────────────────

def dividend_yield_pct(info: dict):
    """Dividend yield in percent, from the dividend and the price when possible
    (yfinance 1.x gives dividendYield in percent, older versions as a fraction)."""
    rate = _num(info.get("dividendRate")) or _num(info.get("trailingAnnualDividendRate"))
    price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice")) or _num(info.get("previousClose"))
    if rate and price and price > 0:
        return rate / price * 100.0
    dy = _num(info.get("dividendYield"))
    if dy is not None:
        return dy
    tdy = _num(info.get("trailingAnnualDividendYield"))
    return tdy * 100.0 if tdy is not None else None


def info_inputs(symbol: str, info: dict, now: str | None = None) -> dict:
    """The latest figures from a quote's info. Call only for a successful answer."""
    from model.engine import is_placeholder_eps
    info = info or {}
    price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice")) or _num(info.get("previousClose"))
    eps = _num(info.get("trailingEps"))
    if eps is not None and is_placeholder_eps(eps, info.get("trailingPE"), price):
        eps = None          # EPS 1.00 with P/E = price stands for "unknown"
    de = _num(info.get("debtToEquity"))
    count = _num(info.get("numberOfAnalystOpinions"))
    now = now or _now()
    return {
        "symbol": canonical(symbol),
        "price": price,                                     # the price these figures came with
        "price_at": now if price else None,
        "currency": str(info.get("currency") or "").upper() or None,
        # the currency of the yearly figures (Infosys reports in USD while trading in INR)
        "financial_currency": str(info.get("financialCurrency") or "").upper() or None,
        "eps_ttm": eps,
        "bvps": _num(info.get("bookValue")),
        "roe": _num(info.get("returnOnEquity")),          # fraction (0.25 = 25%)
        "fcf": _num(info.get("freeCashflow")),
        "debt_to_equity": de / 100.0 if de is not None else None,   # Yahoo gives percent
        "sector": info.get("sector") or "",
        "industry": info.get("industry") or "",
        "dividend_yield": dividend_yield_pct(info),        # percent
        "analyst_target": _num(info.get("targetMeanPrice")),
        "analyst_count": int(count) if count else None,
        "info_updated_at": now,
    }


def history_inputs(ticker, fin=None, now: str | None = None) -> dict:
    """Yearly EPS and revenue (newest first) and the P/E at each year end.
    Network: ticker.financials (unless `fin` is given) and 5 years of monthly prices."""
    import pandas as pd
    out: dict = {}
    eps_series = None
    try:
        if fin is None or getattr(fin, "empty", True):
            fin = ticker.financials
    except Exception as exc:
        log.debug("Yearly figures failed: %s", exc)
        fin = None
    if fin is not None and not fin.empty:
        def row(label):
            if label not in fin.index:
                return None
            s = fin.loc[label]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[0]
            s = pd.to_numeric(s, errors="coerce").dropna()
            return s.sort_index(ascending=False) if len(s) else None
        for label in ("Diluted EPS", "Basic EPS"):
            eps_series = row(label)
            if eps_series is not None:
                break
        if eps_series is not None:
            out["eps_annual"] = [round(float(v), 4) for v in eps_series.values][:5]
            out["eps_years"] = [str(i)[:10] for i in eps_series.index][:5]
        rev = row("Total Revenue")
        if rev is not None:
            out["revenue_annual"] = [float(v) for v in rev.values][:5]
    if eps_series is not None:
        try:
            hist = ticker.history(period="5y", interval="1mo")
        except Exception as exc:
            log.debug("Price history failed: %s", exc)
            hist = None
        if hist is not None and not hist.empty and "Close" in hist:
            close = hist["Close"].dropna()
            if getattr(close.index, "tz", None) is not None:
                close.index = close.index.tz_localize(None)
            pes = []
            for when, e in eps_series.items():
                if e and e > 0:
                    before = close[close.index <= pd.Timestamp(when)]
                    if len(before):
                        pes.append(round(float(before.iloc[-1]) / float(e), 2))
            out["pe_history"] = pes
    out["inputs_updated_at"] = now or _now()
    return out


def extract_inputs(symbol: str, info: dict, ticker=None, fin=None, want_history: bool = True,
                   now: str | None = None) -> dict:
    """Latest figures, plus the yearly ones when `want_history` (network; background only)."""
    now = now or _now()
    inputs = info_inputs(symbol, info, now)
    if want_history and ticker is not None:
        inputs.update(history_inputs(ticker, fin, now))
    return inputs


# ── The fundamentals table ────────────────────────────────────────────────────

@contextmanager
def _session(conn=None):
    if conn is not None:
        yield conn
        return
    from model.database import db_session
    with db_session() as c:
        yield c


def ensure_schema(conn) -> None:
    from model import database
    key = database.DB_PATH
    if key not in _schema_ready:
        conn.execute(_SCHEMA)
        _schema_ready.add(key)


def save_inputs(symbol: str, new_inputs: dict, conn=None) -> None:
    """Merge new figures into the stored ones (yearly figures stay until replaced)."""
    key = canonical(symbol)
    if not key or not new_inputs:
        return
    with _session(conn) as c:
        ensure_schema(c)
        row = c.execute("SELECT inputs FROM fundamentals WHERE symbol = ?", (key,)).fetchone()
        try:
            cur = json.loads(row[0]) if row and row[0] else {}
        except ValueError:
            cur = {}
        cur.update(new_inputs)
        c.execute("""
            INSERT INTO fundamentals (symbol, inputs, inputs_updated_at, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET inputs = excluded.inputs,
                inputs_updated_at = excluded.inputs_updated_at, updated_at = excluded.updated_at
        """, (key, json.dumps(cur), cur.get("inputs_updated_at") or "", _now()))


def save_state(symbol: str, state: dict, conn=None) -> None:
    key = canonical(symbol)
    with _session(conn) as c:
        ensure_schema(c)
        c.execute("UPDATE fundamentals SET state = ? WHERE symbol = ?", (json.dumps(state or {}), key))


def load_records(symbols=None, conn=None) -> dict:
    """{canonical symbol: {"inputs": {...}, "state": {...}}} for `symbols` (all when None)."""
    out: dict = {}
    with _session(conn) as c:
        ensure_schema(c)
        if symbols is None:
            rows = c.execute("SELECT symbol, inputs, state FROM fundamentals").fetchall()
        else:
            keys = sorted({canonical(s) for s in symbols if s})
            rows = []
            for i in range(0, len(keys), 500):
                part = keys[i:i + 500]
                rows += c.execute(f"SELECT symbol, inputs, state FROM fundamentals WHERE symbol IN "
                                  f"({','.join('?' * len(part))})", part).fetchall()
    for sym, inputs, state in rows:
        try:
            out[sym] = {"inputs": json.loads(inputs or "{}"), "state": json.loads(state or "{}")}
        except ValueError:
            continue
    return out


def needs_history(symbols, conn=None, max_age_days: int = HISTORY_MAX_AGE_DAYS) -> set:
    """The symbols (as given) whose yearly figures are missing or older than max_age_days."""
    by_key: dict = {}
    for s in symbols:
        if s and "=" not in str(s) and not str(s).startswith("^"):
            by_key.setdefault(canonical(s), []).append(s)
    if not by_key:
        return set()
    with _session(conn) as c:
        ensure_schema(c)
        fresh = set()
        keys = list(by_key)
        for i in range(0, len(keys), 500):
            part = keys[i:i + 500]
            for sym, at in c.execute(f"SELECT symbol, inputs_updated_at FROM fundamentals WHERE symbol IN "
                                     f"({','.join('?' * len(part))})", part).fetchall():
                try:
                    if at and (datetime.now() - datetime.strptime(at[:19], "%Y-%m-%d %H:%M:%S")).days < max_age_days:
                        fresh.add(sym)
                except ValueError:
                    pass
    return {s for k, syms in by_key.items() if k not in fresh for s in syms}


def market_prices(symbols, conn=None) -> dict:
    """{symbol: (price, last updated)} from the marketdata table (price > 0 only)."""
    out: dict = {}
    syms = [s for s in set(symbols) if s]
    if not syms:
        return out
    with _session(conn) as c:
        for i in range(0, len(syms), 500):
            part = syms[i:i + 500]
            for sym, price, upd in c.execute(
                    f"SELECT symbol, COALESCE(NULLIF(current_price, 0), previous_close), last_updated "
                    f"FROM marketdata WHERE symbol IN ({','.join('?' * len(part))})", part).fetchall():
                if price and price > 0:
                    out[sym] = (float(price), upd)
    return out


def best_price(market, inputs) -> tuple:
    """(price, date) — the newest of the marketdata price (price, last updated) and the
    price saved with the company figures. (None, None) when there is neither."""
    cands = []
    if market and _num(market[0]) and market[0] > 0:
        cands.append((str(market[1] or ""), float(market[0])))
    p = _num((inputs or {}).get("price"))
    if p and p > 0:
        cands.append((str(inputs.get("price_at") or ""), p))
    if not cands:
        return None, None
    when, price = max(cands)
    return price, when or None


def evaluate(symbol: str, price, price_date=None, records: dict | None = None, assumptions: dict | None = None):
    """The decision for `symbol` at `price`, from the stored figures (read-only)."""
    key = canonical(symbol)
    rec = (records if records is not None else load_records([key])).get(key) or {}
    return decide(rec.get("inputs"), price, assumptions or load_assumptions(), rec.get("state"), price_date)


def record(symbol: str, price, price_date=None, conn=None, assumptions: dict | None = None):
    """evaluate() and remember the result (fair value, quality) for the SELL rules.
    Call at refresh time only, not when a page is just showing a stock."""
    key = canonical(symbol)
    A = assumptions or load_assumptions()
    with _session(conn) as c:
        rec = load_records([key], c).get(key)
        if not rec:
            return decide(None, price, A)
        first = decide(rec["inputs"], price, A, rec["state"], price_date)
        state = next_state(rec["state"], first, A)
        save_state(key, state, c)
        # Decide again with what was just remembered, so a fair-value cut or a newly failed
        # quality check shows as SELL now, on every page, not one refresh later
        return decide(rec["inputs"], price, A, state, price_date)
