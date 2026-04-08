# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd

NAME = "apex_momentum_pump"

# ---------------------------------------------------------
# Tunable behavior flags / params (high-level)
# ---------------------------------------------------------
# These constants are the "character" of the agent.
# I’ve made them stricter than the old version to reduce
# dumb losses and late FOMO entries.
#
# - MAX_RISK_PCT:     max % distance from entry to SL
# - MAX_DIST_CLUSTER: max ATR distance from EMA(9/21) cluster
# - MAX_DIST_SLOW:    max ATR distance from EMA50
# - RR_RANGE:         min/max RR target
# - TIME_STOP_BARS:   hard timeout in 5m bars
MAX_RISK_PCT = 0.08          # was ~0.15 – **now much stricter**
MAX_DIST_CLUSTER_ATR = 0.9   # was 1.3 – must be closer to EMA cluster
MAX_DIST_SLOW_ATR = 3.0      # was 4.0 – avoid very stretched trends
RR_MIN = 1.8                 # was ~2.2 – less greedy
RR_MAX = 2.8                 # was up to 4.0 – cap the dream targets
TIME_STOP_BARS = 36          # was 60 – don’t let trades drag

# ---------------------------------------------------------
# Liquidity / context helpers
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
      1) ctx["min_vol_ratio"]
      2) ctx["min_vol_ratio_per_symbol"][symbol]
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
                pass

    # majors get softened band ~[0.20, 0.30]
    if symbol.upper() in MAJOR_SYMBOLS:
        softened = min(default_ratio, 0.30)
        return max(0.20, softened)

    return default_ratio


# ---------------------------------------------------------
# Lightweight state: per-symbol cooldown
# ---------------------------------------------------------
_STATE: Dict[str, Any] = {
    "last_idx_by_symbol": {},  # symbol -> last index used
}
_COOLDOWN_BARS = 1  # min bars between signals per symbol on same TF


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


def _dbg(symbol: str, tf: str, reason: str, extra: Optional[Dict[str, Any]] = None, event: str = "veto") -> None:
    """
    Debug logging that never breaks the agent.
    """
    try:
        payload = {"agent": NAME, "tf": tf, "event": event, "reason": reason}
        if extra:
            payload.update(extra)
        print(f"[DEBUG] {NAME} {symbol} :: " + json.dumps(payload))
    except Exception:
        pass


def _ema(series: pd.Series, span: int) -> pd.Series:
    if series is None or len(series) < max(3, span):
        return series.copy() if series is not None else pd.Series(dtype=float)
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


def _vol_ema(series: pd.Series, span: int = 30) -> float:
    if series is None or len(series) < max(3, span):
        return _safe(series.iloc[-1] if len(series) else np.nan, 0.0)
    return _safe(series.ewm(span=span, adjust=False).mean().iloc[-1], 0.0)


def _is_hot_symbol(symbol: str) -> bool:
    """
    Very rough meme / hyper-volatility detector.
    Used to slightly adjust thresholds.
    """
    toks = ["PEPE", "TRUMP", "DOGE", "SHIB", "FLOKI", "BONK", "MEME", "POPCAT", "WLFI", "1000PEPE"]
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
    is_hot = _is_hot_symbol(symbol)

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
    Map combined trend info into numeric score in [-1, 1].
    Positive => uptrend, negative => downtrend.
    """
    up_words = {"UP", "BULL", "LONG"}
    dn_words = {"DOWN", "BEAR", "SHORT"}

    def _one_score(s: str) -> float:
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

    scores = [
        _one_score(trend_15m),
        _one_score(trend_1h),
        _one_score(trend_hint),
    ]
    return float(np.clip(np.mean(scores), -1.0, 1.0))


def _wick_body_ratios(df: pd.DataFrame) -> Dict[str, float]:
    """
    Wick/body decomposition of the last candle.
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
        "upper_wick": upper,
        "lower_wick": lower,
        "wick_dom": max(upper, lower) / rng,
        "body_ratio": body / rng,
        "upper_ratio": upper / rng,
        "lower_ratio": lower / rng,
    }


