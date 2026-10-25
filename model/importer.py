"""Checking trades before a bulk import (a CSV file or rows pasted on the Trade Entry page).

Everything here is plain Python and pandas with no Tk, so it can be tested on its
own (tests/test_importer.py) and run in a background thread.

How the Trade Entry page uses it:

    df = read_csv_file(path)                 # or parse_pasted_text(text)
    missing = missing_columns(df)            # e.g. ["price"]: tell the user, stop
    saved_keys, saved_ids = existing_trade_index(rows_from_the_trades_table)
    result = validate_rows(df, default_broker="Kite", default_currency="INR",
                           broker_currencies={"Kite": "INR", "NOMURA": "JPY"},
                           existing_keys=saved_keys, existing_ids=saved_ids,
                           today=date.today())
    result.summary()                         # "12 will be imported, 1 rejected, 3 look like duplicates"
    crud.add_trades_batch(result.trades_to_import())

Rules (each rejected row gets every reason that applies, in plain English):
  * date, symbol, type, qty and price are required; a blank one rejects the row.
  * Dates may be ISO (2024-03-05) or day-first (05-03-2024, 05/03/2024, 05.03.2024),
    plus 05-Mar-2024 / 2024-Mar-05 style. Day-first means 05-03-2024 is 5 March.
    Dates in the future are rejected.
  * type must be BUY or SELL (any capitalisation).
  * qty and price must be numbers above 0; commas, spaces and ₹ ¥ $ £ € are ignored,
    so "1,000" is 1000. INR quantities must be whole shares.
  * A blank fee is worked out with the Indian (NSE) charges for INR trades only;
    other currencies get 0.
  * The currency comes from the row's currency column, else the broker's currency,
    else the default currency.
  * A blank trade_id gets a new unique id (never the text "nan").
  * Likely duplicates are flagged, not imported silently:
      - "id"    the trade id is already saved for that broker, or used twice in the
                file (these can never be imported again);
      - "saved" same broker, date, symbol, type, qty and price as a trade you already
                have (counted, so a file with 3 identical rows matches 3 saved trades);
      - "file"  same as an earlier row of this file (only for rows without their own
                trade id: an order filled in parts can look like this).
    Importing the same file twice therefore adds nothing the second time.
"""

from __future__ import annotations

import csv
import io
import math
import re
import time
import warnings
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Iterable, NamedTuple

import pandas as pd

REQUIRED_COLUMNS = ("date", "symbol", "type", "qty", "price")
OPTIONAL_COLUMNS = ("broker", "fee", "currency", "trade_id")

# Other spellings of the column names (after lower-casing and turning spaces into _)
COLUMN_ALIASES = {
    "trade_date": "date",
    "trade_type": "type",
    "quantity": "qty",
    "fees": "fee",
    "tradeid": "trade_id",
}

CURRENCY_SYMBOLS = {"INR": "₹", "JPY": "¥", "USD": "$", "GBP": "£", "CNY": "¥", "EUR": "€"}

# Usual largest quantity and price per currency. Anything above is not refused,
# only questioned ("Are you sure?"), because real trades can be bigger
# (Japanese lots are often 1,000+ shares; MRF trades above ₹1,00,000).
SANITY_LIMITS = {
    "INR": (5_000, 200_000),
    "JPY": (20_000, 100_000),
    "USD": (5_000, 10_000),
    "GBP": (10_000, 10_000),
    "EUR": (10_000, 10_000),
}
DEFAULT_LIMITS = (10_000, 100_000)

_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",          # ISO first: 2024-03-05 is 5 March
    "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",          # day-first: 05-03-2024 is 5 March
    "%Y-%b-%d", "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
)
_MONEY_CHARS = re.compile(r"[₹¥$£€,\s ]")
_CODE_RE = re.compile(r"^[A-Z]{3}$")


class ImportProblem(ValueError):
    """A whole file or paste can't be used (the message is meant for the user)."""


