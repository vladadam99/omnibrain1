# -*- coding: utf-8 -*-
import os
import time
import signal
import traceback
import json
import pickle
import pandas as pd
import numpy as np
import threading
import requests
from datetime import datetime, timedelta, timezone
from safe_fetch_helper import safe_fetch_24h_tickers
from fingerprint_engine import build_indexes, record_fingerprint_on_close, find_best_win_match, find_best_loss_match, WIN_TRIGGER_SIM, LOSS_VETO_SIM, make_live_fingerprint, order_from_match


# ======================
#  TRADE MEMORY (Fingerprint store)
# ======================
import threading
from datetime import timezone

class TradeMemory:
    _lock = threading.Lock()
    def __init__(self, path="trade_memory.jsonl"):
        self.path = path
        self._counts_cache = None  # (wins, losses)

    def _safe_write(self, line: str):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def save(self, fp: dict) -> int:
        """Append a fingerprint and return its ordinal number (1-based)."""
        # assign id by counting lines
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    n = sum(1 for _ in f)
            else:
                n = 0
        except Exception:
            n = 0
        fp_id = n + 1
        fp["fingerprint_id"] = fp_id
        # normalize floats (ensure json serializable)
        def _norm(o):
            if isinstance(o, float):
                if o != o or o == float("inf") or o == float("-inf"):
                    return 0.0
                return float(o)
            return o
        fp = {k: _norm(v) for k, v in fp.items()}
        self._safe_write(json.dumps(fp, ensure_ascii=False))
        # invalidate counts cache
        self._counts_cache = None
        return fp_id

    def stats(self):
        """Return (wins, losses, total)."""
        if self._counts_cache is not None:
            w, l = self._counts_cache
            return w, l, (w + l)
        w = l = 0
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        if obj.get("outcome") == "WIN":
                            w += 1
                        elif obj.get("outcome") == "LOSS":
                            l += 1
                    except Exception:
                        continue
        self._counts_cache = (w, l)
        return w, l, (w + l)

trade_memory = TradeMemory(os.path.join(os.path.dirname(__file__), 'trade_memory.jsonl'))
def telegram_notify(token, chat_id, text):
    """Send Telegram, falling back silently if creds are missing."""
    try:
        if not token or not chat_id:
            return
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass

from binance.um_futures import UMFutures

from collections import defaultdict
from binance.error import ClientError
symbol_locks = defaultdict(threading.Lock)

# === RE-ENTRY COOLDOWN (per symbol) ===
from collections import defaultdict as _dd_cooldown
_COOLDOWN_SEC = 300.0  # 5 minutes
_last_exit_time = _dd_cooldown(lambda: 0.0)

def _record_exit_time(symbol: str):
    import time as _t
    _last_exit_time[symbol] = _t.monotonic()

def _can_enter_now(symbol: str) -> bool:
    import time as _t
    elapsed = _t.monotonic() - _last_exit_time[symbol]
    return elapsed >= _COOLDOWN_SEC




from collections import defaultdict as _dd_for_guard
import threading as _th_for_guard

# ---- Single-close guard (prevents duplicate close spam) ----
closing_guard = _dd_for_guard(_th_for_guard.Event)

def _begin_closing(symbol: str) -> bool:
    ev = closing_guard[symbol]
    if ev.is_set():
        return False
    ev.set()
    return True

def _end_closing(symbol: str):
    closing_guard[symbol].clear()

from omnibrain_utils import (
    load_api_keys, get_futures_balance, futures_execute_trade,
    save_open_positions, load_open_positions,
    send_telegram_message, calculate_atr, log_trade_to_csv
)


# === Fingerprint extractor (simple, symbol-agnostic) ===
def _ema(series, n):
    return series.ewm(span=n, adjust=False).mean()

def _rsi(series, n=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1*delta.clip(upper=0)
    ma_up = up.ewm(com=n-1, adjust=False).mean()
    ma_down = down.ewm(com=n-1, adjust=False).mean()
    rs = ma_up / (ma_down + 1e-9)
    return 100 - (100 / (1 + rs))

def extract_fingerprint(df, symbol, trend15, trend1h):
    close = df['close']
    high = df['high']
    low  = df['low']
    vol  = df['volume']
    # returns
    ret_1m = float((close.iloc[-1] / close.iloc[-2] - 1.0) * 100.0) if len(close) > 2 else 0.0
    ret_5m = float((close.iloc[-1] / close.iloc[-6] - 1.0) * 100.0) if len(close) > 6 else 0.0
    # EMAs
    ema9 = _ema(close, 9)
    ema21= _ema(close, 21)
    ma_fast = float(ema9.iloc[-1])
    ma_slow = float(ema21.iloc[-1])
    ma_fast_prev = float(ema9.iloc[-2]) if len(ema9)>1 else ma_fast
    ma_slow_prev = float(ema21.iloc[-2]) if len(ema21)>1 else ma_slow
    ma_fast_slope = (ma_fast - ma_fast_prev) / max(1e-9, close.iloc[-1]) * 100.0
    ma_slow_slope = (ma_slow - ma_slow_prev) / max(1e-9, close.iloc[-1]) * 100.0
    ma_ratio = ma_fast / max(1e-9, ma_slow)
    # Volatility
    tr = (high.combine(low, lambda h,l: h-l)).rolling(14).mean()
    atr_pct = float((tr.iloc[-1] / max(1e-9, close.iloc[-1])) * 100.0) if len(tr) else 0.0
    # Volume z
    vmed = vol.rolling(50).median()
    vmad = (vol - vmed).abs().rolling(50).median()
    vol_z = float((vol.iloc[-1] - (vmed.iloc[-1] if vmed.iloc[-1] > 0 else vol.iloc[-1])) / max(1e-9, vmad.iloc[-1] if vmad.iloc[-1] > 0 else 1.0))
    # Candle shape
    body = abs(close.iloc[-1] - df['open'].iloc[-1])
    rng  = (high.iloc[-1] - low.iloc[-1])
    body_pct = float(body / max(1e-9, rng))
    up_wick = float(high.iloc[-1] - max(close.iloc[-1], df['open'].iloc[-1]))
    dn_wick = float(min(close.iloc[-1], df['open'].iloc[-1]) - low.iloc[-1])
    wick_ratio = float((up_wick + dn_wick) / max(1e-9, body))
    # RSI/Stoch
    rsi = float(_rsi(close).iloc[-1])
    stoch_k = float(100 * (close.iloc[-1] - low.rolling(14).min().iloc[-1]) / max(1e-9, (high.rolling(14).max().iloc[-1] - low.rolling(14).min().iloc[-1])))
    # Simple pattern flags (bitfield): 1=engulf,2=hammer,4=doji,8=inside
    flags = 0
    # doji
    if body_pct < 0.1: flags |= 4
    # hammer
    if body_pct < 0.3 and dn_wick > body*2: flags |= 2
    # engulf (bull/bear)
    if len(close) > 2 and ( (df['open'].iloc[-1] < close.iloc[-2] and close.iloc[-1] > df['open'].iloc[-2]) or
                            (df['open'].iloc[-1] > close.iloc[-2] and close.iloc[-1] < df['open'].iloc[-2]) ):
        flags |= 1
    # inside bar
    if len(close)>2 and high.iloc[-1] < high.iloc[-2] and low.iloc[-1] > low.iloc[-2]: flags |= 8

    return {
        "ret_1m": ret_1m, "ret_5m": ret_5m,
        "ma_fast_slope": ma_fast_slope, "ma_slow_slope": ma_slow_slope,
        "ma_fast_over_slow": ma_ratio,
        "atr_pct": atr_pct, "vol_z": vol_z,
        "wick_ratio": wick_ratio, "body_pct": body_pct,
        "rsi": rsi, "stoch_k": stoch_k,
        "trend_15m": 1 if trend15=='UP' else (-1 if trend15=='DOWN' else 0),
        "trend_1h":  1 if trend1h=='UP' else (-1 if trend1h=='DOWN' else 0),
        "pattern_flags": flags
    }
last_tick_at = time.time()

# === NEW (optional) config bridge ===
try:
    # If you dropped the agents upgrade pack, this module exists
    from agents.apex_config import get_config as apex_get_config
except Exception:
    apex_get_config = None

# =====================================
#             CONFIGURABLES
# =====================================
TOP_N_SYMBOLS = 10
MIN_24H_VOL = 100_000
TELEGRAM_POLL_INTERVAL = 2

ML_TRAIN_DATA_DIR = "ml_agent_trades"
ML_RETRAIN_INTERVAL_SEC = 36000 * 12
os.makedirs(ML_TRAIN_DATA_DIR, exist_ok=True)

# ---- LOAD AGENTS (original 3 + optional new ones if present) ----
from agents.apex_vwap_pullback import generate_signal as apex_vwap_pullback
from agents.apex_sweep_reversal import generate_signal as apex_sweep_reversal
from agents.apex_microburst import generate_signal as apex_microburst

try:
    from agents.apex_supertrend_adaptive import generate_signal as apex_supertrend_adaptive
    HAS_SUPERTREND = True
except Exception:
    HAS_SUPERTREND = False

try:
    from agents.apex_momentum_pump import generate_signal as apex_momentum_pump
    HAS_MOMENTUM_PUMP = True
except Exception:
    HAS_MOMENTUM_PUMP = False

# --- SAFER RISK SETTINGS (5m is master) ---
LEVERAGE = 5
MIN_TRADE_USDT = 10
DEFAULT_TRADE_TIMEFRAME = "5m"         # 5m MASTER
trade_timeframe = DEFAULT_TRADE_TIMEFRAME
TRADE_TIMEFRAMES = ["5m"]               # entries are 5m-only now
CONFIDENCE_THRESHOLD = 0.70             # global floor (agents still have per-agent thresholds & weights)
MIN_AGREE_AGENTS = 1
MIN_AGREE_TIMEFRAMES = 1
TIME_IN_TRADE_LIMIT_MIN = 400
DAILY_PROFIT_TARGET = 3.0
DAILY_MAX_LOSS = -2
TP_SL_RR = 3.6
SL_ATR_MULT = 1.8                        # base; hybrid engine will adapt dynamically after entry
MIN_EXPECTED_MOVE = 0.009     
COOLDOWN_AFTER_LOSS_SEC = 1800
MAX_NEW_TRADES_PER_HOUR = 15
PAUSE_AFTER_PROFIT_SEC = 360
META_EVOLVE_INTERVAL = 3600
META_EVOLVE_EOD = 60 * 60 * 23
AGENT_MUTE_AFTER_LOSSES = 1
AGENT_MUTE_TIME = 360
MAX_PORTFOLIO_SIZE = 6
MAX_SYMBOL_ALLOC = 0.90
MAX_TOTAL_ALLOC = 0.9
MAX_LOSS_PER_TRADE = 0.10
# Trend filters moved to 15m/1h (agents also self-check). Kept here for extra veto if desired.
TREND_FILTER_ON = os.getenv("TREND_FILTER", "0") == "1"

# === HYBRID SL ENGINE knobs (tunable via TG later) ===
HYBRID_SL_MODE = "hybrid"      # "hybrid" | "hard" | "atr" | "trail"
HYBRID_ARM_RR = 1.5             # arm trailing when MFE >= RR * initial risk
HYBRID_ARM_ATR = 1.5            # or MFE >= N * ATR
HYBRID_TRAIL_K = 2.0            # trail step in ATR multiples when armed
BREAKEVEN_AFTER_MIN = 8 * 60    # seconds; if flat after N sec, tighten to BE - epsilon
BREAKEVEN_EPS_FRAC = 0.22       # fraction of ATR under BE for cushion

# Volatility classes (light heuristic; agents also apply their own)
VOL_HIGH_SYMBOLS = {"TRUMPUSDT", "PEPEUSDT", "DOGEUSDT", "SHIBUSDT", "FARTCOINUSDT"}

# === STATE ===
api_key, api_secret, telegram_token, telegram_chat_id = load_api_keys()
client = UMFutures(key=api_key, secret=api_secret)
symbol_precision_map = {}

# MAIN AGENT LIST (dynamic based on availability)
agents = [
    ("apex_vwap_pullback", apex_vwap_pullback),
    ("apex_sweep_reversal", apex_sweep_reversal),
    ("apex_microburst",    apex_microburst)
]
if HAS_SUPERTREND:
    agents.append(("apex_supertrend_adaptive", apex_supertrend_adaptive))
if HAS_MOMENTUM_PUMP:
    agents.append(("apex_momentum_pump", apex_momentum_pump))

agent_names = [name for name, _ in agents]

open_positions = load_open_positions()
previous_open_symbols = set(open_positions.keys())
daily_realized_pnl = 0.0
daily_trade_count = 0
last_pnl_reset_day = datetime.now(timezone.utc).date()
last_trade_time = None
new_trades_this_hour = []
pause_until = 0

# win/loss stats per agent
AGENT_STATS_FILE = 'agent_stats.pkl'
DEFAULT_THRESHOLD = CONFIDENCE_THRESHOLD

CONF_FLOOR = {
    "apex_vwap_pullback": 0.70,
    "apex_microburst":    0.70,
    "apex_sweep_reversal":0.70,
    "apex_supertrend_adaptive": 0.70,
    "apex_momentum_pump": 0.70,
}

TP_QUICK_PROFIT = 1.0  # USDT, Quick cash capture

# --- Sharper Quick TP controls (adaptive & ratcheting) ---
TP_QUICK_ATR_MULT     = 0.25   # portion of ATR (price units) converted to USDT via qty
QUICKTP_PULLBACK_FRAC = 0.18   # take profit if PnL pulls back this fraction from peak, once peak>=min
QUICKTP_EARLY_SEC     = 240    # early window (seconds) where we're extra-aggressive capturing
QUICKTP_EMA_CONFIRM   = True   # use EMA9/EMA21 confirmation to exit quickly when PnL>=min

# Ultra-sharp progressive capture rules:
# Each tuple is (peak_usdt_trigger, keep_fraction).
QUICKTP_LOCK_RULES = [
    (0.40, 0.78),
    (0.80, 0.85),
    (1.50, 0.90),
]



# Daily breakdown
pnl_day_wins = 0
pnl_day_losses = 0
pnl_day_win_usd = 0.0
pnl_day_loss_usd = 0.0

# Notifier so we only alert once when daily limit/target is hit
notified_daily_stop = False

# ===================
#   WS MARK PRICES
# ===================
_ws_mark = {}
_ws_lock = threading.Lock()
_ws_running = False
last_tick_at = time.time()
SHUTDOWN = threading.Event()

_ws_client = None         # handle for UMFuturesWebsocketClient
_ws_stop_event = threading.Event()

def restart_websocket():
    global _ws_running, _ws_client
    try:
        if _ws_client is not None:
            try:
                _ws_client.stop()
            except Exception:
                pass
    except Exception:
        pass
    _ws_stop_event.set()
    _ws_running = False
    time.sleep(1.0)
    _ws_stop_event.clear()
    # DO NOT restart if shutting down
    if not SHUTDOWN.is_set():
        start_mark_ws()

def stop_websocket():
    global _ws_running, _ws_client
    try:
        if _ws_client is not None:
            try:
                _ws_client.stop()
            except Exception:
                pass
    except Exception:
        pass
    _ws_stop_event.set()
    _ws_running = False

def _handle_signal(signum, frame):
    print(f"[SIGNAL] {signum} received - shutting down...")
    SHUTDOWN.set()
    # Stop WS and prevent any reconnects
    stop_websocket()

for _sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None), getattr(signal, "SIGBREAK", None)):
    if _sig:
        try:
            signal.signal(_sig, _handle_signal)
        except Exception:
            pass


