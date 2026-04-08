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
from datetime import timezone as _timezone_mod

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
        import requests as _rq
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        _rq.post(url, json=payload, timeout=5)
    except Exception:
        pass


# === PERPLEXITY / NEWS SENTIMENT HOOK (optional, Bot 2) ===
PERPLEXITY_SENTIMENT_URL = os.getenv("PERPLEXITY_SENTIMENT_URL", "").strip()
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "").strip()

def get_news_sentiment(symbol: str) -> float:
    """
    Returns sentiment score in [-1.0, 1.0]:
      +1 = very bullish news
       0 = neutral / unknown
      -1 = very bearish news

    Safe stub:
      - If PERPLEXITY_SENTIMENT_URL is not set, returns 0.0 (no effect).
      - You can point this to your own Perplexity-backed microservice later.
    """
    if not PERPLEXITY_SENTIMENT_URL:
        return 0.0

    try:
        asset = symbol.replace("USDT", "")
        payload = {
            "symbol": symbol,
            "asset": asset,
            "market": "crypto",
        }
        headers = {}
        if PERPLEXITY_API_KEY:
            headers["Authorization"] = f"Bearer {PERPLEXITY_API_KEY}"

        resp = requests.post(
            PERPLEXITY_SENTIMENT_URL,
            json=payload,
            headers=headers,
            timeout=5
        )
        data = resp.json() if resp is not None else {}
        score = float(data.get("sentiment_score", 0.0))
        # Clamp into [-1, 1]
        if score > 1.0:
            score = 1.0
        if score < -1.0:
            score = -1.0
        return score
    except Exception as e:
        try:
            print(f"[NEWS] sentiment fetch error for {symbol}: {e}")
        except Exception:
            pass
        return 0.0


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
    down = -1 * delta.clip(upper=0)
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
    ma_fast_prev = float(ema9.iloc[-2]) if len(ema9) > 1 else ma_fast
    ma_slow_prev = float(ema21.iloc[-2]) if len(ema21) > 1 else ma_slow
    ma_fast_slope = (ma_fast - ma_fast_prev) / max(1e-9, close.iloc[-1]) * 100.0
    ma_slow_slope = (ma_slow - ma_slow_prev) / max(1e-9, close.iloc[-1]) * 100.0
    ma_ratio = ma_fast / max(1e-9, ma_slow)
    # Volatility
    tr = (high.combine(low, lambda h, l: h - l)).rolling(14).mean()
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
    if body_pct < 0.1:
        flags |= 4
    # hammer
    if body_pct < 0.3 and dn_wick > body * 2:
        flags |= 2
    # engulf (bull/bear)
    if len(close) > 2 and ( (df['open'].iloc[-1] < close.iloc[-2] and close.iloc[-1] > df['open'].iloc[-2]) or
                            (df['open'].iloc[-1] > close.iloc[-2] and close.iloc[-1] < df['open'].iloc[-2]) ):
        flags |= 1
    # inside bar
    if len(close) > 2 and high.iloc[-1] < high.iloc[-2] and low.iloc[-1] > low.iloc[-2]:
        flags |= 8

    return {
        "ret_1m": ret_1m, "ret_5m": ret_5m,
        "ma_fast_slope": ma_fast_slope, "ma_slow_slope": ma_slow_slope,
        "ma_fast_over_slow": ma_ratio,
        "atr_pct": atr_pct, "vol_z": vol_z,
        "wick_ratio": wick_ratio, "body_pct": body_pct,
        "rsi": rsi, "stoch_k": stoch_k,
        "trend_15m": 1 if trend15 == 'UP' else (-1 if trend15 == 'DOWN' else 0),
        "trend_1h":  1 if trend1h == 'UP' else (-1 if trend1h == 'DOWN' else 0),
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

# Strategy profile tag for this bot instance
STRATEGY_PROFILE = "TREND_SURGE_RIDER"

TOP_N_SYMBOLS = 20
MIN_24H_VOL = 150_000_000
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

# --- TREND CONTINUATION RISK SETTINGS (5m is master) ---
LEVERAGE = 5
MIN_TRADE_USDT = 3.0
MAX_TRADE_USDT = 10.0
DEFAULT_TRADE_TIMEFRAME = "5m"         # 5m MASTER
trade_timeframe = DEFAULT_TRADE_TIMEFRAME
TRADE_TIMEFRAMES = ["5m"]              # entries are 5m-only now
CONFIDENCE_THRESHOLD = 0.75            # global floor (agents still have per-agent thresholds & weights)
MIN_AGREE_AGENTS = 1                   # require at least 2 agents to agree for entries (true confluence)
MIN_AGREE_TIMEFRAMES = 1
TIME_IN_TRADE_LIMIT_MIN = 1900         # allow trades to live a long time; exits via TP/QuickTP/SL
DAILY_PROFIT_TARGET = 5.0
DAILY_MAX_LOSS = -6
TP_SL_RR = 3.6
SL_ATR_MULT = 2.0                       # base; hybrid engine will adapt dynamically after entry
MIN_EXPECTED_MOVE = 0.010
COOLDOWN_AFTER_LOSS_SEC = 1800
MAX_NEW_TRADES_PER_HOUR = 5
PAUSE_AFTER_PROFIT_SEC = 600
META_EVOLVE_INTERVAL = 3600
META_EVOLVE_EOD = 60 * 60 * 23
AGENT_MUTE_AFTER_LOSSES = 1
AGENT_MUTE_TIME = 360
MAX_PORTFOLIO_SIZE = 4
MAX_SYMBOL_ALLOC = 1.0
MAX_TOTAL_ALLOC = 1.0
MAX_LOSS_PER_TRADE = 0.30
# Trend filters moved to 15m/1h (agents also self-check).
# For TREND_SURGE_RIDER this bot *always* aligns with HTF trend.
TREND_FILTER_ON = True

# === BOT 2: EXPECTED-MOVE / NEWS PROFILE ===
# Time horizon (5m bars) for realized volatility   12x5m   1h swing expectation
EM_RV_WINDOW = 12          # bars
EM_ATR_COEFF = 1.10        # how much ATR roughly matches 1h expected move

# Dynamic R:R range for Bot 2
EM_MIN_RR = 2.0            # minimum R:R on boring/low-confidence setups
EM_MAX_RR = 5.0            # allow bigger RR on very strong trend + high confidence

# News / sentiment influence, Perplexity-backed (if wired)
# Positive when news aligns with trade direction, negative otherwise
EM_NEWS_BOOST = 0.40       # 0.0 0.5 is sane

# Optional clamp on expected move % (safety)
EM_MAX_EXPECTED_MOVE = 0.20   # allow up to ~20% moves for TP on strong trends

# === HYBRID SL ENGINE knobs (tunable via TG later) ===
HYBRID_SL_MODE = "hybrid"      # "hybrid" | "hard" | "atr" | "trail"
HYBRID_ARM_RR = 2.5            # arm trailing later (needs bigger RR) for longer runs
HYBRID_ARM_ATR = 2.5           # or MFE >= N * ATR
HYBRID_TRAIL_K = 3.0           # wider trail in ATR multiples to avoid scalping winners
BREAKEVEN_AFTER_MIN = 60 * 60  # give trades ~1h before breakeven tightening kicks in
BREAKEVEN_EPS_FRAC = 0.35      # breakeven cushion: 0.35 ATR below/above entry

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
    "apex_vwap_pullback": 0.90,
    "apex_microburst":    0.95,
    "apex_sweep_reversal":0.90,
    "apex_supertrend_adaptive": 0.90,
    "apex_momentum_pump": 0.98,
}

