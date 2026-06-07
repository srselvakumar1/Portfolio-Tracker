import threading

_ticker_cache = {}
_ticker_lock = threading.Lock()
_fetching = False

def get_mini_tickers():
    with _ticker_lock:
        return dict(_ticker_cache)

def refresh_mini_tickers(callback=None):
    global _fetching
    with _ticker_lock:
        if _fetching:
            return
        _fetching = True
    
    def _fetch():
        global _fetching
        symbols = ['^NSEI', '^N225', '^IXIC', 'INR=X', 'JPY=X', 'JPYINR=X']
        names = ['NIFTY 50', 'Nikkei 225', 'NASDAQ', 'USD/INR', 'USD/JPY', 'JPY/INR']
        results = {}
        
        try:
            import yfinance as yf
            # Use threads=False to avoid ThreadPoolExecutor deadlocks inside daemon threads!
            data = yf.download(symbols, period="2d", progress=False, threads=False)
            
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
                except Exception:
                    pass
        except Exception:
            pass
            
        with _ticker_lock:
            _ticker_cache.update(results)
            _fetching = False
            
        if callback:
            callback()

    threading.Thread(target=_fetch, daemon=True).start()
