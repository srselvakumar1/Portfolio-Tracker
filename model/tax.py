"""Realised capital gains for the Tax Report (FIFO matching).

Pure Python: no Tk and no database, so it can be unit-tested
(tests/test_tax.py). The Tax Report view reads the trades and passes them in.

    result = compute_realised_gains(trades, "2024-04-01", "2025-03-31",
                                    fx_rate=get_exchange_rate)

RULES
    * Shares are matched first-in, first-out separately for every
      (broker, symbol, currency): a sale at one broker is never matched with
      shares bought at another broker or in another currency.
    * Every matched piece of a sale is its own row. Its gain is
          sale value - cost - its share of the buy fee - its share of the sell fee.
      A lot's buy fee is used up as its shares are sold, so a lot sold in two
      halves books its whole buy fee exactly once.
    * INR trades follow the Indian rule for listed shares: held for MORE than
      12 months is long-term, otherwise short-term.
    * Other currencies (JPY ...) are not split: Japan taxes listed-share gains
      at one flat rate, so short/long term does not apply (term is None).
    * Sales with no matching buy (or more shares sold than were bought) are
      returned in unmatched_sells and are left out of the totals.
    * Trades whose date, quantity or price cannot be read are skipped and
      returned in skipped, with the reason.

INPUT
    Each trade is a mapping with the keys broker, symbol, type, date, qty,
    price, fee, currency, or a sequence in that order. Dates are YYYY-MM-DD.
    fx_rate(currency) converts each currency into the currency you want the
    amounts in (default: no conversion). It is called once per currency.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Iterable

EPS = 1e-9
_FIELDS = ("broker", "symbol", "type", "date", "qty", "price", "fee", "currency")

SHORT_TERM = "STCG"
LONG_TERM = "LTCG"

JPY_NOTE = ("JPY gains are not split into short and long term: Japan taxes "
            "listed-share gains at one flat rate (about 20.315%).")
OTHER_NOTE = ("{codes} gains are not split into short and long term: the "
              "12-month rule used here is the Indian one.")


@dataclass
class GainRow:
    """One matched piece of a sale (amounts already converted by fx_rate)."""
    broker: str
    symbol: str
    currency: str        # currency the trade was made in
    buy_date: str        # YYYY-MM-DD
    sell_date: str
    qty: float
    buy_price: float     # per share
    sell_price: float    # per share
    buy_fee: float       # this piece's share of the buy fee
    sell_fee: float      # this piece's share of the sell fee
    days: int            # days held
    term: str | None     # "STCG", "LTCG", or None when not split (non-INR)
    pnl: float           # gain (+) or loss (-) after fees

    @property
    def cost(self) -> float:
        return self.qty * self.buy_price

    @property
    def proceeds(self) -> float:
        return self.qty * self.sell_price


@dataclass
class UnmatchedSell:
    """A sale (or the part of one) for which no earlier buy was found."""
    broker: str
    symbol: str
    currency: str
    date: str
    qty: float           # shares that could not be matched
    sold_qty: float      # shares in the whole sale
    price: float         # per share, converted


@dataclass
class SkippedTrade:
    """A trade that could not be read and was left out of the matching."""
    broker: str
    symbol: str
    type: str
    date: str            # as stored
    reason: str


@dataclass
class TaxResult:
    rows: list = field(default_factory=list)              # list[GainRow]
    short_term: float = 0.0                               # INR, held 12 months or less
    long_term: float = 0.0                                # INR, held more than 12 months
    not_split: float = 0.0                                # non-INR gains (no short/long split)
    unmatched_sells: list = field(default_factory=list)   # list[UnmatchedSell]
    skipped: list = field(default_factory=list)           # list[SkippedTrade]
    notes: list = field(default_factory=list)             # list[str], plain English
    currencies: set = field(default_factory=set)          # currencies of the rows

    @property
    def net(self) -> float:
        """Net realised gains: every row added up (no exemption or set-off)."""
        return self.short_term + self.long_term + self.not_split


# ── helpers ───────────────────────────────────────────────────────────────────
def parse_date(value) -> date:
    """Read a YYYY-MM-DD date (a time part after it is ignored). Raises ValueError."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value or "").strip()
    try:
        # Fast path for the stored form; strptime is ~10x slower on 10,000s of rows.
        if len(s) >= 10 and s[4] == "-" and s[7] == "-" and s[:4].isdigit() and s[5:7].isdigit() and s[8:10].isdigit():
            if len(s) == 10 or not s[10].isdigit():
                return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
        raise ValueError
    except ValueError:
        raise ValueError(f"date '{s}' is not in YYYY-MM-DD form") from None