def ws_watchdog():
    while not SHUTDOWN.is_set():
        try:
            if time.time() - last_tick_at > 30:
                print("[WS] No ticks for 30s - restarting websocket...")
                restart_websocket()
        except Exception as e:
            print("[WS] Watchdog error:", e)
        time.sleep(5)

threading.Thread(target=ws_watchdog, daemon=True).start()

# Initialize fingerprint indexes (phase 1)
build_indexes()



def _set_ws_mark(sym, px):
    with _ws_lock:
        _ws_mark[sym] = float(px)

def get_ws_mark(sym):
    with _ws_lock:
        return _ws_mark.get(sym)


def start_mark_ws():
    global _ws_running, _ws_client, last_tick_at
    if _ws_running:
        return
    try:
        try:
            from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
            _ws_client = UMFuturesWebsocketClient()
            def on_msg(msg):
                # --- UPDATE HEARTBEAT ---
                # NOTE: use global, not nonlocal
                global last_tick_at
                try:
                    data = msg.get('data')
                    if isinstance(data, list):
                        for it in data:
                            s = it.get('s') or it.get('symbol')
                            p = it.get('p') or it.get('markPrice')
                            if s and p:
                                _set_ws_mark(s, p)
                    last_tick_at = time.time()  # <- HEARTBEAT
                except Exception:
                    pass
            _ws_client.start()
            _ws_client.instant_subscribe(stream="!markPrice@arr", id=1, callback=on_msg)
            _ws_running = True
            print("[WS] UMFuturesWebsocketClient markPrice@arr started.")
            return
        except Exception:
            pass

        import json as _j
        import threading as _t
        import websocket as _ws

        def _run():
            global last_tick_at
            url = "wss://fstream.binance.com/stream?streams=!markPrice@arr"
            while not _ws_stop_event.is_set() and not SHUTDOWN.is_set():
                try:
                    ws = _ws.WebSocket()
                    ws.connect(url, timeout=10)
                    print("[WS] Connected to markPrice@arr")
                    while not _ws_stop_event.is_set() and not SHUTDOWN.is_set():
                        raw = ws.recv()
                        if not raw:
                            break
                        msg = _j.loads(raw)
                        data = msg.get('data')
                        if isinstance(data, list):
                            for it in data:
                                s = it.get('s') or it.get('symbol')
                                p = it.get('p') or it.get('markPrice')
                                if s and p:
                                    _set_ws_mark(s, p)
                        last_tick_at = time.time()  # <- HEARTBEAT
                except Exception as e:
                    print(f"[WS] reconnect due to: {e}")
                    time.sleep(2)
                finally:
                    try:
                        ws.close()
                    except Exception:
                        pass

        thr = _t.Thread(target=_run, daemon=True)
        thr.start()
        _ws_running = True
        print("[WS] websocket-client fallback started.")
    except Exception as e:
        print(f"[WS] disabled (no client): {e}")


# =====================================
#             UTILITIES
# =====================================

def compat_user_trades(client, symbol: str, start_ts_ms: int):
    for name in ("account_trades", "user_trades", "get_account_trades", "get_user_trades"):
        fn = getattr(client, name, None)
        if callable(fn):
            return fn(symbol=symbol, startTime=start_ts_ms)
    raise AttributeError("No user-trades method found on client")


def _position_amt_on_binance(symbol: str) -> float:
    try:
        pos = client.get_position_risk(symbol=symbol)
        if isinstance(pos, list) and pos:
            return float(pos[0].get("positionAmt", 0)) or 0.0
        return float(pos.get("positionAmt", 0)) if pos else 0.0
    except Exception as e:
        print(f"[RECONCILE] get_position_risk error {symbol}: {e}")
        return 0.0


def get_unrealized_pnl(symbol: str) -> float:
    """WS->mark fallback; then REST mark. Returns USDT PnL or 0.0 if flat/unknown."""
    try:
        rows = client.get_position_risk(symbol=symbol)
        if not isinstance(rows, list):
            rows = [rows]
        pos = None
        for r in rows:
            try:
                if r.get("symbol") == symbol and abs(float(r.get("positionAmt", "0"))) > 0.0:
                    pos = r
                    break
            except Exception:
                continue
        if not pos:
            return 0.0
        entry_price = float(pos.get("entryPrice", "0"))
        position_amt = float(pos.get("positionAmt", "0"))
        if entry_price == 0.0 or position_amt == 0.0:
            return 0.0
        px = get_ws_mark(symbol)
        if px is None:
            px = float(client.mark_price(symbol=symbol)["markPrice"])
        manual_pnl = (px - entry_price) * position_amt
        return float(manual_pnl)
    except Exception as e:
        print(f"[PnL ERROR] {symbol}: {e}")
        return 0.0


