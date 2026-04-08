# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd

NAME = "apex_sweep_reversal"

# ---------------------------------------------------------
# Tunables – relaxed so agent actually fires on real breakouts
# ---------------------------------------------------------
CONF_DEFAULT = 0.78          # slightly lower than before
MIN_EXPECTED_MOVE = 0.018    # ~1.8% default expected move
RV_MAX = 3.5                 # allow a bit more manic regimes
RV_MIN = 0.30                # allow quieter regimes
VOL_MULT_NORMAL = 1.5        # min volume expansion (non-hot)
VOL_MULT_HOT = 1.9           # min volume expansion (hot memes)
BODY_MIN = 0.30              # minimum body/range for breakout candle
WICK_MAX = 0.65              # max wick domination for breakout side
RISK_PCT_MAX = 0.12          # 12% max percentage risk (unchanged)
LOOK_HOURS = 6.0             # breakout zone lookback window (in hours)

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


def _vol_ema(series: pd.Series, span: int = 30) -> float:
    if series is None or len(series) < max(3, span):
        return _safe(series.iloc[-1] if len(series) else 0.0)
    return _safe(series.ewm(span=span, adjust=False).mean().iloc[-1])


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
    lookback = min(len(vol_series), 288)  # ~24h on 5m if available
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
        "body_ratio": body / rng,
        "upper_ratio": upper / rng,
        "lower_ratio": lower / rng,
        "o": o,
        "c": c,
    }


def _volatility_regime(df: pd.DataFrame) -> float:
    """
    Realized vol ratio: short / long.
    ~1 => balanced; <0.3 very dead; >3.5 crazy.
    """
    c = df["close"].astype(float)
    r = c.pct_change()
    rv_s = _safe(r.rolling(10).std().iloc[-1], 0.0)
    rv_l = _safe(r.rolling(40).std().iloc[-1], 0.0)
    if rv_l <= 0:
        return 1.0
    val = rv_s / rv_l
    return float(np.clip(val, 0.2, 4.5))


def _bars_per_hour(tf: str) -> int:
    tf = (tf or "").lower()
    if tf.endswith("m"):
        try:
            minutes = int(tf[:-1])
        except Exception:
            minutes = 5
        return max(1, int(round(60.0 / max(1, minutes))))
    if tf.endswith("h"):
        return 1
    return 12


