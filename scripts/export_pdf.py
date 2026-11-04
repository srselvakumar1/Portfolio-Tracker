"""The P&L Report as a PDF.

Every currency is included, whatever the page's currency filter shows, and figures are
never converted between currencies. For each currency: the key figures, the brokers,
P&L by broker as a bar chart, the open positions, and the biggest realised gains and
losses from closed positions.
"""
import os
from datetime import datetime
from xml.sax.saxutils import escape as _esc

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from model.applog import log
from model.database import db_session

# ── Look ─────────────────────────────────────────────────────────────────────
INK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#64748B")
LINE = colors.HexColor("#E2E8F0")
ZEBRA = colors.HexColor("#F8FAFC")
TILE = colors.HexColor("#F8FAFC")
GOOD = colors.HexColor("#15803D")
BAD = colors.HexColor("#B91C1C")
GOOD_BAR = colors.HexColor("#22C55E")
BAD_BAR = colors.HexColor("#EF4444")
GRADIENT = ((67, 56, 202), (124, 58, 237), (190, 24, 93))       # the app's header: indigo → violet → pink
ACCENTS = {"INR": colors.HexColor("#4338CA"), "JPY": colors.HexColor("#7C3AED")}
TILE_BARS = {"invested": colors.HexColor("#2563EB"), "value": colors.HexColor("#4338CA"),
             "xirr": colors.HexColor("#D97706")}

PAGE_W, PAGE_H = A4
MARGIN = 36
BAND = 46            # gradient band at the top of every page
CONTENT_W = PAGE_W - 2 * MARGIN

_SYMBOLS = {"INR": "₹", "JPY": "¥", "USD": "$", "GBP": "£", "CNY": "¥"}
_CURRENCY_NAMES = {"INR": "Indian rupee", "JPY": "Japanese yen", "USD": "US dollar"}

FONT, FONT_BOLD = "Helvetica", "Helvetica-Bold"
_HAS_RUPEE = False


def _register_fonts() -> None:
    """Helvetica from macOS (it has ₹ and ¥); Georgia next; else the built-in Helvetica with "Rs "."""
    global FONT, FONT_BOLD, _HAS_RUPEE
    if FONT != "Helvetica":
        return
    choices = (("/System/Library/Fonts/Helvetica.ttc", 0, "/System/Library/Fonts/Helvetica.ttc", 1),
               ("/System/Library/Fonts/Supplemental/Georgia.ttf", 0,
                "/System/Library/Fonts/Supplemental/Georgia Bold.ttf", 0))
    for reg_path, reg_idx, bold_path, bold_idx in choices:
        if not (os.path.exists(reg_path) and os.path.exists(bold_path)):
            continue
        try:
            pdfmetrics.registerFont(TTFont("PT-Regular", reg_path, subfontIndex=reg_idx))
            pdfmetrics.registerFont(TTFont("PT-Bold", bold_path, subfontIndex=bold_idx))
            FONT, FONT_BOLD, _HAS_RUPEE = "PT-Regular", "PT-Bold", True
            return
        except Exception:
            log.warning("PDF export: could not load the font %s", reg_path, exc_info=True)


# ── Numbers ──────────────────────────────────────────────────────────────────
def _symbol(cur: str) -> str:
    if cur == "INR" and not _HAS_RUPEE:
        return "Rs "
    return _SYMBOLS.get(cur, cur + " ")


def _money(v: float, cur: str, decimals: int = 0) -> str:
    """-₹1,234 (minus before the symbol); whole numbers unless decimals are asked for."""
    v = float(v or 0.0)
    return f"{'-' if v < -0.005 else ''}{_symbol(cur)}{abs(v):,.{decimals}f}"


def _signed(v: float, cur: str) -> str:
    """+₹1,234 / -₹1,234 for P&L."""
    v = float(v or 0.0)
    return f"{'+' if v >= 0 else '-'}{_symbol(cur)}{abs(v):,.0f}"


def _price(v: float, cur: str) -> str:
    return _money(v, cur, 0 if cur == "JPY" else 2)


def _pct(v) -> str:
    return f"{float(v or 0.0):+.1f}%"


def _qty(v: float) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def _tone(v: float):
    return GOOD if float(v or 0.0) >= 0 else BAD