class RejectedRow(NamedTuple):
    row: int        # data row number, 1 = first row under the header
    reason: str     # every problem with the row, joined with "; "
    raw: dict       # the row as it was in the file (column -> text)


class DuplicateRow(NamedTuple):
    row: int
    reason: str
    trade: tuple    # same shape as ImportResult.valid items
    kind: str       # "id", "saved" or "file" (see the module docstring)


@dataclass
class ImportResult:
    valid: list = field(default_factory=list)       # tuples for crud.add_trades_batch:
    #   (trade_id, broker, date, symbol, type, qty, price, fee, currency)
    valid_rows: list = field(default_factory=list)  # the row number of each `valid` item
    rejected: list = field(default_factory=list)    # RejectedRow items
    duplicates: list = field(default_factory=list)  # DuplicateRow items
    warnings: list = field(default_factory=list)    # "Row 4: ..." notes that don't stop the import
    total: int = 0                                  # rows looked at

    def duplicate_count(self, kind: str) -> int:
        return sum(1 for d in self.duplicates if d.kind == kind)

    def trades_to_import(self, skip_saved: bool = True, skip_repeats: bool = False) -> list:
        """The trades to save. Rows whose trade id is already used are never included."""
        out = list(self.valid)
        for d in self.duplicates:
            if (d.kind == "saved" and not skip_saved) or (d.kind == "file" and not skip_repeats):
                out.append(d.trade)
        return out

    def skipped_duplicates(self, skip_saved: bool = True, skip_repeats: bool = False) -> list:
        return [d for d in self.duplicates
                if d.kind == "id" or (d.kind == "saved" and skip_saved) or (d.kind == "file" and skip_repeats)]

    def summary(self, skip_saved: bool = True, skip_repeats: bool = False) -> str:
        n = len(self.trades_to_import(skip_saved, skip_repeats))
        d = len(self.duplicates)
        dup = "looks like a duplicate" if d == 1 else "look like duplicates"
        return f"{n} will be imported, {len(self.rejected)} rejected, {d} {dup}"