# ---------------------------------------------------------
# Main signal: Breakout Momentum Trend Agent
# ---------------------------------------------------------
def generate_signal(df: pd.DataFrame, symbol: str, ctx: Dict[str, Any] | None = None):
    """
    BREAKOUT MOMENTUM TREND AGENT (LuxAlgo-style volume confirmed breakout)

    Goal:
      - Enter when price breaks a major resistance/support with a
        decisive candle and real volume expansion, aligned with 15m/1h trend.
      - Designed to ride extended moves (not scalp), with ATR-based swing SL/TP.
      - Tuned to be *alive* on big moves, not a museum piece.
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
    vol_class = str(ctx.get("vol_class", "")).upper()
    news_sent = _safe(ctx.get("news_sentiment", 0.0), 0.0)

    if df is None or len(df) < 120:
        return None

    last_idx = len(df) - 1
    prev_idx = _STATE["last_idx_by_symbol"].get(symbol, -10**9)
    if (last_idx - prev_idx) < _COOLDOWN_BARS:
        _dbg(symbol, tf, "cooldown", {"last_idx": last_idx, "prev_idx": prev_idx})
        return None

    price = _safe(df["close"].iloc[-1])
    if price <= 0:
        return None

    # Liquidity guard
    if not passes_liquidity_filter(df, symbol, ctx):
        return None

    hot = _is_hot(symbol)

    # Volatility regime
    rv_ratio = _volatility_regime(df)
    if rv_ratio > RV_MAX:
        _dbg(symbol, tf, "rv_too_high_for_breakout", {"rv_ratio": rv_ratio})
        return None
    if rv_ratio < RV_MIN:
        _dbg(symbol, tf, "rv_too_low_for_breakout", {"rv_ratio": rv_ratio})
        return None

    # ATR & EMAs
    atr = _atr_last(df, 14)
    if atr <= 0:
        _dbg(symbol, tf, "atr_invalid", {"atr": atr})
        return None

    c = df["close"].astype(float)
    ema_fast = _ema(c, 9)
    ema_mid = _ema(c, 21)
    ema_slow = _ema(c, 50)
    e9 = _safe(ema_fast.iloc[-1], price)
    e21 = _safe(ema_mid.iloc[-1], price)
    e50 = _safe(ema_slow.iloc[-1], price)

    # HTF trend score combined
    trend_score_htf = _trend_numeric(t15, t1h, tmas)

    # 5m EMA structure & slope (slightly relaxed)
    slope9 = (e9 - _safe(ema_fast.iloc[-4], e9)) / max(1e-9, 4 * atr)
    slope21 = (e21 - _safe(ema_mid.iloc[-4], e21)) / max(1e-9, 4 * atr)

    ema_up = (e9 > e21 * 1.0003 and e21 > e50 * 1.0003)
    ema_dn = (e9 < e21 * 0.9997 and e21 < e50 * 0.9997)

    up_trend = (
        trend_score_htf > 0.25
        and ema_up
        and slope9 > 0.008
        and slope21 >= -0.001
    )
    dn_trend = (
        trend_score_htf < -0.25
        and ema_dn
        and slope9 < -0.008
        and slope21 <= 0.001
    )

    if not (up_trend or dn_trend):
        _dbg(
            symbol,
            tf,
            "trend_not_clear_for_breakout",
            {
                "trend_score_htf": round(trend_score_htf, 3),
                "slope9": round(slope9, 3),
                "slope21": round(slope21, 3),
            },
        )
        return None

    # Breakout zones: last ~LOOK_HOURS of highs/lows (timeframe-aware)
    bars_hour = _bars_per_hour(tf)
    L = max(30, int(round(LOOK_HOURS * bars_hour)))
    if len(df) <= L + 5:
        _dbg(symbol, tf, "not_enough_history_for_breakout_zone", {"len_df": len(df), "L": L})
        return None

    high = df["high"].astype(float)
    low = df["low"].astype(float)

    high_zone = float(high.iloc[-(L + 1):-1].max())
    low_zone = float(low.iloc[-(L + 1):-1].min())

    # Volume spike detection
    vol_col = None
    for candidate in ("quote_volume", "quoteVolume", "volume", "vol"):
        if candidate in df.columns:
            vol_col = candidate
            break
    if vol_col is None:
        _dbg(symbol, tf, "no_volume_for_breakout", {}, event="veto")
        return None

    vol_series = df[vol_col].astype(float)
    vol_now = _safe(vol_series.iloc[-1])
    vol_ema_val = _vol_ema(vol_series, 40 if not hot else 35)
    if vol_ema_val <= 0:
        _dbg(symbol, tf, "vol_ema_invalid", {"vol_ema": vol_ema_val})
        return None
    vol_mult = vol_now / max(1e-9, vol_ema_val)

    # Require proper volume expansion – but less extreme than before
    if not hot:
        if vol_mult < VOL_MULT_NORMAL:
            _dbg(symbol, tf, "volume_not_strong_enough", {"vol_mult": round(vol_mult, 3)})
            return None
    else:
        if vol_mult < VOL_MULT_HOT:
            _dbg(symbol, tf, "volume_not_strong_enough_hot", {"vol_mult": round(vol_mult, 3)})
            return None

    # Range compression pre-breakout (NR regime)
    o_last = _safe(df["open"].astype(float).iloc[-1])
    tr1 = (high - low).abs()
    tr2 = (high - c.shift(1)).abs()
    tr3 = (low - c.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    tr_long = _safe(tr.rolling(60).mean().iloc[-1], 0.0)
    tr_short = _safe(tr.rolling(10).mean().iloc[-1], 0.0)
    compression = 1.0
    if tr_short > 0 and tr_long > 0:
        # >1 => last 10 bars compressed vs last 60; we like 1.0–2.0
        compression = float(np.clip(tr_long / tr_short, 0.5, 3.0))

    # Candle micro-structure
    wb = _wick_body(df)
    body_ratio = wb["body_ratio"]
    upper_ratio = wb["upper_ratio"]
    lower_ratio = wb["lower_ratio"]

    # Slightly smaller buffer so we catch real breaks earlier
    eps = 0.0015 if not hot else 0.0025

    side: Optional[str] = None
    break_dist_atr = 0.0

    if up_trend:
        breakout_long = (
            price > high_zone * (1.0 + eps)
            and price > o_last
            and price > e21
            and body_ratio >= BODY_MIN
            and upper_ratio < WICK_MAX
        )
        if breakout_long:
            side = "BUY"
            break_dist_atr = (price - high_zone) / max(1e-9, atr)

    if dn_trend and side is None:
        breakout_short = (
            price < low_zone * (1.0 - eps)
            and price < o_last
            and price < e21
            and body_ratio >= BODY_MIN
            and lower_ratio < WICK_MAX
        )
        if breakout_short:
            side = "SELL"
            break_dist_atr = (low_zone - price) / max(1e-9, atr)

    if side is None:
        _dbg(
            symbol,
            tf,
            "no_valid_breakout",
            {
                "trend_score_htf": round(trend_score_htf, 3),
                "high_zone": high_zone,
                "low_zone": low_zone,
                "vol_mult": round(vol_mult, 3),
                "body_ratio": round(body_ratio, 3),
            },
        )
        return None

    break_dist_atr = float(np.clip(break_dist_atr, 0.0, 3.0))

    if body_ratio < BODY_MIN:
        _dbg(symbol, tf, "body_too_small_for_breakout", {"body_ratio": body_ratio})
        return None

    if wb["rng"] <= 0:
        return None

    # SL: Below/above breakout zone in ATR terms, so trades can breathe
    if side == "BUY":
        sl = min(price - 1.7 * atr, high_zone - 0.75 * atr)
    else:
        sl = max(price + 1.7 * atr, low_zone + 0.75 * atr)

    risk = abs(price - sl)
    if risk <= 0:
        _dbg(symbol, tf, "invalid_risk", {"price": price, "sl": sl})
        return None

    # Guard against insane percentage risk
    risk_pct = risk / max(1e-9, price)
    if risk_pct > RISK_PCT_MAX:
        _dbg(symbol, tf, "risk_too_large_pct", {"risk_pct": round(risk_pct, 4)})
        return None

    # Confidence scoring (trend + breakout structure + volume + compression)
    trend_abs = min(1.0, abs(trend_score_htf))
    vol_score = float(np.clip((vol_mult - 1.0) / 1.3, 0.0, 1.0))
    compression_score = float(np.clip((compression - 1.0) / 1.0, 0.0, 1.0))
    break_score = min(1.0, break_dist_atr / 1.1)

    # Vol regime penalty: avoid extreme manic/dead env
    rv_penalty = 1.0
    if rv_ratio > 2.4:
        rv_penalty = 0.87
    elif rv_ratio < 0.7:
        rv_penalty = 0.90

    # Sentiment alignment
    ns = float(np.clip(news_sent, -1.0, 1.0))
    ns_align = ns if side == "BUY" else -ns
    news_scale = float(np.clip(1.0 + 0.12 * ns_align, 0.9, 1.12))

    base_conf = 0.68
    raw_conf = (
        base_conf
        + 0.19 * trend_abs
        + 0.18 * vol_score
        + 0.14 * compression_score
        + 0.14 * break_score
        + 0.08 * min(1.0, body_ratio / 0.7)
    )
    raw_conf *= rv_penalty
    raw_conf *= news_scale

    conf = raw_conf * w * max(0.65, recent_wr)
    conf = float(np.clip(conf, 0.0, 0.99))

    if conf < thr:
        _dbg(symbol, tf, "conf_below_threshold", {"conf": round(conf, 4), "thr": thr})
        return None

    # Accept signal, set cooldown
    _STATE["last_idx_by_symbol"][symbol] = last_idx

    # TP: 2.0–3.8R depending on trend + volume
    base_rr = 2.4 if not hot else 2.7
    rr_bonus = 0.40 * trend_abs + 0.30 * vol_score
    rr_target = float(np.clip(base_rr + rr_bonus, 2.0, 3.8))

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

    # Management hints (engine still uses its hybrid SL/TP):
    management = {
        "move_be_at_r": 1.0,
        "trail_activation_r": 1.7,
        "partial_tp_r": 1.2,
        "partial_size": 0.40,
        "time_stop_bars": 24,
    }

    rr_effective = abs((tp - price) / max(1e-9, risk))

    # Fingerprint payload for engine (agent-local perspective)
    fingerprint = {
        "tier": "breakout_momentum_trend",
        "ts_utc": datetime.utcnow().isoformat(),
        "side": side,
        "timeframe": tf,
        "trend_score_htf": float(trend_score_htf),
        "vol_mult": float(vol_mult),
        "compression": float(compression),
        "break_dist_atr": float(break_dist_atr),
        "risk_pct": float(risk_pct),
        "rv_ratio": float(rv_ratio),
        "vol_class": vol_class,
        "hot_symbol": bool(hot),
    }

    reason = (
        f"breakout_momentum side={side} "
        f"trend={trend_score_htf:.2f} vol_mult={vol_mult:.2f} "
        f"compression={compression:.2f} break_atr={break_dist_atr:.2f} "
        f"rr={rr_effective:.2f}"
    )

    entry = price
    entry_type = "market"
    entry_stop = None
    prefer_limit = False

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
                    "trend": round(trend_score_htf, 3),
                    "vol_mult": round(vol_mult, 3),
                    "compression": round(compression, 3),
                    "break_dist_atr": round(break_dist_atr, 3),
                    "rv_ratio": round(rv_ratio, 3),
                    "news_sent": round(news_sent, 3),
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
        "entry_stop": entry_stop,
        "prefer_limit": prefer_limit,
        "limit_ticks": 1,

        "sl_hint": float(sl),
        "tp_hint": float(tp),
        "sl": float(sl),
        "tp": float(tp),

        "management": management,
        "fingerprint": fingerprint,
        "reason": reason,
    }