# Extra bias for TREND_SURGE_RIDER: trend/momentum agents get more impact.
AGENT_PROFILE_WEIGHTS = {
    "apex_vwap_pullback":       0.9,  # pullbacks are OK but not king
    "apex_sweep_reversal":      0.7,  # reversals are de-prioritized in trend bot
    "apex_microburst":          1.0,  # neutral
    "apex_supertrend_adaptive": 1.2,  # trend-following -> boosted
    "apex_momentum_pump":       1.3,  # pure momentum -> strongest
}

# === QUICK TP SETTINGS - ONLY TP LOGIC IN THE ENTIRE BOT ===
TP_QUICK_PROFIT = 0.50       # Minimum profit in USDT before allowing any QuickTP exit
TP_QUICK_ATR_MULT = 0.025    # Multiplier for ATR-based dynamic QuickTP threshold
Q_TREND_SURGE_FACTOR = 0.85  # For TREND_SURGE_RIDER: QuickTP based on expected move

# Daily breakdown
pnl_day_wins = 0
pnl_day_losses = 0
pnl_day_win_usd = 0.0
pnl_day_loss_usd = 0.0

# Notifier so we only alert once when daily limit/target is hit
notified_daily_stop = False

# Dynamic risk sizing (anti-martingale, bounded)
RISK_BASE_FRAC = 0.04   # starting risk per trade as fraction of equity
RISK_MIN_FRAC  = 0.02   # lower bound (very defensive)
RISK_MAX_FRAC  = 0.10   # upper bound (never risk more than 10% of equity)
RISK_WIN_MULT  = 1.25   # grow risk after wins (anti-martingale)
RISK_LOSS_MULT = 0.50   # cut risk fast after losses

current_risk_frac = RISK_BASE_FRAC
win_streak = 0
loss_streak = 0
recent_outcomes = []


def get_dynamic_risk_usd(equity: float) -> float:
    """Return desired dollar risk per trade based on equity & recent outcomes.

    - Scales with equity (fraction-based).
    - Bounded between a small floor and MAX_LOSS_PER_TRADE.
    """
    global current_risk_frac
    try:
        equity = float(equity)
    except Exception:
        return 0.0
    if equity <= 0:
        return 0.0

    frac = current_risk_frac if current_risk_frac else RISK_BASE_FRAC
    if frac < RISK_MIN_FRAC:
        frac = RISK_MIN_FRAC
    if frac > RISK_MAX_FRAC:
        frac = RISK_MAX_FRAC

    risk_usd = equity * frac
    # tiny floor so risk doesn't collapse to near-zero on small accounts
    risk_usd = max(0.5, risk_usd)
    # never exceed the global safety cap
    try:
        cap = float(MAX_LOSS_PER_TRADE)
    except Exception:
        cap = risk_usd
    risk_usd = min(risk_usd, cap)
    return risk_usd


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
        if isinstance(x, bool):
            return x
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

    # TREND_SURGE_RIDER bias: emphasize momentum/trend agents, soften reversals
    boost = AGENT_PROFILE_WEIGHTS.get(name, 1.0)
    weight *= boost

    # keep in [0,1]
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
BANLIST = set([])  # default exclusions

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
                    # Get comprehensive balance info
                    try:
                        account_data = client.balance()
                        total_equity = 0.0
                        available_balance = 0.0
                        for asset in account_data:
                            if asset['asset'] == 'USDT':
                                total_equity = float(asset.get('balance', 0) or 0)
                                available_balance = float(asset.get('availableBalance', 0) or 0)
                                break
                        if total_equity == 0:
                            total_equity = get_futures_balance()
                            available_balance = total_equity
                    except Exception as e:
                        print(f"[STATUS] Balance fetch error: {e}")
                        total_equity = get_futures_balance()
                        available_balance = total_equity
                    
                    # Calculate margin in use
                    margin_in_use = total_equity - available_balance
                    
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
                        f"[STATUS]\n"
                        f"?? Total Equity: {total_equity:.2f} USDT\n"
                        f"?? Available: {available_balance:.2f} USDT\n"
                        f"?? Margin in Use: {margin_in_use:.2f} USDT\n"
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


