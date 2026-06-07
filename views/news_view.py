"""
Financial News view for the PTracker application.
"""

import tkinter as tk
from tkinter import ttk
import threading
import datetime
import webbrowser
import sys
import json
import os

from views.base_view import BaseView, _enable_canvas_mousewheel
from ui_theme import ModernStyle
from ui_widgets import ModernButton

class NewsView(BaseView):
    """View to display relevant financial news for portfolio symbols."""
    
    def build(self):
        self.add_gradient_header(
            self,
            "📰 Financial News",
            "Latest news related to your portfolio holdings.",
            right_widget_func=self._build_header_right
        )
        
        # Main container with a slight padding
        main_container = tk.Frame(self, bg=ModernStyle.BG_PRIMARY)
        main_container.pack(fill="both", expand=True, padx=20, pady=(10, 20))
        
        # Scrollable Canvas
        self.canvas = tk.Canvas(main_container, bg=ModernStyle.BG_PRIMARY, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(main_container, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        
        self.vscroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        
        self.scroll_frame = tk.Frame(self.canvas, bg=ModernStyle.BG_PRIMARY)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        
        def _on_cfg(_e=None):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            self.canvas.itemconfigure(self.canvas_window, width=self.canvas.winfo_width())

        self.scroll_frame.bind("<Configure>", _on_cfg)
        self.canvas.bind("<Configure>", _on_cfg)
        
        _enable_canvas_mousewheel(self.canvas, include_widget=self.scroll_frame)
        
        # Loading indicator
        self.loading_label = tk.Label(
            self.scroll_frame,
            text="Fetching latest news...",
            fg=ModernStyle.TEXT_SECONDARY,
            bg=ModernStyle.BG_PRIMARY,
            font=ModernStyle.FONT_SUBHEADING
        )
        self.loading_label.pack(pady=40)
        
        self.is_fetching = False
        
        if getattr(sys, 'frozen', False):
            # Write cache to Application Support directory since sys._MEIPASS is read-only
            app_support = os.path.expanduser("~/Library/Application Support/PTracker")
            os.makedirs(app_support, exist_ok=True)
            self.cache_file = os.path.join(app_support, "news_cache.json")
            
            # If cache file doesn't exist in app_support, but exists in sys._MEIPASS bundle, copy it
            if not os.path.exists(self.cache_file):
                bundle_cache = os.path.join(sys._MEIPASS, "assets", "news_cache.json")
                if os.path.exists(bundle_cache):
                    try:
                        import shutil
                        shutil.copy2(bundle_cache, self.cache_file)
                    except Exception:
                        pass
        else:
            self.cache_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "news_cache.json")
        
    def load_data(self):
        if not getattr(self, "is_fetching", False):
            if self._load_from_cache():
                self._data_loaded = True
            else:
                self.fetch_news_async()
                self._data_loaded = True

    def _load_from_cache(self):
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, "r") as f:
                    data = json.load(f)
                    news_items = data.get("news", [])
                    symbols = data.get("symbols", [])
                    if news_items:
                        self._render_news(news_items, symbols)
                        return True
        except Exception:
            pass
        return False

    def _build_header_right(self, parent):
        ModernButton(
            parent,
            text="⟳ Refresh News",
            command=self.fetch_news_async,
            bg=ModernStyle.BG_TERTIARY,
            fg=ModernStyle.TEXT_PRIMARY,
            canvas_bg="#0D9488",
            width=120,
            height=34
        ).pack(side="right")

    def _on_visible(self, event):
        if not self._data_loaded and not self.is_fetching:
            if self._load_from_cache():
                self._data_loaded = True
            else:
                self.fetch_news_async()
                self._data_loaded = True

    def fetch_news_async(self):
        if self.is_fetching:
            return
        
        self.is_fetching = True
        
        # If the scroll frame is empty (initial load and no cache), show loading label
        if not self.scroll_frame.winfo_children():
            self.loading_label = tk.Label(
                self.scroll_frame,
                text="Fetching latest news...",
                fg=ModernStyle.TEXT_SECONDARY,
                bg=ModernStyle.BG_PRIMARY,
                font=ModernStyle.FONT_SUBHEADING
            )
            self.loading_label.pack(pady=40)

        threading.Thread(target=self._fetch_news_thread, daemon=True).start()

    def _fetch_news_thread(self):
        try:
            import yfinance as yf
            import concurrent.futures
            from deep_translator import GoogleTranslator
            
            symbols = []
            if self.app_state and self.app_state.data_cache:
                symbols = self.app_state.data_cache.get_holdings_symbols()
            
            # If no portfolio symbols, default to some major ones
            if not symbols:
                symbols = ["RELIANCE.NS", "TCS.NS", "AAPL", "MSFT"]
                    # Fetch news for top 5 symbols
            symbols_to_fetch = symbols[:5]
            
            # Add Japan news
            if "^N225" not in symbols_to_fetch:
                symbols_to_fetch.append("^N225")
            if "EWJ" not in symbols_to_fetch:
                symbols_to_fetch.append("EWJ")
            
            # Add currency news & forecast tickers (USD, JPY, INR)
            currency_symbols = ["USDJPY=X", "USDINR=X", "DX-Y.NYB"]
            for cur_sym in currency_symbols:
                if cur_sym not in symbols_to_fetch:
                    symbols_to_fetch.append(cur_sym)
            
            all_news = []
            
            # Helper to check if text contains Japanese characters (Hiragana, Katakana, Kanji)
            def contains_japanese(text):
                if not text:
                    return False
                import re
                # Range for Japanese characters
                return bool(re.search(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]', text))

            def fetch_symbol_news(sym):
                try:
                    ticker = yf.Ticker(sym)
                    news_list = ticker.news
                    results = []
                    if isinstance(news_list, list):
                        translator = GoogleTranslator(source='auto', target='en')
                        for item in news_list:
                            content = item.get('content', item) if isinstance(item, dict) else item
                            if isinstance(content, dict):
                                content['related_symbol'] = sym
                                
                                # Translate title
                                title = content.get('title', '')
                                if contains_japanese(title):
                                    try:
                                        content['title'] = translator.translate(title)
                                    except Exception:
                                        pass
                                        
                                # Translate summary
                                summary = content.get('summary', content.get('description', ''))
                                if contains_japanese(summary):
                                    try:
                                        content['summary'] = translator.translate(summary)
                                    except Exception:
                                        pass
                                        
                            results.append(item)
                    return results
                except Exception as e:
                    print(f"Failed to fetch news for {sym}: {e}")
                    return []

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(fetch_symbol_news, sym): sym for sym in symbols_to_fetch}
                for future in concurrent.futures.as_completed(futures):
                    all_news.extend(future.result())
            
            # Extract content from wrapper if present (yfinance API structure can vary)
            processed_news = []
            for item in all_news:
                if 'content' in item and isinstance(item['content'], dict):
                    processed_news.append(item['content'])
                else:
                    processed_news.append(item)
                    
            # Sort by publication date (descending)
            def get_date(n):
                pub = n.get('pubDate', '')
                if not pub:
                    return ""
                return pub
                
            processed_news.sort(key=get_date, reverse=True)
            
            # Limit to 20 articles max
            processed_news = processed_news[:20]
            
            # Save to cache
            try:
                with open(self.cache_file, "w") as f:
                    json.dump({"news": processed_news, "symbols": symbols_to_fetch}, f)
            except Exception as e:
                print(f"Failed to save news cache: {e}")
            
            # Update UI on main thread
            self.after(0, lambda: self._render_news(processed_news, symbols_to_fetch))
            
        except Exception as e:
            self.after(0, lambda: self._render_error(str(e)))
        finally:
            self.is_fetching = False

    def _render_error(self, error_msg):
        if hasattr(self, 'loading_label') and self.loading_label.winfo_exists():
            self.loading_label.destroy()
            
        err_lbl = tk.Label(
            self.scroll_frame,
            text=f"Error fetching news: {error_msg}",
            fg="#FCA5A5",
            bg=ModernStyle.BG_PRIMARY,
            font=ModernStyle.FONT_BODY
        )
        err_lbl.pack(pady=40)

    def _render_news(self, news_items, symbols_fetched):
        # Clear existing items
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
            
        if not news_items:
            empty_lbl = tk.Label(
                self.scroll_frame,
                text="No news available for your portfolio symbols right now.",
                fg=ModernStyle.TEXT_SECONDARY,
                bg=ModernStyle.BG_PRIMARY,
                font=ModernStyle.FONT_BODY
            )
            empty_lbl.pack(pady=40)
            return

        # Add a summary label
        summary_lbl = tk.Label(
            self.scroll_frame,
            text=f"Showing latest news for: {', '.join(symbols_fetched)}",
            fg=ModernStyle.TEXT_SECONDARY,
            bg=ModernStyle.BG_PRIMARY,
            font=ModernStyle.FONT_SMALL,
            anchor="w"
        )
        summary_lbl.pack(fill="x", pady=(0, 10))

        for item in news_items:
            self._create_news_card(self.scroll_frame, item)

    def _create_news_card(self, parent, item):
        title = item.get('title', 'No Title')
        summary = item.get('summary', item.get('description', 'No summary available.'))
        if not summary:
            summary = ""
        
        provider_dict = item.get('provider', {})
        provider_name = provider_dict.get('displayName', 'Unknown') if isinstance(provider_dict, dict) else provider_dict
        
        pub_date = item.get('pubDate', '')
        if pub_date:
            try:
                # yfinance returns like '2026-04-24T16:34:12Z'
                dt = datetime.datetime.strptime(pub_date, "%Y-%m-%dT%H:%M:%SZ")
                pub_date = dt.strftime("%d %b %Y, %I:%M %p")
            except Exception:
                pass
        
        symbol = item.get('related_symbol', '')
        
        link = ""
        click_url = item.get('clickThroughUrl')
        canon_url = item.get('canonicalUrl')
        if isinstance(click_url, dict) and 'url' in click_url:
            link = click_url['url']
        elif isinstance(canon_url, dict) and 'url' in canon_url:
            link = canon_url['url']
        elif 'link' in item:
            link = item['link']

        # Determine if this is a currency forecast or general news about USD, JPY, or INR
        is_currency = False
        currency_label = "CURRENCY NEWS"
        
        # Check by symbol
        if symbol in ["USDJPY=X", "USDINR=X", "JPY=X", "INR=X", "DX-Y.NYB"]:
            is_currency = True
            if "USDJPY" in symbol:
                currency_label = "USD/JPY FOREX"
            elif "USDINR" in symbol:
                currency_label = "USD/INR FOREX"
            elif "DX-Y" in symbol:
                currency_label = "US DOLLAR INDEX"
            else:
                currency_label = "CURRENCY FOREX"
        else:
            lower_title = title.lower()
            lower_summary = summary.lower()
            
            # Keywords matching
            has_usd = "usd" in lower_title or "dollar" in lower_title or "usd" in lower_summary or "dollar" in lower_summary
            has_jpy = "jpy" in lower_title or "yen" in lower_title or "jpy" in lower_summary or "yen" in lower_summary
            has_inr = "inr" in lower_title or "rupee" in lower_title or "inr" in lower_summary or "rupee" in lower_summary
            
            if has_usd or has_jpy or has_inr:
                is_currency = True
                matched_currencies = []
                if has_usd: matched_currencies.append("USD")
                if has_jpy: matched_currencies.append("JPY")
                if has_inr: matched_currencies.append("INR")
                currency_label = f"{'/'.join(matched_currencies)} NEWS"

        # Check if there is a forecast/outlook/trend keyword
        lower_title = title.lower()
        lower_summary = summary.lower()
        is_forecast = any(k in lower_title or k in lower_summary for k in ["forecast", "outlook", "prediction", "expect", "target", "trend", "project"])
        
        if is_currency and is_forecast:
            currency_label += " & FORECAST"

        # Apply specific highlights/colors for currency news
        if is_currency:
            card_bg = "#FFFDF5"       # Warm ivory/amber tint for currency
            card_border = "#F59E0B"   # Warm amber border
            border_thickness = 2
            meta_fg = "#B45309"       # Deep amber for meta info
            title_fg = "#78350F"      # Dark amber for title
            summary_fg = "#92400E"    # Muted dark amber for summary
        else:
            card_bg = ModernStyle.BG_SECONDARY
            card_border = ModernStyle.BORDER_COLOR
            border_thickness = 1
            meta_fg = ModernStyle.ACCENT_PRIMARY
            title_fg = ModernStyle.TEXT_PRIMARY
            summary_fg = ModernStyle.TEXT_SECONDARY

        # Card container
        card = tk.Frame(
            parent,
            bg=card_bg,
            highlightthickness=border_thickness,
            highlightbackground=card_border,
            padx=16,
            pady=16
        )
        card.pack(fill="x", pady=(0, 16))
        
        # Meta info row (Provider, Date, Symbol, and Button)
        meta_frame = tk.Frame(card, bg=card_bg)
        meta_frame.pack(fill="x", pady=(0, 8))
        
        meta_text = ""
        if is_currency:
            meta_text += f"[💱 {currency_label}] • "
        meta_text += f"{provider_name}"
        if pub_date:
            meta_text += f" • {pub_date}"
        if symbol:
            meta_text += f" • {symbol}"
            
        tk.Label(
            meta_frame,
            text=meta_text.upper(),
            fg=meta_fg,
            bg=card_bg,
            font=ModernStyle.FONT_SMALL_BOLD,
            anchor="w"
        ).pack(side="left")

        # Read More button floating right in the meta frame
        if link:
            def open_link(url=link):
                try:
                    webbrowser.open(url)
                except Exception as e:
                    print(f"Failed to open link: {e}")
                    
            ModernButton(
                meta_frame,
                text="Read Full Article ↗",
                command=open_link,
                bg="#FEF3C7" if is_currency else ModernStyle.BG_TERTIARY,
                fg=ModernStyle.TEXT_PRIMARY,
                canvas_bg=card_bg,
                width=160,
                height=28,
                font=ModernStyle.FONT_SMALL,
                radius=14
            ).pack(side="right")

        # Title
        title_lbl = tk.Label(
            card,
            text=title,
            fg=title_fg,
            bg=card_bg,
            font=ModernStyle.FONT_HEADING,
            anchor="w",
            justify="left",
            wraplength=1000
        )
        title_lbl.pack(fill="x", pady=(0, 8))
        
        # Summary
        if summary:
            # truncate summary if too long
            if len(summary) > 300:
                summary = summary[:297] + "..."
                
            summary_lbl = tk.Label(
                card,
                text=summary,
                fg=summary_fg,
                bg=card_bg,
                font=ModernStyle.FONT_SUBHEADING,
                anchor="w",
                justify="left",
                wraplength=1000
            )
            summary_lbl.pack(fill="x", pady=(0, 4))
