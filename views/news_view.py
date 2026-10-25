"""
Financial News view for the PTracker application.

News comes from Yahoo Finance for up to 10 of your holdings plus the Nikkei,
Japan ETF and currency tickers. It is fetched in a background thread and
cached in ~/Library/Application Support/PTracker/news_cache.json (in the
installed app AND when running from source, so nothing is written into the
project folder). The cache stores when it was fetched: the page shows
"Updated 10:42" and refreshes by itself in the background when the cache is
more than an hour old.
"""

import datetime
import json
import os
import re
import time
import webbrowser
import tkinter as tk
from tkinter import ttk

from model.applog import log
from views.base_view import BaseView, _enable_canvas_mousewheel
from ui.ui_theme import ModernStyle
from ui.ui_widgets import ModernButton
from ui.ui_utils import run_in_background

CACHE_MAX_AGE_S = 3600          # refresh automatically when older than 1 hour
MAX_HOLDINGS = 10               # holdings searched for news
MAX_ARTICLES = 20
MAX_PER_SYMBOL = 4
MARKET_SYMBOLS = ["^N225", "EWJ"]
CURRENCY_SYMBOLS = {
    "USDJPY=X": "USD/JPY Forex",
    "USDINR=X": "USD/INR Forex",
    "DX-Y.NYB": "US Dollar Index",
}
# Only clearly currency-focused HEADLINES get the amber currency style
_CURRENCY_TITLE_RE = re.compile(
    r"\b(rupee|yen|forex|usd/jpy|usd/inr|dollar index|currenc(y|ies)|exchange rates?)\b", re.IGNORECASE)
_FORECAST_TITLE_RE = re.compile(r"\b(forecast|outlook)\b", re.IGNORECASE)
_JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")

# Yahoo's per-ticker news feed (Ticker.news) answers 404 with yfinance 1.4, so
# when it is empty we fall back to Yahoo's search news, which needs words, not
# ticker codes. These are the search words for the market/currency tickers.
SEARCH_QUERIES = {
    "^N225": "Nikkei 225",
    "EWJ": "EWJ",
    "USDJPY=X": "USD/JPY",
    "USDINR=X": "rupee",
    "DX-Y.NYB": "dollar index",
}
_NAME_NOISE_RE = re.compile(
    r"\b(limited|ltd|co|corp|corporation|inc|plc|company|the|india|holdings?)\b|[,.()&]", re.IGNORECASE)


def news_cache_path() -> str:
    return os.path.join(os.path.expanduser("~/Library/Application Support/PTracker"), "news_cache.json")