def _pnl_from_fills(fills, entry_price: float, side: str):
    realized = 0.0
    exit_notional = 0.0
    closed_qty = 0.0

    def _to_bool(x):
        if isinstance(x, bool): return x
        return str(x).lower() in ("1", "true", "t", "yes", "y")

    for tr in (fills or []):
        try:
            px = float(tr.get("price", 0.0) or 0.0)
            q  = float(tr.get("qty",   0.0) or 0.0)
            if px <= 0 or q <= 0:
                continue
            is_buyer = tr.get("isBuyer", tr.get("buyer"))
            is_buyer = _to_bool(is_buyer)
            reduces = ((side.upper() == "BUY"  and not is_buyer) or
                       (side.upper() == "SELL" and     is_buyer))
            if not reduces:
                continue

            # Use exchange-provided realizedPnl if present; DO NOT subtract commission again in that branch
            fill_real = tr.get("realizedPnl")
            if fill_real is not None:
                realized += float(fill_real)
            else:
                # Manual calc fallback
                realized += (px - entry_price) * q if side.upper() == "BUY" else (entry_price - px) * q
                raw = tr.get("_raw") or {}
                commission = float(raw.get("commission", 0) or 0)
                commission_asset = (raw.get("commissionAsset") or "USDT").upper()
                if commission and commission_asset == "USDT":
                    realized -= commission

            exit_notional += px * q
            closed_qty += q
        except Exception:
            continue
    avg_exit = (exit_notional / closed_qty) if closed_qty > 0 else None
    return realized, avg_exit, closed_qty



def _fetch_latest_close(symbol: str, start_ts_ms: int):
    def _to_float(x, default=0.0):
        try:
            return float(x)
        except Exception:
            return default
    try:
        raw_trades = compat_user_trades(client, symbol, start_ts_ms)
        fills = []
        for tr in (raw_trades or []):
            try:
                if tr.get("symbol") and tr.get("symbol") != symbol:
                    continue
                price = _to_float(tr.get("price", tr.get("p")))
                qty = _to_float(tr.get("qty", tr.get("q")))
                quote_qty = _to_float(tr.get("quoteQty", tr.get("Q")))
                realized = _to_float(tr.get("realizedPnl", 0))
                buyer_flag = tr.get("buyer", tr.get("isBuyer"))
                maker_flag = tr.get("maker", tr.get("isMaker"))
                t_ms = tr.get("time", tr.get("T"))
                fills.append({
                    "symbol": symbol,
                    "price": price,
                    "qty": qty,
                    "quoteQty": quote_qty,
                    "realizedPnl": realized,
                    "buyer": buyer_flag,
                    "isBuyer": buyer_flag,
                    "maker": maker_flag,
                    "time": t_ms,
                    "_raw": tr,
                })
            except Exception:
                continue
        if fills:
            return fills
    except Exception as e:
        print(f"[RECONCILE] user_trades unavailable {symbol}: {e}")
    try:
        px = get_ws_mark(symbol)
        if px is None:
            px = float(client.mark_price(symbol=symbol)["markPrice"])
        return {"_fallback": True, "markPrice": px}
    except Exception as e:
        print(f"[RECONCILE] mark_price fallback failed {symbol}: {e}")
        return None

def _fetch_latest_close_with_retry(symbol: str, start_ts_ms: int, retries: int = 5, delay: float = 0.2):
    """Try user trades a few times before falling back to mark price snapshot."""
    for _ in range(max(1, int(retries))):
        res = _fetch_latest_close(symbol, start_ts_ms)
        if isinstance(res, list) and len(res) > 0:
            return res
        time.sleep(delay)
    return _fetch_latest_close(symbol, start_ts_ms)


# ======================
#  PRECISION / OHLCV
# ======================

def get_symbol_precision_and_min(symbol):
    if symbol in symbol_precision_map:
        return symbol_precision_map[symbol]
    info = client.exchange_info()
    qty_precision, price_precision = 3, 2
    min_qty, min_notional = 0.001, 1.0
    for s in info['symbols']:
        if s['symbol'] == symbol:
            for f in s['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    step_size = float(f['stepSize'])
                    qty_precision = int(abs(np.log10(step_size)))
                    min_qty = float(f['minQty'])
                if f['filterType'] == 'PRICE_FILTER':
                    tick_size = float(f['tickSize'])
                    price_precision = int(abs(np.log10(tick_size)))
                if f['filterType'] == 'MIN_NOTIONAL':
                    min_notional = float(f['notional'])
            break
    symbol_precision_map[symbol] = (qty_precision, price_precision, min_qty, min_notional)
    return qty_precision, price_precision, min_qty, min_notional


def fetch_ohlcv(symbol, interval=None, limit=120):
    if interval is None:
        interval = trade_timeframe
    klines = client.klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base', 'taker_buy_quote', 'ignore'
    ])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df


# ======================
#  META / STATS / TUNER
# ======================

def save_agent_stats(stats):
    with open(AGENT_STATS_FILE, 'wb') as f:
        pickle.dump(stats, f)


def load_agent_stats():
    stats = {}
    if os.path.exists(AGENT_STATS_FILE):
        with open(AGENT_STATS_FILE, 'rb') as f:
            stats = pickle.load(f)
    changed = False
    for name in agent_names:
        if name not in stats:
            stats[name] = {'wins': 0, 'losses': 0, 'loss_streak': 0,
                           'last_loss': 0, 'muted_until': 0, 'threshold': DEFAULT_THRESHOLD,
                           'pnl': 0.0, 'trades': 0}
            changed = True
        elif 'threshold' not in stats[name]:
            stats[name]['threshold'] = DEFAULT_THRESHOLD
            changed = True
        if 'pnl' not in stats[name]:
            stats[name]['pnl'] = 0.0
            changed = True
        if 'trades' not in stats[name]:
            stats[name]['trades'] = 0
            changed = True
    if changed:
        save_agent_stats(stats)
    return stats

agent_stats = load_agent_stats()


def _agent_weight(name: str) -> float:
    s = agent_stats.get(name, {})
    wins = s.get('wins', 0)
    losses = s.get('losses', 0)
    total = max(1, wins + losses)
    wr = wins / total
    # base 0.5..1.0 by WR, mute on streak
    weight = 0.5 + 0.5 * wr
    if s.get('muted_until', 0) > time.time():
        return 0.0
    return float(max(0.0, min(1.0, weight)))



def update_agent_threshold(agent_name, trade_win_rate=None):
    """No-op: auto-mutation disabled.
    This function used to tweak per-agent thresholds based on win rate.
    Now it only persists that the agent exists and leaves thresholds unchanged.
    """
    try:
        _ = agent_stats.get(agent_name)  # touch to ensure stats entry exists
    except Exception:
        pass
    return


# ---------- Fingerprint Telegram helper ----------
def notify_fingerprint_saved(fp_row: dict, symbol: str):
    try:
        outcome = fp_row.get("outcome", "?")
        fid = fp_row.get("id", "")
        tmpl = fp_row.get("template") or {}
        slm = tmpl.get("sl_mult_atr")
        tpm = tmpl.get("tp_mult_atr")
        msg = f"?? Fingerprint saved [{outcome}] {symbol} id={fid}"
        if slm is not None and tpm is not None:
            try:
                msg += f"  (SLxATR={float(slm):.2f}, TPxATR={float(tpm):.2f})"
            except Exception:
                pass
        send_telegram_message(telegram_token, telegram_chat_id, msg)
    except Exception:
        pass


def meta_evolution():
    """No-op: global threshold auto-evolution disabled."""
    try:
        print("[META-EVOLUTION] Skipped (auto-mutation disabled).")
    except Exception:
        pass
    return



# ======================
#  TELEGRAM COMMANDS
# ======================
BANLIST = set(["BTCUSDT", "ETHUSDT"])  # default exclusions

