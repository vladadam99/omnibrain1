# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd

NAME = "apex_vwap_pullback"

# --------------------------------------------------------------------
# Tunables – relaxed so this agent is not "dead"
# --------------------------------------------------------------------
CONF_DEFAULT = 0.75           # default confidence threshold if ctx doesn't override
MIN_EXPECTED_MOVE = 0.018     # ~1.8% default expected move (down from 3%)
TREND_BIAS_MIN = 0.18         # min |trend_score| for directional bias (was 0.20)
RISK_PCT_MAX = 0.12           # allow up to 12% price risk (was 10%)
WICK_DOM_MAX = 0.97           # if wick dominates more than this, skip candle

EDGE_POS_LONG = 0.68          # avg position in channel for long "edge" entries
EDGE_POS_SHORT = 0.32         # avg position in channel for short "edge" entries

# --------------------------------------------------------------------
# Liquidity / context helpers (shared pattern with other agents)
# --------------------------------------------------------------------
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
        per_symbol = ctx.get("min_vol_ratio_per_symbol")
        if isinstance(per_symbol, dict) and symbol in per_symbol:
            try:
                return float(per_symbol[symbol])
            except (TypeError, ValueError):
                pass

        if "min_vol_ratio" in ctx:
            try:
                return float(ctx["min_vol_ratio"])
            except (TypeError, ValueError):
                pass

    # majors get softened band ~[0.20, 0.30]
    if symbol.upper() in MAJOR_SYMBOLS:
        softened = min(default_ratio, 0.30)
        return max(0.20, softened)

    return default_ratio


# --------------------------------------------------------------------
# Lightweight state - just per-symbol cooldown
# --------------------------------------------------------------------
_STATE: Dict[str, Any] = {
    "last_idx_by_symbol": {},
}
_COOLDOWN_BARS = 1  # min bars between signals per symbol on same TF


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------
def _safe(x, d: float = 0.0) -> float:
    try:
        v = float(x)
        if not np.isfinite(v):
            return d
        return v
    except Exception:
        return d


def _dbg(symbol: str, tf: str, reason: str, extra: dict | None = None, event: str = "veto") -> None:
    """
    Debug logging - must never break the agent.
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
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))
    return tr.rolling(n).mean()


def _atr_last(df: pd.DataFrame, n: int = 14) -> float:
    s = _atr_series(df, n)
    if len(s) == 0:
        return 0.0
    return _safe(s.iloc[-1], 0.0)


def _vol_ema(series: pd.Series, span: int = 30) -> float:
    if series is None or len(series) < max(3, span):
        return _safe(series.iloc[-1] if len(series) else np.nan, 0.0)
    return _safe(series.ewm(span=span, adjust=False).mean().iloc[-1], 0.0)


def _tf_window_bars(tf: str) -> int:
    """
    Approximate bars to use for VWAP + regime calc based on timeframe.
    Kept for compatibility with other helpers if reused.
    """
    tf = (tf or "").lower()
    if tf.endswith("m"):
        try:
            minutes = int(tf[:-1])
        except Exception:
            minutes = 5
        # ~8h of history by default
        return max(60, int(8 * 60 / max(1, minutes)))
    if tf.endswith("h"):
        try:
            hours = int(tf[:-1])
        except Exception:
            hours = 1
        return max(40, 80)
    return 120


def _vwap_series(df: pd.DataFrame, window: int) -> pd.Series:
    """
    Rolling VWAP over the given window.
    Kept for compatibility though not core to Donchian logic.
    """
    px = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].astype(float)
    pv = px * vol
    cum_pv = pv.rolling(window=window, min_periods=3).sum()
    cum_vol = vol.rolling(window=window, min_periods=3).sum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    return vwap


def _wick_body_ratios(df: pd.DataFrame) -> dict:
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
    }


def _is_hot_symbol(symbol: str) -> bool:
    """
    Very rough "meme / high-spec" detector; used only to nudge parameters.
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
    Positive -> uptrend, negative -> downtrend.
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


