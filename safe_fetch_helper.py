
# safe_fetch_helper.py
# Minimal anti-rate-limit wrapper for Binance 24h tickers.
import time
import threading
try:
    from binance.error import ClientError
except Exception:  # fallback type if package differs
    class ClientError(Exception):
        def __init__(self, status_code=None, code=None, response=None, *a, **k):
            super().__init__(*a)
            self.status_code = status_code
            self.code = code
            self.response = response or {}

_TICKERS_LOCK = threading.Lock()
_TICKERS_CACHE = {"ts": 0.0, "data": None, "backoff": 0.0}

def safe_fetch_24h_tickers(client, min_interval_sec=45, max_backoff_sec=90):
    """
    Fetch /fapi/v1/ticker/24hr safely with light caching and backoff.
    Returns cached data when called too frequently; on 429/-1003 it sleeps & retries.
    """
    now = time.time()
    with _TICKERS_LOCK:
        if _TICKERS_CACHE["data"] is not None and (now - _TICKERS_CACHE["ts"] < min_interval_sec):
            return _TICKERS_CACHE["data"]

    attempts = 0
    backoff = _TICKERS_CACHE["backoff"] or 0.0
    while attempts < 5:
        attempts += 1
        try:
            data = client.ticker_24hr_price_change()
            with _TICKERS_LOCK:
                _TICKERS_CACHE.update(ts=time.time(), data=data, backoff=0.0)
            return data
        except ClientError as e:
            status = getattr(e, "status_code", None) or getattr(e, "status", None)
            code = getattr(e, "error_code", None) if hasattr(e, "error_code") else getattr(e, "code", None)
            if status == 429 or code in (-1003, -1103):
                hdrs = None
                try:
                    hdrs = e.response.get("headers") if isinstance(e.response, dict) else None
                except Exception:
                    hdrs = None
                retry_after = None
                if hdrs and isinstance(hdrs, dict):
                    ra = hdrs.get("retry-after") or hdrs.get("Retry-After")
                    try:
                        retry_after = float(ra)
                    except Exception:
                        retry_after = None
                sleep_s = retry_after if retry_after is not None else max(1.0, min_interval_sec/3.0 + backoff)
                time.sleep(sleep_s)
                backoff = min(max_backoff_sec, (backoff * 1.8) + 1.0)
                with _TICKERS_LOCK:
                    _TICKERS_CACHE["backoff"] = backoff
                continue
            else:
                raise
        except Exception:
            time.sleep(1.0 + attempts * 0.5)
            if attempts >= 3:
                raise

    # Fallback: return last cache if any, else do a final direct call
    with _TICKERS_LOCK:
        if _TICKERS_CACHE["data"] is not None:
            return _TICKERS_CACHE["data"]
    return client.ticker_24hr_price_change()
