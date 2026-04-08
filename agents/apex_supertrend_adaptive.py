# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd

NAME = "apex_supertrend_adaptive"

# ---------------------------------------------------------
# Tunables (behavior knobs – relaxed a bit so agent is not "dead")
# ---------------------------------------------------------
ST_MAX_DIST_ATR = 2.4          # hard cap how far from ST we are willing to enter
ST_RETEST_MAX_DIST_ATR = 1.0   # max distance for "retest" entries
MIN_BODY_RATIO = 0.22          # minimum body/candle range for confirmation
CONF_DEFAULT = 0.76            # default confidence threshold (can be overridden via ctx)
MIN_EXPECTED_MOVE = 0.0065     # ~0.65% default expected move filter
RV_MAX = 3.1                   # max allowed realized vol ratio
RV_MIN = 0.25                  # min allowed realized vol ratio

# ---------------------------------------------------------
# Liquidity / context helpers (shared pattern with other agents)
# ---------------------------------------------------------
MAJOR_SYMBOLS = {
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
}

# Base ratio for this agent, before hot/major adjustments
DEFAULT_MIN_VOL_RATIO = 0.55
MIN_QUOTE_MAJOR = 120_000.0   # 120k USDT per bar for majors
MIN_QUOTE_ALT = 25_000.0      # 25k USDT per bar for non-majors


def _safe_timeframe_from_context(ctx: Optional[Dict[str, Any]], default_tf: str = "5m") -> str:
    if not ctx:
        return default_tf
    tf = ctx.get("timeframe") or ctx.get("tf") or default_tf
    return str(tf)


def _resolve_min_vol_ratio(
    symbol: str,
    ctx: Optional[Dict[str, Any]],
    default_ratio: float,
) -> float:
    """
    Resolve min_vol_ratio with priority:
      1) ctx["min_vol_ratio_per_symbol"][symbol]
      2) ctx["min_vol_ratio"]
      3) auto-softened default for majors
      4) default_ratio
    """
    if ctx:
        if "min_vol_ratio" in ctx:
            try:
                return float(ctx["min_vol_ratio"])
            except (TypeError, ValueError):
                pass

        per_symbol = ctx.get("min_vol_ratio_per_symbol")
        if isinstance(per_symbol, dict) and symbol in per_symbol:
            try:
                return float(per_symbol[symbol])
            except (TypeError, ValueError):
                return default_ratio

    # majors get softened band ~[0.20, 0.30]
    if symbol.upper() in MAJOR_SYMBOLS:
        softened = min(default_ratio, 0.30)
        return max(0.20, softened)

    return default_ratio


# ---------------------------------------------------------
# State (per-symbol cooldown)
# ---------------------------------------------------------
_STATE = {
    "last_idx_by_symbol": {},  # symbol -> last processed bar index
}
_COOLDOWN_BARS = 1  # at most one signal per completed bar


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def _safe(x, d: float = 0.0) -> float:
    try:
        v = float(x)
        if not np.isfinite(v):
            return d
        return v
    except Exception:
        return d


def _ema(series: pd.Series, span: int) -> pd.Series:
    if series is None or len(series) < max(3, span):
        return series.copy()
    return series.ewm(span=span, adjust=False).mean()