def _volatility_regime(df: pd.DataFrame) -> float:
    """
    Realized vol ratio: short / long.
    About 1.0 => balanced, <0.5 dead, >2.5 wild.
    """
    c = df["close"].astype(float)
    r = c.pct_change()
    rv_s = _safe(r.rolling(10).std().iloc[-1], 0.0)
    rv_l = _safe(r.rolling(40).std().iloc[-1], 0.0)
    if rv_l <= 0:
        return 1.0
    val = rv_s / rv_l
    return float(np.clip(val, 0.2, 3.0))


def _trend_wave_metrics(close: pd.Series, atr: float) -> Dict[str, float]:
    """
    Evaluate trend 'wave' structure over the last N bars.
    We want:
      - a clear directional leg behind us
      - a shallow pullback
      - fresh turn back in the trend direction
    """
    out = {
        "leg_atr": 0.0,
        "pullback_atr": 0.0,
        "net_dir": 0.0,
    }

    if close is None or len(close) < 40 or atr <= 0:
        return out

    # last 20 bars
    tail = close.tail(20)
    if len(tail) < 20:
        return out

    # define reference low/high for the wave
    low_ref = float(tail.iloc[:10].min())
    high_ref = float(tail.iloc[:10].max())
    last = float(tail.iloc[-1])

    # net directional bias over last 20 bars
    net_ret = float((tail.iloc[-1] - tail.iloc[0]) / max(1e-9, tail.iloc[0]))

    # leg size in ATR
    leg_up_atr = (tail.max() - low_ref) / max(1e-9, atr)
    leg_dn_atr = (high_ref - tail.min()) / max(1e-9, atr)

    # recent pullback over last 5 bars vs prior extreme
    last5 = tail.iloc[-5:]
    pb_up = (last5.max() - last5.min()) / max(1e-9, atr)
    pb_dn = pb_up  # symmetrical magnitude only

    out["leg_atr"] = float(max(leg_up_atr, leg_dn_atr))
    out["pullback_atr"] = float(pb_up)
    out["net_dir"] = float(net_ret)
    return out


