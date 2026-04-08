### generate_signal (agent)
```diff
--- 
+++ 
@@ -1,316 +1,234 @@
 def generate_signal(df5m: pd.DataFrame, symbol: str, ctx: dict):
-    """
-    VWAP Pullback (v2)
-      * Rejection at adaptive VWAP band (ATR-scaled)
-      * NEW: cross/retest mode so we don't miss strong snaps over VWAP
-      * EMA alignment + HTF filter
-      * Liquidity & volatility health gates
-      * Stop-confirmation by default; limit-first optional
-      * Agent-owned TP/SL + management hints
-    """
-    tf = ctx.get("timeframe", "5m")
-    thr = _safe_float(ctx.get("conf_threshold", 0.78), 0.78)
-    min_move = _safe_float(ctx.get("min_expected_move", 0.001), 0.001)
-    trend_master = (ctx.get("trend_hint", "SIDEWAYS") or "SIDEWAYS").upper()
-    t15 = (ctx.get("trend_15m", "SIDEWAYS") or "SIDEWAYS").upper()
-    t1h = (ctx.get("trend_1h", "SIDEWAYS") or "SIDEWAYS").upper()
-    weight = _safe_float(ctx.get("weight", 1.0), 1.0)
-    recent_wr = _safe_float(ctx.get("recent_wr", 1.0), 1.0)
-
+    try:
+        if 'loss_streak' in locals() and int(loss_streak) >= 2:
+            return None
+    except Exception:
+        pass
+    try:
+        close = df['close']
+        ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
+        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
+        if side == 'BUY' and (not entry > ema9 > ema21) or (side == 'SELL' and (not entry < ema9 < ema21)):
+            return None
+    except Exception:
+        pass
+    "\n    VWAP Pullback (v2)\n      * Rejection at adaptive VWAP band (ATR-scaled)\n      * NEW: cross/retest mode so we don't miss strong snaps over VWAP\n      * EMA alignment + HTF filter\n      * Liquidity & volatility health gates\n      * Stop-confirmation by default; limit-first optional\n      * Agent-owned TP/SL + management hints\n    "
+    tf = ctx.get('timeframe', '5m')
+    thr = _safe_float(ctx.get('conf_threshold', 0.78), 0.78)
+    min_move = _safe_float(ctx.get('min_expected_move', 0.001), 0.001)
+    trend_master = (ctx.get('trend_hint', 'SIDEWAYS') or 'SIDEWAYS').upper()
+    t15 = (ctx.get('trend_15m', 'SIDEWAYS') or 'SIDEWAYS').upper()
+    t1h = (ctx.get('trend_1h', 'SIDEWAYS') or 'SIDEWAYS').upper()
+    weight = _safe_float(ctx.get('weight', 1.0), 1.0)
+    recent_wr = _safe_float(ctx.get('recent_wr', 1.0), 1.0)
     is_memecoin = _is_high_vol_asset(symbol)
-
-    # Tunables
-    if is_memecoin:
-        only_win_mode = bool(ctx.get("only_win_mode", True))
-        rr_base       = _safe_float(ctx.get("rr", 1.9), 1.9)
-        min_wick_dom  = _safe_float(ctx.get("min_wick_dom", 0.33), 0.33)
-        min_body_ratio= _safe_float(ctx.get("min_body_ratio", 0.14), 0.14)
-        max_band_dist = _safe_float(ctx.get("max_band_dist", 1.30), 1.30)
-        min_band_dist = _safe_float(ctx.get("min_band_dist", 0.12), 0.12)
-        sl_atr_mult   = _safe_float(ctx.get("sl_atr_mult", 1.12), 1.12)
-        sl_band_floor = _safe_float(ctx.get("sl_band_floor", 0.42), 0.42)
-        use_stop_entry= bool(ctx.get("use_stop_entry", True))
-        stop_buffer   = _safe_float(ctx.get("stop_buffer_atr", 0.12), 0.12)
-        time_stop_bars= int(ctx.get("time_stop_bars", 8))
-        move_be_at_r  = _safe_float(ctx.get("move_be_at_r", 0.7), 0.7)
-        partial_tp_r  = _safe_float(ctx.get("partial_tp_r", 0.75), 0.75)
-        partial_size  = _safe_float(ctx.get("partial_size", 0.5), 0.5)
-        min_recent_wr = _safe_float(ctx.get("min_recent_wr", 0.52), 0.52)
-        min_ev_r      = _safe_float(ctx.get("min_ev_r", 0.16), 0.16)
-        min_quality   = _safe_float(ctx.get("min_quality", 0.72), 0.72)
-    else:
-        only_win_mode = bool(ctx.get("only_win_mode", True))
-        rr_base       = _safe_float(ctx.get("rr", 1.8), 1.8)
-        min_wick_dom  = _safe_float(ctx.get("min_wick_dom", 0.38), 0.38)
-        min_body_ratio= _safe_float(ctx.get("min_body_ratio", 0.16), 0.16)
-        max_band_dist = _safe_float(ctx.get("max_band_dist", 1.10), 1.10)
-        min_band_dist = _safe_float(ctx.get("min_band_dist", 0.16), 0.16)
-        sl_atr_mult   = _safe_float(ctx.get("sl_atr_mult", 1.00), 1.00)
-        sl_band_floor = _safe_float(ctx.get("sl_band_floor", 0.40), 0.40)
-        use_stop_entry= bool(ctx.get("use_stop_entry", True))
-        stop_buffer   = _safe_float(ctx.get("stop_buffer_atr", 0.10), 0.10)
-        time_stop_bars= int(ctx.get("time_stop_bars", 12))
-        move_be_at_r  = _safe_float(ctx.get("move_be_at_r", 0.8), 0.8)
-        partial_tp_r  = _safe_float(ctx.get("partial_tp_r", 1.0), 1.0)
-        partial_size  = _safe_float(ctx.get("partial_size", 0.5), 0.5)
-        min_recent_wr = _safe_float(ctx.get("min_recent_wr", 0.55), 0.55)
-        min_ev_r      = _safe_float(ctx.get("min_ev_r", 0.18), 0.18)
-        min_quality   = _safe_float(ctx.get("min_quality", 0.78), 0.78)
-
+    if is_memecoin:
+        only_win_mode = bool(ctx.get('only_win_mode', True))
+        rr_base = _safe_float(ctx.get('rr', 1.9), 1.9)
+        min_wick_dom = _safe_float(ctx.get('min_wick_dom', 0.33), 0.33)
+        min_body_ratio = _safe_float(ctx.get('min_body_ratio', 0.14), 0.14)
+        max_band_dist = _safe_float(ctx.get('max_band_dist', 1.3), 1.3)
+        min_band_dist = _safe_float(ctx.get('min_band_dist', 0.12), 0.12)
+        sl_atr_mult = _safe_float(ctx.get('sl_atr_mult', 1.12), 1.12)
+        sl_band_floor = _safe_float(ctx.get('sl_band_floor', 0.42), 0.42)
+        use_stop_entry = bool(ctx.get('use_stop_entry', True))
+        stop_buffer = _safe_float(ctx.get('stop_buffer_atr', 0.12), 0.12)
+        time_stop_bars = int(ctx.get('time_stop_bars', 8))
+        move_be_at_r = _safe_float(ctx.get('move_be_at_r', 0.7), 0.7)
+        partial_tp_r = _safe_float(ctx.get('partial_tp_r', 0.75), 0.75)
+        partial_size = _safe_float(ctx.get('partial_size', 0.5), 0.5)
+        min_recent_wr = _safe_float(ctx.get('min_recent_wr', 0.52), 0.52)
+        min_ev_r = _safe_float(ctx.get('min_ev_r', 0.16), 0.16)
+        min_quality = _safe_float(ctx.get('min_quality', 0.72), 0.72)
+    else:
+        only_win_mode = bool(ctx.get('only_win_mode', True))
+        rr_base = _safe_float(ctx.get('rr', 1.8), 1.8)
+        min_wick_dom = _safe_float(ctx.get('min_wick_dom', 0.38), 0.38)
+        min_body_ratio = _safe_float(ctx.get('min_body_ratio', 0.16), 0.16)
+        max_band_dist = _safe_float(ctx.get('max_band_dist', 1.1), 1.1)
+        min_band_dist = _safe_float(ctx.get('min_band_dist', 0.16), 0.16)
+        sl_atr_mult = _safe_float(ctx.get('sl_atr_mult', 1.0), 1.0)
+        sl_band_floor = _safe_float(ctx.get('sl_band_floor', 0.4), 0.4)
+        use_stop_entry = bool(ctx.get('use_stop_entry', True))
+        stop_buffer = _safe_float(ctx.get('stop_buffer_atr', 0.1), 0.1)
+        time_stop_bars = int(ctx.get('time_stop_bars', 12))
+        move_be_at_r = _safe_float(ctx.get('move_be_at_r', 0.8), 0.8)
+        partial_tp_r = _safe_float(ctx.get('partial_tp_r', 1.0), 1.0)
+        partial_size = _safe_float(ctx.get('partial_size', 0.5), 0.5)
+        min_recent_wr = _safe_float(ctx.get('min_recent_wr', 0.55), 0.55)
+        min_ev_r = _safe_float(ctx.get('min_ev_r', 0.18), 0.18)
+        min_quality = _safe_float(ctx.get('min_quality', 0.78), 0.78)
     if df5m is None or len(df5m) < 60:
         return None
-
     last_idx = len(df5m) - 1
-    prev_idx = _STATE["last_idx_by_symbol"].get(symbol, -10**9)
-    if (last_idx - prev_idx) < _COOLDOWN_BARS:
-        return None
-
-    price = _safe_float(df5m["close"].iloc[-1])
-    o     = _safe_float(df5m["open"].iloc[-1])
-    h     = _safe_float(df5m["high"].iloc[-1])
-    l     = _safe_float(df5m["low"].iloc[-1])
-    rng   = max(1e-12, h - l)
+    prev_idx = _STATE['last_idx_by_symbol'].get(symbol, -10 ** 9)
+    if last_idx - prev_idx < _COOLDOWN_BARS:
+        return None
+    price = _safe_float(df5m['close'].iloc[-1])
+    o = _safe_float(df5m['open'].iloc[-1])
+    h = _safe_float(df5m['high'].iloc[-1])
+    l = _safe_float(df5m['low'].iloc[-1])
+    rng = max(1e-12, h - l)
     body_ratio = abs(price - o) / rng if rng > 0 else 0.0
-
-    vol_now = _safe_float(df5m["volume"].iloc[-1])
-    vol_med = _safe_float(df5m["volume"].tail(30).median(), 0.0)
+    vol_now = _safe_float(df5m['volume'].iloc[-1])
+    vol_med = _safe_float(df5m['volume'].tail(30).median(), 0.0)
     if vol_med <= 0:
-        _dbg(symbol, tf, "vol_med_zero")
-        return None
-
-    atr_ctx = ctx.get("risk", {}).get("atr")
+        _dbg(symbol, tf, 'vol_med_zero')
+        return None
+    atr_ctx = ctx.get('risk', {}).get('atr')
     atr = _safe_float(atr_ctx, 0.0) or _atr(df5m, 14)
     if atr <= 0.0:
-        _dbg(symbol, tf, "atr_invalid", {"atr": atr})
-        return None
-
-    # Liquidity guard
-    min_vol_ratio = (0.40 if is_memecoin else 0.50) if only_win_mode else 0.35
+        _dbg(symbol, tf, 'atr_invalid', {'atr': atr})
+        return None
+    min_vol_ratio = (0.4 if is_memecoin else 0.5) if only_win_mode else 0.35
     if vol_now < min_vol_ratio * vol_med:
-        _dbg(symbol, tf, "low_liquidity", {"vol_now": vol_now, "vol_med": vol_med, "min_vol_ratio": min_vol_ratio})
-        return None
-
+        _dbg(symbol, tf, 'low_liquidity', {'vol_now': vol_now, 'vol_med': vol_med, 'min_vol_ratio': min_vol_ratio})
+        return None
     vwap = _vwap(df5m)
-
-    # Regime-adaptive band
-    rv = _safe_float(df5m["close"].pct_change().rolling(30).std().iloc[-1], 0.0)
-    if rv < 0.004:   k = 0.6
-    elif rv < 0.008: k = 0.9
-    else:            k = 1.2
+    rv = _safe_float(df5m['close'].pct_change().rolling(30).std().iloc[-1], 0.0)
+    if rv < 0.004:
+        k = 0.6
+    elif rv < 0.008:
+        k = 0.9
+    else:
+        k = 1.2
     band = k * atr
     if band <= 0:
-        _dbg(symbol, tf, "band_zero", {"k": k, "atr": atr})
-        return None
-
-    # EMA alignment
-    ema9, ema21 = _ema(df5m["close"], 9), _ema(df5m["close"], 21)
+        _dbg(symbol, tf, 'band_zero', {'k': k, 'atr': atr})
+        return None
+    ema9, ema21 = (_ema(df5m['close'], 9), _ema(df5m['close'], 21))
     if is_memecoin:
         ema_up = price > ema9
         ema_dn = price < ema9
     else:
         ema_up = price > ema9 > ema21
         ema_dn = price < ema9 < ema21
-
-    # Wick anatomy
     lower_wick = max(0.0, min(o, price) - l)
     upper_wick = max(0.0, h - max(o, price))
     wick_dom_buy = lower_wick / rng if rng > 0 else 0.0
     wick_dom_sell = upper_wick / rng if rng > 0 else 0.0
-
-    # Distance from VWAP
-    dist = abs(price - vwap) / max(1e-9, band)
+    dist = abs(price - vwap) / max(1e-09, band)
     if dist < min_band_dist or dist > max_band_dist:
-        _dbg(symbol, tf, "dist_outside_band", {"dist": dist, "min": min_band_dist, "max": max_band_dist})
-        return None
-
-    # HTF alignment (relaxed for memes)
-    if is_memecoin:
-        buy_trend_ok = trend_master != "DOWN" and (t15 != "DOWN" or t1h != "DOWN")
-        sell_trend_ok = trend_master != "UP" and (t15 != "UP" or t1h != "UP")
-    else:
-        buy_trend_ok = trend_master == "UP" and t15 != "DOWN" and t1h != "DOWN"
-        sell_trend_ok = trend_master == "DOWN" and t15 != "UP" and t1h != "UP"
-
+        _dbg(symbol, tf, 'dist_outside_band', {'dist': dist, 'min': min_band_dist, 'max': max_band_dist})
+        return None
+    if is_memecoin:
+        buy_trend_ok = trend_master != 'DOWN' and (t15 != 'DOWN' or t1h != 'DOWN')
+        sell_trend_ok = trend_master != 'UP' and (t15 != 'UP' or t1h != 'UP')
+    else:
+        buy_trend_ok = trend_master == 'UP' and t15 != 'DOWN' and (t1h != 'DOWN')
+        sell_trend_ok = trend_master == 'DOWN' and t15 != 'UP' and (t1h != 'UP')
     side = None
     mode = None
-
-    # ---------- Mode 1: Rejection (original) ----------
-    tap_th  = 0.25 if is_memecoin else 0.20
+    tap_th = 0.25 if is_memecoin else 0.2
     clos_th = 0.18 if is_memecoin else 0.15
-
     if side is None and buy_trend_ok and ema_up:
-        if (l <= vwap - tap_th * band) and (price >= vwap - clos_th * band):
-            if (wick_dom_buy >= min_wick_dom) and (body_ratio >= min_body_ratio):
-                side = "BUY"; mode = "rejection"
-
+        if l <= vwap - tap_th * band and price >= vwap - clos_th * band:
+            if wick_dom_buy >= min_wick_dom and body_ratio >= min_body_ratio:
+                side = 'BUY'
+                mode = 'rejection'
     if side is None and sell_trend_ok and ema_dn:
-        if (h >= vwap + tap_th * band) and (price <= vwap + clos_th * band):
-            if (wick_dom_sell >= min_wick_dom) and (body_ratio >= min_body_ratio):
-                side = "SELL"; mode = "rejection"
-
-    # ---------- Mode 2: Cross/Retest (new) ----------
-    # If we closed across VWAP with decent body, accept with stop confirmation.
+        if h >= vwap + tap_th * band and price <= vwap + clos_th * band:
+            if wick_dom_sell >= min_wick_dom and body_ratio >= min_body_ratio:
+                side = 'SELL'
+                mode = 'rejection'
     cross_body = body_ratio >= (0.28 if is_memecoin else 0.26)
-    crossed_up = (price > vwap) and (o < vwap)
-    crossed_dn = (price < vwap) and (o > vwap)
-
+    crossed_up = price > vwap and o < vwap
+    crossed_dn = price < vwap and o > vwap
     if side is None and buy_trend_ok and ema_up and crossed_up and cross_body:
-        side = "BUY"; mode = "cross"
+        side = 'BUY'
+        mode = 'cross'
     if side is None and sell_trend_ok and ema_dn and crossed_dn and cross_body:
-        side = "SELL"; mode = "cross"
-
+        side = 'SELL'
+        mode = 'cross'
     if side is None:
-        _dbg(symbol, tf, "no_signal", {
-            "dist": dist, "ema_up": bool(ema_up), "ema_dn": bool(ema_dn),
-            "buy_ok": bool(buy_trend_ok), "sell_ok": bool(sell_trend_ok),
-            "wick_buy": wick_dom_buy, "wick_sell": wick_dom_sell, "body": body_ratio
-        })
-        return None
-
-    # ----- SL/TP sizing: agent-owned (structure + ATR + RR base) -----
-    risk_abs = max(sl_atr_mult * atr, 0.40 * band)  # keep a floor from band
-    sl_struct = (l - 0.15 * atr) if side == "BUY" else (h + 0.15 * atr)
-    sl = max(sl_struct, price - risk_abs) if side == "BUY" else min(sl_struct, price + risk_abs)
-    if side == "BUY": sl = min(sl, price - 0.6 * risk_abs)
-    else:             sl = max(sl, price + 0.6 * risk_abs)
-
+        _dbg(symbol, tf, 'no_signal', {'dist': dist, 'ema_up': bool(ema_up), 'ema_dn': bool(ema_dn), 'buy_ok': bool(buy_trend_ok), 'sell_ok': bool(sell_trend_ok), 'wick_buy': wick_dom_buy, 'wick_sell': wick_dom_sell, 'body': body_ratio})
+        return None
+    risk_abs = max(sl_atr_mult * atr, 0.4 * band)
+    sl_struct = l - 0.15 * atr if side == 'BUY' else h + 0.15 * atr
+    sl = max(sl_struct, price - risk_abs) if side == 'BUY' else min(sl_struct, price + risk_abs)
+    if side == 'BUY':
+        sl = min(sl, price - 0.6 * risk_abs)
+    else:
+        sl = max(sl, price + 0.6 * risk_abs)
     risk = abs(price - sl)
     if risk <= 0:
-        _dbg(symbol, tf, "risk_zero")
-        return None
-
-    tp_rr  = price + rr_base * risk if side == "BUY" else price - rr_base * risk
+        _dbg(symbol, tf, 'risk_zero')
+        return None
+    tp_rr = price + rr_base * risk if side == 'BUY' else price - rr_base * risk
     look_ext = 8
-    swing_hi = _safe_float(df5m["high"].iloc[-look_ext:].max(), 0.0)
-    swing_lo = _safe_float(df5m["low"].iloc[-look_ext:].min(), 0.0)
+    swing_hi = _safe_float(df5m['high'].iloc[-look_ext:].max(), 0.0)
+    swing_lo = _safe_float(df5m['low'].iloc[-look_ext:].min(), 0.0)
     impulse = abs(swing_hi - swing_lo)
-    tp_ext = price + 0.9 * impulse if side == "BUY" else price - 0.9 * impulse
-    mult = 2.0 if rv < 0.006 else (1.6 if rv < 0.012 else 1.3)
-    tp_atr = price + mult * atr if side == "BUY" else price - mult * atr
-
-    tp_candidate = min(tp_rr, tp_ext, tp_atr) if side == "BUY" else max(tp_rr, tp_ext, tp_atr)
-    RR_MIN = 1.55 if is_memecoin else 1.70
+    tp_ext = price + 0.9 * impulse if side == 'BUY' else price - 0.9 * impulse
+    mult = 2.0 if rv < 0.006 else 1.6 if rv < 0.012 else 1.3
+    tp_atr = price + mult * atr if side == 'BUY' else price - mult * atr
+    tp_candidate = min(tp_rr, tp_ext, tp_atr) if side == 'BUY' else max(tp_rr, tp_ext, tp_atr)
+    RR_MIN = 1.55 if is_memecoin else 1.7
     rr_eff = abs((tp_candidate - price) / max(1e-12, risk))
-    tp = (price + RR_MIN * risk) if (side == "BUY" and rr_eff < RR_MIN) else \
-         (price - RR_MIN * risk) if (side == "SELL" and rr_eff < RR_MIN) else tp_candidate
-
-    exp_move = abs(tp - price) / max(1e-9, price)
+    tp = price + RR_MIN * risk if side == 'BUY' and rr_eff < RR_MIN else price - RR_MIN * risk if side == 'SELL' and rr_eff < RR_MIN else tp_candidate
+    exp_move = abs(tp - price) / max(1e-09, price)
     if exp_move < min_move or rv > 0.035:
-        _dbg(symbol, tf, "exp_move_or_rv_veto", {"exp_move": exp_move, "min_move": min_move, "rv": rv})
-        return None
-
-    # ----- Confidence + EV/quality gates -----
+        _dbg(symbol, tf, 'exp_move_or_rv_veto', {'exp_move': exp_move, 'min_move': min_move, 'rv': rv})
+        return None
     proximity = _clamp((1.6 - min(1.6, dist)) / 1.6, 0.0, 1.0)
-    wick_dom = (wick_dom_buy if side == "BUY" else wick_dom_sell)
-    htf_bonus = 0.10
+    wick_dom = wick_dom_buy if side == 'BUY' else wick_dom_sell
+    htf_bonus = 0.1
     vol_bonus = 0.05 if vol_now >= vol_med else 0.0
-    mode_bonus = 0.04 if mode == "cross" else 0.0
-    raw_conf = 0.58 + 0.22 * proximity + 0.12 * _clamp((wick_dom - 0.20) / 0.60, 0.0, 1.0) \
-               + htf_bonus + vol_bonus + mode_bonus + _session_bonus()
+    mode_bonus = 0.04 if mode == 'cross' else 0.0
+    raw_conf = 0.58 + 0.22 * proximity + 0.12 * _clamp((wick_dom - 0.2) / 0.6, 0.0, 1.0) + htf_bonus + vol_bonus + mode_bonus + _session_bonus()
     conf = _clamp(raw_conf * weight * max(0.5, recent_wr), 0.0, 0.93)
     if conf < thr:
-        _dbg(symbol, tf, "conf_below_threshold", {"conf": conf, "thr": thr})
-        return None
-
-    # Quality scoring (kept/refined)
+        _dbg(symbol, tf, 'conf_below_threshold', {'conf': conf, 'thr': thr})
+        return None
     dist_score = _tri_score(dist, 0.25, 0.75)
-    ema_score  = 1.0 if ((side == "BUY" and ema_up) or (side == "SELL" and ema_dn)) else 0.0
-    htf_score  = (
-        (1.0 if ((side == "BUY" and trend_master == "UP") or (side == "SELL" and trend_master == "DOWN")) else 0.0) +
-        (1.0 if ((side == "BUY" and t15 != "DOWN") or (side == "SELL" and t15 != "UP")) else 0.0) +
-        (1.0 if ((side == "BUY" and t1h != "DOWN") or (side == "SELL" and t1h != "UP")) else 0.0)
-    ) / 3.0
-    vol_score = _clamp(vol_now / max(1e-9, vol_med), 0.0, 1.0)
-    wick_score = _clamp((wick_dom - min_wick_dom) / max(1e-9, (0.65 - min_wick_dom)), 0.0, 1.0)
-    if is_memecoin:
-        rv_score = 1.0 if 0.006 <= rv <= 0.020 else _clamp(1.0 - abs(rv - 0.013) / 0.020, 0.0, 1.0)
-    else:
-        rv_score = 1.0 if 0.005 <= rv <= 0.015 else _clamp(1.0 - abs(rv - 0.010) / 0.015, 0.0, 1.0)
-
-    quality = 0.25 * wick_score + 0.20 * dist_score + 0.20 * ema_score + 0.20 * htf_score + 0.15 * vol_score
+    ema_score = 1.0 if side == 'BUY' and ema_up or (side == 'SELL' and ema_dn) else 0.0
+    htf_score = ((1.0 if side == 'BUY' and trend_master == 'UP' or (side == 'SELL' and trend_master == 'DOWN') else 0.0) + (1.0 if side == 'BUY' and t15 != 'DOWN' or (side == 'SELL' and t15 != 'UP') else 0.0) + (1.0 if side == 'BUY' and t1h != 'DOWN' or (side == 'SELL' and t1h != 'UP') else 0.0)) / 3.0
+    vol_score = _clamp(vol_now / max(1e-09, vol_med), 0.0, 1.0)
+    wick_score = _clamp((wick_dom - min_wick_dom) / max(1e-09, 0.65 - min_wick_dom), 0.0, 1.0)
+    if is_memecoin:
+        rv_score = 1.0 if 0.006 <= rv <= 0.02 else _clamp(1.0 - abs(rv - 0.013) / 0.02, 0.0, 1.0)
+    else:
+        rv_score = 1.0 if 0.005 <= rv <= 0.015 else _clamp(1.0 - abs(rv - 0.01) / 0.015, 0.0, 1.0)
+    quality = 0.25 * wick_score + 0.2 * dist_score + 0.2 * ema_score + 0.2 * htf_score + 0.15 * vol_score
     quality = _clamp(0.7 * quality + 0.3 * rv_score, 0.0, 1.0)
-
     if only_win_mode:
         if recent_wr < min_recent_wr:
-            _dbg(symbol, tf, "recent_wr_gate", {"recent_wr": recent_wr, "min_recent_wr": min_recent_wr})
+            _dbg(symbol, tf, 'recent_wr_gate', {'recent_wr': recent_wr, 'min_recent_wr': min_recent_wr})
             return None
         p_est = _clamp(0.55 * conf + 0.45 * quality, 0.05, 0.95)
         ev_r = p_est * rr_base - (1.0 - p_est)
-        if quality < min_quality or ev_r < min_ev_r or p_est < 0.60:
-            _dbg(symbol, tf, "ev_or_quality_veto", {"quality": quality, "ev_r": ev_r, "p_est": p_est})
+        if quality < min_quality or ev_r < min_ev_r or p_est < 0.6:
+            _dbg(symbol, tf, 'ev_or_quality_veto', {'quality': quality, 'ev_r': ev_r, 'p_est': p_est})
             return None
     else:
         p_est = _clamp(conf, 0.05, 0.95)
-
-    # ----- Entry model -----
     entry = price
-    entry_type = "market"
+    entry_type = 'market'
     entry_stop = None
     prefer_limit = True
     limit_ticks = 1
-
-    if ctx.get("force_limit_only", False):
-        # user override for maker-only testing
-        entry_type = "limit"
+    if ctx.get('force_limit_only', False):
+        entry_type = 'limit'
         prefer_limit = True
-    elif _safe_float(ctx.get("use_stop_entry", use_stop_entry), use_stop_entry):
-        # confirm continuation beyond signal bar extreme
+    elif _safe_float(ctx.get('use_stop_entry', use_stop_entry), use_stop_entry):
         buf = stop_buffer * atr
-        if side == "BUY":
-            entry_stop = max(price, h + buf) if mode != "rejection" else max(price, max(h, vwap) + 0.5*buf)
+        if side == 'BUY':
+            entry_stop = max(price, h + buf) if mode != 'rejection' else max(price, max(h, vwap) + 0.5 * buf)
         else:
-            entry_stop = min(price, l - buf) if mode != "rejection" else min(price, min(l, vwap) - 0.5*buf)
-        entry_type = "stop"
+            entry_stop = min(price, l - buf) if mode != 'rejection' else min(price, min(l, vwap) - 0.5 * buf)
+        entry_type = 'stop'
         entry = entry_stop
         prefer_limit = False
     else:
-        # limit a touch better toward VWAP
-        adj = 0.10 * band
-        if side == "BUY":
+        adj = 0.1 * band
+        if side == 'BUY':
             entry = max(price - adj, vwap - 0.25 * band)
         else:
             entry = min(price + adj, vwap + 0.25 * band)
-
-    _STATE["last_idx_by_symbol"][symbol] = last_idx
-
-    reason = (
-        f"vwap_pullback_v2 mode={mode} k={k:.2f} trend={trend_master} "
-        f"dist={dist:.2f} rr_eff={abs((tp-price)/max(1e-9,(price-sl))):.2f} "
-        f"rv={rv:.4f} q={quality:.2f} p={p_est:.2f} " + ("memecoin=True" if is_memecoin else "")
-    )
-
+    _STATE['last_idx_by_symbol'][symbol] = last_idx
+    reason = f'vwap_pullback_v2 mode={mode} k={k:.2f} trend={trend_master} dist={dist:.2f} rr_eff={abs((tp - price) / max(1e-09, price - sl)):.2f} rv={rv:.4f} q={quality:.2f} p={p_est:.2f} ' + ('memecoin=True' if is_memecoin else '')
     try:
-        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps(
-            {"agent": NAME, "tf": tf, "event": "signal", "mode": mode, "side": side,
-             "conf": round(conf,4), "entry": entry, "sl": sl, "tp": tp,
-             "vol_ratio": round(vol_now/max(1e-9,vol_med),3)}
-        ))
+        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps({'agent': NAME, 'tf': tf, 'event': 'signal', 'mode': mode, 'side': side, 'conf': round(conf, 4), 'entry': entry, 'sl': sl, 'tp': tp, 'vol_ratio': round(vol_now / max(1e-09, vol_med), 3)}))
     except Exception:
         pass
-
-    return {
-        "agent": NAME,
-        "timeframe": tf,
-        "side": side,
-        "confidence": float(conf),
-
-        "entry": float(entry),
-        "entry_type": entry_type,            # "stop" or "limit"/"market"
-        "entry_stop": float(entry_stop) if entry_stop is not None else None,
-        "prefer_limit": bool(prefer_limit),
-        "limit_ticks": int(limit_ticks),
-
-        "sl_hint": float(sl),
-        "tp_hint": float(tp),
-        "sl": float(sl),
-        "tp": float(tp),
-
-        "management": {
-            "move_be_at_r": float(move_be_at_r),
-            "trail_activation_r": 1.0,
-            "partial_tp_r": float(partial_tp_r),
-            "partial_size": float(partial_size),
-            "time_stop_bars": int(time_stop_bars)
-        },
-        "reason": reason
-    }
+    return {'agent': NAME, 'timeframe': tf, 'side': side, 'confidence': float(conf), 'entry': float(entry), 'entry_type': entry_type, 'entry_stop': float(entry_stop) if entry_stop is not None else None, 'prefer_limit': bool(prefer_limit), 'limit_ticks': int(limit_ticks), 'sl_hint': float(sl), 'tp_hint': float(tp), 'sl': float(sl), 'tp': float(tp), 'management': {'move_be_at_r': float(move_be_at_r), 'trail_activation_r': 1.0, 'partial_tp_r': float(partial_tp_r), 'partial_size': float(partial_size), 'time_stop_bars': int(time_stop_bars)}, 'reason': reason}
```