def _atr_series(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    pc = c.shift(1)

    tr1 = h - l
    tr2 = (h - pc).abs()
    tr3 = (l - pc).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


def _atr_last(df: pd.DataFrame, n: int = 14) -> float:
    s = _atr_series(df, n)
    if len(s) == 0:
        return 0.0
    return _safe(s.iloc[-1], 0.0)


def _dbg(symbol: str, tf: str, reason: str, extra: dict | None = None, event: str = "veto") -> None:
    """
    Safe debug logger (never raises).
    """
    try:
        payload = {"agent": NAME, "tf": tf, "event": event, "reason": reason}
        if extra:
            payload.update(extra)
        print(f"[DEBUG] {NAME} {symbol} :: " + json.dumps(payload))
    except Exception:
        pass


def _is_hot(symbol: str) -> bool:
    """
    Simple meme/volatile detector.
    """
    toks = [
        "PEPE", "DOGE", "SHIB", "FLOKI", "BONK", "TRUMP", "MEME",
        "1000PEPE", "POPCAT", "WLFI",
    ]
    su = symbol.upper()
    return any(t in su for t in toks)


def passes_liquidity_filter(
    df: pd.DataFrame,
    symbol: str,
    ctx: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Volume guard that:
      - Uses dynamic min_vol_ratio (context + majors softening + hot tokens)
      - Also checks absolute quote volume (USDT)
      - Does NOT veto just because vol_med == 0 if current bar has volume
    """
    tf = _safe_timeframe_from_context(ctx, default_tf="5m")

    if df is None or df.empty:
        _dbg(symbol, tf, "empty_df", {"event": "veto"}, event="veto")
        return False

    # choose volume column
    vol_col = None
    for candidate in ("quote_volume", "quoteVolume", "volume", "vol"):
        if candidate in df.columns:
            vol_col = candidate
            break

    if vol_col is None:
        _dbg(symbol, tf, "no_volume_column", {}, event="veto")
        return False

    vol_series = df[vol_col].astype(float)
    vol_now = _safe(vol_series.iloc[-1])
    lookback = min(len(vol_series), 288)  # ~24h on 5m
    vol_med = _safe(vol_series.tail(lookback).median(), 0.0) if lookback > 0 else 0.0

    # approximate quote volume
    quote_now: Optional[float] = None
    for candidate in ("quote_volume", "quoteVolume"):
        if candidate in df.columns:
            try:
                quote_now = float(df[candidate].iloc[-1])
            except Exception:
                quote_now = None
            break

    if quote_now is None and "close" in df.columns:
        try:
            quote_now = vol_now * float(df["close"].iloc[-1])
        except Exception:
            quote_now = None

    is_major = symbol.upper() in MAJOR_SYMBOLS
    is_hot = _is_hot(symbol)

    # Slightly looser base ratio for hot memes, tighter for others
    default_ratio = 0.40 if is_hot else DEFAULT_MIN_VOL_RATIO
    min_vol_ratio = _resolve_min_vol_ratio(symbol, ctx, default_ratio)

    # If median is broken but we clearly have some live volume, do not hard veto.
    if vol_med <= 0:
        if vol_now > 0:
            _dbg(
                symbol,
                tf,
                "no_med_guard",
                {
                    "vol_now": vol_now,
                    "vol_med": vol_med,
                    "quote_now": quote_now,
                    "min_vol_ratio": min_vol_ratio,
                    "is_major": is_major,
                    "is_hot": is_hot,
                },
                event="pass",
            )
            return True
        else:
            _dbg(
                symbol,
                tf,
                "vol_med_zero",
                {
                    "vol_now": vol_now,
                    "vol_med": vol_med,
                    "quote_now": quote_now,
                    "min_vol_ratio": min_vol_ratio,
                    "is_major": is_major,
                    "is_hot": is_hot,
                },
                event="veto",
            )
            return False

    ratio = vol_now / vol_med if vol_med > 0 else 0.0

    # Absolute liquidity guard
    if quote_now is not None:
        if is_major and quote_now >= MIN_QUOTE_MAJOR:
            _dbg(
                symbol,
                tf,
                "abs_liquidity_ok_major",
                {
                    "vol_now": vol_now,
                    "vol_med": vol_med,
                    "ratio": ratio,
                    "min_vol_ratio": min_vol_ratio,
                    "quote_now": quote_now,
                    "is_major": True,
                    "is_hot": is_hot,
                },
                event="pass",
            )
            return True

        if (not is_major) and quote_now < MIN_QUOTE_ALT:
            _dbg(
                symbol,
                tf,
                "abs_liquidity_low_alt",
                {
                    "vol_now": vol_now,
                    "vol_med": vol_med,
                    "ratio": ratio,
                    "min_vol_ratio": min_vol_ratio,
                    "quote_now": quote_now,
                    "is_major": False,
                    "is_hot": is_hot,
                },
                event="veto",
            )
            return False

    # Relative ratio guard
    if ratio < min_vol_ratio:
        _dbg(
            symbol,
            tf,
            "low_liquidity",
            {
                "vol_now": vol_now,
                "vol_med": vol_med,
                "ratio": ratio,
                "min_vol_ratio": min_vol_ratio,
                "quote_now": quote_now,
                "is_major": is_major,
                "is_hot": is_hot,
            },
            event="veto",
        )
        return False

    _dbg(
        symbol,
        tf,
        "liquidity_ok",
        {
            "vol_now": vol_now,
            "vol_med": vol_med,
            "ratio": ratio,
            "min_vol_ratio": min_vol_ratio,
            "quote_now": quote_now,
            "is_major": is_major,
            "is_hot": is_hot,
        },
        event="pass",
    )
    return True


def _trend_numeric(trend_15m: str, trend_1h: str, trend_hint: str) -> float:
    """
    Map combined trend info into a numeric score in [-1, 1].
    Positive = uptrend, negative = downtrend.
    """
    up_words = {"UP", "BULL", "LONG"}
    dn_words = {"DOWN", "BEAR", "SHORT"}

    def _one(s: str) -> float:
        s = (s or "").upper()
        if s in up_words:
            return 1.0
        if s in dn_words:
            return -1.0
        if "UP" in s:
            return 0.7
        if "DOWN" in s:
            return -0.7
        return 0.0

    scores = [_one(trend_15m), _one(trend_1h), _one(trend_hint)]
    val = float(np.mean(scores))
    return float(np.clip(val, -1.0, 1.0))


def _volatility_regime(df: pd.DataFrame) -> float:
    """
    Realized vol ratio: short / long.
    ~1 => balanced; <0.4 very dead; >3.0 crazy.
    """
    c = df["close"].astype(float)
    r = c.pct_change()
    rv_s = _safe(r.rolling(10).std().iloc[-1], 0.0)
    rv_l = _safe(r.rolling(40).std().iloc[-1], 0.0)
    if rv_l <= 0:
        return 1.0
    val = rv_s / rv_l
    return float(np.clip(val, 0.2, 4.0))


def _supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """
    Classic Supertrend implementation.

    Returns df with:
      'st'      : supertrend line
      'st_dir'  : +1 uptrend, -1 downtrend
    """
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)

    atr = _atr_series(df, period)

    hl2 = (h + l) / 2.0
    basic_ub = hl2 + multiplier * atr
    basic_lb = hl2 - multiplier * atr

    final_ub = basic_ub.copy()
    final_lb = basic_lb.copy()

    for i in range(1, len(df)):
        if basic_ub.iloc[i] < final_ub.iloc[i - 1] or c.iloc[i - 1] > final_ub.iloc[i - 1]:
            final_ub.iloc[i] = basic_ub.iloc[i]
        else:
            final_ub.iloc[i] = final_ub.iloc[i - 1]

        if basic_lb.iloc[i] > final_lb.iloc[i - 1] or c.iloc[i - 1] < final_lb.iloc[i - 1]:
            final_lb.iloc[i] = basic_lb.iloc[i]
        else:
            final_lb.iloc[i] = final_lb.iloc[i - 1]

    st = pd.Series(index=df.index, dtype=float)
    st_dir = pd.Series(index=df.index, dtype=int)

    # Proper seeding: start on one of the bands so equality checks work
    if c.iloc[0] <= final_ub.iloc[0]:
        st.iloc[0] = final_ub.iloc[0]
        st_dir.iloc[0] = -1
    else:
        st.iloc[0] = final_lb.iloc[0]
        st_dir.iloc[0] = 1

    for i in range(1, len(df)):
        if st.iloc[i - 1] == final_ub.iloc[i - 1]:
            if c.iloc[i] <= final_ub.iloc[i]:
                st.iloc[i] = final_ub.iloc[i]
                st_dir.iloc[i] = -1
            else:
                st.iloc[i] = final_lb.iloc[i]
                st_dir.iloc[i] = 1
        elif st.iloc[i - 1] == final_lb.iloc[i - 1]:
            if c.iloc[i] >= final_lb.iloc[i]:
                st.iloc[i] = final_lb.iloc[i]
                st_dir.iloc[i] = 1
            else:
                st.iloc[i] = final_ub.iloc[i]
                st_dir.iloc[i] = -1
        else:
            # fallback – should be rare now
            st.iloc[i] = hl2.iloc[i]
            st_dir.iloc[i] = st_dir.iloc[i - 1]

    out = df.copy()
    out["st"] = st
    out["st_dir"] = st_dir
    return out


def _wick_body(df: pd.DataFrame) -> dict:
    """
    Wick/body decomposition on last candle.
    """
    h = _safe(df["high"].iloc[-1])
    l = _safe(df["low"].iloc[-1])
    o = _safe(df["open"].iloc[-1])
    c = _safe(df["close"].iloc[-1])

    rng = max(1e-12, h - l)
    upper = max(0.0, h - max(o, c))
    lower = max(0.0, min(o, c) - l)
    body = abs(c - o)

    return {
        "rng": rng,
        "upper": upper,
        "lower": lower,
        "body": body,
        "body_ratio": body / rng if rng > 0 else 0.0,
        "upper_ratio": upper / rng if rng > 0 else 0.0,
        "lower_ratio": lower / rng if rng > 0 else 0.0,
        "o": o,
        "c": c,
    }


# ---------------------------------------------------------
# Main signal
# ---------------------------------------------------------
def generate_signal(df: pd.DataFrame, symbol: str, ctx: Dict[str, Any] | None = None):
    """
    TREND-SURGE SUPERTREND ADAPTIVE (God Mode):

    Purpose:
    - Core trend follower.
    - Only trades *with* the dominant HTF trend.
    - Enters on Supertrend flips or clean retests, not micro-noise.
    - No scalping, no countertrend gambling.
    """
    ctx = ctx or {}
    tf = _safe_timeframe_from_context(ctx, default_tf="5m")
    thr = _safe(ctx.get("conf_threshold", CONF_DEFAULT), CONF_DEFAULT)
    min_move = _safe(ctx.get("min_expected_move", MIN_EXPECTED_MOVE), MIN_EXPECTED_MOVE)
    w = _safe(ctx.get("weight", 1.0), 1.0)
    recent_wr = _safe(ctx.get("recent_wr", 1.0), 1.0)

    t15 = str(ctx.get("trend_15m", "SIDEWAYS")).upper()
    t1h = str(ctx.get("trend_1h", "SIDEWAYS")).upper()
    tmas = str(ctx.get("trend_hint", "SIDEWAYS")).upper()

    news_sent = _safe(ctx.get("news_sentiment", 0.0), 0.0)

    if df is None or len(df) < 80:
        return None

    last_idx = len(df) - 1
    prev_idx = _STATE["last_idx_by_symbol"].get(symbol, -10**9)
    if (last_idx - prev_idx) < _COOLDOWN_BARS:
        _dbg(symbol, tf, "cooldown", {"last_idx": last_idx, "prev_idx": prev_idx})
        return None

    # Basic price
    price = _safe(df["close"].iloc[-1])
    if price <= 0:
        return None

    # Liquidity gate (dynamic, major-aware, hot-aware)
    if not passes_liquidity_filter(df, symbol, ctx):
        return None

    hot = _is_hot(symbol)

    # Vol regime
    rv_ratio = _volatility_regime(df)
    if rv_ratio > RV_MAX:
        _dbg(symbol, tf, "too_crazy_for_st", {"rv_ratio": rv_ratio})
        return None
    if rv_ratio < RV_MIN:
        _dbg(symbol, tf, "too_dead_for_st", {"rv_ratio": rv_ratio})
        return None

    # ATR
    atr = _atr_last(df, 14)
    if atr <= 0:
        _dbg(symbol, tf, "atr_invalid", {"atr": atr})
        return None

    # EMAs for intraday trend structure
    c = df["close"].astype(float)
    ema9 = _ema(c, 9)
    ema21 = _ema(c, 21)
    ema50 = _ema(c, 50)

    e9 = _safe(ema9.iloc[-1], price)
    e21 = _safe(ema21.iloc[-1], price)
    e50 = _safe(ema50.iloc[-1], price)

    # HTF trend score combined
    trend_score_htf = _trend_numeric(t15, t1h, tmas)

    # EMA structure & slope (intraday backbone)
    slope9 = (e9 - _safe(ema9.iloc[-4], e9)) / max(1e-9, 4 * atr)
    slope21 = (e21 - _safe(ema21.iloc[-4], e21)) / max(1e-9, 4 * atr)

    # Relaxed a bit so we don't miss clear trends
    ema_stack_up = (e9 > e21 * 1.0003 and e21 > e50 * 1.0003)
    ema_stack_dn = (e9 < e21 * 0.9997 and e21 < e50 * 0.9997)

    # Supertrend
    st_df = _supertrend(df, period=11 if hot else 10, multiplier=3.2 if hot else 3.0)
    st_val = _safe(st_df["st"].iloc[-1], price)
    st_prev = _safe(st_df["st"].iloc[-2], st_val)
    st_dir = int(st_df["st_dir"].iloc[-1])
    st_dir_prev = int(st_df["st_dir"].iloc[-2])

    # Directional context from ST & HTF trend
    up_trend = (
        trend_score_htf > 0.24
        and ema_stack_up
        and slope9 > 0.008
        and slope21 >= -0.001
        and st_dir == 1
    )
    dn_trend = (
        trend_score_htf < -0.24
        and ema_stack_dn
        and slope9 < -0.008
        and slope21 <= 0.001
        and st_dir == -1
    )

    if not (up_trend or dn_trend):
        _dbg(
            symbol,
            tf,
            "trend_not_clear_for_supertrend",
            {
                "trend_score_htf": round(trend_score_htf, 3),
                "st_dir": st_dir,
                "ema_stack_up": ema_stack_up,
                "ema_stack_dn": ema_stack_dn,
                "slope9": round(slope9, 4),
                "slope21": round(slope21, 4),
            },
        )
        return None

    # ST slope over last bar in ATR units
    st_slope = (st_val - st_prev) / max(1e-9, atr)

    # Distance from ST in ATR units: avoid entries too far from line
    dist_st = price - st_val
    dist_st_atr = dist_st / max(1e-9, atr)

    # Candle micro-structure
    wb = _wick_body(df)
    body_ratio = wb["body_ratio"]
    o_last = wb["o"]
    c_last = wb["c"]

    # Flip entry logic
    flip_up = (st_dir == 1 and st_dir_prev == -1)
    flip_dn = (st_dir == -1 and st_dir_prev == 1)

    side: Optional[str] = None
    entry_mode = None  # "flip" or "retest"

    # Primary: fresh Supertrend flip in trend direction
    if up_trend and flip_up and body_ratio >= MIN_BODY_RATIO and c_last > o_last:
        side = "BUY"
        entry_mode = "flip"
    elif dn_trend and flip_dn and body_ratio >= MIN_BODY_RATIO and c_last < o_last:
        side = "SELL"
        entry_mode = "flip"

    # Secondary: retest of ST in established trend (no fresh flip on this bar)
    if side is None:
        if up_trend and st_dir == 1 and st_dir_prev == 1:
            # price retesting close to ST with a small continuation candle
            if 0.0 <= dist_st_atr <= ST_RETEST_MAX_DIST_ATR and c_last > o_last:
                side = "BUY"
                entry_mode = "retest"
        elif dn_trend and st_dir == -1 and st_dir_prev == -1:
            if -ST_RETEST_MAX_DIST_ATR <= dist_st_atr <= 0.0 and c_last < o_last:
                side = "SELL"
                entry_mode = "retest"

    if side is None:
        _dbg(
            symbol,
            tf,
            "no_flip_or_retest_in_trend_direction",
            {
                "st_dir": st_dir,
                "st_dir_prev": st_dir_prev,
                "trend_score_htf": round(trend_score_htf, 3),
                "dist_st_atr": round(dist_st_atr, 3),
                "body_ratio": round(body_ratio, 3),
            },
        )
        return None

    # Final distance sanity check – still avoid entries that are too extended from ST
    if side == "BUY":
        if dist_st_atr < 0:
            _dbg(symbol, tf, "price_below_st_for_buy", {"dist_st_atr": dist_st_atr})
            return None
        if dist_st_atr > ST_MAX_DIST_ATR:
            _dbg(symbol, tf, "price_too_far_from_st_buy", {"dist_st_atr": dist_st_atr})
            return None
    else:
        if dist_st_atr > 0:
            _dbg(symbol, tf, "price_above_st_for_sell", {"dist_st_atr": dist_st_atr})
            return None
        if dist_st_atr < -ST_MAX_DIST_ATR:
            _dbg(symbol, tf, "price_too_far_from_st_sell", {"dist_st_atr": dist_st_atr})
            return None

    # News alignment: we *prefer* alignment with macro sentiment
    ns = float(np.clip(news_sent, -1.0, 1.0))
    ns_align = ns if side == "BUY" else -ns

    # SL: just beyond ST line + small buffer
    if side == "BUY":
        sl = st_val - 0.25 * atr
    else:
        sl = st_val + 0.25 * atr

    risk = abs(price - sl)
    if risk <= 0:
        _dbg(symbol, tf, "invalid_risk", {"price": price, "sl": sl})
        return None

    # RR hint
    base_rr = 2.05 if hot else 1.9
    trend_boost = 0.25 * abs(trend_score_htf)
    rv_boost = (rv_ratio - 1.0) * 0.24
    rv_boost = float(np.clip(rv_boost, -0.22, 0.30))

    rr_target = base_rr + trend_boost + rv_boost
    rr_target = float(np.clip(rr_target, 1.7, 2.7))

    if side == "BUY":
        tp = price + rr_target * risk
    else:
        tp = price - rr_target * risk

    exp_move = abs(tp - price) / max(1e-9, price)
    if exp_move < min_move:
        _dbg(
            symbol,
            tf,
            "expected_move_too_small",
            {
                "exp_move": round(exp_move, 5),
                "min_move": min_move,
            },
        )
        return None

    # Confidence scoring
    trend_abs = min(1.0, abs(trend_score_htf))
    st_slope_abs = min(1.0, abs(st_slope) / 0.7)
    ema_stack_score = 1.0 if (ema_stack_up or ema_stack_dn) else 0.85
    dist_score = 1.0 - min(1.0, abs(dist_st_atr) / ST_MAX_DIST_ATR)  # prefer entries near ST
    vol_score = 1.0

    if rv_ratio > 1.9:
        vol_score = 0.82
    elif rv_ratio < 0.7:
        vol_score = 0.88

    news_scale = 1.0 + 0.10 * ns_align
    news_scale = float(np.clip(news_scale, 0.92, 1.10))

    # Flip entries get a tiny edge over retests
    entry_mode_boost = 1.0 if entry_mode == "flip" else 0.96

    base_conf = 0.60
    raw_conf = (
        base_conf
        + 0.19 * trend_abs
        + 0.18 * st_slope_abs
        + 0.16 * ema_stack_score
        + 0.14 * dist_score
    )

    raw_conf *= vol_score
    raw_conf *= news_scale
    raw_conf *= entry_mode_boost

    conf = raw_conf * w * max(0.72, recent_wr)
    conf = float(np.clip(conf, 0.0, 0.985))

    if conf < thr:
        _dbg(
            symbol,
            tf,
            "conf_below_threshold",
            {
                "conf": round(conf, 4),
                "thr": round(thr, 4),
                "trend_score_htf": round(trend_score_htf, 3),
                "st_slope": round(st_slope, 3),
                "dist_st_atr": round(dist_st_atr, 3),
                "entry_mode": entry_mode,
            },
        )
        return None

    # Accept signal, set cooldown
    _STATE["last_idx_by_symbol"][symbol] = last_idx

    # Entry style:
    entry = price
    entry_type = "limit"
    entry_stop = None
    prefer_limit = True

    if abs(dist_st_atr) < 0.35:
        # closer to line, wait for small continuation breakout
        h_last = _safe(df["high"].iloc[-1])
        l_last = _safe(df["low"].iloc[-1])
        buf = 0.08 * atr
        if side == "BUY":
            entry_stop = max(price, h_last + buf)
        else:
            entry_stop = min(price, l_last - buf)
        entry = entry_stop
        entry_type = "stop"
        prefer_limit = False

    # Management hints
    management = {
        "move_be_at_r": 1.0,
        "trail_activation_r": 1.35,
        "partial_tp_r": 1.0,
        "partial_size": 0.40,
        "time_stop_bars": 22,
    }

    # Fingerprint payload
    fingerprint = {
        "tier": "supertrend_trend_core",
        "ts_utc": datetime.utcnow().isoformat(),
        "side": side,
        "trend_score_htf": float(trend_score_htf),
        "st_dir": int(st_dir),
        "st_slope": float(st_slope),
        "dist_st_atr": float(dist_st_atr),
        "rv_ratio": float(rv_ratio),
        "ns_align": float(ns_align),
        "entry_mode": entry_mode,
    }

    rr_effective = abs((tp - price) / max(1e-9, risk))
    reason = (
        f"supertrend_adaptive side={side} "
        f"mode={entry_mode} trend_htf={trend_score_htf:.2f} st_dir={st_dir} "
        f"st_slope={st_slope:.2f} dist_st_atr={dist_st_atr:.2f} "
        f"rv={rv_ratio:.2f} rr_hint={rr_effective:.2f}"
    )

    try:
        print(
            f"[DEBUG] {NAME} {symbol} :: "
            + json.dumps(
                {
                    "agent": NAME,
                    "tf": tf,
                    "event": "signal",
                    "side": side,
                    "conf": round(conf, 4),
                    "entry": float(entry),
                    "sl": float(sl),
                    "tp": float(tp),
                    "trend_htf": round(trend_score_htf, 3),
                    "st_dir": int(st_dir),
                    "st_slope": round(st_slope, 3),
                    "dist_st_atr": round(dist_st_atr, 3),
                    "rv_ratio": round(rv_ratio, 3),
                    "news_sent": round(news_sent, 3),
                    "entry_mode": entry_mode,
                }
            )
        )
    except Exception:
        pass

    return {
        "agent": NAME,
        "timeframe": tf,
        "side": side,
        "confidence": float(conf),

        "entry": float(entry),
        "entry_type": entry_type,
        "entry_stop": float(entry_stop) if entry_stop is not None else None,
        "prefer_limit": bool(prefer_limit),
        "limit_ticks": 1,

        "sl_hint": float(sl),
        "tp_hint": float(tp),
        "sl": float(sl),
        "tp": float(tp),

        "management": management,
        "fingerprint": fingerprint,
        "reason": reason,
    }