def _one_year_later(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:          # 29 Feb -> 28 Feb next year
        return d.replace(year=d.year + 1, day=28)


def is_long_term_india(buy: date, sell: date) -> bool:
    """Indian listed shares: long-term when held for more than 12 months."""
    return sell > _one_year_later(buy)


def _number(value, what: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} '{value}' is not a number") from None
    if x != x:  # NaN
        raise ValueError(f"{what} is not a number")
    return x


def _as_dict(t) -> dict:
    if isinstance(t, Mapping):
        return {k: t.get(k) for k in _FIELDS}
    return dict(zip(_FIELDS, t))


def _bound(d) -> date | None:
    if d is None or d == "":
        return None
    return parse_date(d)


# ── main function ─────────────────────────────────────────────────────────────
def compute_realised_gains(trades: Iterable, fy_start=None, fy_end=None, *,
                           fx_rate: Callable[[str], float] = lambda cur: 1.0) -> TaxResult:
    """Match sells to buys (FIFO) and return the realised gains of sells
    dated fy_start..fy_end (inclusive; None = no limit). See the module notes."""
    start, end = _bound(fy_start), _bound(fy_end)
    result = TaxResult()

    # 1. Read and check every trade.
    clean = []
    for i, raw in enumerate(trades):
        t = _as_dict(raw)
        broker = str(t.get("broker") or "").strip()
        symbol = str(t.get("symbol") or "").strip()
        ttype = str(t.get("type") or "").strip().upper()
        currency = str(t.get("currency") or "INR").strip().upper() or "INR"
        try:
            if ttype not in ("BUY", "SELL"):
                raise ValueError(f"trade type '{t.get('type')}' is not BUY or SELL")
            d = parse_date(t.get("date"))
            qty = _number(t.get("qty"), "quantity")
            price = _number(t.get("price"), "price")
            fee = _number(t.get("fee") or 0.0, "fee")
            if qty <= 0:
                raise ValueError("quantity is zero or negative")
            if price < 0:
                raise ValueError("price is negative")
        except ValueError as e:
            result.skipped.append(SkippedTrade(broker, symbol, ttype, str(t.get("date") or ""), str(e)))
            continue
        clean.append((d, 0 if ttype == "BUY" else 1, i, broker, symbol, ttype, qty, price, fee, currency))

    # Oldest first; on the same day buys come before sells.
    clean.sort(key=lambda x: (x[0], x[1], x[2]))

    rates: dict[str, float] = {}

    def rate_for(cur: str) -> float:
        if cur not in rates:
            rates[cur] = float(fx_rate(cur))
        return rates[cur]

    # 2. FIFO matching per (broker, symbol, currency).
    lots: dict[tuple, deque] = {}
    for d, _order, _i, broker, symbol, ttype, qty, price, fee, currency in clean:
        key = (broker, symbol, currency)
        queue = lots.get(key)
        if queue is None:
            queue = lots[key] = deque()
        rate = rate_for(currency)

        if ttype == "BUY":
            queue.append({"date": d, "qty": qty, "price": price * rate, "fee": fee * rate})
            continue

        in_window = (start is None or d >= start) and (end is None or d <= end)
        remaining = qty
        sell_fee_total = fee * rate
        while remaining > EPS and queue:
            lot = queue[0]
            take = min(remaining, lot["qty"])
            # This piece's share of the lot's remaining fee; the lot keeps the rest.
            buy_fee = lot["fee"] * (take / lot["qty"])
            sell_fee = sell_fee_total * (take / qty)
            lot["fee"] -= buy_fee
            lot["qty"] -= take
            remaining -= take

            if in_window:
                days = (d - lot["date"]).days
                if currency == "INR":
                    term = LONG_TERM if is_long_term_india(lot["date"], d) else SHORT_TERM
                else:
                    term = None
                pnl = take * price * rate - take * lot["price"] - buy_fee - sell_fee
                result.rows.append(GainRow(
                    broker=broker, symbol=symbol, currency=currency,
                    buy_date=lot["date"].isoformat(), sell_date=d.isoformat(),
                    qty=take, buy_price=lot["price"], sell_price=price * rate,
                    buy_fee=buy_fee, sell_fee=sell_fee, days=days, term=term, pnl=pnl,
                ))
                result.currencies.add(currency)
                if term == SHORT_TERM:
                    result.short_term += pnl
                elif term == LONG_TERM:
                    result.long_term += pnl
                else:
                    result.not_split += pnl

            if lot["qty"] <= EPS:
                queue.popleft()

        if remaining > EPS and in_window:
            result.unmatched_sells.append(UnmatchedSell(
                broker=broker, symbol=symbol, currency=currency, date=d.isoformat(),
                qty=remaining, sold_qty=qty, price=price * rate,
            ))

    # 3. Plain-English notes about the rules that were applied.
    others = sorted(c for c in result.currencies if c not in ("INR", "JPY"))
    if "JPY" in result.currencies:
        result.notes.append(JPY_NOTE)
    if others:
        result.notes.append(OTHER_NOTE.format(codes=", ".join(others)))
    return result
