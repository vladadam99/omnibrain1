# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd

NAME = "apex_microburst"

# ---------------------------------------------------------
# Liquidity / context helpers (shared pattern)
# ---------------------------------------------------------
MAJOR_SYMBOLS = {
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
}

# Base ratios for this agent; these get softened automatically for majors
DEFAULT_MIN_VOL_RATIO = 0.50   # base before major softening
MIN_QUOTE_MAJOR = 120_000.0    # 120k USDT per bar for majors
MIN_QUOTE_ALT = 25_000.0       # 25k USDT per bar for non-majors


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
    Resolve min_vol_ratio with the following priority:
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

    # majors get a softer band [0.20, 0.30]
    if symbol.upper() in MAJOR_SYMBOLS:
        softened = min(default_ratio, 0.30)
        return max(0.20, softened)

    return default_ratio


# ---------------------------------------------------------
# State (per-symbol cooldown so we do not spam every candle)
# ---------------------------------------------------------
_STATE: Dict[str, Any] = {
    "last_idx_by_symbol": {},  # symbol -> last index used
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


def passes_liquidity_filter(
    df: pd.DataFrame,
    symbol: str,
    ctx: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Volume gate that:
      - Uses dynamic min_vol_ratio (context + majors softening)
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
    min_vol_ratio = _resolve_min_vol_ratio(symbol, ctx, DEFAULT_MIN_VOL_RATIO)

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
        },
        event="pass",
    )
    return True


def _is_hot(symbol: str) -> bool:
    """
    Simple meme/volatile detector - used to loosen some thresholds
    for known wild tickers.
    """
    toks = [
        "PEPE",
        "DOGE",
        "SHIB",
        "FLOKI",
        "BONK",
        "TRUMP",
        "MEME",
        "1000PEPE",
        "POPCAT",
        "WLFI",
    ]
    su = symbol.upper()
    return any(t in su for t in toks)


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


