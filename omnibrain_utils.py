# -*- coding: utf-8 -*-
import os
import time
import json
import pandas as pd
import numpy as np
from datetime import datetime
from binance.um_futures import UMFutures
import requests
from decimal import Decimal

# NEW: needed for signed PAPI calls
import hmac
import hashlib
from urllib.parse import urlencode


### === Load API Keys === ###
def load_api_keys():
    """
    Load keys from REAL.json. Fail fast if missing/empty.
    Returns: API_KEY, API_SECRET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    """
    path = os.environ.get("BINANCE_KEYS_FILE", "REAL.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"[KEYS] Missing {path}. Put your Binance + Telegram creds there.")
    with open(path, "r") as f:
        keys = json.load(f)

    api_key = keys.get("API_KEY")
    api_secret = keys.get("API_SECRET")
    tg_token = keys.get("TELEGRAM_TOKEN")
    tg_chat = keys.get("TELEGRAM_CHAT_ID")

    if not api_key or not api_secret:
        raise ValueError("[KEYS] API_KEY/API_SECRET missing or empty in REAL.json")

    return api_key, api_secret, tg_token, tg_chat

API_KEY, API_SECRET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID = load_api_keys()

# Create a single authenticated client and reuse it everywhere.
# Your environment expects UMFutures(key=..., secret=...)
client = UMFutures(key=API_KEY, secret=API_SECRET)

# --- BEGIN: Leverage Hard Cap Patch (inserted) ---
LEVERAGE_HARD_CAP = 5

# Keep originals if they exist
_change_lev = getattr(client, "change_leverage", None)
_fut_change_lev = getattr(client, "futures_change_leverage", None)
_set_lev = getattr(client, "set_leverage", None)
_change_margin_type = getattr(client, "change_margin_type", None)

# Per-symbol cache so we don't spam REST:
__lev_ok = set()

def _cap(x):
    try:
        return min(int(x), LEVERAGE_HARD_CAP)
    except Exception:
        return LEVERAGE_HARD_CAP

def ensure_isolated_5x(sym: str):
    """Idempotent: set margin ISOLATED and leverage <= 5x; swallow -4421 gracefully."""
    if sym in __lev_ok:
        return
    # Margin to ISOLATED
    if callable(_change_margin_type):
        try:
            _change_margin_type(symbol=sym, marginType="ISOLATED")
        except Exception:
            pass
    # Clamp leverage to 5
    for fn in (_change_lev, _fut_change_lev, _set_lev):
        if callable(fn):
            try:
                fn(symbol=sym, leverage=LEVERAGE_HARD_CAP)
                __lev_ok.add(sym)
                break
            except Exception as e:
                if "-4421" in str(e):
                    __lev_ok.add(sym)
                    break

def _wrap_change_leverage(orig):
    def _wrapped(*args, **kwargs):
        if "leverage" in kwargs:
            kwargs["leverage"] = _cap(kwargs["leverage"])
        elif len(args) >= 2:
            a = list(args)
            a[1] = _cap(a[1])
            args = tuple(a)
        return orig(*args, **kwargs)
    return _wrapped

if callable(_change_lev):
    client.change_leverage = _wrap_change_leverage(_change_lev)
if callable(_fut_change_lev):
    client.futures_change_leverage = _wrap_change_leverage(_fut_change_lev)
if callable(_set_lev):
    client.set_leverage = _wrap_change_leverage(_set_lev)

def _pre_order_leverage_guard(symbol: str):
    try:
        ensure_isolated_5x(symbol)
    except Exception as e:
        print(f"[LEV-GUARD] warn for {symbol}: {e}")
# --- END: Leverage Hard Cap Patch ---


# === INTERNAL: minimal helpers for signed REST (used only when we must hit PAPI) ===
def _signed_request(method, base_url, path, api_key, api_secret, params=None, timeout=10):
    params = params.copy() if params else {}
    params.setdefault("recvWindow", 50000)
    params["timestamp"] = int(time.time() * 1000)

    q = urlencode(params, doseq=True)
    # Ensure api_secret is a string before encode (prevents None.encode)
    if not isinstance(api_secret, str) or not api_secret:
        raise ValueError("[KEYS] api_secret is missing/invalid for signed request")
    sig = hmac.new(api_secret.encode("utf-8"), q.encode("utf-8"), hashlib.sha256).hexdigest()
    url = f"{base_url}{path}?{q}&signature={sig}"
    headers = {"X-MBX-APIKEY": api_key}

    if method == "GET":
        r = requests.get(url, headers=headers, timeout=timeout)
    else:
        r = requests.post(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

def _signed_get(base_url, path, api_key, api_secret, params=None, timeout=10):
    return _signed_request("GET", base_url, path, api_key, api_secret, params=params, timeout=timeout)

def _signed_post(base_url, path, api_key, api_secret, params=None, timeout=10):
    return _signed_request("POST", base_url, path, api_key, api_secret, params=params, timeout=timeout)


### === Telegram Alerts === ###
def send_telegram_message(bot_token, chat_id, message):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": message})
    except Exception:
        pass


### === ATR Calculation === ###
def calculate_atr(df, period=14):
    """
    Same ATR logic as before (TR rolling mean), but safe:
    - Returns 0.0 if df is None/too short
    - Drops NaNs before taking the last value
    - Never raises IndexError when there isn't a valid ATR yet
    """
    if df is None or len(df) < period + 2:
        return 0.0
    _df = df.copy()
    _df['H-L']  = _df['high'] - _df['low']
    _df['H-PC'] = (_df['high'] - _df['close'].shift(1)).abs()
    _df['L-PC'] = (_df['low']  - _df['close'].shift(1)).abs()
    tr = _df[['H-L', 'H-PC', 'L-PC']].max(axis=1)
    atr = tr.rolling(period).mean()
    atr_last = atr.dropna()
    return float(atr_last.iloc[-1]) if len(atr_last) else 0.0


### === OHLCV Fetch === ###
def fetch_ohlcv(symbol, interval="5m", limit=100):
    klines = client.klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'num_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df.astype(float)
    return df

def safe_fetch_ohlcv(symbol, interval='5m', limit=100):
    try:
        df = fetch_ohlcv(symbol, interval, limit)
        return df if df is not None and len(df) > 20 else None
    except Exception as e:
        print(f" [i] Skipping {symbol}: {e}")
        return None


### === 24h Tickers Compatibility Helper === ###
def _get_24h_tickers(c: UMFutures):
    """
    Handle connector variants gracefully.
    Prefer ticker_24hr(), fallback to ticker_24hr_price_change() if present.
    """
    # Try the common UMFutures method first
    try:
        return c.ticker_24hr()
    except Exception:
        pass
    # Fallback name if available in your environment
    fn = getattr(c, "ticker_24hr_price_change", None)
    if callable(fn):
        return fn()
    # As a last resort, raise to surface the issue
    raise RuntimeError("Neither ticker_24hr() nor ticker_24hr_price_change() is available on UMFutures.")


### === Top Gainers (Debug Version) === ###
def get_top_futures_gainers(client, agents, lookback=100, top_n=30):
    print("?? Running get_top_futures_gainers...")
    tickers = _get_24h_tickers(client)
    banlist = ["FUNUSDT", "GUNUSDT", "SKYAIUSDT", "PORTALUSDT", "MOODENGUSDT", "BANANAUSDT", "BONKUSDT"]
    min_24h_vol = 150000  # 150k
    candidates = []
    print(f"Total symbols to scan: {len(tickers)}")
    for t in tickers:
        symbol = t.get('symbol') or t.get('symbolName')
        if not symbol or (not symbol.endswith('USDT')) or symbol in banlist:
            # print(f"? {symbol}: Not USDT or in banlist")
            continue
        try:
            vol_usd = float(t.get('quoteVolume') or t.get('volume') or 0)
            if vol_usd < min_24h_vol:
                # print(f"? {symbol}: Low volume ({vol_usd})")
                continue
            klines = client.klines(symbol=symbol, interval='5m', limit=lookback)
            closes = [float(k[4]) for k in klines]
            # volumes = [float(k[5]) for k in klines]  # not used further
            if len(closes) < 20:
                # print(f"? {symbol}: Not enough bars ({len(closes)})")
                continue
            ret_1h = (closes[-1] - closes[-12]) / closes[-12]
            atrs = [abs(closes[i] - closes[i-1]) for i in range(1, len(closes))]
            atr_mean = np.mean(atrs[-20:-1])
            atr_now = atrs[-1]
            if atr_mean == 0 or atr_now < atr_mean * 0.1:
                # print(f"? {symbol}: ATR now ({atr_now}) < 0.1 x ATR mean ({atr_mean})")
                continue
            df = fetch_ohlcv(symbol, interval="5m")
            agent_signals = []
            for agent in agents:
                agent_name = getattr(agent, "__name__", "agent")
                try:
                    s = agent(df, symbol)
                    agent_signals.append(s)
                except Exception as e:
                    # print(f"? {symbol}: Agent {agent_name} crashed: {e}")
                    pass
            max_conf = max([float(s['confidence']) for s in agent_signals if s is not None and 'confidence' in s] + [0])
            if max_conf < 0.01:
                # print(f"? {symbol}: No agent confidence above 0.01 (max: {max_conf})")
                continue
            score = vol_usd * atr_now * abs(ret_1h)
            # print(f"? {symbol}: Candidate! vol={vol_usd} atr_now={atr_now} ret_1h={ret_1h} score={score} max_conf={max_conf}")
            candidates.append((symbol, score))
        except Exception:
            continue
    candidates.sort(key=lambda x: x[1], reverse=True)
    print(f"?? {len(candidates)} symbols passed all filters.")
    return [sym for sym, score in candidates[:top_n]]


### === Trade Execution (Futures) === ###
def get_symbol_precision(symbol):
    exchange_info = client.exchange_info()
    symbol_info = next(s for s in exchange_info['symbols'] if s['symbol'] == symbol)
    lot = [f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'][0]
    step_size = float(lot['stepSize'])
    precision = int(abs(Decimal(str(step_size)).as_tuple().exponent))
    min_qty = float(lot['minQty'])
    return step_size, precision, min_qty

def quantize_quantity(qty, step_size):
    step = Decimal(str(step_size))
    qty_decimal = Decimal(str(qty))
    return float((qty_decimal // step) * step)

def futures_execute_trade(symbol, side, qty):
    try:
        mark_price = float(client.mark_price(symbol=symbol)['markPrice'])
        step_size, precision, min_qty = get_symbol_precision(symbol)
        qty = quantize_quantity(qty, step_size)
        if qty < min_qty:
            print(f"? Trade Error [{symbol}] {side}: qty {qty} is below minimum ({min_qty})")
            send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
                f"? Trade Error {symbol}: qty {qty} < min {min_qty}")
            return None

        # Ensure margin/leverage are compliant for subaccounts (ISOLATED + 5x max)
        ensure_isolated_5x(symbol)

        order = client.new_order(
            symbol=symbol,
            side="BUY" if side == "BUY" else "SELL",
            type="MARKET",
            quantity=qty
        )
        print(f"? Futures {side.upper()} {symbol} @ ~{mark_price:.4f} | Qty: {qty}")
        send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
            f"? {side.upper()} {symbol} | Qty: {qty} @ {mark_price:.4f}")
        return {
            'symbol': symbol,
            'side': side,
            'entry_price': mark_price,
            'qty': qty,
            'order': order
        }
    except Exception as e:
        print(f"? Trade Error [{symbol}] {side}: {e}")
        send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
            f"? Trade Error {symbol}: {e}")
        return None


### === Close Trade === ###
def futures_close_trade(symbol, qty, side, reason):
    try:
        step_size, precision, min_qty = get_symbol_precision(symbol)
        qty = quantize_quantity(qty, step_size)
        if qty < min_qty:
            send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
                f"? Cannot close {symbol}: qty {qty} < min ({min_qty})")
            return

        # Guard as well before closing
        ensure_isolated_5x(symbol)

        order = client.new_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            type="MARKET",
            quantity=qty,
            reduceOnly=True
        )
        price = float(client.mark_price(symbol=symbol)['markPrice'])
        print(f"?? Closed {symbol} | Qty: {qty} | Price: {price} | Reason: {reason}")
        send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
            f"?? Closed {symbol} | {qty} @ {price} | Reason: {reason}")
        log_trade_to_csv({
            'timestamp': datetime.utcnow().isoformat(),
            'symbol': symbol,
            'side': 'close',
            'qty': qty,
            'price': price,
            'reason': reason
        })
    except Exception as e:
        print(f"? Close Error {symbol}: {e}")
        send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
            f"? Close Error {symbol}: {e}")