def telegram_command_handler():
    global pause_until, CONFIDENCE_THRESHOLD, agent_stats, open_positions, daily_realized_pnl, daily_trade_count, trade_timeframe, TP_QUICK_PROFIT
    global MIN_TRADE_USDT, SL_ATR_MULT, TP_SL_RR, MIN_EXPECTED_MOVE, MAX_LOSS_PER_TRADE, MAX_NEW_TRADES_PER_HOUR, MIN_AGREE_AGENTS, MIN_AGREE_TIMEFRAMES
    global pnl_day_wins, pnl_day_losses, pnl_day_win_usd, pnl_day_loss_usd, HYBRID_SL_MODE, HYBRID_ARM_RR, HYBRID_ARM_ATR, HYBRID_TRAIL_K

    last_update_id = None
    print("[TELEGRAM] Command handler started.")
    help_text = (
        "?? OMNIBRAIN - Essentials\n"
        "/status | /pnl [day|week]\n"
        "/pause [sec] | /resume\n"
        "/agents  (weights, WR, streaks)\n"
        "/pnl_agents\n"
        "/set_conf <agent> <0.50-0.99>\n"
        "/tighten <pct> | /loosen <pct>\n"
        "/set_min_move <fraction>\n"
        "/tp_settings [usdt] (Quick TP)\n"
        "/set_sl_atr <mult> | /set_tp_rr <ratio>\n"
        "/set_min_trade <usdt> | /set_max_loss <usdt>\n"
        "/set_newtrades_ph <int>\n"
        "/ban <symbol> | /unban <symbol>\n"
        "/force_close <symbol>\n"
        "/tf  (locked to 5m)\n"
        "/help\n"
    )
    while not SHUTDOWN.is_set():
        try:
            url = f"https://api.telegram.org/bot{telegram_token}/getUpdates"
            params = {"timeout": 10, "offset": last_update_id + 1 if last_update_id else None}
            try:
                resp = requests.get(url, params=params, timeout=30)
                data = resp.json()
            except Exception as e:
                print(f"[TELEGRAM CONNECTION ERROR] {e}")
                time.sleep(TELEGRAM_POLL_INTERVAL)
                continue
            if not data.get("ok"):
                time.sleep(TELEGRAM_POLL_INTERVAL)
                continue
            for update in data["result"]:
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                if str(chat_id) != str(telegram_chat_id):
                    continue
                text = (msg.get("text", "") or "").strip()
                if not text:
                    continue
                print(f"[TELEGRAM] Command received: {text}")
                response = ""
                parts = text.split()
                cmd = parts[0].lower()

                if cmd == "/status":
                    balance = get_futures_balance()
                    op = load_open_positions()
                    # open positions details
                    lines = []
                    tot_unreal = 0.0
                    for sym, pos in op.items():
                        px = get_ws_mark(sym)
                        if px is None:
                            try:
                                px = float(client.mark_price(symbol=sym)["markPrice"])
                            except Exception:
                                px = float(pos.get('entry_price', 0.0))
                        qty = float(pos.get('qty', 0.0))
                        side = pos.get('side', '?')
                        entry = float(pos.get('entry_price', 0.0))
                        upnl = (px - entry) * qty if side.upper() == "BUY" else (entry - px) * qty
                        tot_unreal += upnl
                        lines.append(f"{sym} {side} qty={qty} EP={entry:.6f} Px={px:.6f} uPnL={upnl:.2f}$ agent={pos.get('agent','?')}")
                    # agent summary
                    a_lines = []
                    for a in agent_names:
                        sdat = agent_stats.get(a, {})
                        wr = (sdat.get('wins',0) / max(1, sdat.get('wins',0)+sdat.get('losses',0)))
                        a_lines.append(f"{a}: PnL=${sdat.get('pnl',0.0):.2f}, Trades={sdat.get('trades',0)}, WR={wr:.2f}, thr={sdat.get('threshold',CONFIDENCE_THRESHOLD):.2f}, w={_agent_weight(a):.2f}")
                    response = (
                        f"[STATUS]\nBalance: {balance:.2f} USDT\n"
                        f"Open: {len(op)} | Unrealized: {tot_unreal:.2f}$\n"
                        f"Portfolio: {list(op.keys())}\n"
                        f"Daily PnL: {daily_realized_pnl:.2f}$ | Trades: {daily_trade_count}\n"
                        f"TF: {trade_timeframe} (locked) | QuickTP: ${TP_QUICK_PROFIT:.2f} | MinMove: {MIN_EXPECTED_MOVE:.4f}\n"
                        f"Agents:\n" + ("\n".join(a_lines) if a_lines else "n/a") + ("\nPositions:\n" + "\n".join(lines) if lines else "\nPositions: none")
                    )

                elif cmd == "/pnl":
                    response = (
                        f"[PNL - DAY]\nWins: {pnl_day_wins} (+${pnl_day_win_usd:.2f})\n"
                        f"Losses: {pnl_day_losses} (-${pnl_day_loss_usd:.2f})\n"
                        f"Net: ${daily_realized_pnl:.2f} | Trades: {daily_trade_count}"
                    )

                elif cmd == "/pause":
                    seconds = int(parts[1]) if len(parts) > 1 else 3600
                    pause_until = time.time() + seconds
                    response = f"?? Paused for {seconds//60} min."

                elif cmd == "/resume":
                    pause_until = 0
                    response = "?? Resumed."

                elif cmd == "/agents":
                    lines = []
                    for a in agent_names:
                        s = agent_stats.get(a, {})
                        wr = (s.get('wins',0) / max(1, s.get('wins',0)+s.get('losses',0)))
                        lines.append(f"{a}: thr={s.get('threshold',CONFIDENCE_THRESHOLD):.2f}, WR={wr:.2f}, weight={_agent_weight(a):.2f}, streak={s.get('loss_streak',0)}, mute_till={int(s.get('muted_until',0)-time.time()) if s.get('muted_until',0)>time.time() else 0}s")
                    response = "[AGENTS]\n" + "\n".join(lines)

                elif cmd == "/pnl_agents":
                    lines = []
                    for a in agent_names:
                        s = agent_stats.get(a, {})
                        wr = s.get('wins',0) / max(1, s.get('wins',0)+s.get('losses',0))
                        lines.append(
                            f"{a}: PnL=${s.get('pnl',0.0):.2f}, Trades={s.get('trades',0)}, "
                            f"WR={wr:.2f}, thr={s.get('threshold',CONFIDENCE_THRESHOLD):.2f}, w={_agent_weight(a):.2f}"
                        )
                    response = "[AGENT PnL]\n" + "\n".join(lines)

                elif cmd == "/set_conf" and len(parts) == 3:
                    agent, val = parts[1], float(parts[2])
                    if agent in agent_stats:
                        agent_stats[agent]['threshold'] = min(0.99, max(0.50, val))
                        save_agent_stats(agent_stats)
                        response = f"{agent} threshold ? {agent_stats[agent]['threshold']:.2f}"
                    else:
                        response = f"Unknown agent: {agent}"

                elif cmd == "/tighten" and len(parts) == 2:
                    pct = float(parts[1]); factor = 1 + pct/100.0
                    for a in agent_names:
                        agent_stats[a]['threshold'] = min(0.99, agent_stats[a].get('threshold', CONFIDENCE_THRESHOLD) * factor)
                    save_agent_stats(agent_stats)
                    response = "Tightened by {0:.1f}%\n".format(pct) + "\n".join(f"{a}: {agent_stats[a]['threshold']:.2f}" for a in agent_names)

                elif cmd == "/loosen" and len(parts) == 2:
                    pct = float(parts[1]); factor = max(0.0, 1 - pct/100.0)
                    for a in agent_names:
                        agent_stats[a]['threshold'] = max(0.50, agent_stats[a].get('threshold', CONFIDENCE_THRESHOLD) * factor)
                    save_agent_stats(agent_stats)
                    response = "Loosened by {0:.1f}%\n".format(pct) + "\n".join(f"{a}: {agent_stats[a]['threshold']:.2f}" for a in agent_names)

                elif cmd == "/set_min_move" and len(parts) == 2:
                    MIN_EXPECTED_MOVE = max(0.0005, float(parts[1]))
                    response = f"MIN_EXPECTED_MOVE ? {MIN_EXPECTED_MOVE:.5f}"

                elif cmd == "/tp_settings":
                    if len(parts) == 2:
                        TP_QUICK_PROFIT = float(parts[1])
                        response = f"Quick TP ? ${TP_QUICK_PROFIT:.2f}"
                    else:
                        response = f"Quick TP: ${TP_QUICK_PROFIT:.2f}"

                elif cmd == "/set_sl_atr" and len(parts) == 2:
                    SL_ATR_MULT = max(0.05, float(parts[1]))
                    response = f"SL_ATR_MULT ? {SL_ATR_MULT:.3f}"

                elif cmd == "/set_tp_rr" and len(parts) == 2:
                    TP_SL_RR = max(0.5, float(parts[1]))
                    response = f"TP_SL_RR ? {TP_SL_RR:.3f}"

                elif cmd == "/set_min_trade" and len(parts) == 2:
                    MIN_TRADE_USDT = max(1.0, float(parts[1]))
                    response = f"MIN_TRADE_USDT ? {MIN_TRADE_USDT:.2f}"

                elif cmd == "/set_max_loss" and len(parts) == 2:
                    MAX_LOSS_PER_TRADE = max(0.5, float(parts[1]))
                    response = f"MAX_LOSS_PER_TRADE ? ${MAX_LOSS_PER_TRADE:.2f}"

                elif cmd == "/set_newtrades_ph" and len(parts) == 2:
                    MAX_NEW_TRADES_PER_HOUR = max(1, int(parts[1]))
                    response = f"MAX_NEW_TRADES_PER_HOUR ? {MAX_NEW_TRADES_PER_HOUR}"

                elif cmd == "/ban" and len(parts) == 2:
                    BANLIST.add(parts[1].upper())
                    response = f"Banned {parts[1].upper()}"

                elif cmd == "/unban" and len(parts) == 2:
                    BANLIST.discard(parts[1].upper())
                    response = f"Unbanned {parts[1].upper()}"

                elif cmd == "/force_close" and len(parts) == 2:
                    symbol = parts[1].upper()
                    positions_disk = load_open_positions()
                    pos = positions_disk.get(symbol)
                    if not pos:
                        response = f"No open position for {symbol}."
                    else:
                        try:
                            px = get_ws_mark(symbol)
                            if px is None:
                                px = float(client.mark_price(symbol=symbol)["markPrice"])
                            qty = pos['qty']; side = pos['side']
                            close_position(symbol, px, qty, side, "Force close from Telegram", realized_pnl=get_unrealized_pnl(symbol) or 0)
                            response = f"Force close sent for {symbol} at {px}"
                        except Exception as e:
                            response = f"Failed: {e}"

                elif cmd in ("/set_timeframe", "/tf"):
                    response = "Timeframe locked to 5m for entries."

                elif cmd == "/help":
                    response = help_text
                else:
                    response = "Unknown command. /help for options."

                try:
                    send_telegram_message(telegram_token, telegram_chat_id, response)
                except Exception:
                    pass
        except Exception as e:
            print(f"[TELEGRAM ERROR] {e}")
        time.sleep(TELEGRAM_POLL_INTERVAL)


telegram_thread = threading.Thread(target=telegram_command_handler, daemon=True)
telegram_thread.start()


# ======================
#  TREND (HTF)
# ======================
_trend_cache = {}
TREND_EMA_FAST = 9
TREND_EMA_SLOW = 21
TREND_HYSTERESIS_SECS = 60

def _trend_label_from_emas(df: pd.DataFrame, fast=TREND_EMA_FAST, slow=TREND_EMA_SLOW):
    if df is None or len(df) < slow + 2:
        return "SIDEWAYS"
    efast = df['close'].ewm(span=fast, adjust=False).mean()
    eslow = df['close'].ewm(span=slow, adjust=False).mean()
    if efast.iloc[-1] > eslow.iloc[-1] * 1.0003:
        return "UP"
    if efast.iloc[-1] * 1.0003 < eslow.iloc[-1]:
        return "DOWN"
    return "SIDEWAYS"