def _when(text) -> str:
    try:
        return datetime.strptime(str(text)[:16], "%Y-%m-%d %H:%M").strftime("%d %b %Y, %H:%M")
    except ValueError:
        return "not fetched yet"


# ── Data ─────────────────────────────────────────────────────────────────────
def _report_data() -> dict:
    """Broker metrics, positions and XIRR for every currency (worker thread, no Tk)."""
    from model.engine import calculate_overall_xirr, get_metrics_by_broker

    metrics = get_metrics_by_broker(currency_filter="All", force_refresh=True)
    with db_session() as conn:
        rows = conn.execute("""
            SELECT h.broker, h.symbol, h.qty, h.avg_price,
                   COALESCE(NULLIF(m.current_price, 0.0), NULLIF(m.previous_close, 0.0), h.avg_price),
                   h.realized_pnl, UPPER(COALESCE(NULLIF(h.currency, ''), 'INR')), m.stock_name
            FROM holdings h LEFT JOIN marketdata m ON m.symbol = h.symbol
        """).fetchall()
        prices_at = conn.execute("SELECT MAX(last_updated) FROM marketdata").fetchone()[0]

    currencies: dict = {}

    def section(cur):
        return currencies.setdefault(cur, {"brokers": [], "open": [], "closed": []})

    for broker, d in metrics.items():
        section(str(d.get("currency") or "INR").upper())["brokers"].append((broker, d))
    for broker, symbol, qty, avg, price, realized, cur, name in rows:
        qty, avg, price, realized = (float(x or 0.0) for x in (qty, avg, price, realized))
        if qty > 1e-4:
            section(cur)["open"].append({
                "broker": broker, "symbol": symbol, "name": name or "", "qty": qty, "avg": avg, "price": price,
                "invested": qty * avg, "value": qty * price, "pnl": qty * (price - avg), "realized": realized})
        elif abs(realized) > 0.005:
            section(cur)["closed"].append({"broker": broker, "symbol": symbol, "name": name or "",
                                           "realized": realized})
    for cur, sec in currencies.items():
        try:
            sec["xirr"] = float(calculate_overall_xirr(currency_filter=cur) or 0.0)
        except Exception:
            log.warning("PDF export: XIRR for %s failed", cur, exc_info=True)
            sec["xirr"] = None
    return {"currencies": currencies, "prices_at": prices_at}


def _totals(sec: dict) -> dict:
    keys = ("total_invested", "total_value", "unrealized_pnl", "realized_pnl", "overall_pnl", "day_pnl")
    out = {k: sum(float(d.get(k) or 0.0) for _b, d in sec["brokers"]) for k in keys}
    out["return"] = out["overall_pnl"] / out["total_invested"] * 100 if out["total_invested"] else 0.0
    return out


# ── Building blocks ──────────────────────────────────────────────────────────
def _styles() -> dict:
    def st(name, **kw):
        kw.setdefault("fontName", FONT)
        kw.setdefault("textColor", INK)
        return ParagraphStyle(name, **kw)
    return {
        "title": st("title", fontName=FONT_BOLD, fontSize=22, leading=26),
        "lead": st("lead", fontSize=9.5, leading=13, textColor=MUTED),
        "h2": st("h2", fontName=FONT_BOLD, fontSize=12, leading=15, spaceBefore=14, spaceAfter=6),
        "note": st("note", fontSize=8, leading=10.5, textColor=MUTED),
        "tile_label": st("tile_label", fontSize=7.5, leading=9, textColor=MUTED),
        "tile_value": st("tile_value", fontName=FONT_BOLD, fontSize=14, leading=17),
        "tile_sub": st("tile_sub", fontSize=7.5, leading=9, textColor=MUTED),
        "sym": st("sym", fontName=FONT_BOLD, fontSize=8, leading=9.5),
        "name": st("name", fontSize=6.5, leading=8, textColor=MUTED),
        "section": st("section", fontName=FONT_BOLD, fontSize=16, leading=19, textColor=colors.white),
        "section_sub": st("section_sub", fontSize=8.5, leading=11, textColor=colors.white),
    }