### === Balance Check (PM-aware) === ###
_last_bal_cache = 0.0
def get_futures_balance() -> float:
    """
    Return USDT futures wallet balance.
    Uses the global authenticated client first (no env dependency).
    If that fails and USE_PAPI=1, try Portfolio Margin PAPI.
    """
    global _last_bal_cache

    # --- UMFutures first (global client) ---
    try:
        # Prefer account() ? assets parsing
        acc = client.account()
        for a in acc.get("assets", []):
            if a.get("asset") == "USDT":
                ab = a.get("availableBalance")
                if ab is not None:
                    _last_bal_cache = float(ab)
                    return _last_bal_cache
                wb = a.get("walletBalance")
                if wb is not None:
                    _last_bal_cache = float(wb)
                    return _last_bal_cache
        # Fallback: balance()
        bals = client.balance()
        for b in bals:
            if b.get("asset") == "USDT":
                for k in ("availableBalance", "balance", "crossWalletBalance", "walletBalance"):
                    if k in b and b[k] is not None:
                        _last_bal_cache = float(b[k])
                        return _last_bal_cache
    except Exception as e:
        print(f"[BAL] UMFutures error: {e}. Using last={_last_bal_cache}")

    # --- Optional PAPI (only if explicitly enabled) ---
    if os.getenv("USE_PAPI", "0") == "1":
        try:
            base = "https://papi.binance.com"
            ts = str(int(time.time()*1000))
            params = f"recvWindow=50000&timestamp={ts}"
            sig = hmac.new(API_SECRET.encode(), params.encode(), hashlib.sha256).hexdigest()
            r = requests.get(f"{base}/papi/v1/balance?{params}&signature={sig}",
                             headers={"X-MBX-APIKEY": API_KEY}, timeout=5)
            r.raise_for_status()
            data = r.json()
            for row in data:
                if row.get("asset") == "USDT":
                    _last_bal_cache = float(row.get("balance", 0.0))
                    return _last_bal_cache
        except Exception as e:
            print(f"[BAL] PAPI error: {e}. Using last={_last_bal_cache}")

    return _last_bal_cache


