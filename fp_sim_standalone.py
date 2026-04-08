# -*- coding: utf-8 -*-
"""
Standalone FP simulator (no file I/O)
- Builds tiny win/loss fingerprint libraries in memory
- Runs the same veto/override logic your bot uses
- Prints PLACE / VETO / OVERRIDE decisions
"""

import math
import time
from math import sqrt

# thresholds (match your engine defaults)
WIN_TRIGGER_SIM = 0.92
LOSS_VETO_SIM   = 0.90
HALF_LIFE_HOURS = 72.0

def _bin(x, step):
    try: return int(round(float(x) / step))
    except Exception: return 0

def _clip(x, a, b):
    try: xv = float(x)
    except Exception: xv = 0.0
    return max(a, min(b, xv))

def _signature_key(F: dict):
    return (
        _bin(F.get("ret_5m",0.0), 0.25),
        _bin(F.get("ma_fast_slope",0.0), 0.25),
        _bin(F.get("vol_z",0.0), 0.5),
        _bin(F.get("atr_pct",0.0), 0.25),
        _bin(F.get("ma_fast_over_slow",1.0)-1.0, 0.0025),
        int(F.get("trend_15m",0)),
        int(F.get("trend_1h",0)),
        int(F.get("pattern_flags",0)) & 0b1111,
    )

def _vectorize(F: dict):
    return [
        _clip(F.get("ret_1m",0.0), -5, 5),
        _clip(F.get("ret_5m",0.0), -10, 10),
        _clip(F.get("ma_fast_slope",0.0), -5, 5),
        _clip(F.get("ma_slow_slope",0.0), -5, 5),
        _clip(F.get("ma_fast_over_slow",1.0), 0.8, 1.2),
        _clip(F.get("atr_pct",0.0), 0, 10),
        _clip(F.get("vol_z",0.0), -5, 5),
        _clip(F.get("wick_ratio",0.0), 0, 3),
        _clip(F.get("body_pct",0.0), 0, 1),
        _clip(F.get("rsi",50.0)/100.0, 0, 1),
        _clip(F.get("stoch_k",50.0)/100.0, 0, 1),
        float(F.get("trend_15m",0)),
        float(F.get("trend_1h",0)),
    ]

def _cosine(a, b):
    num = sum(x*y for x,y in zip(a,b))
    da = sqrt(sum(x*x for x in a))
    db = sqrt(sum(y*y for y in b))
    return 0.0 if da==0 or db==0 else num / da / db

def _recency_w(age_hours: float) -> float:
    return math.exp(-age_hours / HALF_LIFE_HOURS)

# Mock feature shapes
F_BUY  = {
    "ret_1m": 0.2, "ret_5m": 0.8,
    "ma_fast_slope": 0.3, "ma_slow_slope": 0.15,
    "ma_fast_over_slow": 1.01,
    "atr_pct": 1.2, "vol_z": 2.0,
    "wick_ratio": 0.2, "body_pct": 0.6,
    "rsi": 58.0, "stoch_k": 72.0,
    "trend_15m": 1, "trend_1h": 1,
    "pattern_flags": 1,
}
F_SELL = {
    "ret_1m": -0.3, "ret_5m": -0.9,
    "ma_fast_slope": -0.35, "ma_slow_slope": -0.18,
    "ma_fast_over_slow": 0.99,
    "atr_pct": 1.3, "vol_z": 1.7,
    "wick_ratio": 0.25, "body_pct": 0.55,
    "rsi": 42.0, "stoch_k": 28.0,
    "trend_15m": -1, "trend_1h": -1,
    "pattern_flags": 2,
}

# In-memory libraries
index_wins   = {}  # key -> list of entries
index_losses = {}

def _add(idx, _id, side, F, age_hours=0.2):
    e = {
        "id": _id,
        "side": side,
        "vec": _vectorize(F),
        "age_h": age_hours,
    }
    idx.setdefault(_signature_key(F), []).append(e)