def _table(data, widths, *, total_row=False, align_right_from=1, accent=INK, extra=()):
    """A zebra table with a coloured header row, rounded corners and an optional bold total row."""
    t = Table(data, colWidths=widths, repeatRows=1)
    last = len(data) - 1
    style = [
        ("FONTNAME", (0, 0), (-1, -1), FONT), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, last - 1 if total_row else last), [colors.white, ZEBRA]),
        ("LINEBELOW", (0, 1), (-1, last), 0.4, LINE),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]
    if total_row:
        style += [("FONTNAME", (0, last), (-1, last), FONT_BOLD), ("BACKGROUND", (0, last), (-1, last), LINE),
                  ("LINEABOVE", (0, last), (-1, last), 0.8, MUTED)]
    t.setStyle(TableStyle(style + list(extra)))
    return t


def _tile(label: str, value: str, sub: str, bar, value_color, styles) -> Table:
    """A rounded KPI tile: a coloured line on top, a small label, the figure and a note."""
    width = (CONTENT_W - 2 * 10) / 3
    vs = ParagraphStyle("v", parent=styles["tile_value"], textColor=value_color)
    t = Table([[Paragraph(_esc(label.upper()), styles["tile_label"])], [Paragraph(_esc(value), vs)],
               [Paragraph(_esc(sub), styles["tile_sub"])]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TILE), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LINEABOVE", (0, 0), (-1, 0), 2.5, bar), ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, 0), 9), ("BOTTOMPADDING", (0, -1), (-1, -1), 9),
        ("TOPPADDING", (0, 1), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -2), 0),
    ]))
    return t


def _tiles(cur: str, sec: dict, tot: dict, styles) -> Table:
    n_open = len(sec["open"])
    xirr = sec.get("xirr")
    tiles = [
        _tile("Invested", _money(tot["total_invested"], cur), f"{n_open} open position{'s' * (n_open != 1)}",
              TILE_BARS["invested"], INK, styles),
        _tile("Current value", _money(tot["total_value"], cur),
              f"Today {_signed(tot['day_pnl'], cur)}", TILE_BARS["value"], INK, styles),
        _tile("Total P&L", _signed(tot["overall_pnl"], cur), f"{_pct(tot['return'])} on the money invested",
              _tone(tot["overall_pnl"]), _tone(tot["overall_pnl"]), styles),
        _tile("Unrealised P&L", _signed(tot["unrealized_pnl"], cur), "On the shares you still hold",
              _tone(tot["unrealized_pnl"]), _tone(tot["unrealized_pnl"]), styles),
        _tile("Realised P&L", _signed(tot["realized_pnl"], cur), "Booked by selling",
              _tone(tot["realized_pnl"]), _tone(tot["realized_pnl"]), styles),
        _tile("XIRR", f"{xirr:+.2f}%" if xirr is not None else "—", "Yearly return, cash-flow weighted",
              TILE_BARS["xirr"], _tone(xirr or 0), styles),
    ]
    grid = Table([tiles[:3], tiles[3:]], colWidths=[(CONTENT_W - 20) / 3 + 10] * 2 + [(CONTENT_W - 20) / 3])
    grid.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
                              ("BOTTOMPADDING", (0, 1), (-1, 1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return grid


def _section_banner(cur: str, sec: dict, styles) -> Table:
    n_b = len(sec["brokers"])
    title = f"{_symbol(cur).strip()}  {cur} portfolio"
    sub = (f"{_CURRENCY_NAMES.get(cur, cur)}  ·  {n_b} broker{'s' * (n_b != 1)}  ·  "
           f"{len(sec['open'])} open, {len(sec['closed'])} closed positions")
    t = Table([[Paragraph(_esc(title), styles["section"])], [Paragraph(_esc(sub), styles["section_sub"])]],
              colWidths=[CONTENT_W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ACCENTS.get(cur, INK)),
                           ("ROUNDEDCORNERS", [8, 8, 8, 8]),
                           ("LEFTPADDING", (0, 0), (-1, -1), 14), ("TOPPADDING", (0, 0), (-1, 0), 10),
                           ("BOTTOMPADDING", (0, -1), (-1, -1), 10), ("TOPPADDING", (0, 1), (-1, 1), 1),
                           ("BOTTOMPADDING", (0, 0), (-1, 0), 0)]))
    return t