# ── Reading ─────────────────────────────────────────────────────────────────────
def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case the column names, turn spaces/hyphens into _, apply COLUMN_ALIASES."""
    names = []
    for c in df.columns:
        n = str(c).replace("﻿", "").strip().lower()
        n = re.sub(r"[\s\-]+", "_", n)
        names.append(n)
    taken = set(names)
    final = []
    for n in names:
        target = COLUMN_ALIASES.get(n)
        if target and target not in taken:
            taken.add(target)
            final.append(target)
        else:
            final.append(n)
    out = df.copy()
    out.columns = final
    return out


def missing_columns(df: pd.DataFrame) -> list:
    return [c for c in REQUIRED_COLUMNS if c not in df.columns]


def _drop_blank_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    filled = df.astype(str).apply(lambda col: col.str.strip()).ne("")
    return df[filled.any(axis=1)]


def _too_many_values(line_no: int, saw: int, expected: int) -> str:
    return (f"Line {line_no} has {saw} values but the header has {expected} columns. "
            "Check for an extra comma (write 1000 instead of 1,000, or put it in quotes).")


def _check_field_counts(text: str, sep: str) -> None:
    """Refuse rows with more values than the header: pandas would silently drop the
    extra ones, so 3,500 written without quotes would be saved as 3."""
    reader = csv.reader(io.StringIO(text), delimiter=sep, skipinitialspace=True)
    expected = None
    for fields in reader:
        if expected is None:
            if not any(f.strip() for f in fields):
                continue
            expected = len(fields)
            continue
        extra = fields[expected:]
        if any(f.strip() for f in extra):
            raise ImportProblem(_too_many_values(reader.line_num, len(fields), expected))


def _read(text: str, sep: str) -> pd.DataFrame:
    _check_field_counts(text, sep)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", pd.errors.ParserWarning)   # trailing empty values
            df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False,
                             index_col=False, skipinitialspace=True)
    except pd.errors.EmptyDataError:
        raise ImportProblem("There are no rows to import.")
    except (pd.errors.ParserError, csv.Error):
        raise ImportProblem("The rows couldn't be read. Make sure the first line is a header "
                            "like: date,symbol,type,qty,price")
    return _drop_blank_rows(normalize_columns(df))


def _pick_separator(header: str) -> str:
    if "\t" in header:
        return "\t"
    if "," in header:
        return ","
    return ";" if ";" in header else ","


def parse_pasted_text(text: str) -> pd.DataFrame:
    """Turn pasted rows (tab, comma or semicolon separated, with a header) into a DataFrame."""
    raw = (text or "").strip()
    if not raw:
        raise ImportProblem("Nothing pasted yet.")
    return _read(raw, _pick_separator(raw.splitlines()[0]))


def read_csv_file(path: str) -> pd.DataFrame:
    """Read a CSV file, trying the usual text encodings (a UTF-8 BOM is handled)."""
    for enc in ("utf-8-sig", "cp1252", "latin1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                text = f.read()
        except UnicodeDecodeError:
            continue
        except OSError:
            raise ImportProblem("The file couldn't be opened. Is it still there?")
        text = text.strip()
        if not text:
            raise ImportProblem("The file is empty.")
        return _read(text, _pick_separator(text.splitlines()[0]))
    raise ImportProblem("The file's text couldn't be read. Save it as CSV (UTF-8) and try again.")


# ── Small parsers ───────────────────────────────────────────────────────────────
def _clean(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    s = str(v).strip().strip("'\"").strip()
    return "" if s.lower() in ("nan", "none", "null", "nat") else s


def parse_number(text) -> tuple[float | None, str]:
    """(value, "") or (None, "missing") or (None, "bad")."""
    s = _clean(text)
    if not s:
        return None, "missing"
    s = _MONEY_CHARS.sub("", s)
    if s.upper().startswith("RS."):
        s = s[3:]
    try:
        v = float(s)
    except ValueError:
        return None, "bad"
    if not math.isfinite(v):
        return None, "bad"
    return v, ""


def parse_date(text) -> str | None:
    """Return the date as YYYY-MM-DD, or None if it can't be read. Day-first, never US month-first."""
    s = _clean(text)
    if not s:
        return None
    # "2024-01-15 00:00:00" / "2024-01-15T09:15:00" from spreadsheets: keep the date part
    if len(s) > 10 and s[:4].isdigit() and s[10] in " T":
        s = s[:10]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_type(text) -> str | None:
    s = _clean(text).upper()
    return s if s in ("BUY", "SELL") else None


def money(value: float, currency: str = "INR") -> str:
    code = (currency or "INR").upper()
    sym = CURRENCY_SYMBOLS.get(code, code + " ")
    sign = "-" if value < 0 else ""
    return f"{sign}{sym}{abs(value):,.2f}"


def trade_key(broker, date_s, symbol, t_type, qty, price) -> tuple:
    """What two trades must share to look like the same trade."""
    return (str(broker or "").strip(), str(date_s or "").strip(), str(symbol or "").strip().upper(),
            str(t_type or "").strip().upper(), round(float(qty or 0), 4), round(float(price or 0), 2))


def existing_trade_index(rows: Iterable) -> tuple[Counter, set]:
    """From (broker, trade_id, date, symbol, type, qty, price) rows of saved trades, build
    (Counter of trade_key -> how many, set of (broker, trade_id))."""
    keys: Counter = Counter()
    ids: set = set()
    for broker, trade_id, d, sym, t, q, p in rows:
        try:
            keys[trade_key(broker, d, sym, t, q, p)] += 1
        except (TypeError, ValueError):
            pass
        ids.add((str(broker or "").strip(), str(trade_id or "").strip()))
    return keys, ids