### generate_signal (agent)
```diff
--- 
+++ 
@@ -1,270 +1,179 @@
-def generate_signal(df: pd.DataFrame, symbol: str, ctx: Dict[str, Any] = None):
-    """
-    Liquidity Sweep + Flip (V2)
-    Modes:
-      A) Instant rejection: sweep of swing + close back inside with wick dominance.
-      B) Retest-flip: after sweep, store pending level; if price retests that level
-         within 3 bars and fails, we enter on the retest.
-
-    Works with: fingerprint veto/override, Momentum Pump (trend), Microburst (impulse).
-    Returns bot-compatible payload (entry/sl/tp + management).
-    """
+def generate_signal(df: pd.DataFrame, symbol: str, ctx: Dict[str, Any]=None):
+    try:
+        if 'loss_streak' in locals() and int(loss_streak) >= 2:
+            return None
+    except Exception:
+        pass
+    try:
+        close = df['close']
+        ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
+        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
+        if side == 'BUY' and (not entry > ema9 > ema21) or (side == 'SELL' and (not entry < ema9 < ema21)):
+            return None
+    except Exception:
+        pass
+    '\n    Liquidity Sweep + Flip (V2)\n    Modes:\n      A) Instant rejection: sweep of swing + close back inside with wick dominance.\n      B) Retest-flip: after sweep, store pending level; if price retests that level\n         within 3 bars and fails, we enter on the retest.\n\n    Works with: fingerprint veto/override, Momentum Pump (trend), Microburst (impulse).\n    Returns bot-compatible payload (entry/sl/tp + management).\n    '
     ctx = ctx or {}
-    tf   = str(ctx.get("timeframe", "5m"))
-    thr  = _safe(ctx.get("conf_threshold", 0.72), 0.72)
-    w    = _safe(ctx.get("weight", 1.0), 1.0)
-    min_move = _safe(ctx.get("min_expected_move", 0.006), 0.006)
-    recent_wr = _safe(ctx.get("recent_wr", 1.0), 1.0)
-
-    t15  = str(ctx.get("trend_15m", "SIDEWAYS")).upper()
-    t1h  = str(ctx.get("trend_1h", "SIDEWAYS")).upper()
-    tmas = str(ctx.get("trend_hint", "SIDEWAYS")).upper()
-
+    tf = str(ctx.get('timeframe', '5m'))
+    thr = _safe(ctx.get('conf_threshold', 0.72), 0.72)
+    w = _safe(ctx.get('weight', 1.0), 1.0)
+    min_move = _safe(ctx.get('min_expected_move', 0.006), 0.006)
+    recent_wr = _safe(ctx.get('recent_wr', 1.0), 1.0)
+    t15 = str(ctx.get('trend_15m', 'SIDEWAYS')).upper()
+    t1h = str(ctx.get('trend_1h', 'SIDEWAYS')).upper()
+    tmas = str(ctx.get('trend_hint', 'SIDEWAYS')).upper()
     if df is None or len(df) < 60:
         return None
-
     last_idx = len(df) - 1
-    if (last_idx - _STATE["last_idx_by_symbol"].get(symbol, -10**9)) < _COOLDOWN_BARS:
+    if last_idx - _STATE['last_idx_by_symbol'].get(symbol, -10 ** 9) < _COOLDOWN_BARS:
         return None
-
-    price = _safe(df["close"].iloc[-1])
-    o     = _safe(df["open"].iloc[-1])
-    h     = _safe(df["high"].iloc[-1])
-    l     = _safe(df["low"].iloc[-1])
-    rng   = max(1e-12, h - l)
+    price = _safe(df['close'].iloc[-1])
+    o = _safe(df['open'].iloc[-1])
+    h = _safe(df['high'].iloc[-1])
+    l = _safe(df['low'].iloc[-1])
+    rng = max(1e-12, h - l)
     if rng <= 0:
         return None
-
-    # anatomy
     upper_wick = max(0.0, h - max(o, price))
     lower_wick = max(0.0, min(o, price) - l)
-    wick_dom   = max(upper_wick, lower_wick) / rng
+    wick_dom = max(upper_wick, lower_wick) / rng
     body_ratio = abs(price - o) / rng
-
-    # liquidity
-    vol_now = _safe(df["volume"].iloc[-1])
-    vol_med = _safe(df["volume"].tail(30).median(), 0.0)
-    if vol_med <= 0: return None
-
+    vol_now = _safe(df['volume'].iloc[-1])
+    vol_med = _safe(df['volume'].tail(30).median(), 0.0)
+    if vol_med <= 0:
+        return None
     hot = _is_hot(symbol)
     min_vol_ratio = 0.25 if hot else 0.45
     if vol_now < min_vol_ratio * vol_med:
-        _dbg(symbol, tf, "low_liquidity", {"vol_now":vol_now,"vol_med":vol_med,"min_vol_ratio":min_vol_ratio})
+        _dbg(symbol, tf, 'low_liquidity', {'vol_now': vol_now, 'vol_med': vol_med, 'min_vol_ratio': min_vol_ratio})
         return None
-
     atr = _atr_last(df, 14)
     if atr <= 0:
         return None
-
-    # recent swings
     look = 6 if hot else 8
-    prev_hi = _safe(df["high"].iloc[-(look+1):-1].max(), 0.0)
-    prev_lo = _safe(df["low"].iloc[-(look+1):-1].min(), 0.0)
-
-    # sweep tests
-    # a small tolerance (eps) lets partial/micro sweeps count
+    prev_hi = _safe(df['high'].iloc[-(look + 1):-1].max(), 0.0)
+    prev_lo = _safe(df['low'].iloc[-(look + 1):-1].min(), 0.0)
     eps = (0.05 if hot else 0.035) * atr
-    swept_high = (h >= prev_hi - eps)
-    swept_low  = (l <= prev_lo + eps)
-
-    # rejection tests
-    need_wick = 0.20 if hot else 0.26
+    swept_high = h >= prev_hi - eps
+    swept_low = l <= prev_lo + eps
+    need_wick = 0.2 if hot else 0.26
     need_body = 0.22 if hot else 0.28
-    reject_high = swept_high and (price < prev_hi) and (upper_wick >= need_wick * rng) and (body_ratio >= need_body)
-    reject_low  = swept_low  and (price > prev_lo) and (lower_wick >= need_wick * rng) and (body_ratio >= need_body)
-
-    ema9  = _ema(df["close"], 9)
-    ema21 = _ema(df["close"], 21)
+    reject_high = swept_high and price < prev_hi and (upper_wick >= need_wick * rng) and (body_ratio >= need_body)
+    reject_low = swept_low and price > prev_lo and (lower_wick >= need_wick * rng) and (body_ratio >= need_body)
+    ema9 = _ema(df['close'], 9)
+    ema21 = _ema(df['close'], 21)
     ema_up = price > ema9 > ema21
     ema_dn = price < ema9 < ema21
     if hot:
-        # allow just ema9 for hot coins
         ema_up = price > ema9
         ema_dn = price < ema9
-
-    # -------------------- Mode A: instant rejection --------------------
     side = None
     mode = None
-    if reject_high and (ema_dn or t15 != "UP" or t1h != "UP"):
-        side = "SELL"; mode = "instant"
-    elif reject_low and (ema_up or t15 != "DOWN" or t1h != "DOWN"):
-        side = "BUY";  mode = "instant"
-
-    # -------------------- Mode B: retest-flip (pending) ----------------
-    # if we see a sweep but no instant rejection, set a pending level
-    pend = _STATE["pending"].get(symbol)
+    if reject_high and (ema_dn or t15 != 'UP' or t1h != 'UP'):
+        side = 'SELL'
+        mode = 'instant'
+    elif reject_low and (ema_up or t15 != 'DOWN' or t1h != 'DOWN'):
+        side = 'BUY'
+        mode = 'instant'
+    pend = _STATE['pending'].get(symbol)
     if side is None:
         set_new_pending = False
-        if swept_high and price >= prev_hi:  # closed outside or at level
-            _STATE["pending"][symbol] = {
-                "dir": "SELL", "level": prev_hi, "set_idx": last_idx, "expires_idx": last_idx + 3
-            }
+        if swept_high and price >= prev_hi:
+            _STATE['pending'][symbol] = {'dir': 'SELL', 'level': prev_hi, 'set_idx': last_idx, 'expires_idx': last_idx + 3}
             set_new_pending = True
         elif swept_low and price <= prev_lo:
-            _STATE["pending"][symbol] = {
-                "dir": "BUY", "level": prev_lo, "set_idx": last_idx, "expires_idx": last_idx + 3
-            }
+            _STATE['pending'][symbol] = {'dir': 'BUY', 'level': prev_lo, 'set_idx': last_idx, 'expires_idx': last_idx + 3}
             set_new_pending = True
         if set_new_pending:
-            _dbg(symbol, tf, "pending_set", _STATE["pending"][symbol], event="info")
-
-    # If a pending exists, look for a retest failure within horizon
-    pend = _STATE["pending"].get(symbol)
-    if side is None and pend and last_idx <= pend["expires_idx"]:
-        level = float(pend["level"])
-        # close back inside with body in flip direction, or wick reject around level
-        near = abs(price - level) <= 0.10 * atr  # within 0.1*ATR of level
-        if pend["dir"] == "SELL":
-            # retest to/beyond level then close back under
-            if (df["high"].iloc[-1] >= level - 0.02*atr) and (price < level) and (upper_wick >= 0.18 * rng or body_ratio >= 0.22):
-                side = "SELL"; mode = "retest"
-        else:
-            if (df["low"].iloc[-1] <= level + 0.02*atr) and (price > level) and (lower_wick >= 0.18 * rng or body_ratio >= 0.22):
-                side = "BUY";  mode = "retest"
-
+            _dbg(symbol, tf, 'pending_set', _STATE['pending'][symbol], event='info')
+    pend = _STATE['pending'].get(symbol)
+    if side is None and pend and (last_idx <= pend['expires_idx']):
+        level = float(pend['level'])
+        near = abs(price - level) <= 0.1 * atr
+        if pend['dir'] == 'SELL':
+            if df['high'].iloc[-1] >= level - 0.02 * atr and price < level and (upper_wick >= 0.18 * rng or body_ratio >= 0.22):
+                side = 'SELL'
+                mode = 'retest'
+        elif df['low'].iloc[-1] <= level + 0.02 * atr and price > level and (lower_wick >= 0.18 * rng or body_ratio >= 0.22):
+            side = 'BUY'
+            mode = 'retest'
         if not side and near:
-            _dbg(symbol, tf, "pending_touch", {"dir": pend["dir"], "level": level, "price": price}, event="info")
-
-    # expire stale pending
-    if pend and last_idx > pend["expires_idx"]:
-        _dbg(symbol, tf, "pending_expired", pend, event="info")
-        _STATE["pending"].pop(symbol, None)
-
+            _dbg(symbol, tf, 'pending_touch', {'dir': pend['dir'], 'level': level, 'price': price}, event='info')
+    if pend and last_idx > pend['expires_idx']:
+        _dbg(symbol, tf, 'pending_expired', pend, event='info')
+        _STATE['pending'].pop(symbol, None)
     if side is None:
-        _dbg(symbol, tf, "no_trigger", {
-            "swept_high": bool(swept_high), "swept_low": bool(swept_low),
-            "reject_high": bool(reject_high), "reject_low": bool(reject_low),
-            "wick_dom": wick_dom, "body_ratio": body_ratio,
-            "t15": t15, "t1h": t1h, "ema_up": bool(ema_up), "ema_dn": bool(ema_dn)
-        })
+        _dbg(symbol, tf, 'no_trigger', {'swept_high': bool(swept_high), 'swept_low': bool(swept_low), 'reject_high': bool(reject_high), 'reject_low': bool(reject_low), 'wick_dom': wick_dom, 'body_ratio': body_ratio, 't15': t15, 't1h': t1h, 'ema_up': bool(ema_up), 'ema_dn': bool(ema_dn)})
         return None
-
-    # ========================== Agent-owned SL/TP ==========================
-    # SL beyond extreme + ATR cushion + structure guard
-    if side == "SELL":
-        sl_struct = h + 0.20 * atr
-        sl_cush   = (max(prev_hi, h)) + 0.10 * atr
-        sl_floor  = price + (1.05 if hot else 1.00) * atr
+    if side == 'SELL':
+        sl_struct = h + 0.2 * atr
+        sl_cush = max(prev_hi, h) + 0.1 * atr
+        sl_floor = price + (1.05 if hot else 1.0) * atr
         sl = max(sl_struct, sl_cush, sl_floor)
     else:
-        sl_struct = l - 0.20 * atr
-        sl_cush   = (min(prev_lo, l)) - 0.10 * atr
-        sl_floor  = price - (1.05 if hot else 1.00) * atr
+        sl_struct = l - 0.2 * atr
+        sl_cush = min(prev_lo, l) - 0.1 * atr
+        sl_floor = price - (1.05 if hot else 1.0) * atr
         sl = min(sl_struct, sl_cush, sl_floor)
-
     risk = abs(price - sl)
     if risk <= 0:
         return None
-
-    # TPs: RR, mean reversion to EMA21, measured box
     RR_BASE = 2.0 if hot else 2.1
-    tp_rr = price - RR_BASE * risk if side == "SELL" else price + RR_BASE * risk
-
-    ema_target = _ema(df["close"], 21)
-    tp_ema = (ema_target - 0.10 * atr) if side == "SELL" else (ema_target + 0.10 * atr)
-
-    box_hi = _safe(df["high"].iloc[-(look+1):-1].max(), 0.0)
-    box_lo = _safe(df["low"].iloc[-(look+1):-1].min(), 0.0)
+    tp_rr = price - RR_BASE * risk if side == 'SELL' else price + RR_BASE * risk
+    ema_target = _ema(df['close'], 21)
+    tp_ema = ema_target - 0.1 * atr if side == 'SELL' else ema_target + 0.1 * atr
+    box_hi = _safe(df['high'].iloc[-(look + 1):-1].max(), 0.0)
+    box_lo = _safe(df['low'].iloc[-(look + 1):-1].min(), 0.0)
     impulse = abs(box_hi - box_lo)
-    tp_mm = price - 0.80 * impulse if side == "SELL" else price + 0.80 * impulse
-
+    tp_mm = price - 0.8 * impulse if side == 'SELL' else price + 0.8 * impulse
     cands = [tp_rr, tp_ema, tp_mm]
-    tp_candidate = (max([c for c in cands if c < price], default=tp_rr)
-                    if side == "SELL"
-                    else min([c for c in cands if c > price], default=tp_rr))
-
-    RR_MIN = 1.65 if hot else 1.80
+    tp_candidate = max([c for c in cands if c < price], default=tp_rr) if side == 'SELL' else min([c for c in cands if c > price], default=tp_rr)
+    RR_MIN = 1.65 if hot else 1.8
     rr = abs((tp_candidate - price) / risk)
-    tp = (price - RR_MIN * risk) if (side == "SELL" and rr < RR_MIN) else \
-         (price + RR_MIN * risk) if (side == "BUY"  and rr < RR_MIN) else tp_candidate
-
-    exp_move = abs(tp - price) / max(1e-9, price)
+    tp = price - RR_MIN * risk if side == 'SELL' and rr < RR_MIN else price + RR_MIN * risk if side == 'BUY' and rr < RR_MIN else tp_candidate
+    exp_move = abs(tp - price) / max(1e-09, price)
     if exp_move < min_move:
-        _dbg(symbol, tf, "expected_move_small", {"exp_move":exp_move, "min_move":min_move})
+        _dbg(symbol, tf, 'expected_move_small', {'exp_move': exp_move, 'min_move': min_move})
         return None
-
-    # --------------------------- Confidence ------------------------------
-    depth = (h - prev_hi) / max(1e-12, atr) if side == "SELL" else (prev_lo - l) / max(1e-12, atr)
-    wick_score  = min(1.0, max(0.0, (wick_dom - (0.18 if hot else 0.22))) / 0.50)
-    depth_score = min(1.0, max(0.0, depth) / (0.35 if hot else 0.40))
-    cluster_hi = (df["high"].iloc[-(look+1):-1] >= (prev_hi - eps)).sum()
-    cluster_lo = (df["low"].iloc[-(look+1):-1]  <= (prev_lo + eps)).sum()
-    cluster = cluster_hi if side == "SELL" else cluster_lo
+    depth = (h - prev_hi) / max(1e-12, atr) if side == 'SELL' else (prev_lo - l) / max(1e-12, atr)
+    wick_score = min(1.0, max(0.0, wick_dom - (0.18 if hot else 0.22)) / 0.5)
+    depth_score = min(1.0, max(0.0, depth) / (0.35 if hot else 0.4))
+    cluster_hi = (df['high'].iloc[-(look + 1):-1] >= prev_hi - eps).sum()
+    cluster_lo = (df['low'].iloc[-(look + 1):-1] <= prev_lo + eps).sum()
+    cluster = cluster_hi if side == 'SELL' else cluster_lo
     cluster_score = min(1.0, cluster / 3.0)
-
-    htf_ok = ((side == "SELL" and t15 != "UP" and t1h != "UP") or
-              (side == "BUY"  and t15 != "DOWN" and t1h != "DOWN"))
-    htf_bonus = 0.10 if htf_ok else 0.04
-    ema_bonus = 0.08 if ((side == "SELL" and price < ema9) or (side == "BUY" and price > ema9)) else 0.0
+    htf_ok = side == 'SELL' and t15 != 'UP' and (t1h != 'UP') or (side == 'BUY' and t15 != 'DOWN' and (t1h != 'DOWN'))
+    htf_bonus = 0.1 if htf_ok else 0.04
+    ema_bonus = 0.08 if side == 'SELL' and price < ema9 or (side == 'BUY' and price > ema9) else 0.0
     sess_bonus = 0.02 if 16 <= datetime.utcnow().hour <= 23 else 0.0
     vol_ratio = vol_now / max(1e-12, vol_med)
-    reg_adj = 0.03 if vol_ratio >= 1.20 else 0.0
-    mode_bonus = 0.04 if mode == "retest" else 0.0  # retest entries are usually higher quality
-
-    raw_conf = 0.62 + 0.16*wick_score + 0.10*depth_score + 0.08*cluster_score \
-               + htf_bonus + ema_bonus + reg_adj + sess_bonus + mode_bonus
+    reg_adj = 0.03 if vol_ratio >= 1.2 else 0.0
+    mode_bonus = 0.04 if mode == 'retest' else 0.0
+    raw_conf = 0.62 + 0.16 * wick_score + 0.1 * depth_score + 0.08 * cluster_score + htf_bonus + ema_bonus + reg_adj + sess_bonus + mode_bonus
     conf = max(0.0, min(0.94, raw_conf * w * max(0.65, recent_wr)))
     if conf < thr:
-        _dbg(symbol, tf, "conf_below_threshold", {"conf":conf,"thr":thr,"mode":mode})
+        _dbg(symbol, tf, 'conf_below_threshold', {'conf': conf, 'thr': thr, 'mode': mode})
         return None
-
-    _STATE["last_idx_by_symbol"][symbol] = last_idx
-    # clear pending if we used it
-    pend = _STATE["pending"].get(symbol)
-    if pend and mode == "retest":
-        _STATE["pending"].pop(symbol, None)
-
-    # Entry semantics:
-    # - limit by default (cheaper), but for instant mode we can suggest a stop confirmation
-    entry_type = "limit"
+    _STATE['last_idx_by_symbol'][symbol] = last_idx
+    pend = _STATE['pending'].get(symbol)
+    if pend and mode == 'retest':
+        _STATE['pending'].pop(symbol, None)
+    entry_type = 'limit'
     entry = price
     entry_stop = None
     prefer_limit = True
-    if mode == "instant":
-        # confirmation: break the rejection candle low/high by a buffer
+    if mode == 'instant':
         buf = 0.08 * atr
-        if side == "SELL":
+        if side == 'SELL':
             entry_stop = min(price, l - buf)
         else:
             entry_stop = max(price, h + buf)
-        entry_type = "stop"
+        entry_type = 'stop'
         entry = entry_stop
-
-    management = {
-        "move_be_at_r": 0.9 if hot else 1.0,
-        "trail_activation_r": 1.0 if hot else 1.2,
-        "partial_tp_r": 0.75 if hot else 0.95,
-        "partial_size": 0.45 if hot else 0.35,
-        "time_stop_bars": 8 if hot else 12
-    }
-
-    reason = f"sweep_flip mode={mode} side={side} rr={abs((tp-price)/risk):.2f} wick={wick_dom:.2f} depth={depth:.2f} ema21={ema21:.6f} atr={atr:.6f}"
-
+    management = {'move_be_at_r': 0.9 if hot else 1.0, 'trail_activation_r': 1.0 if hot else 1.2, 'partial_tp_r': 0.75 if hot else 0.95, 'partial_size': 0.45 if hot else 0.35, 'time_stop_bars': 8 if hot else 12}
+    reason = f'sweep_flip mode={mode} side={side} rr={abs((tp - price) / risk):.2f} wick={wick_dom:.2f} depth={depth:.2f} ema21={ema21:.6f} atr={atr:.6f}'
     try:
-        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps(
-            {"agent": NAME, "tf": tf, "event":"signal", "mode":mode, "side":side,
-             "conf": round(conf,4), "entry": entry, "sl": sl, "tp": tp, "vol_ratio": round(vol_ratio,3)}
-        ))
+        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps({'agent': NAME, 'tf': tf, 'event': 'signal', 'mode': mode, 'side': side, 'conf': round(conf, 4), 'entry': entry, 'sl': sl, 'tp': tp, 'vol_ratio': round(vol_ratio, 3)}))
     except Exception:
         pass
-
-    return {
-        "agent": NAME,
-        "timeframe": tf,
-        "side": side,
-        "confidence": float(conf),
-
-        "entry": float(entry),
-        "entry_type": entry_type,       # "limit" or "stop"
-        "entry_stop": float(entry_stop) if entry_stop is not None else None,
-        "prefer_limit": bool(prefer_limit),
-        "limit_ticks": 1,
-
-        "sl_hint": float(sl),
-        "tp_hint": float(tp),
-        "sl": float(sl),
-        "tp": float(tp),
-
-        "management": management,
-        "reason": reason
-    }
+    return {'agent': NAME, 'timeframe': tf, 'side': side, 'confidence': float(conf), 'entry': float(entry), 'entry_type': entry_type, 'entry_stop': float(entry_stop) if entry_stop is not None else None, 'prefer_limit': bool(prefer_limit), 'limit_ticks': 1, 'sl_hint': float(sl), 'tp_hint': float(tp), 'sl': float(sl), 'tp': float(tp), 'management': management, 'reason': reason}
```