# ---------------------------------------------------------
# Main signal: Triple Moving Average Trend Rider
# ---------------------------------------------------------
def generate_signal(df: pd.DataFrame, symbol: str, ctx: Optional[Dict[str, Any]] = None):
    """
    TRIPLE MA TREND RIDER (No more scalp pump-chasing)

    Role:
      - Trade only in strong 15m/1h trend, confirmed by EMA(9/21/50) stack.
      - Wait for a trend wave, then a controlled pullback into the EMA cluster.
      - Enter when price re-aligns with the trend, aiming for multi-hour legs.

    Inputs:
      df   : 5m OHLCV
      ctx  : {
               timeframe: "5m",
               conf_threshold: float,
               min_expected_move: float,
               trend_15m, trend_1h, trend_hint,
               vol_class, news_sentiment, recent_wr, ...
             }

    Returns:
      dict or None.
    """
    ctx = ctx or {}

    tf = _safe_timeframe_from_context(ctx, default_tf="5m")
    thr = _safe(ctx.get("conf_threshold", 0.83), 0.83)
    # require at least ~2.5% expected move on underlying
    min_move = _safe(ctx.get("min_expected_move", 0.025), 0.025)
    w = _safe(ctx.get("weight", 1.0), 1.0)
    recent_wr = _safe(ctx.get("recent_wr", 1.0), 1.0)

    t15 = str(ctx.get("trend_15m", "SIDEWAYS")).upper()
    t1h = str(ctx.get("trend_1h", "SIDEWAYS")).upper()
    tmas = str(ctx.get("trend_hint", "SIDEWAYS")).upper()

    vol_class = str(ctx.get("vol_class", "")).upper()
    news_sentiment = _safe(ctx.get("news_sentiment", 0.0), 0.0)

    if df is None or len(df) < 120:
        return None

    last_idx = len(df) - 1
    prev_idx = _STATE["last_idx_by_symbol"].get(symbol, -10**9)
    if (last_idx - prev_idx) < _COOLDOWN_BARS:
        _dbg(symbol, tf, "cooldown", {"last_idx": last_idx, "prev_idx": prev_idx})
        return None

    price = _safe(df["close"].iloc[-1])
    h = _safe(df["high"].iloc[-1])
    l = _safe(df["low"].iloc[-1])
    rng = max(1e-12, h - l)
    if price <= 0 or rng <= 0:
        return None

    # Liquidity gate (dynamic, major-aware, hot-aware)
    if not passes_liquidity_filter(df, symbol, ctx):
        return None

    hot = _is_hot_symbol(symbol)

    atr = _atr_last(df, 14)
    if atr <= 0:
        _dbg(symbol, tf, "atr_invalid", {"atr": atr})
        return None

    rv_ratio = _volatility_regime(df)
    # avoid absolute chaos and sleep
    if rv_ratio > 2.9:
        _dbg(symbol, tf, "too_crazy_for_trend_rider", {"rv_ratio": rv_ratio})
        return None
    if rv_ratio < 0.35:
        _dbg(symbol, tf, "too_dead_for_trend_rider", {"rv_ratio": rv_ratio})
        return None

    close = df["close"].astype(float)
    ema_fast = _ema(close, 9)
    ema_mid = _ema(close, 21)
    ema_slow = _ema(close, 50)

    ef = _safe(ema_fast.iloc[-1], price)
    em = _safe(ema_mid.iloc[-1], price)
    es = _safe(ema_slow.iloc[-1], price)

    trend_score = _trend_numeric(t15, t1h, tmas)

    # EMA slopes
    slope9 = (ef - _safe(ema_fast.iloc[-5], ef)) / max(1e-9, 5 * atr)
    slope21 = (em - _safe(ema_mid.iloc[-5], em)) / max(1e-9, 5 * atr)

    # EMA spacing relative to price
    ema_spread_up = (ef - es) / max(1e-9, price)
    ema_spread_norm = float(np.clip(ema_spread_up / 0.015, -3.0, 3.0))

    ema_up_stack = (ef > em * 1.0005 and em > es * 1.0005)
    ema_dn_stack = (ef < em * 0.9995 and em < es * 0.9995)

    up_trend = (
        trend_score > 0.35
        and ema_up_stack
        and slope9 > 0.015
        and slope21 >= 0.0
        and ema_spread_norm > 0.4
    )
    dn_trend = (
        trend_score < -0.35
        and ema_dn_stack
        and slope9 < -0.015
        and slope21 <= 0.0
        and ema_spread_norm < -0.4
    )

    if not (up_trend or dn_trend):
        _dbg(
            symbol,
            tf,
            "trend_not_clear_for_trend_rider",
            {
                "trend_score": round(trend_score, 3),
                "ema_spread_norm": round(ema_spread_norm, 3),
                "slope9": round(slope9, 3),
                "slope21": round(slope21, 3),
            },
        )
        return None

    # Evaluate wave structure (leg + pullback)
    wave = _trend_wave_metrics(close, atr)
    leg_atr = wave["leg_atr"]
    pullback_atr = wave["pullback_atr"]
    net_dir = wave["net_dir"]

    # we want a decent leg (at least ~1–1.5 ATR) behind us
    if leg_atr < 1.0:
        _dbg(symbol, tf, "leg_too_small", {"leg_atr": round(leg_atr, 3)})
        return None

    # pullback must be controlled (not a full reversal)
    if pullback_atr > 2.2:
        _dbg(symbol, tf, "pullback_too_deep", {"pullback_atr": round(pullback_atr, 3)})
        return None

    # micro structure on trigger bar
    ratios = _wick_body_ratios(df)
    body_ratio = ratios["body_ratio"]
    upper_ratio = ratios["upper_ratio"]
    lower_ratio = ratios["lower_ratio"]
    wick_dom = ratios["wick_dom"]

    if body_ratio < 0.25:
        _dbg(symbol, tf, "body_too_small_for_trigger", {"body_ratio": body_ratio})
        return None

    if wick_dom > 0.85:
        _dbg(symbol, tf, "wick_dominated_trigger", {"wick_dom": wick_dom})
        return None

    # distance to EMA cluster (9/21)
    ema_cluster = 0.5 * (ef + em)
    dist_cluster_atr = abs(price - ema_cluster) / max(1e-9, atr)

    # ENTER CLOSER TO EMA CLUSTER (tighter than old version)
    if dist_cluster_atr > MAX_DIST_CLUSTER_ATR:
        _dbg(
            symbol,
            tf,
            "price_too_far_from_cluster",
            {"dist_cluster_atr": round(dist_cluster_atr, 3)},
        )
        return None

    # ensure we are not at immediate channel extremes vs EMA50
    ext_slow_atr = abs(price - es) / max(1e-9, atr)
    if ext_slow_atr > MAX_DIST_SLOW_ATR:
        _dbg(
            symbol,
            tf,
            "too_far_from_slow_ema",
            {"ext_slow_atr": round(ext_slow_atr, 3)},
        )
        return None

    # simple local pattern: check last 4 closes
    last4 = close.tail(4)
    if len(last4) < 4:
        return None

    side: Optional[str] = None

    if up_trend:
        # we want a small pullback then a fresh higher close
        cond_pullback_ok = (last4.iloc[-3] >= last4.iloc[-4]) and (last4.iloc[-2] <= last4.iloc[-3])
        cond_break = (last4.iloc[-1] > last4.iloc[-2]) and (price > ema_cluster) and (price > em)
        if cond_pullback_ok and cond_break and net_dir >= 0:
            side = "BUY"
    if dn_trend and side is None:
        cond_pullback_ok = (last4.iloc[-3] <= last4.iloc[-4]) and (last4.iloc[-2] >= last4.iloc[-3])
        cond_break = (last4.iloc[-1] < last4.iloc[-2]) and (price < ema_cluster) and (price < em)
        if cond_pullback_ok and cond_break and net_dir <= 0:
            side = "SELL"

    if side is None:
        _dbg(
            symbol,
            tf,
            "no_valid_wave_trigger",
            {
                "leg_atr": round(leg_atr, 3),
                "pullback_atr": round(pullback_atr, 3),
                "net_dir": round(net_dir, 4),
            },
        )
        return None

    # Swing levels for SL
    swing_look = 18
    recent_hi = _safe(df["high"].iloc[-swing_look:].max(), h)
    recent_lo = _safe(df["low"].iloc[-swing_look:].min(), l)

    if side == "BUY":
        sl_candidates = [
            price - 1.6 * atr,
            em - 1.0 * atr,
            recent_lo - 0.5 * atr,
        ]
        sl = min(sl_candidates)
    else:
        sl_candidates = [
            price + 1.6 * atr,
            em + 1.0 * atr,
            recent_hi + 0.5 * atr,
        ]
        sl = max(sl_candidates)

    risk = abs(price - sl)
    if risk <= 0:
        _dbg(symbol, tf, "invalid_risk", {"price": price, "sl": sl})
        return None

    # guard on % risk – **tightened** to MAX_RISK_PCT
    risk_pct = risk / max(1e-9, price)
    if risk_pct > MAX_RISK_PCT:
        _dbg(symbol, tf, "risk_too_large_pct", {"risk_pct": round(risk_pct, 4)})
        return None

    # TP based on R:R and trend quality (less greedy than old)
    trend_abs = min(1.0, abs(trend_score))
    leg_score = min(1.0, leg_atr / 2.0)
    cluster_tight = max(0.0, 1.0 - dist_cluster_atr / MAX_DIST_CLUSTER_ATR)

    base_rr = 2.0 if hot else 1.8
    rr_bonus = 0.32 * trend_abs + 0.22 * leg_score + 0.16 * cluster_tight
    rr_target = float(np.clip(base_rr + rr_bonus, RR_MIN, RR_MAX))

    if side == "BUY":
        tp = price + rr_target * risk
    else:
        tp = price - rr_target * risk

    expected_move = abs(tp - price) / max(1e-9, price)
    if expected_move < min_move:
        _dbg(
            symbol,
            tf,
            "expected_move_small",
            {
                "expected_move": round(expected_move, 4),
                "min_move": min_move,
            },
        )
        return None

    # Confidence scoring
    vol_reg = 1.0
    if rv_ratio > 2.2:
        vol_reg = 0.85
    elif rv_ratio < 0.7:
        vol_reg = 0.9

    # vol_class preference
    if vol_class == "HIGH":
        vol_class_score = 1.0
    elif vol_class == "MED":
        vol_class_score = 0.85
    elif vol_class == "LOW":
        vol_class_score = 0.45
    else:
        vol_class_score = 0.65
    vol_score = 0.5 * vol_reg + 0.5 * vol_class_score

    # News alignment
    ns = float(np.clip(news_sentiment, -1.0, 1.0))
    ns_align = ns if side == "BUY" else -ns
    news_scale = float(np.clip(1.0 + 0.12 * ns_align, 0.88, 1.12))

    struct_score = max(0.0, 1.0 - abs(dist_cluster_atr) / MAX_DIST_CLUSTER_ATR)
    body_score = min(1.0, body_ratio / 0.7)

    base_conf = 0.68
    raw_conf = (
        base_conf
        + 0.18 * trend_abs
        + 0.16 * leg_score
        + 0.14 * struct_score
        + 0.12 * body_score
        + 0.10 * vol_score
    )

    raw_conf *= news_scale

    conf = raw_conf * w * max(0.65, recent_wr)
    conf = float(np.clip(conf, 0.0, 0.99))

    if conf < thr:
        _dbg(
            symbol,
            tf,
            "conf_below_threshold",
            {
                "conf": round(conf, 4),
                "thr": round(thr, 4),
                "trend_score": round(trend_score, 3),
                "leg_atr": round(leg_atr, 3),
                "pullback_atr": round(pullback_atr, 3),
            },
        )
        return None

    # Signal accepted; update cooldown
    _STATE["last_idx_by_symbol"][symbol] = last_idx

    # Entry: trend rider = just enter at market on trigger
    entry = price
    entry_type = "market"
    entry_stop = None
    prefer_limit = False

    rr_effective = abs((tp - price) / max(1e-9, risk))

    # Management hints – more protective than before
    management = {
        "move_be_at_r": 0.7,            # was ~1.0 – lock BE earlier
        "trail_activation_r": 1.35,     # was ~1.8 – trail sooner
        "partial_tp_r": 0.9,            # was 1.3 – bank profits earlier
        "partial_size": 0.45,
        "time_stop_bars": TIME_STOP_BARS,
    }

    fingerprint = {
        "agent": NAME,
        "tier": "triple_ma_trend_rider",
        "ts_utc": datetime.utcnow().isoformat(),
        "side": side,
        "timeframe": tf,
        "trend_score": float(trend_score),
        "ema_spread_norm": float(ema_spread_norm),
        "slope9": float(slope9),
        "slope21": float(slope21),
        "rv_ratio": float(rv_ratio),
        "leg_atr": float(leg_atr),
        "pullback_atr": float(pullback_atr),
        "net_dir": float(net_dir),
        "dist_cluster_atr": float(dist_cluster_atr),
        "ext_slow_atr": float(ext_slow_atr),
        "risk_pct": float(risk_pct),
        "body_ratio": float(body_ratio),
        "upper_ratio": float(upper_ratio),
        "lower_ratio": float(lower_ratio),
        "vol_class": vol_class,
        "news_sentiment": float(news_sentiment),
        "hot_symbol": bool(hot),
    }

    reason = (
        f"triple_ma_trend_rider side={side} "
        f"trend={trend_score:.2f} leg_atr={leg_atr:.2f} "
        f"pb_atr={pullback_atr:.2f} dist_cluster_atr={dist_cluster_atr:.2f} "
        f"rv={rv_ratio:.2f} rr={rr_effective:.2f}"
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
                    "trend_score": round(trend_score, 3),
                    "leg_atr": round(leg_atr, 3),
                    "pullback_atr": round(pullback_atr, 3),
                    "rv_ratio": round(rv_ratio, 3),
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
        "expected_move": float(expected_move),

        "management": management,
        "fingerprint": fingerprint,
        "reason": reason,
    }