def get_trend_htf(symbol):
    try:
        df15 = fetch_ohlcv(symbol, interval="15m", limit=200)
        df1h = fetch_ohlcv(symbol, interval="1h", limit=240)
        t15 = _trend_label_from_emas(df15)
        t1h = _trend_label_from_emas(df1h)
        # Basic merge: prefer 1h, otherwise 15m
        if t1h == t15:
            label = t1h
        else:
            label = t1h if t1h != "SIDEWAYS" else t15
        # hysteresis
        now = time.time()
        last = _trend_cache.get(symbol)
        if last and last[0] != label and (now - last[1]) < TREND_HYSTERESIS_SECS:
            label = last[0]
        _trend_cache[symbol] = (label, now)
        return label, t15, t1h
    except Exception as e:
        print(f"[HTF TREND ERROR] {symbol}: {e}")
        return "SIDEWAYS", "SIDEWAYS", "SIDEWAYS"


# ======================
#   CORE LOOP HELPERS
# ======================

def _vol_class(symbol, vol_usd):
    if symbol in VOL_HIGH_SYMBOLS:
        return "HIGH"
    if vol_usd >= 1_000_000_000:
        return "MED"
    return "LOW"


def _expected_move_ratio(entry, tp):
    try:
        return abs(tp - entry) / max(1e-9, entry)
    except Exception:
        return 0.0


def _call_agent(agent_fn, df5m, symbol, ctx):
    """Call new agents (df, symbol, ctx). If older signature, adapt gracefully."""
    try:
        return agent_fn(df5m, symbol, ctx)
    except TypeError:
        try:
            # very old agents may expect (dfs_dict, symbol)
            return agent_fn({trade_timeframe: df5m}, symbol)
        except Exception:
            return None


def smart_vote(symbol, signals_by_agent, min_agents=MIN_AGREE_AGENTS, min_timeframes=MIN_AGREE_TIMEFRAMES):
    """
    5m-only vote with agent weights. Confidence is multiplied by agent weight.
    Returns: (winner_side, avg_weighted_conf, used_list[(agent, eff_conf, sig), ...])
    """
    col = []
    for agent_name, sig in signals_by_agent.items():
        if not sig or not isinstance(sig, dict):
            continue
        s = sig.get(trade_timeframe) if trade_timeframe in sig else sig
        if s and s.get('side') in ('BUY','SELL'):
            w = _agent_weight(agent_name) or 0.0
            eff_conf = float(s.get('confidence', 0)) * w
            col.append((agent_name, s['side'], eff_conf, s))
    if not col:
        return None

    sides = {'BUY':[], 'SELL':[]}
    for an, side, eff_conf, s in col:
        sides[side].append((an, eff_conf, s))

    sum_buy  = sum(c for _, c, _ in sides['BUY'])
    sum_sell = sum(c for _, c, _ in sides['SELL'])
    winner = 'BUY' if sum_buy >= sum_sell else 'SELL'

    used = [x for x in sides[winner] if x[1] > 0]
    if len(used) < min_agents:
        return None

    avg_conf = float(np.mean([c for _, c, _ in used])) if used else 0.0
    return winner, avg_conf, used


# ======================
#   CLOSE / ACCOUNTING
# ======================

def record_outcome(pnl):
    global pnl_day_wins, pnl_day_losses, pnl_day_win_usd, pnl_day_loss_usd
    if pnl is None:
        return
    if pnl >= 0:
        pnl_day_wins += 1
        pnl_day_win_usd += pnl
    else:
        pnl_day_losses += 1
        pnl_day_loss_usd += abs(pnl)





def close_position(symbol, mark_price, qty, side, reason, realized_pnl=0, features=None, agent_for_stats=None):
    """
    Idempotent closer to cap fees at ONE open + ONE close per trade.
    Cancels children first, then a single reduce-only market close.
    """
    global daily_realized_pnl, daily_trade_count, agent_stats

    if not _begin_closing(symbol):
        return
    try:
        with symbol_locks[symbol]:
            try:
                client.cancel_all_open_orders(symbol=symbol)
            except Exception:
                pass

            rows = client.get_position_risk(symbol=symbol)
            if isinstance(rows, list):
                pos_row = next((r for r in rows if r.get('symbol') == symbol), None)
            else:
                pos_row = rows if rows and rows.get('symbol') == symbol else None

            live_amt = 0.0
            if pos_row:
                try:
                    live_amt = abs(float(pos_row.get("positionAmt", "0") or 0.0))
                except Exception:
                    live_amt = 0.0
            if live_amt <= 0.0:
                send_telegram_message(telegram_token, telegram_chat_id, f"No open position for {symbol}.")
                return

            qty_precision, price_precision, min_qty, _ = get_symbol_precision_and_min(symbol)
            qty_to_close = round(live_amt, qty_precision)
            opposite = 'SELL' if (str(side).upper() == 'BUY') else 'BUY'

            client.new_order(symbol=symbol, side=opposite, type="MARKET", quantity=qty_to_close, reduceOnly=True)

            pos = open_positions.get(symbol, {})
            entry_price = float(pos.get('entry_price', 0.0))
            entry_iso = pos.get('time')
            from datetime import datetime, timezone, timedelta
            entry_dt = datetime.fromisoformat(entry_iso).replace(tzinfo=timezone.utc) if entry_iso else datetime.now(timezone.utc) - timedelta(minutes=5)
            start_ms = int(entry_dt.timestamp() * 1000)

            fills = _fetch_latest_close_with_retry(symbol, start_ms, retries=5, delay=0.2)
            exit_price_for_msg = mark_price
            realized_pnl_final = float(realized_pnl or 0.0)

            if isinstance(fills, list) and fills:
                realized_pnl_final, avg_exit, _ = _pnl_from_fills(fills, entry_price, side)
                if avg_exit is not None:
                    exit_price_for_msg = float(avg_exit)
            else:
                try:
                    px = get_ws_mark(symbol)
                    if px is None:
                        px = float(client.mark_price(symbol=symbol)["markPrice"])
                    exit_price_for_msg = float(px)
                except Exception:
                    pass
                if entry_price and qty_to_close:
                    realized_pnl_final = (exit_price_for_msg - entry_price) * qty_to_close if str(side).upper()=="BUY" else (entry_price - exit_price_for_msg) * qty_to_close

            log_trade_to_csv({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'symbol': symbol, 'side': 'close', 'qty': qty_to_close, 'price': exit_price_for_msg, 'reason': reason
            })
            daily_realized_pnl += (realized_pnl_final or 0.0)
            daily_trade_count  += 1
            # Persist fingerprint outcome
            try:
                pos_features = open_positions.get(symbol, {}).get('features_open')
                fp_row = record_fingerprint_on_close(
                    symbol=symbol, side=side, timeframe=trade_timeframe, agent=pos.get('agent'),
                    entry_price=entry_price, exit_price=exit_price_for_msg, qty=qty_to_close, pnl=realized_pnl_final,
                    ts_open_iso=pos.get('time'), features_open=pos_features, leverage=LEVERAGE,
                    sl_price=pos.get('sl'), tp_price=pos.get('tp'), reason=reason
                )
                try:
                    notify_fingerprint_saved(fp_row, symbol)
                except Exception:
                    pass
            except Exception as _e:
                print("[FP SAVE] close error:", _e)

            record_outcome(realized_pnl_final or 0.0)

            agents_str = agent_for_stats if agent_for_stats else open_positions.get(symbol, {}).get('agent', None)
            agent_list = [a.strip() for a in str(agents_str or "").split(',') if a.strip()]
            share = float(realized_pnl_final or 0.0) / max(1, len(agent_list) or 1)
            for agent in (agent_list or []):
                if agent in agent_stats:
                    if (realized_pnl_final or 0) < 0:
                        agent_stats[agent]['losses'] += 1
                        agent_stats[agent]['loss_streak'] += 1
                        if agent_stats[agent]['loss_streak'] >= AGENT_MUTE_AFTER_LOSSES:
                            agent_stats[agent]['muted_until'] = time.time() + AGENT_MUTE_TIME
                    else:
                        agent_stats[agent]['wins'] += 1
                        agent_stats[agent]['loss_streak'] = 0
                    agent_stats[agent]['pnl']    = agent_stats[agent].get('pnl', 0.0) + share
                    agent_stats[agent]['trades'] = agent_stats[agent].get('trades', 0) + 1
                    update_agent_threshold(agent)
            save_agent_stats(agent_stats)

            try:
                send_telegram_message(telegram_token, telegram_chat_id, f"? Closed {symbol} ({side}) qty={qty_to_close} @ {exit_price_for_msg:.6f} | PnL {realized_pnl_final:+.2f}$ | {reason}")
            except Exception:
                pass
    except Exception as e:
        try:
            send_telegram_message(telegram_token, telegram_chat_id, f"Error closing {symbol}: {e}")
        except Exception:
            pass
    finally:
        _record_exit_time(symbol)
        _record_exit_time(symbol)
        open_positions.pop(symbol, None)
        save_open_positions(open_positions)
        _end_closing(symbol)

def place_tp_sl_orders(symbol, side, tp, sl):
    """
    Intentionally a NO-OP.
    We don't place any TP/SL orders on-exchange to avoid extra fees or order churn.
    All exits are handled internally in _monitor_positions_once() with a single
    reduce-only market order when thresholds are hit.
    """
    return

def current_winrate(n=20):
    if not recent_outcomes:
        return None
    tail = recent_outcomes[-n:] if len(recent_outcomes) >= n else recent_outcomes[:]
    wins = sum(1 for x in tail if x > 0)
    return wins / len(tail)