def read_news_cache(path: str) -> dict | None:
    """{"news": [...], "symbols": [...], "fetched_at": epoch seconds or None}, or None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except Exception:
        log.warning("News cache %s could not be read", path, exc_info=True)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("news"), list):
        return None
    fetched_at = data.get("fetched_at")
    return {"news": data["news"], "symbols": data.get("symbols") or [],
            "fetched_at": float(fetched_at) if isinstance(fetched_at, (int, float)) else None}


def write_news_cache(path: str, news: list, symbols: list, fetched_at: float) -> None:
    """Write the cache atomically (a half-written file can't be left behind)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"news": news, "symbols": symbols, "fetched_at": fetched_at}, f)
    os.replace(tmp, path)


def _company_names(symbols: list[str]) -> dict[str, str]:
    """Company names for the search fallback (from the watchlist and price tables)."""
    names: dict[str, str] = {}
    if not symbols:
        return names
    try:
        from model.database import db_session
        marks = ",".join("?" * len(symbols))
        with db_session() as conn:
            for table in ("watchlist", "marketdata"):
                try:
                    rows = conn.execute(
                        f"SELECT symbol, stock_name FROM {table} WHERE symbol IN ({marks})", symbols).fetchall()
                except Exception:
                    continue
                for sym, name in rows:
                    if name and str(name).strip():
                        names[sym] = str(name).strip()
    except Exception:
        log.debug("Reading company names for the news failed", exc_info=True)
    return names


def _search_terms(sym: str, name: str) -> tuple[str, str | None, str]:
    """(search words, word a headline must contain or None, base ticker code)."""
    base = sym.split(".")[0].lstrip("^").upper()
    if sym in SEARCH_QUERIES:
        return SEARCH_QUERIES[sym], None, base
    if name:
        words = _NAME_NOISE_RE.sub(" ", name).split()
        if words:
            return " ".join(words[:3]), words[0], base
    return base, base, base


def _search_news(yf, sym: str, name: str) -> list[dict]:
    """Yahoo search news for one symbol, in the same shape as Ticker.news content."""
    query, must, base = _search_terms(sym, name)
    items = yf.Search(query, news_count=8, max_results=1).news or []
    out = []
    for a in items:
        title = a.get("title") or ""
        related = [str(t).split(".")[0].upper() for t in (a.get("relatedTickers") or [])]
        if must and must.lower() not in title.lower() and base not in related:
            continue  # search results are loose; keep only articles about this company
        ts = a.get("providerPublishTime")
        pub = (datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
               if isinstance(ts, (int, float)) else "")
        out.append({
            "id": a.get("uuid"), "title": title, "summary": "", "pubDate": pub,
            "provider": {"displayName": a.get("publisher") or ""},
            "clickThroughUrl": {"url": a.get("link") or ""},
            "related_symbol": sym,
        })
    return out


def fetch_news(holdings: list[str], cache_path: str) -> tuple[list, list, float]:
    """Fetch, translate, de-duplicate and sort the news. BACKGROUND THREAD ONLY.

    Returns (articles, symbols searched, fetched_at). Saves the cache when
    articles were found. Raises ConnectionError when every request failed.
    """
    import concurrent.futures
    import yfinance as yf

    symbols = list(holdings[:MAX_HOLDINGS]) or ["RELIANCE.NS", "TCS.NS", "AAPL", "MSFT"]
    for sym in MARKET_SYMBOLS + list(CURRENCY_SYMBOLS):
        if sym not in symbols:
            symbols.append(sym)

    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="auto", target="en")
    except Exception:
        translator = None   # translation is a nice-to-have

    def translate(text):
        if translator and text and _JAPANESE_RE.search(text):
            try:
                return translator.translate(text) or text
            except Exception:
                return text
        return text

    names = _company_names(symbols)

    def fetch_symbol(sym):
        try:
            feed = yf.Ticker(sym).news or []
        except Exception as exc:
            log.debug("Ticker news for %s failed: %s", sym, exc)
            feed = []
        if not feed:
            results = _search_news(yf, sym, names.get(sym, ""))
            for content in results:
                content["title"] = translate(content["title"])
            return results
        results = []
        for item in feed:
            content = item.get("content", item) if isinstance(item, dict) else None
            if not isinstance(content, dict):
                continue
            content = dict(content)
            content["related_symbol"] = sym
            content["title"] = translate(content.get("title", ""))
            content["summary"] = translate(content.get("summary") or content.get("description") or "")
            results.append(content)
        return results

    articles, failures = [], 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_symbol, s): s for s in symbols}
        for fut in concurrent.futures.as_completed(futures):
            try:
                articles.extend(fut.result())
            except Exception as exc:
                failures += 1
                log.warning("News for %s failed: %s", futures[fut], exc)
    if failures == len(symbols):
        raise ConnectionError("Couldn't reach Yahoo Finance. Check the internet connection and press Refresh.")
    if not articles:
        raise LookupError("Yahoo Finance returned no news for any symbol right now. Try Refresh again later.")

    # Newest first, no duplicates, and at most 4 per symbol so one busy
    # ticker can't fill the whole page
    seen, per_symbol, unique = set(), {}, []
    for a in sorted(articles, key=lambda n: n.get("pubDate") or "", reverse=True):
        key = a.get("id") or (a.get("title") or "").strip().lower()
        sym = a.get("related_symbol", "")
        if key and key not in seen and per_symbol.get(sym, 0) < MAX_PER_SYMBOL:
            seen.add(key)
            per_symbol[sym] = per_symbol.get(sym, 0) + 1
            unique.append(a)
    unique = unique[:MAX_ARTICLES]

    fetched_at = time.time()
    if unique:
        try:
            write_news_cache(cache_path, unique, symbols, fetched_at)
        except Exception:
            log.exception("Saving the news cache failed")
    return unique, symbols, fetched_at