### generate_signal (agent)
```diff
--- 
+++ 
@@ -1,72 +1,57 @@
 def generate_signal(df5m: pd.DataFrame, symbol: str, ctx: dict):
-    """
-    Momentum Pump: expansion + (pre)breakout + trend alignment.
-    + ignition(5m) + micro-confirm(1m) + late-chase veto (non-breaking)
-    """
-    tf = ctx.get("timeframe", "5m")
-    thr = _safe(ctx.get("conf_threshold", 0.74), 0.74)
-    min_move = _safe(ctx.get("min_expected_move", 0.001), 0.001)
-
-    t15 = (ctx.get("trend_15m") or "SIDEWAYS").upper()
-    t1h = (ctx.get("trend_1h") or "SIDEWAYS").upper()
-    trend_master = (ctx.get("trend_hint") or "SIDEWAYS").upper()
-
-    # Guard against accidental zero weight (which can hide/evict the agent)
-    weight = _safe(ctx.get("weight", 1.0), 1.0)
+    try:
+        if 'loss_streak' in locals() and int(loss_streak) >= 2:
+            return None
+    except Exception:
+        pass
+    try:
+        close = df['close']
+        ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
+        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
+        if side == 'BUY' and (not entry > ema9 > ema21) or (side == 'SELL' and (not entry < ema9 < ema21)):
+            return None
+    except Exception:
+        pass
+    '\n    Momentum Pump: expansion + (pre)breakout + trend alignment.\n    + ignition(5m) + micro-confirm(1m) + late-chase veto (non-breaking)\n    '
+    tf = ctx.get('timeframe', '5m')
+    thr = _safe(ctx.get('conf_threshold', 0.74), 0.74)
+    min_move = _safe(ctx.get('min_expected_move', 0.001), 0.001)
+    t15 = (ctx.get('trend_15m') or 'SIDEWAYS').upper()
+    t1h = (ctx.get('trend_1h') or 'SIDEWAYS').upper()
+    trend_master = (ctx.get('trend_hint') or 'SIDEWAYS').upper()
+    weight = _safe(ctx.get('weight', 1.0), 1.0)
     if weight <= 0.0:
         weight = 1.0
-    recent_wr = _safe(ctx.get("recent_wr", 1.0), 1.0)
-
-    # optional params override (kept as in your original)
-    USE_STOP       = bool(ctx.get("params", {}).get("USE_STOP", True))
-    STOP_BUF_ATR   = _safe(ctx.get("params", {}).get("STOP_BUF_ATR", 0.10), 0.10)
-    MEAN_GUARD_ATR = _safe(ctx.get("params", {}).get("MEAN_GUARD_ATR", 0.60), 0.60)
-
-    # OPTIONAL: absolute QuickTP (kept OFF unless you pass it)
-    quick_tp_abs = _safe(ctx.get("quick_tp_abs", 0.0), 0.0)
-
+    recent_wr = _safe(ctx.get('recent_wr', 1.0), 1.0)
+    USE_STOP = bool(ctx.get('params', {}).get('USE_STOP', True))
+    STOP_BUF_ATR = _safe(ctx.get('params', {}).get('STOP_BUF_ATR', 0.1), 0.1)
+    MEAN_GUARD_ATR = _safe(ctx.get('params', {}).get('MEAN_GUARD_ATR', 0.6), 0.6)
+    quick_tp_abs = _safe(ctx.get('quick_tp_abs', 0.0), 0.0)
     is_memecoin = _is_high_vol_asset(symbol)
-
-    # Session bonus (US hours)
     hour_utc = datetime.utcnow().hour
     us_session = 16 <= hour_utc <= 23
     session_bonus = 0.03 if us_session else 0.0
-
-    # History requirement
     if df5m is None or len(df5m) < 60:
         return None
-
-    # Optional 1m data from ctx
-    df1m = ctx.get("df1m")
-
-    # Cooldown
+    df1m = ctx.get('df1m')
     last_idx = len(df5m) - 1
-    prev_idx = _STATE.get("last_idx_by_symbol", {}).get(symbol, -10**9)
+    prev_idx = _STATE.get('last_idx_by_symbol', {}).get(symbol, -10 ** 9)
     cooldown_bars = 1 if is_memecoin else _DEFAULT_COOLDOWN_BARS
-    if (last_idx - prev_idx) < cooldown_bars:
-        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps(
-            {"agent": NAME, "tf": tf, "event": "veto", "reason": "cooldown",
-             "last_idx": last_idx, "prev_idx": prev_idx}
-        ))
-        return None
-
-    price = _safe(df5m["close"].iloc[-1])
-    vol_now = _safe(df5m["volume"].iloc[-1])
-    vol_med = _safe(df5m["volume"].tail(30).median(), 0.0)
-    atr_ctx = _safe(ctx.get("risk", {}).get("atr"), 0.0)
+    if last_idx - prev_idx < cooldown_bars:
+        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps({'agent': NAME, 'tf': tf, 'event': 'veto', 'reason': 'cooldown', 'last_idx': last_idx, 'prev_idx': prev_idx}))
+        return None
+    price = _safe(df5m['close'].iloc[-1])
+    vol_now = _safe(df5m['volume'].iloc[-1])
+    vol_med = _safe(df5m['volume'].tail(30).median(), 0.0)
+    atr_ctx = _safe(ctx.get('risk', {}).get('atr'), 0.0)
     atr = atr_ctx if atr_ctx > 0 else _atr(df5m, 14)
     if atr <= 0.0:
-        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps(
-            {"agent": NAME, "tf": tf, "event": "veto", "reason": "atr_invalid", "atr": atr}
-        ))
-        return None
-
-    hi = _safe(df5m["high"].iloc[-1])
-    lo = _safe(df5m["low"].iloc[-1])
+        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps({'agent': NAME, 'tf': tf, 'event': 'veto', 'reason': 'atr_invalid', 'atr': atr}))
+        return None
+    hi = _safe(df5m['high'].iloc[-1])
+    lo = _safe(df5m['low'].iloc[-1])
     rng = max(0.0, hi - lo)
-
-    # Candle anatomy
-    o = _safe(df5m["open"].iloc[-1])
+    o = _safe(df5m['open'].iloc[-1])
     c = price
     body = c - o
     body_ratio = abs(body) / max(1e-12, rng)
@@ -74,41 +59,27 @@
     lower_wick = max(0.0, min(c, o) - lo)
     wick_dom = max(upper_wick, lower_wick) / max(1e-12, rng)
     if wick_dom > 0.55 and abs(body) < 0.35 * rng:
-        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps(
-            {"agent": NAME, "tf": tf, "event": "veto", "reason": "exhaustion_wick", "wick_dom": wick_dom}
-        ))
-        return None
-
-    # Short-term whipsaw veto
-    rv30 = _safe(df5m["close"].pct_change().rolling(30).std().iloc[-1], 0.0)
-    rv10 = _safe(df5m["close"].pct_change().rolling(10).std().iloc[-1], 0.0)
+        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps({'agent': NAME, 'tf': tf, 'event': 'veto', 'reason': 'exhaustion_wick', 'wick_dom': wick_dom}))
+        return None
+    rv30 = _safe(df5m['close'].pct_change().rolling(30).std().iloc[-1], 0.0)
+    rv10 = _safe(df5m['close'].pct_change().rolling(10).std().iloc[-1], 0.0)
     if rv10 > 1.7 * max(1e-12, rv30):
-        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps(
-            {"agent": NAME, "tf": tf, "event": "veto", "reason": "whipsaw_vol", "rv10": rv10, "rv30": rv30}
-        ))
-        return None
-
-    # Expansion requirement adjusted by volume surge (same as original)
-    surge_threshold = 1.00 if is_memecoin else 1.05
-    has_volume_surge = (vol_now >= surge_threshold * max(1e-9, vol_med))
-    exp_req = (0.40 if is_memecoin else 0.48) * atr if has_volume_surge else (0.52 if is_memecoin else 0.58) * atr
+        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps({'agent': NAME, 'tf': tf, 'event': 'veto', 'reason': 'whipsaw_vol', 'rv10': rv10, 'rv30': rv30}))
+        return None
+    surge_threshold = 1.0 if is_memecoin else 1.05
+    has_volume_surge = vol_now >= surge_threshold * max(1e-09, vol_med)
+    exp_req = (0.4 if is_memecoin else 0.48) * atr if has_volume_surge else (0.52 if is_memecoin else 0.58) * atr
     exp_ok = rng >= exp_req
-
-    # Momentum
-    r1 = _safe(df5m["close"].pct_change().iloc[-1])
-    r3 = _safe(df5m["close"].pct_change(3).iloc[-1])
-    r5 = _safe(df5m["close"].pct_change(5).iloc[-1]) if is_memecoin else 0.0
-    mom = (r1 + 0.4 * r3 + 0.2 * r5) if is_memecoin else (r1 + 0.5 * r3)
-
-    # EMAs
-    ema_fast = _ema(df5m["close"], 9)
-    ema_slow = _ema(df5m["close"], 21)
-    ema_up = (price > ema_fast) if is_memecoin else (price > ema_fast > ema_slow)
-    ema_dn = (price < ema_fast) if is_memecoin else (price < ema_fast < ema_slow)
-
-    # Mean-band guard (EMA99 + SuperTrend)   softened during ignition only
-    ema99 = _ema(df5m["close"], 99)
-    st_mult = 2.8 if rv30 < 0.010 else 3.2
+    r1 = _safe(df5m['close'].pct_change().iloc[-1])
+    r3 = _safe(df5m['close'].pct_change(3).iloc[-1])
+    r5 = _safe(df5m['close'].pct_change(5).iloc[-1]) if is_memecoin else 0.0
+    mom = r1 + 0.4 * r3 + 0.2 * r5 if is_memecoin else r1 + 0.5 * r3
+    ema_fast = _ema(df5m['close'], 9)
+    ema_slow = _ema(df5m['close'], 21)
+    ema_up = price > ema_fast if is_memecoin else price > ema_fast > ema_slow
+    ema_dn = price < ema_fast if is_memecoin else price < ema_fast < ema_slow
+    ema99 = _ema(df5m['close'], 99)
+    st_mult = 2.8 if rv30 < 0.01 else 3.2
     st = _supertrend(df5m, period=10, multiplier=st_mult)
     st_val = _safe(st.iloc[-1], np.nan)
 
@@ -116,7 +87,7 @@
         if not np.isfinite(st_val):
             return False
         pad = MEAN_GUARD_ATR * atr * (0.7 if during_ignition else 1.0)
-        if side == "SELL":
+        if side == 'SELL':
             if price > ema99:
                 return True
             if price >= st_val - pad:
@@ -127,243 +98,127 @@
             if price <= st_val + pad:
                 return True
         return False
-
-    # Breakout levels
     lookback = 4 if is_memecoin else 6
-    prev_hi = _safe(df5m["high"].iloc[-lookback:-1].max(), 0.0)
-    prev_lo = _safe(df5m["low"].iloc[-lookback:-1].min(), 0.0)
+    prev_hi = _safe(df5m['high'].iloc[-lookback:-1].max(), 0.0)
+    prev_lo = _safe(df5m['low'].iloc[-lookback:-1].min(), 0.0)
     buffer = 0.02 * atr if is_memecoin else 0.0
-    bos_up = c > (prev_hi - buffer)
-    bos_dn = c < (prev_lo + buffer)
-
-    # Pre-breakout awareness
-    c_live = float(ctx.get("last_price", price))
-    early_margin = (0.10 if is_memecoin else 0.15) * atr
-    pre_bos_up = (prev_hi > 0) and (prev_hi - c_live) <= early_margin
-    pre_bos_dn = (prev_lo > 0) and (c_live - prev_lo) <= early_margin
-
-    # Liquidity/expansion gate
-    vol_threshold = 0.55 if is_memecoin else 0.60
-    exp_threshold = 0.65 if is_memecoin else 0.70
-    liquidity_ok = (
-        (vol_now >= vol_threshold * max(1e-9, vol_med)) or
-        (rng >= exp_threshold * atr) or
-        ((pre_bos_up or pre_bos_dn) and abs(mom) > (0.6 if is_memecoin else 0.4))
-    )
+    bos_up = c > prev_hi - buffer
+    bos_dn = c < prev_lo + buffer
+    c_live = float(ctx.get('last_price', price))
+    early_margin = (0.1 if is_memecoin else 0.15) * atr
+    pre_bos_up = prev_hi > 0 and prev_hi - c_live <= early_margin
+    pre_bos_dn = prev_lo > 0 and c_live - prev_lo <= early_margin
+    vol_threshold = 0.55 if is_memecoin else 0.6
+    exp_threshold = 0.65 if is_memecoin else 0.7
+    liquidity_ok = vol_now >= vol_threshold * max(1e-09, vol_med) or rng >= exp_threshold * atr or ((pre_bos_up or pre_bos_dn) and abs(mom) > (0.6 if is_memecoin else 0.4))
     if not liquidity_ok:
-        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps(
-            {"agent": NAME, "tf": tf, "event": "veto", "reason": "low_liquidity",
-             "vol_now": vol_now, "vol_med": vol_med, "vol_ratio": vol_now/max(1e-9, vol_med)}
-        ))
-        return None
-
-    # Tight consolidation check
+        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps({'agent': NAME, 'tf': tf, 'event': 'veto', 'reason': 'low_liquidity', 'vol_now': vol_now, 'vol_med': vol_med, 'vol_ratio': vol_now / max(1e-09, vol_med)}))
+        return None
     if len(df5m) > 5:
-        recent_ranges = [_safe(df5m["high"].iloc[i] - df5m["low"].iloc[i]) for i in range(-5, -1)]
+        recent_ranges = [_safe(df5m['high'].iloc[i] - df5m['low'].iloc[i]) for i in range(-5, -1)]
         avg_range = np.mean(recent_ranges) if recent_ranges else 0.0
         tight_consolidation = avg_range < 0.7 * rng
     else:
         tight_consolidation = False
-
-    # --------- NEW: ignition (5m) + micro-confirm (1m) ---------
     ignition5m = _is_ignition_5m(df5m, atr, is_memecoin)
-    micro = _is_ignition_1m(ctx.get("df1m"), is_memecoin)
-    micro_up, micro_dn, micro_score = micro["up"], micro["down"], micro["score"]
-
-    # Direction choice (accept BOS/PRE-BOS as before; also allow ignition/micro)
+    micro = _is_ignition_1m(ctx.get('df1m'), is_memecoin)
+    micro_up, micro_dn, micro_score = (micro['up'], micro['down'], micro['score'])
     side = None
     if is_memecoin:
-        if (exp_ok or ignition5m or micro_up) and mom > 0 and (ema_up or trend_master == "UP" or t15 == "UP") and (bos_up or pre_bos_up or ignition5m or micro_up):
-            side = "BUY"
-        elif (exp_ok or ignition5m or micro_dn) and mom < 0 and (ema_dn or trend_master == "DOWN" or t15 == "DOWN") and (bos_dn or pre_bos_dn or ignition5m or micro_dn):
-            side = "SELL"
-    else:
-        if (exp_ok or ignition5m or micro_up) and mom > 0 and (ema_up or trend_master == "UP") and t15 != "DOWN" and (bos_up or pre_bos_up or ignition5m or micro_up):
-            side = "BUY"
-        elif (exp_ok or ignition5m or micro_dn) and mom < 0 and (ema_dn or trend_master == "DOWN") and t15 != "UP" and (bos_dn or pre_bos_dn or ignition5m or micro_dn):
-            side = "SELL"
-
-    # HTF guardrail against 1h trend unless thrust is strong (unchanged logic)
-    if side == "BUY" and t1h == "DOWN":
+        if (exp_ok or ignition5m or micro_up) and mom > 0 and (ema_up or trend_master == 'UP' or t15 == 'UP') and (bos_up or pre_bos_up or ignition5m or micro_up):
+            side = 'BUY'
+        elif (exp_ok or ignition5m or micro_dn) and mom < 0 and (ema_dn or trend_master == 'DOWN' or t15 == 'DOWN') and (bos_dn or pre_bos_dn or ignition5m or micro_dn):
+            side = 'SELL'
+    elif (exp_ok or ignition5m or micro_up) and mom > 0 and (ema_up or trend_master == 'UP') and (t15 != 'DOWN') and (bos_up or pre_bos_up or ignition5m or micro_up):
+        side = 'BUY'
+    elif (exp_ok or ignition5m or micro_dn) and mom < 0 and (ema_dn or trend_master == 'DOWN') and (t15 != 'UP') and (bos_dn or pre_bos_dn or ignition5m or micro_dn):
+        side = 'SELL'
+    if side == 'BUY' and t1h == 'DOWN':
         if not ((exp_ok or ignition5m or micro_up) and mom > (0.002 if is_memecoin else 0.0015)):
             side = None
-    elif side == "SELL" and t1h == "UP":
-        if not ((exp_ok or ignition5m or micro_dn) and (-mom) > (0.002 if is_memecoin else 0.0015)):
+    elif side == 'SELL' and t1h == 'UP':
+        if not ((exp_ok or ignition5m or micro_dn) and -mom > (0.002 if is_memecoin else 0.0015)):
             side = None
-
     if side is None:
-        reason = "no_momentum_alignment" if exp_ok else "no_expansion"
-        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps(
-            {"agent": NAME, "tf": tf, "event": "veto", "reason": reason,
-             "exp_ok": exp_ok, "mom": mom, "bos_up": bos_up, "bos_dn": bos_dn,
-             "ema_up": ema_up, "ema_dn": ema_dn}
-        ))
-        return None
-
-    # Late-chase veto; allow re-arm only after a tiny pullback
+        reason = 'no_momentum_alignment' if exp_ok else 'no_expansion'
+        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps({'agent': NAME, 'tf': tf, 'event': 'veto', 'reason': reason, 'exp_ok': exp_ok, 'mom': mom, 'bos_up': bos_up, 'bos_dn': bos_dn, 'ema_up': ema_up, 'ema_dn': ema_dn}))
+        return None
     if _too_late_from_breakout(side, price, prev_hi, prev_lo, atr, is_memecoin):
         if not _recent_micro_pullback(df5m, atr):
-            print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps(
-                {"agent": NAME, "tf": tf, "event": "veto", "reason": "late_chase", "atr": atr}
-            ))
+            print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps({'agent': NAME, 'tf': tf, 'event': 'veto', 'reason': 'late_chase', 'atr': atr}))
             return None
-
-    # Mean-band guard after direction is chosen (softened if ignition/micro)
-    if _mean_guard(side, during_ignition=(ignition5m or micro_up or micro_dn)):
-        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps(
-            {"agent": NAME, "tf": tf, "event": "veto", "reason": "mean_guard",
-             "side": side, "price": price, "ema99": ema99, "st": st_val}
-        ))
-        return None
-
+    if _mean_guard(side, during_ignition=ignition5m or micro_up or micro_dn):
+        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps({'agent': NAME, 'tf': tf, 'event': 'veto', 'reason': 'mean_guard', 'side': side, 'price': price, 'ema99': ema99, 'st': st_val}))
+        return None
     breakout_score = _detect_breakout_quality(df5m, side, prev_hi, prev_lo)
-
-    # Stop-entry confirmation (same as original)
-    entry_type = "limit"
+    entry_type = 'limit'
     entry = price
     entry_stop = None
     if USE_STOP:
-        if side == "BUY":
+        if side == 'BUY':
             trigger = max(price, prev_hi + STOP_BUF_ATR * atr) if prev_hi > 0 else price
         else:
             trigger = min(price, prev_lo - STOP_BUF_ATR * atr) if prev_lo > 0 else price
-        entry_type = "stop"
+        entry_type = 'stop'
         entry_stop = trigger
         entry = trigger
-
-    # Structure-aware SL (same as original)
-    if side == "BUY":
-        sl_struct = min(lo, o) - 0.20 * atr
-        sl_floor  = price - 0.90 * atr
+    if side == 'BUY':
+        sl_struct = min(lo, o) - 0.2 * atr
+        sl_floor = price - 0.9 * atr
         sl = min(sl_struct, sl_floor)
         if pre_bos_up:
             sl = min(sl, price - 0.85 * atr)
     else:
-        sl_struct = max(hi, o) + 0.20 * atr
-        sl_floor  = price + 0.90 * atr
+        sl_struct = max(hi, o) + 0.2 * atr
+        sl_floor = price + 0.9 * atr
         sl = max(sl_struct, sl_floor)
         if pre_bos_dn:
             sl = max(sl, price + 0.85 * atr)
-
     rr_base = 1.8 if is_memecoin else 2.0
-    rr_boost = 0.2 if (breakout_score > 0.2 or tight_consolidation) else 0.0
+    rr_boost = 0.2 if breakout_score > 0.2 or tight_consolidation else 0.0
     rr = rr_base + rr_boost
-
-    # Original RR TP
-    tp_rr = price + rr * abs(price - sl) if side == "BUY" else price - rr * abs(price - sl)
-
-    # OPTIONAL QuickTP: only used if provided in ctx; otherwise identical behavior
+    tp_rr = price + rr * abs(price - sl) if side == 'BUY' else price - rr * abs(price - sl)
     if quick_tp_abs > 0:
-        tp_quick = price + quick_tp_abs if side == "BUY" else price - quick_tp_abs
-        # Take the earlier of the two to secure the scalp
-        tp = min(tp_quick, tp_rr) if side == "BUY" else max(tp_quick, tp_rr)
+        tp_quick = price + quick_tp_abs if side == 'BUY' else price - quick_tp_abs
+        tp = min(tp_quick, tp_rr) if side == 'BUY' else max(tp_quick, tp_rr)
     else:
         tp = tp_rr
-
-    exp_move = abs(tp - price) / max(1e-9, price)
+    exp_move = abs(tp - price) / max(1e-09, price)
     if exp_move < min_move:
-        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps(
-            {"agent": NAME, "tf": tf, "event": "veto", "reason": "expected_move_small",
-             "exp_move": exp_move, "min_move": min_move}
-        ))
-        return None
-
-    # Confidence (original + micro bonus only)
-    surge_strength = min(2.0, vol_now / max(1e-9, vol_med))
-    exp_strength = min(2.0, rng / max(1e-9, atr))
-
-    if side == "BUY":
-        htf_bonus = 0.12 if (trend_master == "UP" and t15 == "UP") else (0.08 if t15 != "DOWN" else 0.0)
-    else:
-        htf_bonus = 0.12 if (trend_master == "DOWN" and t15 == "DOWN") else (0.08 if t15 != "UP" else 0.0)
-
-    ema_bonus = 0.08 if ((side == "BUY" and price > ema_fast > ema_slow) or
-                         (side == "SELL" and price < ema_fast < ema_slow)) else (
-                0.04 if ((side == "BUY" and price > ema_fast) or
-                         (side == "SELL" and price < ema_fast)) else 0.0)
-
+        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps({'agent': NAME, 'tf': tf, 'event': 'veto', 'reason': 'expected_move_small', 'exp_move': exp_move, 'min_move': min_move}))
+        return None
+    surge_strength = min(2.0, vol_now / max(1e-09, vol_med))
+    exp_strength = min(2.0, rng / max(1e-09, atr))
+    if side == 'BUY':
+        htf_bonus = 0.12 if trend_master == 'UP' and t15 == 'UP' else 0.08 if t15 != 'DOWN' else 0.0
+    else:
+        htf_bonus = 0.12 if trend_master == 'DOWN' and t15 == 'DOWN' else 0.08 if t15 != 'UP' else 0.0
+    ema_bonus = 0.08 if side == 'BUY' and price > ema_fast > ema_slow or (side == 'SELL' and price < ema_fast < ema_slow) else 0.04 if side == 'BUY' and price > ema_fast or (side == 'SELL' and price < ema_fast) else 0.0
     consolidation_bonus = 0.05 if tight_consolidation else 0.0
     body_bonus = 0.04 if body_ratio > 0.6 else 0.0
     bos_bonus = 0.06 + breakout_score
-    micro_bonus = micro_score  # small additive bump when 1m thrust present
-
-    raw_conf = (
-        0.62
-        + 0.08 * (surge_strength - 1.0)
-        + 0.10 * (exp_strength - 1.0)
-        + htf_bonus
-        + ema_bonus
-        + bos_bonus
-        + body_bonus
-        + consolidation_bonus
-        + micro_bonus
-        + session_bonus
-    )
+    micro_bonus = micro_score
+    raw_conf = 0.62 + 0.08 * (surge_strength - 1.0) + 0.1 * (exp_strength - 1.0) + htf_bonus + ema_bonus + bos_bonus + body_bonus + consolidation_bonus + micro_bonus + session_bonus
     conf = max(0.0, min(0.95, raw_conf * weight * max(0.6, recent_wr)))
     if conf < thr:
-        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps(
-            {"agent": NAME, "tf": tf, "event": "veto", "reason": "conf_below_threshold",
-             "conf": conf, "thr": thr}
-        ))
-        return None
-
-    # Record cooldown
-    _STATE["last_idx_by_symbol"][symbol] = last_idx
-
-    # Position management parameters (unchanged)
+        print(f'[DEBUG] {NAME} {symbol} :: ' + json.dumps({'agent': NAME, 'tf': tf, 'event': 'veto', 'reason': 'conf_below_threshold', 'conf': conf, 'thr': thr}))
+        return None
+    _STATE['last_idx_by_symbol'][symbol] = last_idx
     move_be_at_r = 0.8 if is_memecoin else 1.0
     trail_activation_r = 0.9 if is_memecoin else 1.2
     partial_tp_r = 0.7 if is_memecoin else 1.0
     partial_size = 0.4 if is_memecoin else 0.3
     time_stop_bars = 8 if is_memecoin else 12
-
-    # TP ladder (unchanged)
     R = abs(price - sl)
     if R <= 0:
         tp_ladder_px = []
         tp_ladder_sz = []
     else:
         base_levels = [1.2, 2.0, 3.0] if breakout_score <= 0.2 else [1.3, 2.2, 3.2]
-        sizes = [0.45, 0.35, 0.20] if is_memecoin else [0.40, 0.35, 0.25]
-        if side == "BUY":
+        sizes = [0.45, 0.35, 0.2] if is_memecoin else [0.4, 0.35, 0.25]
+        if side == 'BUY':
             tp_ladder_px = [price + r * R for r in base_levels]
         else:
             tp_ladder_px = [price - r * R for r in base_levels]
         tp_ladder_sz = sizes
-
-    return {
-        "agent": NAME,
-        "timeframe": tf,
-        "side": side,
-        "confidence": float(conf),
-
-        # entry semantics
-        "entry": float(entry),
-        "entry_type": entry_type,                   # "stop" when confirmation is on
-        "entry_stop": float(entry_stop) if entry_stop is not None else None,
-        "prefer_limit": False if USE_STOP else True,
-        "limit_ticks": 1,
-
-        # targets & protection
-        "sl_hint": float(sl),
-        "tp_hint": float(tp),
-        "sl": float(sl),
-        "tp": float(tp),
-
-        "management": {
-            "move_be_at_r": move_be_at_r,
-            "trail_activation_r": trail_activation_r,
-            "partial_tp_r": partial_tp_r,
-            "partial_size": partial_size,
-            "time_stop_bars": time_stop_bars,
-            "tp_ladder_px": tp_ladder_px,
-            "tp_ladder_sz": tp_ladder_sz
-        },
-        "reason": (
-            f"momentum_pump stop_confirm={int(USE_STOP)} exp={rng/max(1e-9,atr):.2f} "
-            f"rv10={rv10:.3f} rv30={rv30:.3f} htf={trend_master} "
-            f"ign5m={int(ignition5m)} micro1m="
-            f"{'U' if micro_up else ('D' if micro_dn else '0')} "
-            f"{'memecoin=True' if is_memecoin else ''}"
-        )
-    }
+    return {'agent': NAME, 'timeframe': tf, 'side': side, 'confidence': float(conf), 'entry': float(entry), 'entry_type': entry_type, 'entry_stop': float(entry_stop) if entry_stop is not None else None, 'prefer_limit': False if USE_STOP else True, 'limit_ticks': 1, 'sl_hint': float(sl), 'tp_hint': float(tp), 'sl': float(sl), 'tp': float(tp), 'management': {'move_be_at_r': move_be_at_r, 'trail_activation_r': trail_activation_r, 'partial_tp_r': partial_tp_r, 'partial_size': partial_size, 'time_stop_bars': time_stop_bars, 'tp_ladder_px': tp_ladder_px, 'tp_ladder_sz': tp_ladder_sz}, 'reason': f'momentum_pump stop_confirm={int(USE_STOP)} exp={rng / max(1e-09, atr):.2f} rv10={rv10:.3f} rv30={rv30:.3f} htf={trend_master} ign5m={int(ignition5m)} micro1m={('U' if micro_up else 'D' if micro_dn else '0')} {('memecoin=True' if is_memecoin else '')}'}
```