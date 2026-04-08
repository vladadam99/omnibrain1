# -*- coding: utf-8 -*-
import numpy as np
import builtins
from collections.abc import Iterable

def multi_timeframe_vote(agent_func, symbol, df_dict):
    signals = []
    for tf, df in df_dict.items():
        try:
            try:
                result = agent_func(df, symbol) if 'symbol' in agent_func.__code__.co_varnames else agent_func(df)
            except TypeError as e:
                if (
                    "'<' not supported between instances of 'dict' and 'dict'" in str(e)
                    or "got an unexpected keyword argument" in str(e)
                    or "'tuple' object has no attribute 'get'" in str(e)
                    or "'int' object is not iterable" in str(e)
                ):
                    orig_min = builtins.min
                    orig_max = builtins.max
                    orig_sorted = builtins.sorted

                    def safe_key(x):
                        print(f"[DEBUG][safe_key] Called with {x!r} (type: {type(x)})")
                        try:
                            if isinstance(x, dict):
                                return x.get("confidence", 0)
                            elif isinstance(x, (int, float)):
                                return x
                            elif isinstance(x, tuple):
                                for v in x:
                                    if isinstance(v, (float, int)):
                                        return v
                                return 0
                            elif isinstance(x, Iterable) and not isinstance(x, (str, bytes, dict)):
                                for v in x:
                                    if isinstance(v, (float, int)):
                                        return v
                                return 0
                            return 0
                        except Exception as ex:
                            print(f"[safe_key] Exception: {ex} for x={x!r}")
                            return 0

                    def safe_min(lst, key=None):
                        if not isinstance(lst, Iterable) or isinstance(lst, (str, bytes, dict)):
                            lst = [lst]
                        if key is None:
                            key = safe_key
                        try:
                            return orig_min(lst, key=key)
                        except Exception as ex:
                            print(f"[safe_min] Exception: {ex} for lst={lst!r}")
                            return None

                    def safe_max(lst, key=None):
                        if not isinstance(lst, Iterable) or isinstance(lst, (str, bytes, dict)):
                            lst = [lst]
                        if key is None:
                            key = safe_key
                        try:
                            return orig_max(lst, key=key)
                        except Exception as ex:
                            print(f"[safe_max] Exception: {ex} for lst={lst!r}")
                            return None

                    def safe_sorted(lst, key=None, reverse=False):
                        if not isinstance(lst, Iterable) or isinstance(lst, (str, bytes, dict)):
                            lst = [lst]
                        if key is None:
                            key = safe_key
                        try:
                            return orig_sorted(lst, key=key, reverse=reverse)
                        except Exception as ex:
                            print(f"[safe_sorted] Exception: {ex} for lst={lst!r}")
                            return lst

                    builtins.min, builtins.max, builtins.sorted = safe_min, safe_max, safe_sorted
                    try:
                        result = agent_func(df, symbol) if 'symbol' in agent_func.__code__.co_varnames else agent_func(df)
                    finally:
                        builtins.min, builtins.max, builtins.sorted = orig_min, orig_max, orig_sorted
                else:
                    raise
            if result and isinstance(result, dict) and result.get("side") in ("BUY", "SELL"):
                result = dict(result)
                result["timeframe"] = tf
                signals.append(result)
        except Exception as e:
            print(f"[multi_timeframe_vote] Error for {agent_func.__name__} on {symbol} {tf}: {e}")

    if not signals:
        return None

    sides = [sig["side"] for sig in signals]
    side_counts = {side: sides.count(side) for side in set(sides)}
    dominant_side = max(side_counts, key=side_counts.get)
    agree_count = side_counts[dominant_side]
    confidences = [sig["confidence"] for sig in signals if sig["side"] == dominant_side]
    avg_conf = float(np.mean(confidences)) if confidences else 0.0

    if agree_count >= (len(signals) // 2 + 1):
        reason = f"{dominant_side} on {agree_count}/{len(signals)} timeframes"
        return {
            "symbol": symbol,
            "action": "open",
            "side": dominant_side,
            "confidence": avg_conf,
            "agent": agent_func.__name__,
            "reason": reason,
        }
    return None