# === NEW: Precise wallet/available snapshot for /status (prefers 'totalWalletBalance' first) ===
def get_futures_balances_snapshot():
    """
    Returns a dict with:
      - wallet: total wallet equity (USDT)
      - available: free USDT (availableBalance / availableMargin)
      - margin_in_use: wallet - available (>= 0)

    Strategy:
      1) UMFutures account()['totalWalletBalance'] if present.
      2) Otherwise account()['assets'][]: prefer 'balance' then 'walletBalance'.
      3) Otherwise balance() rows.
      4) As a last resort, derive: wallet = available + (totalInitialMargin or totalMaintMargin).
    """
    wallet = 0.0
    available = 0.0
    total_initial_margin = 0.0
    total_maint_margin = 0.0

    # ---- Try UMFutures account() (top-level first) ----
    try:
        acc = client.account()
        # Top-level totals many connectors expose
        twb = acc.get("totalWalletBalance")
        if twb is not None:
            wallet = float(twb)
        total_initial_margin = float(acc.get("totalInitialMargin", 0.0) or 0.0)
        total_maint_margin = float(acc.get("totalMaintMargin", 0.0) or 0.0)

        # Per-asset fallback from account()
        if wallet == 0.0:
            for a in acc.get("assets", []):
                if (a.get("asset") or "").upper() == "USDT":
                    wallet = float(a.get("balance", a.get("walletBalance", 0)) or 0.0)
                    available = float(a.get("availableBalance", a.get("availableMargin", 0)) or 0.0)
                    break
        else:
            # Still want available if we haven’t got it yet
            if available == 0.0:
                for a in acc.get("assets", []):
                    if (a.get("asset") or "").upper() == "USDT":
                        available = float(a.get("availableBalance", a.get("availableMargin", 0)) or 0.0)
                        break
    except Exception:
        acc = None  # keep for logic clarity

    # ---- If still empty, try balance() rows ----
    if wallet == 0.0 and available == 0.0:
        try:
            bals = client.balance()
            for b in (bals or []):
                if (b.get("asset") or "").upper() == "USDT":
                    wallet = float(b.get("balance", b.get("walletBalance", 0)) or 0.0)
                    available = float(b.get("availableBalance", b.get("availableMargin", 0)) or 0.0)
                    break
        except Exception:
            pass

    # ---- Last resort: derive wallet from available + margin ----
    if wallet == 0.0:
        implied_margin = total_initial_margin if total_initial_margin > 0 else total_maint_margin
        if available > 0.0 or implied_margin > 0.0:
            wallet = available + implied_margin

    margin_in_use = max(0.0, wallet - available)
    return {"wallet": wallet, "available": available, "margin_in_use": margin_in_use}