def _brokers_table(cur: str, sec: dict, tot: dict) -> Table:
    rows = sorted(sec["brokers"], key=lambda bd: float(bd[1].get("overall_pnl") or 0.0), reverse=True)
    data = [["Broker", "Invested", "Value", "Unrealised", "Realised", "Total P&L", "Return", "XIRR"]]
    extra = []
    for i, (broker, d) in enumerate(rows, start=1):
        inv, pnl = float(d.get("total_invested") or 0.0), float(d.get("overall_pnl") or 0.0)
        ret = pnl / inv * 100 if inv else 0.0
        xirr = float(d.get("overall_xirr") or 0.0)
        data.append([broker, _money(inv, cur), _money(d.get("total_value"), cur),
                     _signed(d.get("unrealized_pnl"), cur), _signed(d.get("realized_pnl"), cur),
                     _signed(pnl, cur), _pct(ret), f"{xirr:+.2f}%"])
        for col, v in ((3, d.get("unrealized_pnl")), (4, d.get("realized_pnl")), (5, pnl), (6, ret), (7, xirr)):
            extra.append(("TEXTCOLOR", (col, i), (col, i), _tone(v)))
    last = len(data)
    data.append(["Total", _money(tot["total_invested"], cur), _money(tot["total_value"], cur),
                 _signed(tot["unrealized_pnl"], cur), _signed(tot["realized_pnl"], cur),
                 _signed(tot["overall_pnl"], cur), _pct(tot["return"]),
                 f"{sec['xirr']:+.2f}%" if sec.get("xirr") is not None else ""])
    for col, v in ((3, tot["unrealized_pnl"]), (4, tot["realized_pnl"]), (5, tot["overall_pnl"]),
                   (6, tot["return"]), (7, sec.get("xirr") or 0)):
        extra.append(("TEXTCOLOR", (col, last), (col, last), _tone(v)))
    widths = [96, 66, 66, 66, 62, 66, 48, 53]
    return _table(data, widths, total_row=True, accent=ACCENTS.get(cur, INK), extra=extra)


def _pnl_chart(cur: str, sec: dict) -> Drawing:
    """Total P&L by broker: green bars to the right of zero, red to the left, each labelled."""
    rows = sorted(((b, float(d.get("overall_pnl") or 0.0)) for b, d in sec["brokers"]),
                  key=lambda r: r[1], reverse=True)
    row_h, label_w, value_w = 20, 96, 74
    h = row_h * len(rows) + 8
    d = Drawing(CONTENT_W, h)
    span_w = CONTENT_W - label_w - 2 * value_w
    hi = max([v for _b, v in rows] + [0.0])
    lo = min([v for _b, v in rows] + [0.0])
    scale = span_w / ((hi - lo) or 1.0)
    zero_x = label_w + value_w + (-lo) * scale
    d.add(Line(zero_x, 2, zero_x, h - 2, strokeColor=MUTED, strokeWidth=0.6))
    for i, (broker, v) in enumerate(rows):
        y = h - (i + 1) * row_h + 4
        name = broker if len(broker) <= 16 else broker[:15] + "…"
        d.add(String(label_w - 8, y + 4, name, fontName=FONT, fontSize=8, fillColor=INK, textAnchor="end"))
        w = abs(v) * scale
        x = zero_x if v >= 0 else zero_x - w
        d.add(Rect(x, y, max(w, 1.5), row_h - 8, rx=3, ry=3, fillColor=GOOD_BAR if v >= 0 else BAD_BAR,
                   strokeColor=None))
        label_x, anchor = (x + w + 5, "start") if v >= 0 else (x - 5, "end")
        d.add(String(label_x, y + 4, _signed(v, cur), fontName=FONT_BOLD, fontSize=7.5,
                     fillColor=_tone(v), textAnchor=anchor))
    return d