def autotune_if_stale():
    """Passive monitor only.
    Previously adjusted CONFIDENCE_THRESHOLD and MIN_EXPECTED_MOVE over time.
    Now it computes stats but *does not* change values* to avoid auto-drift.
    Use /tighten, /loosen, or /set_conf via Telegram to adjust manually.
    *Also resilient if globals aren't defined yet.
    """
    global last_trade_or_signal_time
    now = time.time()
    # Safe reads of globals with defaults if not yet defined
    _base_conf_default = 0.72
    _base_move_default = 0.001
    _base_conf = float(globals().get("CONFIDENCE_THRESHOLD", _base_conf_default))
    _base_move = float(globals().get("MIN_EXPECTED_MOVE", _base_move_default) or _base_move_default)

    if not hasattr(autotune_if_stale, "_wr_ema"):
        autotune_if_stale._wr_ema = None
        autotune_if_stale._base_conf = _base_conf
        autotune_if_stale._base_move = _base_move
        autotune_if_stale._last_notice = 0.0
        autotune_if_stale._stale_step = 0

    wr20 = current_winrate(20)
    wr_ema_prev = autotune_if_stale._wr_ema
    if wr20 is not None:
        autotune_if_stale._wr_ema = wr20 if wr_ema_prev is None else (0.2*wr20 + 0.8*wr_ema_prev)
    # No threshold adjustments here (intentionally).
    return

    wr20 = current_winrate(20)
    wr_ema_prev = autotune_if_stale._wr_ema
    if wr20 is not None:
        autotune_if_stale._wr_ema = wr20 if wr_ema_prev is None else (0.2*wr20 + 0.8*wr_ema_prev)
    # No threshold adjustments here (intentionally).
    return

    wr20 = current_winrate(20)
    wr_ema_prev = autotune_if_stale._wr_ema
    if wr20 is not None:
        autotune_if_stale._wr_ema = wr20 if wr_ema_prev is None else (0.2*wr20 + 0.8*wr_ema_prev)
    wr_ema = autotune_if_stale._wr_ema

    # bounds
    HARD_CONF_MIN, HARD_CONF_MAX = 0.60, 0.83
    HARD_MOVE_MIN, HARD_MOVE_MAX = 0.0008, 0.0035

    new_conf = float(CONFIDENCE_THRESHOLD)
    new_move = float(MIN_EXPECTED_MOVE)
    stale_secs = max(0.0, now - float(last_trade_or_signal_time or 0))

    # mild regime tweaks
    if wr_ema is not None and wr_ema >= 0.70:
        new_conf = min(HARD_CONF_MAX, new_conf + 0.01)
        new_move = min(HARD_MOVE_MAX, new_move * 1.05)
    elif wr_ema is not None and wr_ema <= 0.35:
        new_conf = max(HARD_CONF_MIN, new_conf - 0.02)
        new_move = max(HARD_MOVE_MIN, new_move * 0.92)
    else:
        new_conf += (autotune_if_stale._base_conf - new_conf) * 0.25
        new_move += (autotune_if_stale._base_move - new_move) * 0.25

    if abs(new_conf - CONFIDENCE_THRESHOLD) > 1e-9 or abs(new_move - MIN_EXPECTED_MOVE) > 5e-7:
        CONFIDENCE_THRESHOLD = float(round(new_conf, 3))
        MIN_EXPECTED_MOVE = float(round(new_move, 6))



# ======================
#  POSITION MONITOR (Quick TP + Hybrid SL)  refactored to avoid syntax errors
# ======================
def _monitor_positions_once():
    """
    Enforce internal fixed exits:
      • Quick TP (USDT): close when unrealized PnL >= TP_QUICK_PROFIT
      • Max Loss per Trade (USDT): close when unrealized PnL <= -MAX_LOSS_PER_TRADE
    No TP/SL orders are placed on the exchange; we only send a single reduce-only
    market order when a threshold is hit.
    """
    try:
        if not open_positions:
            return
        # iterate on a copy to avoid mutation issues during close
        for symbol, pos in list(open_positions.items()):
            try:
                side = str(pos.get('side', '')).upper()
                qty  = float(pos.get('qty', 0.0) or 0.0)
                if side not in ('BUY', 'SELL') or qty <= 0:
                    continue

                # Use exchange/account data to get unrealized PnL in USDT
                upnl = float(get_unrealized_pnl(symbol) or 0.0)

                # Quick TP (USDT)
                if upnl >= float(TP_QUICK_PROFIT):
                    px = get_ws_mark(symbol)
                    if px is None:
                        try:
                            px = float(client.mark_price(symbol=symbol)["markPrice"])
                        except Exception:
                            px = float(pos.get('entry_price', 0.0) or 0.0)
                    close_position(
                        symbol=symbol,
                        mark_price=px,
                        qty=qty,
                        side=side,
                        reason="Quick TP hit (internal)",
                        realized_pnl=upnl
                    )
                    continue

                # Max loss per trade (USDT)
                max_loss_usdt = float(MAX_LOSS_PER_TRADE)
                if upnl <= -max_loss_usdt:
                    px = get_ws_mark(symbol)
                    if px is None:
                        try:
                            px = float(client.mark_price(symbol=symbol)["markPrice"])
                        except Exception:
                            px = float(pos.get('entry_price', 0.0) or 0.0)
                    close_position(
                        symbol=symbol,
                        mark_price=px,
                        qty=qty,
                        side=side,
                        reason=f"Max loss per trade hit (internal {max_loss_usdt:.2f} USDT)",
                        realized_pnl=upnl
                    )
                    continue
            except Exception as e:
                print(f"[INTERNAL TP/SL] {symbol} monitor error: {e}")
                continue
    except Exception as e:
        print(f"[INTERNAL TP/SL] monitor fatal: {e}")