### === Resume Support === ###
def save_open_positions(data):
    with open("open_positions.json", "w") as f:
        json.dump(data, f, indent=2)

def load_open_positions():
    if os.path.exists("open_positions.json"):
        with open("open_positions.json", "r") as f:
            return json.load(f)
    return {}


### === Trade Logging === ###
def log_trade_to_csv(data):
    file = "trade_log.csv"
    df = pd.DataFrame([data])
    if not os.path.isfile(file):
        df.to_csv(file, index=False)
    else:
        df.to_csv(file, mode='a', header=False, index=False)

def get_precision(symbol):
    step_size, precision, _ = get_symbol_precision(symbol)
    return precision

def fetch_market_sentiment():
    return 50  # Neutral fallback sentiment


### === Unrealized PnL Fetch (PM-aware) === ###
def get_unrealized_pnl(symbol):
    """
    Try PAPI positionRisk first (Portfolio Margin), then fall back to UMFutures.
    Returns float or None on error.
    """
    # ---- Portfolio Margin (PAPI) ----
    for path in ("/papi/v2/positionRisk", "/papi/v1/positionRisk"):
        try:
            data = _signed_get("https://papi.binance.com", path, API_KEY, API_SECRET, params={"symbol": symbol})
            rows = data if isinstance(data, list) else [data]
            # Prefer exact symbol match if multiple rows
            for row in rows:
                if str(row.get("symbol")) == symbol:
                    if "unRealizedProfit" in row:
                        return float(row["unRealizedProfit"])
            # Fallback: first row
            if rows and "unRealizedProfit" in rows[0]:
                return float(rows[0]["unRealizedProfit"])
        except Exception:
            pass

    # ---- FAPI fallback ----
    try:
        info = client.position_information(symbol=symbol)
        if isinstance(info, list):
            info = info[0]
        return float(info["unRealizedProfit"])
    except Exception as e:
        print(f"? Unrealized PnL fetch error for {symbol}: {e}")
        return None


# === Optional: light shims to avoid -2015 when other code calls FAPI position endpoints ===
def _install_pm_shims_on_client(c):
    """
    Replace the instance's 'position_information' with a PM-aware shim.
    Only affects this 'client' object. Trading logic and everything else stays as-is.
    """
    try:
        c._orig_position_information = c.position_information
    except Exception:
        pass

    def _position_information_shim(symbol=None, **kwargs):
        # Try PAPI first
        for path in ("/papi/v2/positionRisk", "/papi/v1/positionRisk"):
            try:
                data = _signed_get("https://papi.binance.com", path, API_KEY, API_SECRET,
                                   params={"symbol": symbol} if symbol else None)
                # Match UMFutures shape: list of dicts
                return data if isinstance(data, list) else [data]
            except Exception:
                continue
        # Fallback to original UMFutures method
        try:
            return c._orig_position_information(symbol=symbol, **kwargs)
        except Exception as e:
            # Surface the same error to callers (your log already prints it)
            raise e

    try:
        c.position_information = _position_information_shim
    except Exception:
        pass

# install shims right away on the global client
_install_pm_shims_on_client(client)