def _positions_table(cur: str, sec: dict, styles) -> Table:
    rows = sorted(sec["open"], key=lambda p: p["value"], reverse=True)
    data = [["Stock", "Broker", "Qty", "Avg cost", "Price", "Invested", "Value", "P&L", "Return"]]
    extra = []
    for i, p in enumerate(rows, start=1):
        name = p["name"] if len(p["name"]) <= 30 else p["name"][:29] + "…"
        stock = [Paragraph(_esc(p["symbol"]), styles["sym"])] + ([Paragraph(_esc(name), styles["name"])] if name else [])
        ret = p["pnl"] / p["invested"] * 100 if p["invested"] else 0.0
        broker = p["broker"] if len(p["broker"]) <= 12 else p["broker"][:11] + "…"
        data.append([stock, broker, _qty(p["qty"]), _price(p["avg"], cur), _price(p["price"], cur),
                     _money(p["invested"], cur), _money(p["value"], cur), _signed(p["pnl"], cur), _pct(ret)])
        extra += [("TEXTCOLOR", (7, i), (8, i), _tone(p["pnl"]))]
    inv = sum(p["invested"] for p in rows)
    val = sum(p["value"] for p in rows)
    pnl = val - inv
    last = len(data)
    data.append([f"{len(rows)} positions", "", "", "", "", _money(inv, cur), _money(val, cur), _signed(pnl, cur),
                 _pct(pnl / inv * 100 if inv else 0.0)])
    extra += [("TEXTCOLOR", (7, last), (8, last), _tone(pnl)), ("SPAN", (0, last), (4, last)),
              ("ALIGN", (1, 0), (1, -1), "LEFT"), ("TOPPADDING", (0, 1), (-1, -1), 3.5),
              ("BOTTOMPADDING", (0, 1), (-1, -1), 3.5)]
    widths = [118, 64, 38, 52, 52, 54, 54, 52, 39]
    return _table(data, widths, total_row=True, align_right_from=2, accent=ACCENTS.get(cur, INK), extra=extra)