def main_loop():
    global open_positions, last_trade_time, daily_realized_pnl, daily_trade_count
    global pause_until, new_trades_this_hour, agent_stats, CONFIDENCE_THRESHOLD
    global MIN_AGREE_AGENTS, TP_QUICK_PROFIT, previous_open_symbols, last_trade_or_signal_time

    start_mark_ws()  # start WS (no-op if unavailable)

    last_meta_evolve = time.time()
    last_eod_evolve = time.time()
    last_heartbeat_ts = 0.0

    while not SHUTDOWN.is_set():
        try:
            # -- Daily reset + meta -----------------------------------------------
            today = datetime.now(timezone.utc).date()
            if today != globals().get('last_pnl_reset_day', today):
                globals()['last_pnl_reset_day'] = today
                globals()['daily_realized_pnl'] = 0.0
                globals()['daily_trade_count'] = 0
                globals()['pnl_day_wins'] = 0
                globals()['pnl_day_losses'] = 0
                globals()['pnl_day_win_usd'] = 0.0
                globals()['pnl_day_loss_usd'] = 0.0

            autotune_if_stale()

            now_sec = time.time()
            if now_sec - last_meta_evolve > META_EVOLVE_INTERVAL:
                last_meta_evolve = now_sec
                meta_evolution()

            # Pause gating
            if now_sec < pause_until:
                time.sleep(1)
                continue

            # -- Position monitoring (Hybrid SL, QuickTP) -------------------------
            _monitor_positions_once()

            for symbol in list(open_positions.keys()):
                try:
                    amt = _position_amt_on_binance(symbol)
                    if abs(amt) >= 1e-12:
                        continue

                    # exchange shows flat ? compute realized & notify
                    pos = open_positions.get(symbol, {})
                    entry_price = float(pos.get('entry_price', 0))
                    qty = float(pos.get('qty', 0))
                    side = pos.get('side')
                    entry_iso = pos.get('time')

                    entry_dt = datetime.fromisoformat(entry_iso).replace(tzinfo=timezone.utc) if entry_iso else datetime.now(timezone.utc) - timedelta(minutes=5)
                    start_ms = int(entry_dt.timestamp() * 1000)

                    tdata = _fetch_latest_close_with_retry(symbol, start_ms, retries=5, delay=0.2)
                    realized_pnl = None
                    exit_price = None

                    if isinstance(tdata, list):
                        realized_pnl, exit_price, _ = _pnl_from_fills(tdata, entry_price, side)
                    elif isinstance(tdata, dict) and tdata.get('_fallback'):
                        exit_price = float(tdata.get('markPrice'))
                        if entry_price and qty:
                            realized_pnl = (exit_price - entry_price) * qty if side.upper() == "BUY" else (entry_price - exit_price) * qty

                    if realized_pnl is None:
                        realized_pnl = 0.0
                    if exit_price is None:
                        px = get_ws_mark(symbol)
                        if px is None:
                            px = float(client.mark_price(symbol=symbol)["markPrice"])
                        exit_price = float(px)

                    log_trade_to_csv({
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'symbol': symbol,
                        'side': 'close',
                        'qty': qty,
                        'price': exit_price,
                        'reason': 'Reconciled close (exchange TP/SL/Manual)'
                    })
                    daily_realized_pnl += realized_pnl
                    daily_trade_count += 1
                    record_outcome(realized_pnl)

                    send_telegram_message(
                        telegram_token, telegram_chat_id,
                        f"?? Position Reconciled\n"
                        f"Symbol: {symbol}\nSide: {side}\nQty: {qty}\n"
                        f"Exit: {exit_price:.6f}\nRealized PnL: {realized_pnl:.2f}$\n"
                        f"Daily PnL: {daily_realized_pnl:.2f}$ | Trades: {daily_trade_count}"
                    )

                    # Save fingerprint on reconcile close
                    try:
                        pos_rec = open_positions.get(symbol, {})
                        fp_row = record_fingerprint_on_close(
                            symbol=symbol, side=side, timeframe=trade_timeframe, agent=pos_rec.get('agent'),
                            entry_price=entry_price, exit_price=exit_price, qty=qty, pnl=realized_pnl,
                            ts_open_iso=pos_rec.get('time'), features_open=pos_rec.get('features_open'),
                            leverage=LEVERAGE, sl_price=pos_rec.get('sl'), tp_price=pos_rec.get('tp'),
                            reason='Reconciled close'
                        )
                        try:
                            notify_fingerprint_saved(fp_row, symbol)
                        except Exception:
                            pass
                    except Exception as _e:
                        print("[FP SAVE] reconcile error:", _e)
                    open_positions.pop(symbol, None)
                    save_open_positions(open_positions)

                except Exception as e:
                    print(f"[RECONCILE] {symbol} error: {e}")

            # -- Discovery: symbols + exposure ------------------------------------
            balance = get_futures_balance()

            # Current allocated USDT across open positions (pre-leverage notionals)
            current_alloc = 0.0
            for p in open_positions.values():
                if 'usdt_amt' in p:
                    current_alloc += float(p['usdt_amt'])
                else:
                    q = float(p.get('qty', 0))
                    px = float(p.get('entry_price', 0))
                    current_alloc += (q * px) / max(1, LEVERAGE)

            tickers = safe_fetch_24h_tickers(client, min_interval_sec=45)
            pairs = []
            for t in tickers:
                sym = t.get('symbol')
                if sym and sym.endswith('USDT') and sym not in BANLIST:
                    vol_usd = float(t.get('quoteVolume', 0) or 0.0)
                    if vol_usd >= MIN_24H_VOL:
                        pairs.append((sym, vol_usd))
            pairs.sort(key=lambda x: x[1], reverse=True)
            top_symbols = pairs[:TOP_N_SYMBOLS]

            # Heartbeat/visibility every 1s
            if time.time() - last_heartbeat_ts > 1:
                last_heartbeat_ts = time.time()
                try:
                    top_preview = ", ".join([f"{sym}:{vol/1e6:.1f}M" for sym, vol in top_symbols[:5]])
                    a_lines = []
                    for a in agent_names:
                        sdat = agent_stats.get(a, {})
                        wr = (sdat.get('wins',0) / max(1, sdat.get('wins',0)+sdat.get('losses',0)))
                        a_lines.append(f"{a}[pnl={sdat.get('pnl',0.0):.2f},tr={sdat.get('trades',0)},wr={wr:.2f},w={_agent_weight(a):.2f}]")
                    print(f"[LOOP] {datetime.now(timezone.utc).isoformat()} | Top: {top_preview} | DailyPnL={daily_realized_pnl:.2f} | Open={len(open_positions)}")
                    print("[AGENTS]", " | ".join(a_lines))
                except Exception as _e:
                    print("[HEARTBEAT ERROR]", _e)

            # Respect hourly cap *before* scanning entries
            new_trades_this_hour[:] = [t for t in new_trades_this_hour if time.time() - t < 3600]
            if len(new_trades_this_hour) >= MAX_NEW_TRADES_PER_HOUR:
                time.sleep(2)
                continue

            # --- Daily stop (new entries only) ---
            if (daily_realized_pnl >= DAILY_PROFIT_TARGET) or (daily_realized_pnl <= DAILY_MAX_LOSS):
                if not globals().get('notified_daily_stop', False):
                    globals()['notified_daily_stop'] = True
                    try:
                        reason = 'profit target' if daily_realized_pnl >= DAILY_PROFIT_TARGET else 'loss limit'
                        send_telegram_message(
                            telegram_token, telegram_chat_id,
                            f"Daily {reason} reached. PnL={daily_realized_pnl:.2f} | "
                            f"Target={DAILY_PROFIT_TARGET:.2f} | MaxLoss={DAILY_MAX_LOSS:.2f}. "
                            "Pausing new entries for the rest of the day."
                        )
                        print(f"[DAILY STOP] {reason} reached - blocking new entries for the day.")
                    except Exception:
                        pass
                time.sleep(1)
                continue


            # -- Agent signals (5m master) & entries ------------------------------
            for symbol, vol_usd in top_symbols:
                # portfolio & per-symbol caps
                if len(open_positions) >= MAX_PORTFOLIO_SIZE and symbol not in open_positions:
                    continue
                if abs(_position_amt_on_binance(symbol)) > 0:
                    # optional: reconcile instead of skipping
                    continue
                if symbol in open_positions:
                    continue

                try:
                    df5 = fetch_ohlcv(symbol, interval=trade_timeframe, limit=120)
                except Exception as e:
                    print(f"[DATA] {symbol} 5m fetch failed: {e}")
                    continue

                # HTF trend context
                trend_master, t15, t1h = get_trend_htf(symbol)

                # Risk inputs
                atr_now = calculate_atr(df5)
                price = float(df5['close'].iloc[-1])
                vol_class = _vol_class(symbol, vol_usd)

                # Shared ctx for agents
                ctx_base = {
                    'timeframe': trade_timeframe,
                    'min_expected_move': MIN_EXPECTED_MOVE,
                    'conf_threshold': CONFIDENCE_THRESHOLD,
                    'trend_hint': trend_master,
                    'trend_15m': t15, 'trend_1h': t1h,
                    'vol_class': vol_class,
                    'risk': {'atr': float(atr_now), 'price': float(price)},
                    'rules': {'sl_mode': HYBRID_SL_MODE, 'tp_quick_profit': TP_QUICK_PROFIT},
                }

                # Collect signals
                signals_by_agent = {}
                for agent_name, agent_fn in agents:
                    thr = agent_stats.get(agent_name, {}).get('threshold', CONFIDENCE_THRESHOLD)
                    w = _agent_weight(agent_name)
                    if w <= 0:
                        continue  # muted
                    ctx = dict(ctx_base)
                    ctx['conf_threshold'] = thr
                    ctx['weight'] = w
                    try:
                        sig = _call_agent(agent_fn, df5, symbol, ctx)
                    except Exception as e:
                        print(f"[AGENT] {agent_name} error {symbol}: {e}")
                        sig = None

                    if sig:
                        # mark any usable signal so autotuner doesn't think we're idle
                        if sig.get('side') in ('BUY', 'SELL'):
                            last_trade_or_signal_time = time.time()
                        signals_by_agent[agent_name] = {trade_timeframe: sig}

                vote = smart_vote(symbol, signals_by_agent, MIN_AGREE_AGENTS, MIN_AGREE_TIMEFRAMES)
                if not vote:
                    continue

                side, avg_conf, used = vote

                # --- Fingerprint veto / override (new engine) ---
                try:
                    # Build rich live fingerprints for both sides
                    ctx_fp = {
                        'timeframe': trade_timeframe,
                        'trend_hint': trend_master, 'trend_15m': t15, 'trend_1h': t1h,
                        'risk': {'atr': float(atr_now), 'price': float(price)}
                    }
                    F_live_BUY  = make_live_fingerprint(df5, symbol, 'BUY',  ctx_fp)
                    F_live_SELL = make_live_fingerprint(df5, symbol, 'SELL', ctx_fp)

                    # Veto
                    _loss_buy,  _ls_buy  = find_best_loss_match(F_live_BUY,  'BUY')
                    _loss_sell, _ls_sell = find_best_loss_match(F_live_SELL, 'SELL')
                    veto_buy  = (_loss_buy  is not None and _ls_buy  >= LOSS_VETO_SIM)
                    veto_sell = (_loss_sell is not None and _ls_sell >= LOSS_VETO_SIM)
                    if (side == 'BUY' and veto_buy) or (side == 'SELL' and veto_sell):
                        send_telegram_message(telegram_token, telegram_chat_id, f"?? FP Veto {symbol} {side} s={_ls_buy if side=='BUY' else _ls_sell:.2f}")
                        continue

                    # Override
                    _win_buy,  _ws_buy  = find_best_win_match(F_live_BUY,  'BUY')
                    _win_sell, _ws_sell = find_best_win_match(F_live_SELL, 'SELL')
                    override_side = None; override_order = None; override_sim = 0.0
                    if _win_buy and _ws_buy >= WIN_TRIGGER_SIM and not veto_buy:
                        override_side = 'BUY'; override_sim = _ws_buy
                        override_order = order_from_match(_win_buy, F_live_BUY)
                    if _win_sell and _ws_sell >= WIN_TRIGGER_SIM and not veto_sell and _ws_sell > override_sim:
                        override_side = 'SELL'; override_sim = _ws_sell
                        override_order = order_from_match(_win_sell, F_live_SELL)

                    if override_order:
                        send_telegram_message(telegram_token, telegram_chat_id, f"? FP Override {symbol} {override_side} s={override_sim:.2f}")
                        placed = place_order_from_fingerprint(symbol, override_order, ctx_fp)
                        if placed:
                            continue  # skip normal agent pipeline
                    # If no override, proceed with normal pipeline (veto implied by continue above)
                except Exception as _e:
                    print("[FP] veto/override error:", _e)

                if TREND_FILTER_ON and (
                    (side == "BUY"  and trend_master != "UP") or
                    (side == "SELL" and trend_master != "DOWN")
                ):
                    continue

                # SL/TP baseline from ATR (hybrid refines after entry)
                sl = price - (SL_ATR_MULT * atr_now) if side == 'BUY' else price + (SL_ATR_MULT * atr_now)
                tp = price + (TP_SL_RR * abs(price - sl)) if side == 'BUY' else price - (TP_SL_RR * abs(price - sl))
                exp_move = abs(tp - price) / max(1e-9, price)
                if exp_move < MIN_EXPECTED_MOVE:
                    continue

                # Sizing & exchange filters
                risk_per_unit = abs(price - sl)
                if risk_per_unit <= 0:
                    continue
                max_qty_by_loss = MAX_LOSS_PER_TRADE / risk_per_unit
                alloc = min(balance * MAX_SYMBOL_ALLOC, MIN_TRADE_USDT, max_qty_by_loss * price)
                if alloc < MIN_TRADE_USDT:
                    continue

                # portfolio exposure guard
                if current_alloc + alloc > balance * MAX_TOTAL_ALLOC:
                    continue

                qty_precision, price_precision, min_qty, min_notional = get_symbol_precision_and_min(symbol)
                qty = round(alloc * LEVERAGE / price, qty_precision)
                if qty < min_qty or qty * price < min_notional:
                    continue

                # Ensure leverage set (best effort)
                try:
                    brackets = client.leverage_brackets()
                    sb = next((b for b in brackets if b.get('symbol') == symbol), None)
                    if sb:
                        max_lev = max(x.get('initialLeverage', LEVERAGE) for x in sb.get('brackets', []))
                        client.change_leverage(symbol=symbol, leverage=min(LEVERAGE, max_lev))
                except Exception as e:
                    print(f"[ORDER] leverage set skipped {symbol}: {e}")

                # Place order
                # Re-entry cooldown guard (5 minutes)
                if not _can_enter_now(symbol):
                    # skip signal; still cooling down for this symbol
                    continue
                try:
                    res = futures_execute_trade(symbol, side, qty)
                except Exception as e:
                    print(f"[ORDER] {symbol} trade error: {e}")
                    continue
                if not res:
                    continue

                # Persist position with authoritative filled entry if available
                entry_price_authoritative = float(price)
                try:
                    # tiny wait then fetch recent user trades to compute avg fill that INCREASED the position
                    start_ms_entry = int((datetime.now(timezone.utc) - timedelta(seconds=5)).timestamp() * 1000)
                    tr_list = compat_user_trades(client, symbol, start_ms_entry)
                    incr_qty = 0.0
                    incr_notional = 0.0
                    def _to_bool(z):
                        if isinstance(z, bool): return z
                        return str(z).lower() in ("1","true","t","yes","y")
                    for tr in (tr_list or []):
                        try:
                            if tr.get("symbol") != symbol:
                                continue
                            px = float(tr.get("price") or tr.get("p") or 0)
                            q  = float(tr.get("qty")   or tr.get("q") or 0)
                            if px <= 0 or q <= 0:
                                continue
                            is_buyer = _to_bool(tr.get("buyer", tr.get("isBuyer")))
                            increases = ((side.upper() == "BUY"  and is_buyer) or
                                         (side.upper() == "SELL" and not is_buyer))
                            if not increases:
                                continue
                            incr_qty += q
                            incr_notional += px * q
                        except Exception:
                            continue
                    if incr_qty > 0:
                        entry_price_authoritative = incr_notional / incr_qty
                except Exception:
                    pass
                # --- compute absolute Quick TP / Hard SL thresholds ---
                quick_usd = float(TP_QUICK_PROFIT)
                if side.upper() == "BUY":
                    quick_tp_px = float(entry_price_authoritative) + (quick_usd / max(1e-9, float(qty)))
                    hard_sl_px  = float(entry_price_authoritative) - (float(MAX_LOSS_PER_TRADE) / max(1e-9, float(qty)))
                else:
                    quick_tp_px = float(entry_price_authoritative) - (quick_usd / max(1e-9, float(qty)))
                    hard_sl_px  = float(entry_price_authoritative) + (float(MAX_LOSS_PER_TRADE) / max(1e-9, float(qty)))

                # Attach features for fingerprint logging on close
                order_hint_fp = {
                    "entry_type": "limit",
                    "entry": float(entry_price_authoritative),
                    "sl": float(sl),
                    "tp": float(tp),
                    "sl_mult_atr": abs(float(entry_price_authoritative) - float(sl)) / max(1e-9, float(atr_entry or 0.0)),
                    "tp_mult_atr": abs(float(tp) - float(entry_price_authoritative)) / max(1e-9, float(atr_entry or 0.0)),
                    "stop_buf_atr": 0.0
                }
                F_live_save = make_live_fingerprint(df_entry, symbol, side, {**ctx_base, "order_hint": order_hint_fp})

                open_positions[symbol] = {
                'entry_price': float(entry_price_authoritative),
                'qty': float(qty),
                'side': side,
                'tp': float(tp),
                'sl': float(sl),
                'time': datetime.now(timezone.utc).isoformat(),
                'agent': ','.join([a for a, _, _ in used]),
                'tf': [trade_timeframe],
                'usdt_amt': float(alloc),
                'trail_armed': False,
                'best_px': float(price),
                'quick_tp_px': float(quick_tp_px),
                'hard_sl_px': float(hard_sl_px),
                                'features_open': F_live_save,
                }
                save_open_positions(open_positions)

                last_trade_time = datetime.now(timezone.utc)

                # Track exposure & hourly rate
                current_alloc += alloc
                new_trades_this_hour = [t for t in new_trades_this_hour if time.time() - t < 3600]
                new_trades_this_hour.append(time.time())
                if len(new_trades_this_hour) >= MAX_NEW_TRADES_PER_HOUR:
                    break

                # Telegram summary
                expected_usd = abs(tp - price) * qty
                agent_lines = ", ".join([f"{a}({c:.2f})" for a, c, _ in used])
                rationale = (
                    f"?? NEW TRADE\n{symbol} {side} qty={qty}\n"
                    f"Entry={price:.6f}  SL={sl:.6f}  TP={tp:.6f}\n"
                    f"ExpMove={exp_move:.4%}  Exp$~{expected_usd:.2f}\n"
                    f"Leverage={LEVERAGE}  Alloc~${alloc:.2f}\n"
                    f"Agents: {agent_lines}\n"
                    f"Trend: 5m/HTF={trend_master} (15m={t15}, 1h={t1h})"
                )
                send_telegram_message(telegram_token, telegram_chat_id, rationale)

            time.sleep(2)

        except Exception as e:
            send_telegram_message(
                telegram_token, telegram_chat_id,
                f"OMNIBRAIN ERROR: {e}\n{traceback.format_exc()}"
            )
            time.sleep(6)