def _wick_body_ratios(df: pd.DataFrame) -> dict:
    """
    Last candle wick/body decomposition.
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
        "wick_dom": max(upper, lower) / rng if rng > 0 else 0.0,
    }


def _volatility_regime(df: pd.DataFrame) -> float:
    """
    Realized vol ratio: short / long.
    about 1 => balanced; <0.5 very dead; >2.5 crazy.
    """
    c = df["close"].astype(float)
    r = c.pct_change()
    rv_s = _safe(r.rolling(10).std().iloc[-1], 0.0)   # short
    rv_l = _safe(r.rolling(40).std().iloc[-1], 0.0)   # long
    if rv_l <= 0:
        return 1.0
    val = rv_s / rv_l
    return float(np.clip(val, 0.2, 3.0))


def _channel_breakout_metrics(df: pd.DataFrame, atr: float, is_hot: bool) -> Dict[str, float]:
    """
    Measure strength of a breakout from a recent price channel.

    We use:
      - prior channel high/low (last ~40 bars, excluding the most recent 3)
      - depth of close beyond channel in ATR units
      - volume multiple vs EMA

    Returns:
      {
        "up": bool,
        "down": bool,
        "depth_atr": float,
        "channel_range_atr": float,
        "vol_mult": float,
      }
    """
    out = {
        "up": False,
        "down": False,
        "depth_atr": 0.0,
        "channel_range_atr": 0.0,
        "vol_mult": 0.0,
    }
    if df is None or len(df) < 50 or atr <= 0:
        return out

    # Use a window to approximate recent range
    lookback = 40
    tail = df.tail(lookback + 5)
    if len(tail) < lookback + 3:
        return out

    high_tail = tail["high"].astype(float)
    low_tail = tail["low"].astype(float)
    close_tail = tail["close"].astype(float)
    vol_tail = tail["volume"].astype(float)

    # prior channel excludes the last 3 bars (so we don't include current breakout)
    prior_high = float(high_tail.iloc[:-3].max())
    prior_low = float(low_tail.iloc[:-3].min())
    last_close = float(close_tail.iloc[-1])
    last_high = float(high_tail.iloc[-1])
    last_low = float(low_tail.iloc[-1])

    channel_range_atr = (prior_high - prior_low) / max(1e-9, atr)

    vema = _vol_ema(vol_tail, 30 if not is_hot else 24)
    vnow = _safe(vol_tail.iloc[-1])
    vol_mult = vnow / max(1e-9, vema)

    # thresholds
    if is_hot:
        vol_thr = 1.25
        min_depth = 0.7
    else:
        vol_thr = 1.40
        min_depth = 0.8

    up_break = last_high > prior_high and last_close > prior_high
    dn_break = last_low < prior_low and last_close < prior_low

    depth_atr_up = (last_close - prior_high) / max(1e-9, atr)
    depth_atr_dn = (prior_low - last_close) / max(1e-9, atr)

    if up_break and depth_atr_up >= min_depth and vol_mult >= vol_thr:
        direction = "up"
        depth_atr = depth_atr_up
    elif dn_break and depth_atr_dn >= min_depth and vol_mult >= vol_thr:
        direction = "down"
        depth_atr = depth_atr_dn
    else:
        return out

    out[direction] = True
    out["depth_atr"] = float(depth_atr)
    out["channel_range_atr"] = float(channel_range_atr)
    out["vol_mult"] = float(vol_mult)
    return out


# ---------------------------------------------------------
# Main signal
# ---------------------------------------------------------
def generate_signal(df: pd.DataFrame, symbol: str, ctx: Dict[str, Any] | None = None):
    """
    BREAKOUT MOMENTUM TREND-RIDER:

    Purpose:
    - Join strong established trends only when price cleanly breaks out
      of a well-defined range, with volume + volatility expansion.
    - Avoid bottom-catching, mean reversion and late FOMO blow-offs.

    Inputs:
      df   : 5m OHLCV (main timeframe)
      ctx  : {
               timeframe: "5m",
               conf_threshold: float,
               min_expected_move: float,
               trend_15m, trend_1h, trend_hint,
               vol_class, news_sentiment, recent_wr, ...
             }

    Returns:
      dict with keys:
        side: "BUY"/"SELL"
        confidence: [0,1]
        entry, sl, tp, management hints
      or None if no trade.
    """
    ctx = ctx or {}
    tf = _safe_timeframe_from_context(ctx, default_tf="5m")
    thr = _safe(ctx.get("conf_threshold", 0.82), 0.82)
    min_move = _safe(ctx.get("min_expected_move", 0.02), 0.02)
    w = _safe(ctx.get("weight", 1.0), 1.0)
    recent_wr = _safe(ctx.get("recent_wr", 1.0), 1.0)  # agent-local WR if provided

    t15 = str(ctx.get("trend_15m", "SIDEWAYS")).upper()
    t1h = str(ctx.get("trend_1h", "SIDEWAYS")).upper()
    tmas = str(ctx.get("trend_hint", "SIDEWAYS")).upper()

    news_sent = _safe(ctx.get("news_sentiment", 0.0), 0.0)
    vol_class = str(ctx.get("vol_class", "")).upper()

    if df is None or len(df) < 100:
        return None

    last_idx = len(df) - 1
    prev_idx = _STATE["last_idx_by_symbol"].get(symbol, -10**9)
    if (last_idx - prev_idx) < _COOLDOWN_BARS:
        _dbg(symbol, tf, "cooldown", {"last_idx": last_idx, "prev_idx": prev_idx}, event="veto")
        return None

    # Basic price sanity
    price = _safe(df["close"].iloc[-1])
    h = _safe(df["high"].iloc[-1])
    l = _safe(df["low"].iloc[-1])
    rng = max(1e-12, h - l)
    if price <= 0 or rng <= 0:
        return None

    # Liquidity gate (dynamic & major-aware)
    if not passes_liquidity_filter(df, symbol, ctx):
        return None

    hot = _is_hot(symbol)

    # ATR & EMAs
    atr = _atr_last(df, 14)
    if atr <= 0:
        _dbg(symbol, tf, "atr_invalid", {"atr": atr}, event="veto")
        return None

    # Volatility regime
    rv_ratio = _volatility_regime(df)
    if rv_ratio > 3.0:
        _dbg(symbol, tf, "too_crazy_for_breakout", {"rv_ratio": rv_ratio}, event="veto")
        return None
    if rv_ratio < 0.35:
        _dbg(symbol, tf, "too_dead_for_breakout", {"rv_ratio": rv_ratio}, event="veto")
        return None

    c = df["close"].astype(float)
    ema_fast = _ema(c, 9)
    ema_mid = _ema(c, 21)
    ema_slow = _ema(c, 50)

    ef = _safe(ema_fast.iloc[-1], price)
    em = _safe(ema_mid.iloc[-1], price)
    es = _safe(ema_slow.iloc[-1], price)

    # HTF trend score + 5m EMA context
    trend_score_htf = _trend_numeric(t15, t1h, tmas)

    slope_fast = (ef - _safe(ema_fast.iloc[-5], ef)) / max(1e-9, 5 * atr)
    slope_mid = (em - _safe(ema_mid.iloc[-5], em)) / max(1e-9, 5 * atr)

    ema_spread = (ef - es) / max(1e-9, price)
    # 1.5% separation ~= spread_norm = 1.0
    ema_spread_norm = float(np.clip(ema_spread / 0.015, -3.0, 3.0))

    # Candle micro-structure
    ratios = _wick_body_ratios(df)
    body_ratio = ratios["body_ratio"]
    upper_ratio = ratios["upper_ratio"]
    lower_ratio = ratios["lower_ratio"]
    wick_dom = ratios["wick_dom"]

    if body_ratio < 0.35:
        _dbg(symbol, tf, "body_too_small_for_breakout", {"body_ratio": body_ratio}, event="veto")
        return None
    if wick_dom > 0.90:
        _dbg(symbol, tf, "wick_dominated_breakout_bar", {"wick_dom": wick_dom}, event="veto")
        return None

    # Strong directional trend filter
    up_trend = (
        trend_score_htf > 0.40
        and ef > em * 1.0005
        and em > es * 1.0005
        and ema_spread_norm > 0.5
        and slope_fast > 0.02
        and slope_mid >= 0.0
    )
    dn_trend = (
        trend_score_htf < -0.40
        and ef < em * 0.9995
        and em < es * 0.9995
        and ema_spread_norm < -0.5
        and slope_fast < -0.02
        and slope_mid <= 0.0
    )

    if not (up_trend or dn_trend):
        _dbg(
            symbol,
            tf,
            "trend_not_clear_for_breakout",
            {
                "trend_score_htf": round(trend_score_htf, 3),
                "ema_spread_norm": round(ema_spread_norm, 3),
                "slope_fast": round(slope_fast, 3),
                "slope_mid": round(slope_mid, 3),
            },
            event="veto",
        )
        return None

    # Avoid entries when price is absurdly far from EMA21
    dist_mid_atr = abs(price - em) / max(1e-9, atr)
    # Anything beyond ~3 ATR from EMA21 is usually late FOMO on fast alts
    if dist_mid_atr > 3.0:
        _dbg(
            symbol,
            tf,
            "too_far_from_mid_ema",
            {"dist_mid_atr": dist_mid_atr},
            event="veto",
        )
        return None

    # Avoid obvious blow-off bars: if this candle is way larger than recent ones, skip.
    recent_ranges = (df["high"].astype(float) - df["low"].astype(float)).tail(40)
    if len(recent_ranges) > 5:
        last_range = h - l
        max_prev_range = recent_ranges.iloc[:-1].max()
        # If current bar is > 1.6x any of the last 39 ranges, treat as exhaustion, not breakout.
        if last_range > max_prev_range * 1.6:
            _dbg(
                symbol,
                tf,
                "blowoff_bar_skip",
                {"last_range": last_range, "max_prev_range": max_prev_range},
                event="veto",
            )
            return None

    # Channel breakout metrics
    breakout = _channel_breakout_metrics(df, atr, hot)
    if not (breakout["up"] or breakout["down"]):
        _dbg(symbol, tf, "no_channel_breakout", {}, event="veto")
        return None

    side: Optional[str] = None
    if breakout["up"] and up_trend:
        side = "BUY"
    elif breakout["down"] and dn_trend:
        side = "SELL"
    else:
        _dbg(
            symbol,
            tf,
            "breakout_not_aligned_with_trend",
            {
                "trend_score_htf": round(trend_score_htf, 3),
                "break_up": breakout["up"],
                "break_down": breakout["down"],
            },
            event="veto",
        )
        return None

    depth_atr = breakout["depth_atr"]
    channel_range_atr = breakout["channel_range_atr"]
    vol_mult = breakout["vol_mult"]

    # Filter unrealistic breakouts
    if depth_atr < 0.8:
        _dbg(symbol, tf, "breakout_too_shallow", {"depth_atr": depth_atr}, event="veto")
        return None
    if depth_atr > 4.0:
        _dbg(symbol, tf, "breakout_too_deep", {"depth_atr": depth_atr}, event="veto")
        return None

    if channel_range_atr < 1.0:
        _dbg(
            symbol,
            tf,
            "channel_too_narrow",
            {"channel_range_atr": channel_range_atr},
            event="veto",
        )
        return None

    # Micro confirmation: last few bars should show continuation in breakout direction
    tail = df.tail(6)
    c_tail = tail["close"].astype(float)
    v_tail = tail["volume"].astype(float)
    r1 = _safe(c_tail.pct_change().iloc[-1])
    r3 = _safe(c_tail.pct_change(3).iloc[-1])
    vema_tail = _vol_ema(v_tail, 20)
    vnow_tail = _safe(v_tail.iloc[-1])
    vol_mult_tail = vnow_tail / max(1e-9, vema_tail)

    micro_dir = np.sign(c_tail.diff().iloc[-3:]).sum()
    micro_score = 0.0

    if side == "BUY":
        if micro_dir <= 0:
            _dbg(symbol, tf, "micro_dir_not_up", {"micro_dir": float(micro_dir)}, event="veto")
            return None
        if r1 <= 0:
            _dbg(symbol, tf, "no_up_impulse_on_bar", {"r1": r1}, event="veto")
            return None
        micro_score = 0.4 + 0.2 * min(1.5, r3 / max(1e-6, 0.01)) + 0.2 * min(2.0, vol_mult_tail / 1.4)
    else:
        if micro_dir >= 0:
            _dbg(symbol, tf, "micro_dir_not_down", {"micro_dir": float(micro_dir)}, event="veto")
            return None
        if r1 >= 0:
            _dbg(symbol, tf, "no_down_impulse_on_bar", {"r1": r1}, event="veto")
            return None
        micro_score = 0.4 + 0.2 * min(1.5, -r3 / max(1e-6, 0.01)) + 0.2 * min(2.0, vol_mult_tail / 1.4)

    micro_score = float(np.clip(micro_score / 2.0, 0.0, 1.0))

    # Swing levels for SL placement
    swing_look = 14
    recent_hi = _safe(df["high"].iloc[-swing_look:].max(), h)
    recent_lo = _safe(df["low"].iloc[-swing_look:].min(), l)

    if side == "BUY":
        # breakout_level approximated by backing out the ATR depth from current price
        breakout_level = price - depth_atr * atr
        sl_candidates = [
            breakout_level - 0.4 * atr,
            em - 1.0 * atr,
            recent_lo - 0.6 * atr,
        ]
        sl = min(sl_candidates)
    else:
        breakout_level = price + depth_atr * atr
        sl_candidates = [
            breakout_level + 0.4 * atr,
            em + 1.0 * atr,
            recent_hi + 0.6 * atr,
        ]
        sl = max(sl_candidates)

    risk = abs(price - sl)
    if risk <= 0:
        _dbg(symbol, tf, "invalid_risk", {"price": price, "sl": sl}, event="veto")
        return None

    risk_pct = risk / max(1e-9, price)
    # Hard cap: don't allow more than ~10% underlying move as SL on this agent.
    if risk_pct > 0.10:
        _dbg(symbol, tf, "risk_pct_too_large", {"risk_pct": risk_pct}, event="veto")
        return None

    # R:R target: trend-based extension
    # Slightly more conservative RR – aim for ~1.8–3.0R, not 3–4R
    base_rr = 2.2 if hot else 2.0
    trend_abs = min(1.0, abs(trend_score_htf))
    depth_score = min(1.0, depth_atr / 2.0)
    rr_bonus = 0.28 * trend_abs + 0.22 * depth_score
    rr_target = float(np.clip(base_rr + rr_bonus, 1.8, 3.0))

    if side == "BUY":
        tp = price + rr_target * risk
    else:
        tp = price - rr_target * risk

    expected_move = abs(tp - price) / max(1e-9, price)
    if expected_move < min_move:
        _dbg(
            symbol,
            tf,
            "expected_move_too_small",
            {"expected_move": expected_move, "min_move": min_move},
            event="veto",
        )
        return None

    # Vol regime + class blend
    if rv_ratio > 2.2:
        vol_reg = 0.8
    elif rv_ratio < 0.7:
        vol_reg = 0.9
    else:
        vol_reg = 1.0

    if vol_class == "HIGH":
        vol_class_score = 1.0
    elif vol_class == "MED":
        vol_class_score = 0.85
    elif vol_class == "LOW":
        vol_class_score = 0.45
    else:
        vol_class_score = 0.7

    vol_score = 0.5 * vol_reg + 0.5 * vol_class_score

    # News alignment
    ns = float(np.clip(news_sent, -1.0, 1.0))
    ns_align = ns if side == "BUY" else -ns
    news_scale = float(np.clip(1.0 + 0.12 * ns_align, 0.88, 1.12))

    # Structure: penalize if too far from EMA21
    struct_score = max(0.0, 1.0 - dist_mid_atr / 4.5)

    base_conf = 0.66
    raw_conf = (
        base_conf
        + 0.18 * trend_abs
        + 0.16 * depth_score
        + 0.14 * micro_score
        + 0.12 * struct_score
        + 0.10 * vol_score
    )

    raw_conf *= news_scale

    # incorporate agent weight and recent WR (if provided by Optimizer / engine)
    conf = raw_conf * w * max(0.70, recent_wr)
    conf = float(np.clip(conf, 0.0, 0.99))

    if conf < thr:
        _dbg(
            symbol,
            tf,
            "conf_below_threshold",
            {
                "conf": conf,
                "thr": thr,
                "trend_score_htf": trend_score_htf,
                "depth_atr": depth_atr,
                "micro_score": micro_score,
            },
            event="veto",
        )
        return None

    # Signal accepted; update cooldown
    _STATE["last_idx_by_symbol"][symbol] = last_idx

    # Breakout-style entry: stop above/below trigger bar
    buf = 0.10 * atr
    if side == "BUY":
        entry_stop = max(price, h + buf)
    else:
        entry_stop = min(price, l - buf)

    entry = entry_stop
    entry_type = "stop"
    prefer_limit = False

    rr_effective = abs((tp - price) / max(1e-9, risk))

    # Management hints: more defensive – lock BE earlier and don’t let losers run
    management = {
        "move_be_at_r": 0.8,
        "trail_activation_r": 1.4,
        "partial_tp_r": 1.0,
        "partial_size": 0.50,
        "time_stop_bars": 40,  # ~3.3h on 5m
    }

    # Fingerprint payload (agent-local perspective)
    fingerprint = {
        "tier": "breakout_momentum_trend",
        "ts_utc": datetime.utcnow().isoformat(),
        "side": side,
        "timeframe": tf,
        "trend_score_htf": float(trend_score_htf),
        "ema_spread_norm": float(ema_spread_norm),
        "slope_fast": float(slope_fast),
        "slope_mid": float(slope_mid),
        "rv_ratio": float(rv_ratio),
        "depth_atr": float(depth_atr),
        "channel_range_atr": float(channel_range_atr),
        "vol_mult": float(vol_mult),
        "micro_score": float(micro_score),
        "body_ratio": float(body_ratio),
        "upper_ratio": float(upper_ratio),
        "lower_ratio": float(lower_ratio),
        "dist_mid_atr": float(dist_mid_atr),
        "risk_pct": float(risk_pct),
        "vol_class": vol_class,
        "news_sentiment": float(news_sent),
        "hot_symbol": bool(hot),
    }

    reason = (
        f"breakout_momentum_trend side={side} "
        f"trend_htf={trend_score_htf:.2f} depth_atr={depth_atr:.2f} "
        f"channel_atr={channel_range_atr:.2f} micro={micro_score:.2f} "
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
                    "trend_htf": round(trend_score_htf, 3),
                    "depth_atr": round(depth_atr, 3),
                    "channel_atr": round(channel_range_atr, 3),
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
        "entry_stop": float(entry_stop),
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