def local_article_time(pub: str) -> str:
    """'2026-04-24T16:34:12Z' (UTC) → '25 Apr 2026, 01:34' in the Mac's time zone."""
    if not pub:
        return ""
    try:
        dt = datetime.datetime.strptime(pub, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone().strftime("%d %b %Y, %H:%M")
    except Exception:
        return pub


def updated_text(fetched_at: float | None) -> str:
    if not fetched_at:
        return "Not updated yet"
    dt = datetime.datetime.fromtimestamp(fetched_at)
    if dt.date() == datetime.date.today():
        return f"Updated {dt:%H:%M}"
    return f"Updated {dt:%d %b, %H:%M}"


class NewsView(BaseView):
    """View to display relevant financial news for portfolio symbols."""

    def build(self):
        self.add_gradient_header(
            self,
            "📰 Financial News",
            "Latest news related to your portfolio holdings.",
            right_widget_func=self._build_header_right
        )

        self.cache_file = news_cache_path()
        self.is_fetching = False
        self._fetched_at: float | None = None
        self._shown_fetched_at = object()   # what the cards on screen came from
        self._cards_shown = False
        self._wrap = 900
        self._wrap_after = None
        self._wrap_labels: list[tk.Label] = []

        main_container = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        main_container.pack(fill="both", expand=True, padx=20, pady=(10, 20))

        # Status row: which symbols, and when the news was fetched
        status_row = tk.Frame(main_container, bg=ModernStyle.BG_PRIMARY)
        status_row.pack(fill="x", pady=(0, 8))
        self.updated_lbl = tk.Label(
            status_row, text="", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_PRIMARY,
            font=ModernStyle.FONT_SMALL_BOLD,
        )
        self.updated_lbl.pack(side="right", padx=(12, 0))
        self.symbols_lbl = tk.Label(
            status_row, text="", fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_PRIMARY,
            font=ModernStyle.FONT_SMALL, anchor="w", justify="left", wraplength=700,
        )
        self.symbols_lbl.pack(side="left", fill="x", expand=True)

        # Error banner (shown at the TOP, above the cards, only when needed)
        self.error_banner = tk.Frame(main_container, bg=ModernStyle.BG_SECONDARY,
                                     highlightthickness=1, highlightbackground=ModernStyle.ERROR)
        self.error_lbl = tk.Label(
            self.error_banner, text="", fg=ModernStyle.ERROR, bg=ModernStyle.BG_SECONDARY,
            font=ModernStyle.FONT_BODY_BOLD, anchor="w", justify="left", wraplength=800,
        )
        self.error_lbl.pack(fill="x", padx=14, pady=10)

        # Scrollable list of cards
        self.list_frame = tk.Frame(main_container, bg=ModernStyle.BG_PRIMARY)
        self.list_frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.list_frame, bg=ModernStyle.BG_PRIMARY, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(self.list_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.vscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.scroll_frame = tk.Frame(self.canvas, bg=ModernStyle.BG_PRIMARY)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.scroll_frame.bind("<Configure>",
                               lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        _enable_canvas_mousewheel(self.canvas, include_widget=self.scroll_frame)

        self._show_placeholder("Fetching latest news…")

    def _build_header_right(self, parent):
        self.refresh_btn = ModernButton(
            parent,
            text="↻ Refresh News",
            command=self.fetch_news_async,
            bg=ModernStyle.INFO_FILL,
            fg=ModernStyle.TEXT_ON_ACCENT,
            canvas_bg=ModernStyle.PURPLE_FILL,
            width=170,
            height=34,
            font=ModernStyle.FONT_BODY_BOLD,
        )
        self.refresh_btn.pack(side="right")

    # ── Layout: wrap text to the card width (debounced) ──────────────────────

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.canvas_window, width=event.width)
        new_wrap = max(280, event.width - 48)   # card padding + border
        if abs(new_wrap - self._wrap) < 16:
            return
        if self._wrap_after:
            self.after_cancel(self._wrap_after)
        self._wrap_after = self.after(200, lambda: self._apply_wrap(new_wrap))

    def _apply_wrap(self, wrap: int):
        self._wrap_after = None
        self._wrap = wrap
        self.symbols_lbl.configure(wraplength=max(240, wrap - 160))
        self.error_lbl.configure(wraplength=max(240, wrap - 20))
        for lbl in self._wrap_labels:
            try:
                lbl.configure(wraplength=wrap)
            except tk.TclError:
                pass

    # ── Loading ───────────────────────────────────────────────────────────────

    def on_show(self):
        self._is_active = True
        if not self._data_loaded:
            self.load_data()
        elif self._is_stale():
            self.fetch_news_async()

    def _is_stale(self) -> bool:
        return not self._fetched_at or time.time() - self._fetched_at > CACHE_MAX_AGE_S

    def load_data(self):
        self._data_loaded = True
        if self.is_fetching:
            return
        cache = read_news_cache(self.cache_file)   # small file: a few ms
        if cache and cache["news"]:
            self._fetched_at = cache["fetched_at"]
            if self._shown_fetched_at != self._fetched_at or not self._cards_shown:
                self._render_news(cache["news"], cache["symbols"])
                self._shown_fetched_at = self._fetched_at
            self._show_updated()
            if self._is_stale():
                self.fetch_news_async()
        else:
            self.fetch_news_async()

    def fetch_news_async(self):
        if self.is_fetching:
            return
        self.is_fetching = True
        holdings = []
        try:
            if self.app_state and self.app_state.data_cache:
                holdings = self.app_state.data_cache.get_holdings_symbols()
        except Exception:
            log.exception("Reading holdings for the news failed")

        self._hide_error()
        self.updated_lbl.config(text="⟳ Refreshing…", fg=ModernStyle.TEXT_ACCENT)
        self.refresh_btn.set_text("⟳ Refreshing…")
        if not self._cards_shown:
            self._show_placeholder("Fetching latest news…")

        path = self.cache_file
        run_in_background(lambda: fetch_news(holdings, path),
                          on_done=self._on_news, on_error=self._on_news_failed,
                          widget=self, name="news-fetch")

    def _end_fetch(self):
        self.is_fetching = False
        self.refresh_btn.set_text("↻ Refresh News")

    def _on_news(self, result):
        news, symbols, fetched_at = result
        self._end_fetch()
        if news:
            self._fetched_at = fetched_at
            self._render_news(news, symbols)
            self._shown_fetched_at = fetched_at
        elif self._cards_shown:
            self._show_error("Yahoo Finance returned no articles just now; showing the earlier news.")
        else:
            self._show_placeholder("No news available for your portfolio symbols right now.")
        self._show_updated()

    def _on_news_failed(self, err):
        self._end_fetch()
        self._show_updated()
        extra = " Showing the earlier news." if self._cards_shown else ""
        self._show_error(f"⚠ Couldn't refresh the news: {err}{extra}")
        if not self._cards_shown:
            self._show_placeholder("No news to show yet.")

    # ── Status / error ────────────────────────────────────────────────────────

    def _show_updated(self):
        stale = self._is_stale()
        self.updated_lbl.config(text=updated_text(self._fetched_at),
                                fg=ModernStyle.WARNING if stale and self._fetched_at else ModernStyle.TEXT_SECONDARY)

    def _show_error(self, msg: str):
        self.error_lbl.config(text=msg)
        if not self.error_banner.winfo_manager():
            self.error_banner.pack(fill="x", pady=(0, 10), before=self.list_frame)

    def _hide_error(self):
        if self.error_banner.winfo_manager():
            self.error_banner.pack_forget()

    def _clear_cards(self):
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self._wrap_labels = []
        self._cards_shown = False

    def _show_placeholder(self, text: str):
        self._clear_cards()
        tk.Label(self.scroll_frame, text=text, fg=ModernStyle.TEXT_SECONDARY, bg=ModernStyle.BG_PRIMARY,
                 font=ModernStyle.FONT_SUBHEADING).pack(pady=40)

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render_news(self, news_items, symbols_fetched):
        self._clear_cards()
        self.symbols_lbl.config(text=f"News for: {', '.join(symbols_fetched)}" if symbols_fetched else "")
        if not news_items:
            self._show_placeholder("No news available for your portfolio symbols right now.")
            return
        for item in news_items:
            self._create_news_card(self.scroll_frame, item)
        self._cards_shown = True
        self.canvas.yview_moveto(0)

    def _create_news_card(self, parent, item):
        title = item.get("title") or "No Title"
        summary = item.get("summary") or item.get("description") or ""
        provider = item.get("provider", {})
        provider_name = provider.get("displayName", "") if isinstance(provider, dict) else str(provider or "")
        pub_date = local_article_time(item.get("pubDate", ""))
        symbol = item.get("related_symbol", "")

        link = ""
        for key in ("clickThroughUrl", "canonicalUrl"):
            val = item.get(key)
            if isinstance(val, dict) and val.get("url"):
                link = val["url"]
                break
        if not link and isinstance(item.get("link"), str):
            link = item["link"]

        # Currency style only for the currency tickers or clearly currency headlines
        currency_label = CURRENCY_SYMBOLS.get(symbol)
        if not currency_label and _CURRENCY_TITLE_RE.search(title):
            currency_label = "Currency news"
        if currency_label and _FORECAST_TITLE_RE.search(title):
            currency_label += " & forecast"

        if currency_label:
            card_bg, card_border, border_thickness = ModernStyle.KPI_TINT_AMBER, ModernStyle.WARNING, 2
            meta_fg = ModernStyle.WARNING
        else:
            card_bg, card_border, border_thickness = ModernStyle.BG_SECONDARY, ModernStyle.BORDER_COLOR, 1
            meta_fg = ModernStyle.TEXT_ACCENT

        card = tk.Frame(parent, bg=card_bg, highlightthickness=border_thickness,
                        highlightbackground=card_border, padx=16, pady=14)
        card.pack(fill="x", pady=(0, 14))

        meta_frame = tk.Frame(card, bg=card_bg)
        meta_frame.pack(fill="x", pady=(0, 6))
        meta_parts = [f"💱 {currency_label}"] if currency_label else []
        meta_parts += [p for p in (provider_name, pub_date, symbol) if p]
        tk.Label(meta_frame, text="  ·  ".join(meta_parts), fg=meta_fg, bg=card_bg,
                 font=ModernStyle.FONT_SMALL, anchor="w").pack(side="left")

        if link:
            def open_link(url=link):
                try:
                    webbrowser.open(url)
                except Exception:
                    log.exception("Opening %s failed", url)

            ModernButton(
                meta_frame, text="Read article ↗", command=open_link,
                bg=ModernStyle.ACCENT_PRIMARY_PALE, fg=ModernStyle.TEXT_ACCENT,
                canvas_bg=card_bg, width=140, height=28,
                font=ModernStyle.FONT_SMALL_BOLD, radius=14,
            ).pack(side="right")

        title_lbl = tk.Label(card, text=title, fg=ModernStyle.TEXT_PRIMARY, bg=card_bg,
                             font=ModernStyle.FONT_HEADING, anchor="w", justify="left", wraplength=self._wrap)
        title_lbl.pack(fill="x", pady=(0, 6))
        self._wrap_labels.append(title_lbl)

        if summary:
            if len(summary) > 300:
                summary = summary[:297].rstrip() + "…"
            summary_lbl = tk.Label(card, text=summary, fg=ModernStyle.TEXT_SECONDARY, bg=card_bg,
                                   font=ModernStyle.FONT_BODY, anchor="w", justify="left", wraplength=self._wrap)
            summary_lbl.pack(fill="x")
            self._wrap_labels.append(summary_lbl)