def _realised_tables(cur: str, sec: dict, styles):
    """The five biggest realised gains and losses from closed positions, side by side."""
    closed = sec["closed"]
    gains = sorted((p for p in closed if p["realized"] > 0), key=lambda p: -p["realized"])[:5]
    losses = sorted((p for p in closed if p["realized"] < 0), key=lambda p: p["realized"])[:5]
    half = (CONTENT_W - 12) / 2

    def one(title, items, tone):
        data = [[title, "Broker", "Realised"]]
        for p in items:
            broker = p["broker"] if len(p["broker"]) <= 12 else p["broker"][:11] + "…"
            data.append([Paragraph(_esc(p["symbol"]), styles["sym"]), broker, _signed(p["realized"], cur)])
        if not items:
            data.append(["None", "", ""])
        return _table(data, [half - 132, 70, 62], align_right_from=2, accent=tone,
                      extra=[("TEXTCOLOR", (2, 1), (2, -1), tone), ("ALIGN", (1, 0), (1, -1), "LEFT")])

    pair = Table([[one("Biggest gains", gains, GOOD), one("Biggest losses", losses, BAD)]],
                 colWidths=[half + 12, half])
    pair.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, 0), 12),
                              ("RIGHTPADDING", (1, 0), (1, 0), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    total = sum(p["realized"] for p in closed)
    note = Paragraph(f"From {len(closed)} closed position{'s' * (len(closed) != 1)}, realised in total "
                     f"<font color='{_tone(total).hexval()}'>{_signed(total, cur)}</font>.", styles["note"])
    return pair, note


def _overview(currencies: dict, order: list, styles) -> Table:
    data = [["Currency", "Brokers", "Open", "Invested", "Value", "Total P&L", "Return", "XIRR"]]
    extra = []
    for i, cur in enumerate(order, start=1):
        sec, tot = currencies[cur], _totals(currencies[cur])
        xirr = sec.get("xirr")
        data.append([f"{_symbol(cur).strip()}  {cur}", str(len(sec["brokers"])), str(len(sec["open"])),
                     _money(tot["total_invested"], cur), _money(tot["total_value"], cur),
                     _signed(tot["overall_pnl"], cur), _pct(tot["return"]),
                     f"{xirr:+.2f}%" if xirr is not None else "—"])
        extra += [("TEXTCOLOR", (5, i), (6, i), _tone(tot["overall_pnl"])),
                  ("TEXTCOLOR", (7, i), (7, i), _tone(xirr or 0)), ("FONTNAME", (0, i), (0, i), FONT_BOLD)]
    return _table(data, [80, 52, 44, 78, 78, 78, 54, 59], accent=INK, extra=extra)


# ── Page decoration ──────────────────────────────────────────────────────────
class _NumberedCanvas(rl_canvas.Canvas):
    """Draws the band and footer once the page count is known ("Page 2 of 5")."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total: int) -> None:
        self.saveState()
        # Gradient band (the app's header colours)
        steps = 60
        for i in range(steps):
            t = i / (steps - 1)
            a, b, u = (GRADIENT[0], GRADIENT[1], t * 2) if t < 0.5 else (GRADIENT[1], GRADIENT[2], t * 2 - 1)
            r, g, bl = (int(x + (y - x) * u) for x, y in zip(a, b))
            self.setFillColorRGB(r / 255, g / 255, bl / 255)
            self.rect(PAGE_W * i / steps, PAGE_H - BAND, PAGE_W / steps + 1, BAND, fill=1, stroke=0)
        self.setFillColor(colors.white)
        self.setFont(FONT_BOLD, 13)
        self.drawString(MARGIN, PAGE_H - BAND / 2 - 4, "PTracker")
        self.setFont(FONT, 11)
        self.drawString(MARGIN + pdfmetrics.stringWidth("PTracker ", FONT_BOLD, 13), PAGE_H - BAND / 2 - 4,
                        "·  P&L Report")
        self.setFont(FONT, 9.5)
        self.drawRightString(PAGE_W - MARGIN, PAGE_H - BAND / 2 - 3, datetime.now().strftime("%d %B %Y"))
        # Footer
        self.setStrokeColor(LINE)
        self.setLineWidth(0.6)
        self.line(MARGIN, 30, PAGE_W - MARGIN, 30)
        self.setFillColor(MUTED)
        self.setFont(FONT, 7.5)
        self.drawString(MARGIN, 18, f"Generated {datetime.now().strftime('%d %b %Y, %H:%M')}  ·  "
                                    "figures in each portfolio's own currency")
        self.drawRightString(PAGE_W - MARGIN, 18, f"Page {self._pageNumber} of {total}")
        self.restoreState()


# ── The report ───────────────────────────────────────────────────────────────
def generate_broker_report_pdf(filepath: str, metrics: dict | None = None, currency_filter: str = "All") -> None:
    """Write the P&L Report PDF. It always covers every currency; `metrics` and
    `currency_filter` are accepted for older callers and not used."""
    _register_fonts()
    styles = _styles()
    data = _report_data()
    currencies = data["currencies"]
    order = sorted((c for c in currencies if currencies[c]["brokers"]),
                   key=lambda c: (c != "INR", c != "JPY", c))

    doc = SimpleDocTemplate(filepath, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=BAND + 22, bottomMargin=44, title="P&L Report", author="PTracker")
    story = [Paragraph("Portfolio P&amp;L Report", styles["title"]), Spacer(1, 4),
             Paragraph(f"All brokers and currencies  ·  prices as of {_when(data['prices_at'])}", styles["lead"]),
             Spacer(1, 12)]
    if not order:
        story.append(Paragraph("There are no trades yet, so there is nothing to report.", styles["lead"]))
    else:
        story += [Paragraph("Summary by currency", styles["h2"]), _overview(currencies, order, styles),
                  Paragraph("Each currency is shown on its own; nothing is converted.", styles["note"])]

    for n, cur in enumerate(order):
        sec, tot = currencies[cur], _totals(currencies[cur])
        story += [PageBreak()] if n else [Spacer(1, 18)]
        story += [_section_banner(cur, sec, styles), Spacer(1, 12), _tiles(cur, sec, tot, styles)]
        story += [KeepTogether([Paragraph("Brokers", styles["h2"]), _brokers_table(cur, sec, tot)])]
        story += [KeepTogether([Paragraph("Total P&amp;L by broker", styles["h2"]), _pnl_chart(cur, sec)])]
        # The short gains / losses tables before the long positions list, so no page is left half empty
        if sec["closed"]:
            pair, note = _realised_tables(cur, sec, styles)
            story += [KeepTogether([Paragraph("Realised from closed positions", styles["h2"]), pair,
                                    Spacer(1, 4), note])]
        if sec["open"]:
            story += [Paragraph("Open positions", styles["h2"]), _positions_table(cur, sec, styles),
                      Paragraph("P&amp;L here is on the shares still held (price minus average cost); the broker "
                                "totals above also include what was booked by selling.", styles["note"])]

    doc.build(story, canvasmaker=_NumberedCanvas)