def sanity_warnings(qty: float, price: float, currency: str = "INR", last_price: float | None = None) -> list:
    """Reasons a trade looks unusual (for an "Are you sure?" question). Empty if it looks normal."""
    code = (currency or "INR").upper()
    max_qty, max_price = SANITY_LIMITS.get(code, DEFAULT_LIMITS)
    out = []
    if qty > max_qty:
        out.append(f"Quantity {qty:,g} is more than the usual {max_qty:,} for {code} trades.")
    if price > max_price:
        out.append(f"Price {money(price, code)} is more than the usual {money(max_price, code)} for {code} trades.")
    if last_price and last_price > 0 and price > 0 and (price > last_price * 3 or price < last_price / 3):
        out.append(f"Price {money(price, code)} is far from the last known price {money(last_price, code)}.")
    return out


def indian_fees(t_type: str, qty: float, price: float) -> float:
    from model.engine import calculate_trade_fees
    return float(calculate_trade_fees(t_type, qty, price, is_delivery=True) or 0.0)


# ── Checking ────────────────────────────────────────────────────────────────────
def validate_rows(
    df: pd.DataFrame,
    *,
    default_broker: str = "",
    default_currency: str = "INR",
    broker_currencies: dict | None = None,
    existing_keys=None,
    existing_ids=None,
    today: date | None = None,
    fee_fn: Callable[[str, float, float], float] | None = None,
    id_prefix: str = "IMP",
    id_stamp: str | None = None,
) -> ImportResult:
    """Check every row and sort it into valid / rejected / duplicates (see the module docstring).

    broker_currencies: {broker name: currency}. When given, a broker that isn't in it is
        rejected (it must be added in Settings first) and names are matched ignoring case.
    existing_keys: Counter (or set) of trade_key(...) for saved trades.
    existing_ids:  set of (broker, trade_id) for saved trades.
    fee_fn(type, qty, price): Indian fees for a blank fee on an INR trade (default: NSE rules).
    """
    today = today or date.today()
    today_s = today.strftime("%Y-%m-%d")
    fee_fn = fee_fn or indian_fees
    id_stamp = id_stamp or str(int(time.time() * 1000))
    default_currency = (default_currency or "INR").strip().upper()
    brokers = dict(broker_currencies or {})
    by_lower = {str(b).strip().lower(): b for b in brokers}
    has_broker_col = "broker" in df.columns

    saved_left = Counter()
    if existing_keys:
        if isinstance(existing_keys, Counter) or isinstance(existing_keys, dict):
            saved_left.update(dict(existing_keys))
        else:
            saved_left.update({k: 1 for k in existing_keys})
    saved_ids = set(existing_ids or ())

    res = ImportResult()
    first_row_for_key: dict = {}
    first_row_for_id: dict = {}
    cols = list(df.columns)

    for pos, (idx, rec) in enumerate(df.iterrows()):
        try:
            row_no = int(idx) + 1
        except (TypeError, ValueError):
            row_no = pos + 1
        raw = {c: _clean(rec[c]) for c in cols}
        res.total += 1
        reasons = []

        # Broker
        broker = raw.get("broker", "") or (default_broker or "").strip()
        if not broker:
            reasons.append("Broker is missing (choose one above)" if has_broker_col else "Choose a broker for this import")
        elif brokers:
            canon = by_lower.get(broker.lower())
            if canon is None:
                reasons.append(f"Broker '{broker}' isn't set up yet (add it in Settings first)")
            else:
                broker = canon

        # Date
        d_txt = raw.get("date", "")
        trade_date = parse_date(d_txt)
        if not d_txt:
            reasons.append("Date is missing")
        elif trade_date is None:
            reasons.append(f"Date '{d_txt}' isn't a date I can read (use 2024-01-15 or 15-01-2024)")
        elif trade_date > today_s:
            reasons.append("Date is in the future")

        # Symbol and type
        symbol = raw.get("symbol", "").upper()
        if not symbol:
            reasons.append("Symbol is missing")
        t_txt = raw.get("type", "")
        t_type = normalize_type(t_txt)
        if not t_txt:
            reasons.append("Type is missing (BUY or SELL)")
        elif t_type is None:
            reasons.append(f"Type must be BUY or SELL (found '{t_txt}')")

        # Quantity and price
        qty, q_err = parse_number(raw.get("qty", ""))
        if q_err == "missing":
            reasons.append("Quantity is missing")
        elif q_err:
            reasons.append(f"Quantity '{raw.get('qty')}' is not a number")
        elif qty <= 0:
            reasons.append("Quantity must be more than 0")
        price, p_err = parse_number(raw.get("price", ""))
        if p_err == "missing":
            reasons.append("Price is missing")
        elif p_err:
            reasons.append(f"Price '{raw.get('price')}' is not a number")
        elif price <= 0:
            reasons.append("Price must be more than 0")

        # Currency
        c_txt = raw.get("currency", "").upper()
        broker_cur = str(brokers.get(broker, "") or "").strip().upper()
        if c_txt and not _CODE_RE.match(c_txt):
            reasons.append(f"Currency '{raw.get('currency')}' should be a 3-letter code like INR or JPY")
            currency = c_txt
        else:
            currency = c_txt or broker_cur or default_currency
        if qty is not None and not q_err and qty > 0 and currency == "INR" and abs(qty - round(qty)) > 1e-9:
            reasons.append("Quantity must be a whole number for INR trades")

        # Fee
        fee = 0.0
        f_txt = raw.get("fee", "")
        if f_txt:
            fee_v, f_err = parse_number(f_txt)
            if f_err:
                reasons.append(f"Fee '{f_txt}' is not a number")
            elif fee_v < 0:
                reasons.append("Fee can't be negative")
            else:
                fee = fee_v

        if reasons:
            res.rejected.append(RejectedRow(row_no, "; ".join(reasons), raw))
            continue

        if not f_txt and currency == "INR":
            try:
                fee = round(float(fee_fn(t_type, qty, price) or 0.0), 2)
            except Exception:
                fee = 0.0
                res.warnings.append(f"Row {row_no}: the fee couldn't be worked out, so 0 was used")

        if c_txt and broker_cur and c_txt != broker_cur:
            res.warnings.append(f"Row {row_no}: currency {c_txt} is not {broker}'s usual {broker_cur}")
        for w in sanity_warnings(qty, price, currency):
            res.warnings.append(f"Row {row_no}: {w}")

        own_id = raw.get("trade_id", "")
        trade_id = own_id or f"{id_prefix}_{id_stamp}_{row_no}"
        trade = (trade_id, broker, trade_date, symbol, t_type, float(qty), float(price), float(fee), currency)
        key = trade_key(broker, trade_date, symbol, t_type, qty, price)

        dup = None
        if own_id and (broker, own_id) in saved_ids:
            dup = DuplicateRow(row_no, f"Trade id {own_id} is already saved for {broker}", trade, "id")
            if saved_left.get(key, 0) > 0:   # that saved trade is now accounted for
                saved_left[key] -= 1
        elif own_id and (broker, own_id) in first_row_for_id:
            dup = DuplicateRow(row_no, f"Same trade id as row {first_row_for_id[(broker, own_id)]}", trade, "id")
        elif saved_left.get(key, 0) > 0:
            saved_left[key] -= 1
            dup = DuplicateRow(row_no, "Matches a trade you already have", trade, "saved")
        elif not own_id and key in first_row_for_key:
            dup = DuplicateRow(row_no, f"Same as row {first_row_for_key[key]} in this file", trade, "file")

        if own_id:
            first_row_for_id.setdefault((broker, own_id), row_no)
        first_row_for_key.setdefault(key, row_no)

        if dup:
            res.duplicates.append(dup)
        else:
            res.valid.append(trade)
            res.valid_rows.append(row_no)

    return res