# ----------------------------------------------------------------------
# Main TrendSurge signal (Donchian Ensemble Trend-Follower)
# ----------------------------------------------------------------------
def generate_signal(df: pd.DataFrame, symbol: str, ctx: Dict[str, Any] | None = None):
    """
    Donchian Ensemble Trend-Follower (TrendSurge variant):

      - Master TF: typically 5m (but works generically).
      - Uses multi-window Donchian channels (~4h, 8h, 24h equivalents).
      - Only trades in direction of combined 15m/1h trend.
      - Signals on decisive breakouts ABOVE/BELOW those channels,
        OR near the edge of the channel in the trend direction
        (fallback "edge trend entry").

    Compatible with existing OMNIBRAIN engine:
      - Returns side/action/confidence/sl_hint/tp_hint/expected_move/fingerprint.
    """
    ctx = ctx or {}

    tf = _safe_timeframe_from_context(ctx, default_tf="5m")
    # Loosened default threshold; can still be overridden via ctx["conf_threshold"]
    thr = _safe(ctx.get("conf_threshold", CONF_DEFAULT), CONF_DEFAULT)
    w = _safe(ctx.get("weight", 1.0), 1.0)
    # Lower default expected move so it can participate in more runs
    min_move = _safe(ctx.get("min_expected_move", MIN_EXPECTED_MOVE), MIN_EXPECTED_MOVE)
    recent_wr = _safe(ctx.get("recent_wr", 1.0), 1.0)

    t15 = str(ctx.get("trend_15m", "SIDEWAYS")).upper()
    t1h = str(ctx.get("trend_1h", "SIDEWAYS")).upper()
    tmas = str(ctx.get("trend_hint", "SIDEWAYS")).upper()

    vol_class = str(ctx.get("vol_class", "")).upper()  # HIGH / MED / LOW / ""
    news_sentiment = _safe(ctx.get("news_sentiment", 0.0), 0.0)  # [-1, 1]

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

    # --- Liquidity/volume sanity ---
    if not passes_liquidity_filter(df, symbol, ctx):
        return None

    hot = _is_hot_symbol(symbol)

    # --- Core volatility regime / ATR ---
    atr = _atr_last(df, 14)
    if atr <= 0:
        _dbg(symbol, tf, "atr_invalid", {"atr": atr})
        return None

    # --- Donchian lookbacks ~ 4h, 8h, 24h in bars for this TF ---
    tf_l = tf.lower()
    bars_per_hour = 12  # default ~5m
    if tf_l.endswith("m"):
        try:
            minutes = int(tf_l[:-1])
        except Exception:
            minutes = 5
        bars_per_hour = max(1, int(round(60.0 / max(1, minutes))))
    elif tf_l.endswith("h"):
        # 1 bar per hour on hourly charts
        bars_per_hour = 1

    def _hours_to_bars(h: float) -> int:
        return max(10, int(round(h * bars_per_hour)))

    raw_lookbacks = [
        _hours_to_bars(4.0),   # ~4h
        _hours_to_bars(8.0),   # ~8h
        _hours_to_bars(24.0),  # ~1 day
    ]

    max_n = len(df) - 5
    lookbacks = [L for L in raw_lookbacks if L <= max_n]
    if len(lookbacks) < 1:
        _dbg(symbol, tf, "not_enough_history_for_donchian", {"len_df": len(df), "lookbacks": raw_lookbacks})
        return None

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    # --- Trend alignment based on HTF (15m/1h) ---
    trend_score = _trend_numeric(t15, t1h, tmas)
    long_bias = trend_score > TREND_BIAS_MIN
    short_bias = trend_score < -TREND_BIAS_MIN

    if not (long_bias or short_bias):
        _dbg(symbol, tf, "htf_trend_not_strong", {"trend_score": trend_score})
        return None

    # --- Donchian breakout + position-in-channel detection ---
    eps = 0.0015 if not hot else 0.0025  # small buffer

    hits_up = 0
    hits_dn = 0
    breakout_strength_up = 0.0
    breakout_strength_dn = 0.0
    pos_list = []

    for L in lookbacks:
        donch_high = high.rolling(L).max().iloc[-1]
        donch_low = low.rolling(L).min().iloc[-1]

        if not np.isfinite(donch_high) or not np.isfinite(donch_low):
            continue

        width = max(1e-9, donch_high - donch_low)
        pos = (price - donch_low) / width  # 0 near low, 1 near high
        pos_list.append(float(np.clip(pos, 0.0, 1.0)))

        # distance in ATR units from channel boundary
        dist_up_atr = (price - donch_high) / max(1e-9, atr)
        dist_dn_atr = (donch_low - price) / max(1e-9, atr)

        # Long breakout: close decisively above prior Donchian high
        if price > donch_high * (1.0 + eps):
            hits_up += 1
            breakout_strength_up += max(0.0, dist_up_atr)

        # Short breakout: close decisively below prior Donchian low
        if price < donch_low * (1.0 - eps):
            hits_dn += 1
            breakout_strength_dn += max(0.0, dist_dn_atr)

    if not pos_list:
        _dbg(symbol, tf, "no_valid_donchian_windows", {"lookbacks": lookbacks})
        return None

    pos_avg = float(np.clip(np.mean(pos_list), 0.0, 1.0))
    n_bases = max(1, len(lookbacks))

    side: Optional[str] = None
    breakout_hits = 0
    breakout_strength = 0.0

    # --- Primary: real breakout above/below channel ---
    if hits_up > 0 or hits_dn > 0:
        if n_bases >= 3:
            min_hits_required = 2
        else:
            min_hits_required = 1

        if long_bias and hits_up >= min_hits_required:
            side = "BUY"
            breakout_hits = hits_up
            breakout_strength = breakout_strength_up
        elif short_bias and hits_dn >= min_hits_required:
            side = "SELL"
            breakout_hits = hits_dn
            breakout_strength = breakout_strength_dn

    # --- Fallback: edge-of-channel trend entry ---
    if side is None:
        if long_bias and pos_avg >= EDGE_POS_LONG:
            side = "BUY"
            breakout_hits = 1
            edge_prox = (pos_avg - EDGE_POS_LONG) / max(1e-6, (1.0 - EDGE_POS_LONG))
            edge_prox = float(np.clip(edge_prox, 0.0, 1.0))
            breakout_strength = max(0.6, edge_prox + 0.6 * abs(trend_score))
            _dbg(
                symbol,
                tf,
                "edge_trend_entry_long",
                {"pos_avg": pos_avg, "trend_score": trend_score, "edge_prox": edge_prox},
                event="pass",
            )
        elif short_bias and pos_avg <= EDGE_POS_SHORT:
            side = "SELL"
            breakout_hits = 1
            edge_prox = (EDGE_POS_SHORT - pos_avg) / max(1e-6, EDGE_POS_SHORT)
            edge_prox = float(np.clip(edge_prox, 0.0, 1.0))
            breakout_strength = max(0.6, edge_prox + 0.6 * abs(trend_score))
            _dbg(
                symbol,
                tf,
                "edge_trend_entry_short",
                {"pos_avg": pos_avg, "trend_score": trend_score, "edge_prox": edge_prox},
                event="pass",
            )
        else:
            _dbg(
                symbol,
                tf,
                "no_donchian_breakout",
                {"hits_up": hits_up, "hits_dn": hits_dn, "lookbacks": lookbacks, "pos_avg": pos_avg},
            )
            return None

    # --- Candle sanity: avoid insane wick-only spikes on the entry candle ---
    ratios = _wick_body_ratios(df)
    wick_dom = ratios["wick_dom"]
    if wick_dom > WICK_DOM_MAX:
        _dbg(symbol, tf, "wick_too_extreme_for_entry", {"wick_dom": wick_dom})
        return None

    # --- Trend-rider SL/TP construction ---
    swing_look = max(20, min(len(df) // 4, _hours_to_bars(6.0)))
    recent_hi = _safe(df["high"].iloc[-swing_look:].max(), price)
    recent_lo = _safe(df["low"].iloc[-swing_look:].min(), price)

    if side == "BUY":
        sl_candidates = [
            price - 1.8 * atr,
            recent_lo - 0.6 * atr,
        ]
        sl = min(sl_candidates)
    else:
        sl_candidates = [
            price + 1.8 * atr,
            recent_hi + 0.6 * atr,
        ]
        sl = max(sl_candidates)

    risk = abs(price - sl)
    if risk <= 0:
        _dbg(symbol, tf, "bad_risk", {})
        return None

    risk_pct = risk / max(1e-9, price)
    if risk_pct > RISK_PCT_MAX:
        _dbg(symbol, tf, "risk_too_large_pct", {"risk_pct": round(risk_pct, 4)})
        return None

    # TP: multi-R target for trend riding (roughly 2.4-4.2R depending on trend/strength)
    hit_frac = breakout_hits / float(max(1, n_bases))
    strength_norm = float(np.clip(breakout_strength / float(max(1, breakout_hits)), 0.0, 3.0))

    trend_abs = min(1.0, abs(trend_score))
    rr_base = 2.9 if hot else 2.6
    rr_bonus = 0.5 * trend_abs + 0.4 * min(1.0, strength_norm / 1.8)
    rr_target = float(np.clip(rr_base + rr_bonus, 2.4, 4.2))

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
            {"expected_move": round(expected_move, 4), "min_move": min_move},
        )
        return None

    # --- Volatility / news influence for confidence ---
    if vol_class == "HIGH":
        vol_score = 1.0
    elif vol_class == "MED":
        vol_score = 0.8
    elif vol_class == "LOW":
        vol_score = 0.4
    else:
        vol_score = 0.6

    news_bonus = 0.0
    if news_sentiment != 0.0:
        if side == "BUY" and news_sentiment > 0:
            news_bonus = min(0.07, 0.05 * news_sentiment)
        elif side == "SELL" and news_sentiment < 0:
            news_bonus = min(0.07, -0.05 * news_sentiment)

    # --- Confidence scoring: trend strength + Donchian confirmation ---
    base_conf = 0.72
    raw_conf = (
        base_conf
        + 0.18 * trend_abs
        + 0.16 * hit_frac
        + 0.12 * min(1.0, strength_norm / 1.8)
        + 0.08 * vol_score
        + news_bonus
    )

    # Factor in agent weight + recent winrate (never let recent_wr nuke it below 0.65)
    conf = raw_conf * w * max(0.65, recent_wr)
    conf = max(0.0, min(0.99, conf))

    if conf < thr:
        _dbg(symbol, tf, "conf_below_threshold", {"conf": round(conf, 4), "thr": round(thr, 4)})
        return None

    # Cooldown after we finally take a shot
    _STATE["last_idx_by_symbol"][symbol] = last_idx

    rr_effective = abs((tp - price) / max(1e-9, risk))

    reason = (
        f"donchian_trend side={side} "
        f"trend_score={trend_score:.2f} hits={breakout_hits}/{n_bases} "
        f"strength_norm={strength_norm:.2f} rr={rr_effective:.2f} "
        f"vol={vol_class or 'N/A'} news={news_sentiment:.2f}"
    )

    fingerprint = {
        "agent": NAME,
        "tier": "donchian_trend",
        "ts_utc": datetime.utcnow().isoformat(),
        "side": side,
        "timeframe": tf,
        "trend_score": float(trend_score),
        "donch_hits": int(breakout_hits),
        "donch_lookbacks_bars": list(map(int, lookbacks)),
        "breakout_strength_norm": float(strength_norm),
        "risk_pct": float(risk_pct),
        "rr_effective": float(rr_effective),
        "vol_class": vol_class,
        "news_sentiment": float(news_sentiment),
        "hot_symbol": bool(hot),
        "pos_avg": float(pos_avg),
    }

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
                    "entry": float(price),
                    "sl": float(sl),
                    "tp": float(tp),
                    "expected_move": round(expected_move, 4),
                    "trend_score": round(trend_score, 3),
                    "hits": breakout_hits,
                    "lookbacks": lookbacks,
                    "strength_norm": round(strength_norm, 3),
                    "rr_effective": round(rr_effective, 3),
                    "pos_avg": round(pos_avg, 3),
                    "vol_class": vol_class,
                    "news_sentiment": round(news_sentiment, 3),
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
        "entry": float(price),
        "entry_type": "market",
        "entry_stop": None,
        "prefer_limit": False,
        "sl_hint": float(sl),
        "tp_hint": float(tp),
        "sl": float(sl),
        "tp": float(tp),
        "expected_move": float(expected_move),
        "fingerprint": fingerprint,
        "reason": reason,
    }