def compute_expected_move_sl_tp(
    symbol: str,
    side: str,
    price: float,
    atr_now: float,
    df5: pd.DataFrame,
    avg_conf: float,
    trend_master: str,
    vol_class,
    news_sentiment: float,
    profile_bias: float = 1.0,
):
    """
    Bot 2: expected-move based SL/TP.

    Returns:
        (sl_soft, tp, exp_move_pct, rr_used)
        sl_soft / tp: floats or (None, None, exp_move_pct, rr) if trade should be skipped.

    NOTE:
    - This SL is now treated as the *soft/hybrid* SL for winners.
    - The *hard* catastrophic SL is derived separately from MAX_LOSS_PER_TRADE.
    """
    try:
        price = float(price)
        atr_now = float(atr_now)
    except Exception:
        return None, None, 0.0, TP_SL_RR

    if price <= 0 or atr_now <= 0:
        return None, None, 0.0, TP_SL_RR

    # --- base expected move from ATR and realized vol ---
    atr_pct = atr_now / price

    rv = 0.0
    try:
        closes = df5["close"].astype(float)
        rets = closes.pct_change().dropna()
        if len(rets) >= EM_RV_WINDOW:
            tail = rets.tail(EM_RV_WINDOW)
            rv = float(tail.std() * (EM_RV_WINDOW ** 0.5))
        else:
            rv = float(rets.std())
    except Exception:
        rv = 0.0

    base_exp_move = max(float(MIN_EXPECTED_MOVE), atr_pct * EM_ATR_COEFF, abs(rv))
    base_exp_move *= float(profile_bias or 1.0)

    # --- trend factor ---
    trend_factor = 1.0
    tm = (trend_master or "").upper()
    if side == "BUY" and tm == "UP":
        trend_factor = 1.25
    elif side == "SELL" and tm == "DOWN":
        trend_factor = 1.25
    elif tm in ("UP", "DOWN"):
        # going against a clear HTF trend   penalize expected move
        trend_factor = 0.85

    # --- vol class factor ---
    vc = str(vol_class or "").upper()
    if "HIGH" in vc:
        vol_factor = 1.05   # allow a bit bigger targets on wild coins
    elif "LOW" in vc:
        vol_factor = 0.85   # don't expect too much from slow coins
    else:
        vol_factor = 1.0

    # --- news factor (Perplexity) ---
    try:
        ns = float(news_sentiment or 0.0)
    except Exception:
        ns = 0.0
    if ns > 1.0:
        ns = 1.0
    if ns < -1.0:
        ns = -1.0

    # align direction (positive if news supports our side)
    dir_sign = 1.0 if side == "BUY" else -1.0
    aligned = dir_sign * ns
    news_factor = 1.0 + EM_NEWS_BOOST * aligned
    if news_factor < 0.5:
        news_factor = 0.5
    if news_factor > 1.5:
        news_factor = 1.5

    # --- combine expected move ---
    exp_move_pct = base_exp_move * trend_factor * vol_factor * news_factor
    if exp_move_pct > EM_MAX_EXPECTED_MOVE:
        exp_move_pct = EM_MAX_EXPECTED_MOVE

    # --- dynamic RR based on confidence, centered around TP_SL_RR ---
    try:
        conf = float(avg_conf or 0.0)
    except Exception:
        conf = 0.0

    span = max(0.01, 0.99 - CONFIDENCE_THRESHOLD)
    conf_norm = (conf - CONFIDENCE_THRESHOLD) / span
    if conf_norm < 0.0:
        conf_norm = 0.0
    if conf_norm > 1.0:
        conf_norm = 1.0

    try:
        base_rr = float(globals().get("TP_SL_RR", EM_MIN_RR) or EM_MIN_RR)
    except Exception:
        base_rr = EM_MIN_RR

    rr_min = min(EM_MIN_RR, base_rr)
    rr_max = max(EM_MAX_RR, base_rr)
    rr = rr_min + conf_norm * (rr_max - rr_min)
    if rr < 0.5:
        rr = 0.5

    # If expected move still too small, skip this trade
    if exp_move_pct < MIN_EXPECTED_MOVE:
        return None, None, exp_move_pct, rr

    # --- derive *soft* SL distance from RR and expected move ---
    risk_pct_soft = exp_move_pct / rr
    if risk_pct_soft <= 0:
        return None, None, exp_move_pct, rr

    sl_dist_soft = risk_pct_soft * price

    if side == "BUY":
        sl_soft = price - sl_dist_soft
        tp = price + exp_move_pct * price
    else:
        sl_soft = price + sl_dist_soft
        tp = price - exp_move_pct * price

    return float(sl_soft), float(tp), float(exp_move_pct), float(rr)


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
            from datetime import datetime as _dt_mod, timezone as _tz_mod, timedelta as _td_mod
            entry_dt = _dt_mod.fromisoformat(entry_iso).replace(tzinfo=_tz_mod.utc) if entry_iso else _dt_mod.now(_tz_mod.utc) - _td_mod(minutes=5)
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
    Place only SL orders (TP is handled by software QuickTP monitor).
    Uses closePosition=True STOP_MARKET for clean execution.
    """
    try:
        qty_precision, price_precision, min_qty, min_notional = get_symbol_precision_and_min(symbol)
        sl_rounded = round(sl, price_precision)
        mark_price = get_ws_mark(symbol)
        if mark_price is None:
            mark_price = float(client.mark_price(symbol=symbol)["markPrice"])
        order_side = "SELL" if side == "BUY" else "BUY"

        def _can_place_sl(stop):
            if side == "BUY":
                return stop < mark_price - 1e-8
            else:
                return stop > mark_price + 1e-8

        can_place = _can_place_sl(sl_rounded)

        # Attempt: closePosition=True (no reduceOnly param needed)
        try:
            if can_place:
                client.new_order(
                    symbol=symbol, side=order_side, type="STOP_MARKET",
                    stopPrice=sl_rounded, closePosition=True, workingType="MARK_PRICE"
                )
                send_telegram_message(telegram_token, telegram_chat_id, f"??? {symbol} SL set: {sl_rounded}")
            else:
                send_telegram_message(telegram_token, telegram_chat_id, f"?? {symbol} SL skipped (too close to mark)")
            return
        except ClientError as ce:
            # Fallback if -1106 (some client versions)
            if getattr(ce, 'error_code', None) != -1106 and "-1106" not in str(ce):
                raise

        # Fallback: explicit quantity with reduceOnly=True
        def _live_qty(sym: str) -> float:
            try:
                rows = client.get_position_risk(symbol=sym)
                if isinstance(rows, list) and rows:
                    amt = float(rows[0].get("positionAmt", 0) or 0.0)
                else:
                    amt = float(rows.get("positionAmt", 0) or 0.0) if rows else 0.0
                return abs(amt)
            except Exception:
                return 0.0

        qty_on_exch = round(_live_qty(symbol), qty_precision)
        if qty_on_exch <= 0:
            send_telegram_message(telegram_token, telegram_chat_id, f"?? {symbol} SL fallback skipped (no live qty).")
            return

        if can_place:
            client.new_order(
                symbol=symbol, side=order_side, type="STOP_MARKET", stopPrice=sl_rounded,
                quantity=qty_on_exch, reduceOnly=True, workingType="MARK_PRICE"
            )
            send_telegram_message(telegram_token, telegram_chat_id, f"??? {symbol} SL set (fallback): {sl_rounded}")
        else:
            send_telegram_message(telegram_token, telegram_chat_id, f"?? {symbol} SL skipped (too close to mark)")
    except Exception as e:
        send_telegram_message(telegram_token, telegram_chat_id, f"Error placing SL for {symbol}: {e}")


# ======================
#  AUTOTUNE
# ======================
last_trade_or_signal_time = time.time()
recent_outcomes = []  # +1 or -1


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
    _base_move = float(globals().get("MIN_EXPECTED_MOVE", _base_move_default) if False else _base_move_default)  # keep original behaviour safe

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


# ======================
#  POSITION MONITOR (Soft SL + per-trade hard SL + trailing)
# ======================
def _monitor_positions_once():
    """
    Monitors open positions for:
      - Soft SL at expected-move / hybrid level (pos['sl'])
      - Hard stop at per-trade risk_usd (bounded by MAX_LOSS_PER_TRADE)
      - Expected-move / hybrid SL arming & trailing (for winners)

    NOTE:
    TP logic (target + QuickTP) is handled by quick_profit_monitor() thread.
    Soft SL protects per-trade downside, hard SL is a final safety net.
    """
    global open_positions

    from datetime import datetime as _dt_mod, timezone as _tz_mod

    # Iterate over a copy of keys (may mutate during close_position)
    for symbol in list(open_positions.keys()):
        try:
            pos = open_positions.get(symbol) or {}
            ts = pos.get('time')
            if ts:
                try:
                    entry_time = _dt_mod.fromisoformat(ts)
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=_tz_mod.utc)
                except Exception:
                    entry_time = _dt_mod.now(_tz_mod.utc)
            else:
                entry_time = _dt_mod.now(_tz_mod.utc)

            side  = (pos.get('side', 'BUY') or 'BUY').upper()
            entry = float(pos.get('entry_price', 0.0))
            qty   = float(pos.get('qty', 0.0))
            if qty <= 0 or entry <= 0:
                # invalid position footprint; drop it
                open_positions.pop(symbol, None)
                save_open_positions(open_positions)
                continue

            # Live price & ATR
            df5 = fetch_ohlcv(symbol, interval=trade_timeframe, limit=60)
            atr_now = calculate_atr(df5)
            px = get_ws_mark(symbol)
            if px is None:
                try:
                    px = float(client.mark_price(symbol=symbol)['markPrice'])
                except Exception:
                    # As last resort, skip this symbol this tick
                    continue

            px = float(px)

            # PnL in USDT
            pnl = (px - entry) * qty if side == "BUY" else (entry - px) * qty

            # ---------------- HARD STOP (per-trade risk_usd, bounded) ----------------
            try:
                risk_cap = float(pos.get('risk_usd', 0.0) or 0.0)
            except Exception:
                risk_cap = 0.0
            if risk_cap <= 0:
                # fallback for legacy positions
                try:
                    risk_cap = float(MAX_LOSS_PER_TRADE)
                except Exception:
                    risk_cap = 0.0
            if risk_cap > 0 and pnl <= -risk_cap:
                close_position(symbol, px, qty, side, f"Hard stop -${risk_cap:.2f}", realized_pnl=pnl)
                continue

            # ---------------- HYBRID TRAILING (update SL / best_px) ----------------
            try:
                # Start from stored SL or entry (if missing)
                sl_cur = float(pos.get('sl', entry))
                mfe = (max(px, entry) - entry) if side == "BUY" else (entry - min(px, entry))
                init_risk = max(1e-12, abs(entry - sl_cur))
                armed_prev = bool(pos.get('trail_armed', False))
                best = float(pos.get('best_px', entry))
                best = max(best, px) if side == "BUY" else min(best, px)

                armed = armed_prev
                if not armed:
                    rr_hit  = (mfe >= float(HYBRID_ARM_RR)  * init_risk)
                    atr_hit = (mfe >= float(HYBRID_ARM_ATR) * float(atr_now))
                    armed = bool(rr_hit or atr_hit)

                if armed:
                    trail_step = float(HYBRID_TRAIL_K) * float(atr_now)
                    if side == "BUY":
                        sl_cur = max(sl_cur, best - trail_step)
                    else:
                        sl_cur = min(sl_cur, best + trail_step)

                    # Breakeven time guard (once trade has had time to work)
                    if (_dt_mod.now(_tz_mod.utc) - entry_time).total_seconds() > float(BREAKEVEN_AFTER_MIN):
                        be = entry - (float(BREAKEVEN_EPS_FRAC) * float(atr_now)) if side == "BUY" else entry + (float(BREAKEVEN_EPS_FRAC) * float(atr_now))
                        if (side == "BUY" and sl_cur < be) or (side == "SELL" and sl_cur > be):
                            sl_cur = be

                    pos['trail_armed'] = True

                # Persist live-tuned SL/best (or just best if not armed)
                pos['sl'] = float(sl_cur)
                pos['best_px'] = float(best)
                open_positions[symbol] = pos
                save_open_positions(open_positions)
            except Exception:
                # Do not kill the loop if trailing fails
                pass

            # ---------------- SOFT SL (expected-move / hybrid) ENFORCEMENT ----------------
            try:
                sl_soft = float(pos.get('sl', 0.0) or 0.0)
            except Exception:
                sl_soft = 0.0

            if sl_soft > 0.0:
                hit_soft = (side == "BUY" and px <= sl_soft) or (side == "SELL" and px >= sl_soft)
                if hit_soft:
                    close_position(symbol, px, qty, side, "Soft SL hit (expected-move/hybrid)", realized_pnl=pnl)
                    continue

        except Exception as e:
            # Keep the main loop resilient
            try:
                send_telegram_message(telegram_token, telegram_chat_id, f"[MONITOR ERROR] {symbol}: {e}")
            except Exception:
                pass
            continue


# ======================
#  MAIN LOOP
# ======================


def place_order_from_fingerprint(symbol: str, ordz: dict, ctx_symbol: dict):
    """
    Execute a fingerprint-based override trade.

    ordz = {
        "entry_type": "limit|stop",
        "entry": float,
        "sl": float,   # soft / analytical SL from the template
        "tp": float,
        "side": "BUY|SELL",
    }

    This version uses the same dynamic risk engine as normal entries:
      - Risk per trade is fraction-of-equity and bounded.
      - Position size is derived from (risk_usd, SL distance, leverage).
      - Margin is clamped to [MIN_TRADE_USDT, MAX_TRADE_USDT].
    """
    try:
        # --------- Basic validation ---------
        if not isinstance(ordz, dict):
            msg = f"? FP Override {symbol}: invalid ordz (not a dict)"
            send_telegram_message(telegram_token, telegram_chat_id, msg)
            print(f"[FP OVERRIDE] {msg}")
            return False

        side = (ordz.get("side") or "BUY").upper()
        entry = float(ordz.get("entry", 0.0) or 0.0)
        sl_soft = float(ordz.get("sl", 0.0) or 0.0)
        tp = float(ordz.get("tp", 0.0) or 0.0)

        if side not in ("BUY", "SELL"):
            msg = f"? FP Override {symbol}: invalid side '{side}'"
            send_telegram_message(telegram_token, telegram_chat_id, msg)
            print(f"[FP OVERRIDE] {msg}")
            return False
        if entry <= 0 or sl_soft <= 0 or tp <= 0:
            msg = (
                f"? FP Override {symbol}: invalid prices\n"
                f"Entry={entry}, SL={sl_soft}, TP={tp}"
            )
            send_telegram_message(telegram_token, telegram_chat_id, msg)
            print(f"[FP OVERRIDE] {msg}")
            return False

        print(f"[FP OVERRIDE] {symbol} {side} | entry={entry}, sl_soft={sl_soft}, tp={tp}")

        # --------- Live price & equity ---------
        try:
            price = float(entry or 0.0)
            if price <= 0:
                price = float(get_ws_mark(symbol) or client.mark_price(symbol=symbol)["markPrice"])
        except Exception:
            price = float(client.mark_price(symbol=symbol)["markPrice"])

        # Total equity (not just free balance)
        try:
            account_data = client.balance()
            total_equity = 0.0
            available_balance = 0.0
            for asset in account_data:
                if asset.get("asset") == "USDT":
                    total_equity = float(asset.get("balance", 0) or 0)
                    available_balance = float(asset.get("availableBalance", 0) or 0)
                    break
            if total_equity == 0:
                total_equity = get_futures_balance()
        except Exception as e:
            print(f"[FP OVERRIDE] Balance fetch error {symbol}: {e}")
            total_equity = get_futures_balance()
            available_balance = total_equity

        # Hard guard: cannot trade if equity is tiny
        if total_equity <= 0:
            msg = f"? FP Override {symbol}: no equity available"
            send_telegram_message(telegram_token, telegram_chat_id, msg)
            print(f"[FP OVERRIDE] {msg}")
            return False

        # --------- Dynamic risk -> margin & qty ---------
        risk_per_unit_soft = abs(price - sl_soft)
        if risk_per_unit_soft <= 0:
            msg = f"? FP Override {symbol}: SL too close to entry (no risk distance)"
            send_telegram_message(telegram_token, telegram_chat_id, msg)
            print(f"[FP OVERRIDE] {msg}")
            return False

        risk_usd = get_dynamic_risk_usd(total_equity)
        if risk_usd <= 0:
            msg = f"? FP Override {symbol}: dynamic risk is zero"
            send_telegram_message(telegram_token, telegram_chat_id, msg)
            print(f"[FP OVERRIDE] {msg}")
            return False

        try:
            margin_to_use = risk_usd * price / (risk_per_unit_soft * LEVERAGE)
        except Exception:
            msg = f"? FP Override {symbol}: failed to convert risk into margin"
            send_telegram_message(telegram_token, telegram_chat_id, msg)
            print(f"[FP OVERRIDE] {msg}")
            return False

        # Clamp margin between configured bounds
        margin_to_use = max(MIN_TRADE_USDT, min(MAX_TRADE_USDT, float(margin_to_use)))

        # Exposure guard: do not exceed total equity * MAX_TOTAL_ALLOC
        if margin_to_use > total_equity * MAX_TOTAL_ALLOC:
            margin_to_use = total_equity * MAX_TOTAL_ALLOC

        if margin_to_use < MIN_TRADE_USDT:
            msg = (
                f"? FP Override {symbol}: computed margin {margin_to_use:.2f}$ "
                f"is below MIN_TRADE_USDT={MIN_TRADE_USDT:.2f}$"
            )
            send_telegram_message(telegram_token, telegram_chat_id, msg)
            print(f"[FP OVERRIDE] {msg}")
            return False

        qty_precision, price_precision, min_qty, min_notional = get_symbol_precision_and_min(symbol)
        qty = round(margin_to_use * LEVERAGE / price, qty_precision)

        if qty < min_qty or qty * price < min_notional:
            msg = (
                f"? FP Override {symbol} sizing failed:\n"
                f"Qty={qty:.8f} (min={min_qty}) | Notional={qty*price:.2f} (min_notional={min_notional})"
            )
            send_telegram_message(telegram_token, telegram_chat_id, msg)
            print(f"[FP OVERRIDE] {msg}")
            return False

        # Effective risk with this size (for bookkeeping)
        risk_usd_effective = risk_per_unit_soft * qty
        # Cap by global safety
        risk_cap = float(min(risk_usd_effective, MAX_LOSS_PER_TRADE))

        print(
            f"[FP OVERRIDE] {symbol} qty={qty:.8f}, margin={margin_to_use:.2f}$, "
            f"risk_usd_effective={risk_usd_effective:.2f}$ (cap={risk_cap:.2f}$)"
        )

        # --------- Execute MARKET order ---------
        print(f"[FP OVERRIDE] Executing MARKET {side} {symbol}, qty={qty}")
        res = futures_execute_trade(symbol, side, qty)
        if not res:
            msg = (
                f"? FP Override {symbol}: futures_execute_trade returned no result\n"
                f"Side={side} Qty={qty:.8f} Margin~{margin_to_use:.2f}$"
            )
            send_telegram_message(telegram_token, telegram_chat_id, msg)
            print(f"[FP OVERRIDE] {msg}")
            return False

        # --------- Authoritative entry price from fills ---------
        try:
            from datetime import datetime as _dt2, timezone as _tz2, timedelta as _td2
            start_ms_entry = int((_dt2.now(_tz2.utc) - _td2(seconds=5)).timestamp() * 1000)
            tr_list = compat_user_trades(client, symbol, start_ms_entry)

            incr_qty = 0.0
            incr_notional = 0.0

            def _to_bool(z):
                if isinstance(z, bool):
                    return z
                return str(z).lower() in ("1", "true", "t", "yes", "y")

            for tr in (tr_list or []):
                if tr.get("symbol") != symbol:
                    continue
                px_tr = float(tr.get("price") or tr.get("p") or 0)
                q_tr = float(tr.get("qty") or tr.get("q") or 0)
                if px_tr <= 0 or q_tr <= 0:
                    continue
                is_buyer = _to_bool(tr.get("buyer", tr.get("isBuyer")))
                increases = ((side == "BUY" and is_buyer) or (side == "SELL" and not is_buyer))
                if not increases:
                    continue
                incr_qty += q_tr
                incr_notional += px_tr * q_tr

            if incr_qty > 0:
                entry_price_authoritative = incr_notional / incr_qty
            else:
                entry_price_authoritative = price
        except Exception:
            entry_price_authoritative = price

        # --------- ATR & fingerprint snapshot for this trade ---------
        try:
            df_entry = fetch_ohlcv(symbol, interval=trade_timeframe, limit=60)
            atr_entry = calculate_atr(df_entry)
        except Exception:
            df_entry = None
            atr_entry = 0.0

        if atr_entry is None:
            atr_entry = 0.0

        order_hint_fp = {
            "entry_type": "limit",
            "entry": float(entry_price_authoritative),
            "sl": float(sl_soft),
            "tp": float(tp),
            "sl_mult_atr": abs(float(entry_price_authoritative) - float(sl_soft)) / max(1e-9, float(atr_entry or 0.0)),
            "tp_mult_atr": abs(float(tp) - float(entry_price_authoritative)) / max(1e-9, float(atr_entry or 0.0)),
            "stop_buf_atr": 0.0,
        }

        if df_entry is not None:
            F_live_save = make_live_fingerprint(df_entry, symbol, side, {**ctx_symbol, "order_hint": order_hint_fp})
        else:
            F_live_save = None

        expected_usd = abs(tp - entry_price_authoritative) * qty

        # Hard SL in price terms from the per-trade risk cap
        try:
            if side.upper() == "BUY":
                hard_sl = entry_price_authoritative - (risk_cap / max(1e-9, qty))
            else:
                hard_sl = entry_price_authoritative + (risk_cap / max(1e-9, qty))
        except Exception:
            hard_sl = sl_soft

        from datetime import datetime as _dt3, timezone as _tz3
        open_positions[symbol] = {
            "entry_price": float(entry_price_authoritative),
            "qty": float(qty),
            "side": side,
            "tp": float(tp),
            "sl": float(sl_soft),              # soft/hybrid SL for winners & losers
            "hard_sl_px": float(hard_sl),      # catastrophic per-trade hard SL
            "risk_usd": float(risk_cap),
            "time": _dt3.now(_tz3.utc).isoformat(),
            "agent": "FP_OVERRIDE",
            "tf": [trade_timeframe],
            "usdt_amt": float(margin_to_use),
            "trail_armed": False,
            "best_px": float(entry_price_authoritative),
            "expected_pnl_usd": float(expected_usd),
            "features_open": F_live_save,
        }
        save_open_positions(open_positions)

        send_telegram_message(
            telegram_token,
            telegram_chat_id,
            f"? FP Override executed: {symbol} {side} qty={qty} @ {entry_price_authoritative:.6f} | "
            f"risk~${risk_cap:.2f} margin~${margin_to_use:.2f}",
        )
        return True

    except Exception as e:
        try:
            send_telegram_message(telegram_token, telegram_chat_id, f"[FP override error] {symbol}: {e}")
        except Exception:
            pass
        print(f"[FP OVERRIDE] error {symbol}: {e}")
        return False


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
                # reset dynamic risk state each new UTC day
                globals()['win_streak'] = 0
                globals()['loss_streak'] = 0
                globals()['current_risk_frac'] = RISK_BASE_FRAC

            autotune_if_stale()

            now_sec = time.time()
            if now_sec - last_meta_evolve > META_EVOLVE_INTERVAL:
                last_meta_evolve = now_sec
                meta_evolution()

            # Pause gating
            if now_sec < pause_until:
                time.sleep(1)
                continue

            # -- Position monitoring (Soft SL + Hard SL + trailing; QuickTP in separate thread) ------
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

                # News sentiment (Perplexity / external service)
                news_sentiment = get_news_sentiment(symbol)

                # Shared ctx for agents
                ctx_base = {
                    'strategy_profile': STRATEGY_PROFILE,
                    'timeframe': trade_timeframe,
                    'min_expected_move': MIN_EXPECTED_MOVE,
                    'conf_threshold': CONFIDENCE_THRESHOLD,
                    'trend_hint': trend_master,
                    'trend_15m': t15, 'trend_1h': t1h,
                    'vol_class': vol_class,
                    'risk': {'atr': float(atr_now), 'price': float(price)},
                    'rules': {'sl_mode': HYBRID_SL_MODE, 'tp_quick_profit': TP_QUICK_PROFIT},
                    'news_sentiment': float(news_sentiment),
                }

                # Collect signals
                signals_by_agent = {}
                debug_signals = []
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
                        if sig.get('side') in ('BUY','SELL'):
                            debug_signals.append(f"{agent_name}:{sig.get('side')}@{sig.get('confidence',0):.2f}")

                if debug_signals:
                    print(f"[DEBUG] {symbol} signals: " + ", ".join(debug_signals))

                vote = smart_vote(symbol, signals_by_agent, MIN_AGREE_AGENTS, MIN_AGREE_TIMEFRAMES)
                if not vote:
                    continue

                side, avg_conf, used = vote
                print(f"[DEBUG] {symbol} vote={side}, avg_conf={avg_conf:.2f}, trend_master={trend_master}, t15={t15}, t1h={t1h}")

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
                        send_telegram_message(telegram_token, telegram_chat_id, f"?? FP Override triggered: {symbol} {override_side} similarity={override_sim:.2f}")
                        placed = place_order_from_fingerprint(symbol, override_order, ctx_fp)
                        if placed:
                            send_telegram_message(telegram_token, telegram_chat_id, f"? FP Override executed: {symbol} {override_side}")
                            continue  # skip normal agent pipeline
                        else:
                            send_telegram_message(telegram_token, telegram_chat_id, f"? FP Override failed to execute (see details above)")
                    # If no override, proceed with normal pipeline (veto implied by continue above)
                except Exception as _e:
                    print("[FP] veto/override error:", _e)

                # STRONG trend filter for TREND_SURGE_RIDER: HTF must align
                if STRATEGY_PROFILE == "TREND_SURGE_RIDER" and TREND_FILTER_ON:
                    if side == "BUY":
                        if trend_master != "UP":
                            continue
                    elif side == "SELL":
                        if trend_master != "DOWN":
                            continue

                # === BOT 2: expected-move based SL/TP (hybrid engine still refines after entry) ===
                # Per-agent risk/expectation bias (longer holds for trend/momentum, tighter for scalp/reversal)
                style_bias_map = {
                    'momentum': 1.25,
                    'trend': 1.15,
                    'pullback': 1.00,
                    'reversal': 0.95,
                    'scalp': 0.90,
                }
                agent_style = {
                    'apex_momentum_pump': 'momentum',
                    'apex_supertrend_adaptive': 'trend',
                    'apex_vwap_pullback': 'pullback',
                    'apex_sweep_reversal': 'reversal',
                    'apex_microburst': 'scalp',
                }
                num_eff = 0.0
                bias_acc = 0.0
                for a_name, eff_c, sig_used in used:
                    style = agent_style.get(a_name, 'pullback')
                    b = style_bias_map.get(style, 1.0)
                    w_eff = max(0.0, float(eff_c))
                    bias_acc += b * w_eff
                    num_eff += w_eff
                profile_bias = (bias_acc / num_eff) if num_eff > 0 else 1.0
                # Clamp profile bias so overrides cannot explode targets
                if profile_bias < 0.85:
                    profile_bias = 0.85
                if profile_bias > 1.35:
                    profile_bias = 1.35

                sl_soft, tp, exp_move, rr_used = compute_expected_move_sl_tp(
                    symbol=symbol,
                    side=side,
                    price=price,
                    atr_now=atr_now,
                    df5=df5,
                    avg_conf=avg_conf,
                    trend_master=trend_master,
                    vol_class=vol_class,
                    news_sentiment=news_sentiment,
                    profile_bias=profile_bias,
                )
                if sl_soft is None or tp is None:
                    # expected move too small or invalid   skip this setup
                    continue

                # Sizing & exchange filters (dynamic risk-based)
                risk_per_unit_soft = abs(price - sl_soft)
                if risk_per_unit_soft <= 0:
                    continue

                # Dynamic per-trade risk in USDT
                risk_usd = get_dynamic_risk_usd(balance)
                if risk_usd <= 0:
                    continue

                try:
                    alloc = risk_usd * price / (risk_per_unit_soft * LEVERAGE)
                except Exception:
                    continue

                # Clamp margin between MIN_TRADE_USDT and MAX_TRADE_USDT
                alloc = max(MIN_TRADE_USDT, min(MAX_TRADE_USDT, float(alloc)))

                # portfolio exposure guard (pre-leverage margin terms)
                if current_alloc + alloc > balance * MAX_TOTAL_ALLOC:
                    continue

                qty_precision, price_precision, min_qty, min_notional = get_symbol_precision_and_min(symbol)
                qty = round(alloc * LEVERAGE / price, qty_precision)
                if qty < min_qty or qty * price < min_notional:
                    continue

                # Effective risk with this configuration (capped by global safety)
                risk_usd_effective = risk_per_unit_soft * qty
                risk_cap = float(min(risk_usd_effective, MAX_LOSS_PER_TRADE))

                # Ensure leverage set (best effort)
                try:
                    brackets = client.leverage_brackets()
                    sb = next((b for b in brackets if b.get('symbol') == symbol), None)
                    if sb:
                        max_lev = max(x.get('initialLeverage', LEVERAGE) for x in sb.get('brackets', []))
                        client.change_leverage(symbol=symbol, leverage=min(LEVERAGE, max_lev))
                except Exception as e:
                    print(f"[ORDER] leverage set skipped {symbol}: {e}")

                # Re-entry cooldown guard (5 minutes)
                if not _can_enter_now(symbol):
                    # skip signal; still cooling down for this symbol
                    continue

                # Place order
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
                            px_tr = float(tr.get("price") or tr.get("p") or 0)
                            q_tr  = float(tr.get("qty")   or tr.get("q") or 0)
                            if px_tr <= 0 or q_tr <= 0:
                                continue
                            is_buyer = _to_bool(tr.get("buyer", tr.get("isBuyer")))
                            increases = ((side.upper() == "BUY"  and is_buyer) or
                                         (side.upper() == "SELL" and not is_buyer))
                            if not increases:
                                continue
                            incr_qty += q_tr
                            incr_notional += px_tr * q_tr
                        except Exception:
                            continue
                    if incr_qty > 0:
                        entry_price_authoritative = incr_notional / incr_qty
                except Exception:
                    pass

                # Attach features for fingerprint logging on close
                try:
                    df_entry = fetch_ohlcv(symbol, interval=trade_timeframe, limit=60)
                    atr_entry = calculate_atr(df_entry)
                except Exception:
                    atr_entry = 0.0

                order_hint_fp = {
                    "entry_type": "limit",
                    "entry": float(entry_price_authoritative),
                    "sl": float(sl_soft),
                    "tp": float(tp),
                    "sl_mult_atr": abs(float(entry_price_authoritative) - float(sl_soft)) / max(1e-9, float(atr_entry or 0.0)),
                    "tp_mult_atr": abs(float(tp) - float(entry_price_authoritative)) / max(1e-9, float(atr_entry or 0.0)),
                    "stop_buf_atr": 0.0
                }
                F_live_save = make_live_fingerprint(df_entry, symbol, side, {**ctx_base, "order_hint": order_hint_fp})

                expected_usd = abs(tp - price) * qty

                # Hard stop: catastrophic level based on per-trade risk_cap (bounded by MAX_LOSS_PER_TRADE)
                try:
                    if side.upper() == "BUY":
                        hard_sl = entry_price_authoritative - (risk_cap / max(1e-9, qty))
                    else:
                        hard_sl = entry_price_authoritative + (risk_cap / max(1e-9, qty))
                except Exception:
                    hard_sl = sl_soft

                open_positions[symbol] = {
                    'entry_price': float(entry_price_authoritative),
                    'qty': float(qty),
                    'side': side,
                    'tp': float(tp),
                    'sl': float(sl_soft),              # soft/hybrid SL
                    'hard_sl_px': float(hard_sl),      # catastrophic hard SL
                    'risk_usd': float(risk_cap),       # per-trade risk cap in USDT
                    'time': datetime.now(timezone.utc).isoformat(),
                    'agent': ','.join([a for a, _, _ in used]),
                    'tf': [trade_timeframe],
                    'usdt_amt': float(alloc),
                    'trail_armed': False,
                    'best_px': float(price),
                    'expected_pnl_usd': float(expected_usd),
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
                agent_lines = ", ".join([f"{a}({c:.2f})" for a, c, _ in used])
                rationale = (
                    f"?? NEW TRADE\n{symbol} {side} qty={qty}\n"
                    f"Entry={price:.6f}  SL_soft={sl_soft:.6f}  TP={tp:.6f}\n"
                    f"ExpMove={exp_move:.4%}  Exp$~{expected_usd:.2f}\n"
                    f"Leverage={LEVERAGE}  Alloc~${alloc:.2f}\n"
                    f"Agents: {agent_lines}\n"
                    f"Trend: HTF={trend_master} (15m={t15}, 1h={t1h})"
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

    IMPORTANT:
    - ONLY protects LOSING trades (pnl < 0) at the per-trade hard SL (risk_usd, bounded by MAX_LOSS_PER_TRADE).
    - It no longer closes positive or breakeven trades.
    - Profit-taking is fully handled by TP + QuickTP engine.
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

                # Ultra guard = ONLY for adverse moves (trade in loss territory)
                pnl = (px - entry) * qty if side == 'BUY' else (entry - px) * qty
                if pnl >= 0:
                    # Trade is at breakeven or in profit -> TP / QuickTP / hybrid manage it
                    continue

                hsl = pos.get('hard_sl_px')
                if hsl is None:
                    # Fallback: derive catastrophic hard SL from per-trade risk_usd (bounded)
                    try:
                        risk_cap = float(pos.get('risk_usd', 0.0) or 0.0)
                    except Exception:
                        risk_cap = 0.0
                    if risk_cap <= 0:
                        risk_cap = float(MAX_LOSS_PER_TRADE)
                    if side == 'BUY':
                        hsl = entry - (risk_cap / max(1e-9, qty))
                    else:
                        hsl = entry + (risk_cap / max(1e-9, qty))
                    pos['hard_sl_px'] = float(hsl)
                    open_positions[symbol] = pos
                    save_open_positions(open_positions)

                hit_hsl = (px <= hsl) if side == 'BUY' else (px >= hsl)
                if hit_hsl:
                    try:
                        client.cancel_all_open_orders(symbol=symbol)
                    except Exception:
                        pass
                    close_position(symbol, px, qty, side, "HardSL (ultra guard)", realized_pnl=pnl)
        except Exception:
            pass
        time.sleep(SLEEP)

# start ultra-fast guard
try:
    threading.Thread(target=ultra_fast_guard, daemon=True).start()
except Exception:
    pass


# ======================
#  QUICK TP MONITOR - ONLY TP LOGIC IN THE ENTIRE BOT
# ======================
def quick_profit_monitor():
    """
    TP engine for TREND_SURGE_RIDER.

    - Primary TP: expected-move target stored in pos['tp'].
      As soon as price touches that level, we exit: "Target hit (expected-move TP)".
    - QuickTP: dynamic, based on expected_pnl_usd * Q_TREND_SURGE_FACTOR
      (for big moves) or ATR-based fallback for other profiles.

    Logic:
    1. If TP target is hit -> exit immediately (full expected move captured).
    2. Otherwise, once PnL >= QuickTP threshold:
       - Track peak PnL.
       - Never allow winner to go negative after threshold.
       - If PnL falls >40% from peak -> exit.
       - If momentum no longer EXTREMELY strong -> exit.
    """
    print("[QuickTP MONITOR] Starting - TP engine (checks every 0.5s)...")
    print("[QuickTP MONITOR] Target TP: pos['tp'] is PRIMARY exit (expected-move).")
    print("[QuickTP MONITOR] QuickTP: dynamic bonus lock, scaled to expected_pnl_usd for TREND_SURGE_RIDER.")

    while not SHUTDOWN.is_set():
        try:
            for symbol in list(open_positions):
                try:
                    pos = open_positions.get(symbol) or {}
                    qty = pos.get('qty')
                    side = (pos.get('side') or '').upper()
                    entry = pos.get('entry_price')

                    if not qty or side not in ("BUY", "SELL") or entry is None:
                        continue

                    entry = float(entry)
                    qty = float(qty)

                    # Get current price from websocket
                    px = get_ws_mark(symbol)
                    if px is None:
                        continue

                    # --- 1) PRIMARY EXIT: expected-move TP hit ---
                    tp = float(pos.get('tp', 0.0) or 0.0)
                    if tp > 0.0:
                        if (side == "BUY" and px >= tp) or (side == "SELL" and px <= tp):
                            pnl_target = ((px - entry) if side == "BUY" else (entry - px)) * qty
                            close_position(
                                symbol, px, qty, side,
                                reason=f"Target hit (expected-move TP) @ {px:.6f}",
                                realized_pnl=pnl_target
                            )
                            continue

                    # --- 2) QuickTP bonus lock (only after some profit) ---
                    delta = (px - entry) if side == "BUY" else (entry - px)
                    pnl_current = delta * qty

                    expected_usd = float(pos.get('expected_pnl_usd', 0.0) or 0.0)

                    quicktp_threshold = TP_QUICK_PROFIT
                    df1m = None
                    try:
                        df1m = fetch_ohlcv(symbol, interval="1m", limit=60)
                        atr_val = calculate_atr(df1m)
                        atr_usd = atr_val * qty
                        base_from_atr = TP_QUICK_ATR_MULT * atr_usd

                        if STRATEGY_PROFILE == "TREND_SURGE_RIDER" and expected_usd > 0.0:
                            # For true trend rides: arm QuickTP based on a big chunk of the expected move
                            dyn = expected_usd * Q_TREND_SURGE_FACTOR
                            quicktp_threshold = max(TP_QUICK_PROFIT, dyn, base_from_atr)
                        else:
                            # Other profiles or missing expected: ATR + fixed minimum
                            quicktp_threshold = max(TP_QUICK_PROFIT, base_from_atr)
                    except Exception:
                        # Fallback to fixed minimum if data fetch fails
                        quicktp_threshold = max(TP_QUICK_PROFIT, quicktp_threshold)

                    # Haven't hit QuickTP threshold yet -> let trade breathe
                    if pnl_current < quicktp_threshold:
                        continue

                    # --- WE'VE HIT QUICKTP THRESHOLD - NOW PROTECT PROFITS ---
                    peak_pnl = float(pos.get('peak_pnl', pnl_current))
                    if pnl_current > peak_pnl:
                        peak_pnl = pnl_current
                        pos['peak_pnl'] = peak_pnl
                        pos['threshold_hit'] = True
                        open_positions[symbol] = pos
                        save_open_positions(open_positions)

                    # Never let a winner go negative once threshold was hit
                    if pos.get('threshold_hit') and pnl_current <= 0:
                        close_position(
                            symbol, px, qty, side,
                            reason=f"QuickTP PROTECTION: Winner went negative! Peak=${peak_pnl:.2f} | Current=${pnl_current:.2f}",
                            realized_pnl=pnl_current
                        )
                        continue

                    # If PnL drops below 60% of peak after threshold, exit
                    if peak_pnl > quicktp_threshold and pnl_current < peak_pnl * 0.60:
                        close_position(
                            symbol, px, qty, side,
                            reason=f"QuickTP PROTECTION: 40% pullback from peak! Peak=${peak_pnl:.2f} | Current=${pnl_current:.2f}",
                            realized_pnl=pnl_current
                        )
                        continue

                    # --- VERY STRICT momentum check (only if still profitable) ---
                    try:
                        if df1m is None:
                            df1m = fetch_ohlcv(symbol, interval="1m", limit=60)
                        ema9 = df1m['close'].ewm(span=9, adjust=False).mean()
                        ema21 = df1m['close'].ewm(span=21, adjust=False).mean()

                        ema9_current = float(ema9.iloc[-1])
                        ema21_current = float(ema21.iloc[-1])
                        ema9_prev = float(ema9.iloc[-2])

                        momentum_gap_pct = abs(ema9_current - ema21_current) / max(1e-9, ema21_current)
                        strong_momentum = False

                        if side == "BUY":
                            # Longs: need very strong continuation to keep holding after QuickTP
                            if (ema9_current > ema21_current * 1.003 and
                                momentum_gap_pct > 0.005 and
                                px > ema9_current * 1.002 and
                                ema9_current > ema9_prev):
                                strong_momentum = True
                        else:
                            # Shorts: mirrored criteria
                            if (ema9_current < ema21_current * 0.997 and
                                momentum_gap_pct > 0.005 and
                                px < ema9_current * 0.998 and
                                ema9_current < ema9_prev):
                                strong_momentum = True

                        if strong_momentum:
                            # Let it run, but keep tracking peak for pullback guard
                            continue

                        # Momentum no longer extreme -> bank the QuickTP win
                        close_position(
                            symbol, px, qty, side,
                            reason=f"QuickTP: Momentum weakened at ${pnl_current:.2f} (peak was ${peak_pnl:.2f})",
                            realized_pnl=pnl_current
                        )

                    except Exception:
                        # If momentum check fails, always take the money (safety first)
                        close_position(
                            symbol, px, qty, side,
                            reason=f"QuickTP: ${quicktp_threshold:.2f} hit, momentum check failed (SAFETY EXIT)",
                            realized_pnl=pnl_current
                        )

                except Exception as e:
                    print(f"[QuickTP MONITOR ERROR] {symbol}: {e}")
                    continue

        except Exception as e:
            print(f"[QuickTP MONITOR CRITICAL ERROR] {e}")
        
        # Check every 0.5 seconds as requested
        time.sleep(0.5)


# ======================
#  ENTRY POINT
# ======================
if __name__ == "__main__":
    try:
        # Start the TP engine thread (target + QuickTP)
        threading.Thread(target=quick_profit_monitor, daemon=True).start()
        print("[MAIN] QuickTP monitor thread started - TP logic (target + QuickTP)")

        # Start main trading loop
        main_loop()
    except KeyboardInterrupt:
        pass
    finally:
        SHUTDOWN.set()
        try:
            stop_websocket()
        except Exception:
            pass
        print("[EXIT] Bye.")