def ultra_fast_guard():
    """
    50 ms guard using only websocket mark price.
    Triggers Quick TP / Hard SL instantly against absolute thresholds.
    """
    SLEEP = 0.05
    while not SHUTDOWN.is_set():
        try:
            for symbol in tuple(open_positions.keys()):
                pos = open_positions.get(symbol) or {}
                px = get_ws_mark(symbol)
                if px is None:
                    continue
                side = (pos.get('side') or 'BUY').upper()
                qty  = float(pos.get('qty') or 0)
                entry = float(pos.get('entry_price') or 0)
                if qty <= 0 or entry <= 0:
                    continue
                qtp = pos.get('quick_tp_px'); hsl = pos.get('hard_sl_px')
                if qtp is None or hsl is None:
                    continue
                hit_qtp = (px >= qtp) if side == 'BUY' else (px <= qtp)
                hit_hsl = (px <= hsl) if side == 'BUY' else (px >= hsl)
                if hit_qtp or hit_hsl:
                    try:
                        client.cancel_all_open_orders(symbol=symbol)
                    except Exception:
                        pass
                    pnl = (px - entry) * qty if side == 'BUY' else (entry - px) * qty
                    close_position(symbol, px, qty, side, "QuickTP" if hit_qtp else "HardSL", realized_pnl=pnl)
        except Exception:
            pass
        time.sleep(SLEEP)

# start ultra-fast guard
try:
    threading.Thread(target=ultra_fast_guard, daemon=True).start()
except Exception:
    pass


# ======================
#  QUICK TP MONITOR
# ======================
def quick_profit_monitor():
    """Disabled: exits are enforced solely by ultra_fast_guard().""" 
    return
# ======================
#  ENTRY POINT
# ======================
if __name__ == "__main__":
    try:
        threading.Thread(target=quick_profit_monitor, daemon=True).start()
        main_loop()
    except KeyboardInterrupt:
        pass
    finally:
        SHUTDOWN.set()
        try:
            restart_websocket()
        except Exception:
            pass
        print("[EXIT] Bye.")


# ======================
#  FP OVERRIDE EXECUTOR
# ======================
def place_order_from_fingerprint(symbol: str, ordz: dict, ctx_symbol: dict):
    """
    ordz = {"entry_type": "limit|stop", "entry": float, "sl": float, "tp": float, "side": "BUY|SELL"}
    This executes a market entry sized by SL distance (risk-based), then sets quick/hard thresholds.
    """
    try:
        side = (ordz.get("side") or "BUY").upper()
        entry = float(ordz.get("entry", 0.0))
        sl = float(ordz.get("sl", 0.0))
        tp = float(ordz.get("tp", 0.0))

        # Sizing by SL distance
        price = entry or float(get_ws_mark(symbol) or client.mark_price(symbol=symbol)["markPrice"])
        risk_per_unit = abs(price - sl)
        if risk_per_unit <= 0:
            return False

        balance = get_futures_balance()
        max_qty_by_loss = float(MAX_LOSS_PER_TRADE) / max(1e-9, risk_per_unit)
        alloc = min(balance * MAX_SYMBOL_ALLOC, max_qty_by_loss * price)
        if alloc < MIN_TRADE_USDT:
            return False

        qty_precision, price_precision, min_qty, min_notional = get_symbol_precision_and_min(symbol)
        qty = round(alloc * LEVERAGE / price, qty_precision)
        if qty < min_qty or qty * price < min_notional:
            return False

        # Execute market (simple & reliable)
        res = futures_execute_trade(symbol, side, qty)
        if not res:
            return False

        # Compute quick/hard thresholds using fixed USDT amounts (no ATR)
        quick_usd = float(TP_QUICK_PROFIT)
        if side == "BUY":
            quick_tp_px = float(entry_price_authoritative) + (quick_usd / max(1e-9, float(qty)))
            hard_sl_px  = float(entry_price_authoritative) - (float(MAX_LOSS_PER_TRADE) / max(1e-9, float(qty)))
        else:
            quick_tp_px = float(entry_price_authoritative) - (quick_usd / max(1e-9, float(qty)))
            hard_sl_px  = float(entry_price_authoritative) + (float(MAX_LOSS_PER_TRADE) / max(1e-9, float(qty)))

        # Persist open position with fingerprint features for logging on close
        from datetime import datetime, timezone
        F_live_for_save = make_live_fingerprint(
            df_entry, symbol, side, {**ctx_symbol, "order_hint": {
                "entry_type": ordz.get("entry_type","limit"),
                "entry": entry_price_authoritative, "sl": sl, "tp": tp,
                "sl_mult_atr": abs(entry_price_authoritative - sl) / max(1e-9, float(atr_entry or 0.0)),
                "tp_mult_atr": abs(tp - entry_price_authoritative) / max(1e-9, float(atr_entry or 0.0)),
                "stop_buf_atr": 0.10 if ordz.get("entry_type")=="stop" else 0.0
            }}
        )

        open_positions[symbol] = {
            'entry_price': float(entry_price_authoritative),
            'qty': float(qty),
            'side': side,
            'tp': float(tp),
            'sl': float(sl),
            'time': datetime.now(timezone.utc).isoformat(),
            'agent': 'FP_OVERRIDE',
            'tf': [trade_timeframe],
            'usdt_amt': float(alloc),
            'trail_armed': False,
            'best_px': float(entry_price_authoritative),
            'quick_tp_px': float(quick_tp_px),
            'hard_sl_px': float(hard_sl_px),
            'features_open': F_live_for_save
        }
        save_open_positions(open_positions)
        return True
    except Exception as e:
        try:
            send_telegram_message(telegram_token, telegram_chat_id, f"[FP override error] {symbol}: {e}")
        except Exception:
            pass
        return False