# Create 3 example fingerprints
_add(index_wins,   "WIN-BUY-1",  "BUY",  F_BUY,  age_hours=0.2)
_add(index_losses, "LOSS-BUY-1", "BUY",  F_BUY,  age_hours=0.3)
_add(index_wins,   "WIN-SELL-1", "SELL", F_SELL, age_hours=0.4)

def _find_best(idx, F_live, side):
    key = _signature_key(F_live)
    vec = _vectorize(F_live)
    best, best_s = None, 0.0
    for e in idx.get(key, []):
        if e["side"] != side: 
            continue
        s = _cosine(vec, e["vec"]) * _recency_w(e["age_h"])
        if s > best_s:
            best, best_s = e, s
    return best, best_s

def find_best_win_match(F_live, side):   return _find_best(index_wins,   F_live, side)
def find_best_loss_match(F_live, side):  return _find_best(index_losses, F_live, side)

def decide_with_fingerprints(symbol, side_from_agents, F_live):
    # 1) Loss veto
    loss, ls = find_best_loss_match(F_live, side_from_agents)
    if loss and ls >= LOSS_VETO_SIM:
        return "VETO", {"symbol": symbol, "side": side_from_agents, "match_id": loss["id"], "score": round(ls, 4)}

    # 2) Win override
    win_buy,  ws_buy  = find_best_win_match(F_live, "BUY")
    win_sell, ws_sell = find_best_win_match(F_live, "SELL")
    best_side, win, ws = side_from_agents, None, 0.0
    if win_buy  and ws_buy  >= WIN_TRIGGER_SIM: best_side, win, ws = "BUY",  win_buy,  ws_buy
    if win_sell and ws_sell >= WIN_TRIGGER_SIM and ws_sell > ws + 0.02:
        best_side, win, ws = "SELL", win_sell, ws_sell
    if win and best_side != side_from_agents:
        return "OVERRIDE", {"symbol": symbol, "from": side_from_agents, "to": best_side, "match_id": win["id"], "score": round(ws, 4)}

    # 3) Place as usual
    return "PLACE", {
        "symbol": symbol, "side": side_from_agents,
        "loss_score": round(ls or 0.0, 4),
        "winBUY_score": round(ws_buy or 0.0, 4),
        "winSELL_score": round(ws_sell or 0.0, 4),
    }

def show(title, result):
    action, info = result
    if action == "PLACE":
        print(f"[{title}] → PLACE (no strong match) :: scores loss={info['loss_score']:.3f} winBUY={info['winBUY_score']:.3f} winSELL={info['winSELL_score']:.3f}")
    elif action == "VETO":
        print(f"[{title}] → 🛑 VETO {info['side']} match={info['match_id']} score={info['score']:.3f}")
    elif action == "OVERRIDE":
        print(f"[{title}] → 🚀 OVERRIDE {info['from']} → {info['to']} match={info['match_id']} score={info['score']:.3f}")
    else:
        print(f"[{title}] → ERROR {info}")

def main():
    print(f"Thresholds  win≥{WIN_TRIGGER_SIM:.2f}  loss≥{LOSS_VETO_SIM:.2f}  (half-life={HALF_LIFE_HOURS}h)")
    # A: Agent wants BUY; live context == losing BUY ⇒ VETO
    show("A loss veto",    decide_with_fingerprints("TESTUSDT", "BUY",  F_BUY))
    # B: Agent wants BUY; live context == winning SELL ⇒ OVERRIDE to SELL
    show("B win override", decide_with_fingerprints("TESTUSDT", "BUY",  F_SELL))
    # C: Agent wants BUY; unrelated ⇒ PLACE
    F_none = dict(F_BUY); F_none["ret_5m"] = 3.5; F_none["vol_z"] = -3.5
    show("C no match",     decide_with_fingerprints("TESTUSDT", "BUY",  F_none))
    # D: Agent wants SELL; context looks like WIN-BUY ⇒ PLACE (no strong winSELL)
    show("D irrelevant",   decide_with_fingerprints("TESTUSDT", "SELL", F_BUY))

if __name__ == "__main__":
    main()
