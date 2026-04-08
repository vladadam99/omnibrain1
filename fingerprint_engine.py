
# -*- coding: utf-8 -*-
"""
Fingerprint v2.1 - Rich features (LIQ, ATR MAs, Expected Move), hard override/veto.
ASCII-safe version (no fancy dashes or unicode).

Public API:
- make_live_fingerprint(df5m, symbol, side, ctx) -> dict
- find_best_win_match(F_live, side)
- find_best_loss_match(F_live, side)
- order_from_match(win_rec, F_live) -> executable order dict
- record_fingerprint_on_close(...) (alias: record_fingerprint)
- build_indexes()
"""

import os, json, time, math, threading
from typing import Dict, Any, Optional, List, Tuple

# ---------- config ----------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
WIN_PATH  = os.path.join(BASE_DIR, "fingerprints_wins.jsonl")
LOSS_PATH = os.path.join(BASE_DIR, "fingerprints_losses.jsonl")

WIN_TRIGGER_SIM  = 0.92   # win override threshold
LOSS_VETO_SIM    = 0.90   # loss veto threshold
RECENCY_HALFLIFE_H = 99999999999999999
MAX_PER_BUCKET = 120

# ---------- utils ----------
def _safe(x, d=0.0):
    try:
        v = float(x)
        return v if math.isfinite(v) else d
    except Exception:
        return d

def _clip(x, lo, hi):
    return max(lo, min(hi, _safe(x, 0.0)))

def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b): return 0.0
    sa = math.sqrt(sum(x*x for x in a)); sb = math.sqrt(sum(y*y for y in b))
    if sa <= 1e-12 or sb <= 1e-12: return 0.0
    return sum(x*y for x,y in zip(a,b)) / (sa*sb)

def _recency_w(age_h: float, half_life=RECENCY_HALFLIFE_H) -> float:
    if age_h <= 0: return 1.0
    return 0.5 ** (age_h / max(1e-9, half_life))

def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _jsonl_append(path: str, obj: dict) -> str:
    ts_ms = int(time.time() * 1000)
    seed = f'{obj.get("symbol","")}|{obj.get("side","")}|{obj.get("ts_open","")}'
    short = f"{abs(hash(seed)) & 0xffffffff:08x}"
    fid = f"{ts_ms}-{short}"
    row = dict(obj); row["id"] = fid
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",",":")) + "\n")
    return fid

def _iso_to_epoch(ts_iso: str) -> float:
    try:
        import datetime as dt
        return dt.datetime.strptime(ts_iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp()
    except Exception:
        return time.time()

# ---------- feature schema ----------
FEATURE_KEYS = [
    "ret_1m","ret_3m","ret_5m",
    "rng_atr","body_pct","wick_ratio",
    "atr_pct","atr7_pct","atr14_pct","atr21_pct","atr50_pct",
    "atr_slope14","atr_ema14_pct",
    "vol_ratio","vol_ma20_ratio","vol_z20","vwap_dev",
    "em_1h_rv","em_1h_atr",
    "skew_20_80",
    "trend_15m","trend_1h","trend_master",
    "spread_bps","depth5bps_k","depth10bps_k","impact20k_bps",
    "funding_8h","oi_norm","oi_chg_5m_norm","basis_ann",
]

def _trend_to_num(x: str) -> float:
    s = (x or "SIDEWAYS").upper()
    if s == "UP": return 1.0
    if s == "DOWN": return -1.0
    return 0.0

def _expected_move_from_rv(rv_per_bar: float, bars_ahead: int) -> float:
    return abs(rv_per_bar) * math.sqrt(max(1, bars_ahead))

def _nan_to(x, d=0.0):
    try:
        if x != x: return d
        return x
    except Exception:
        return d

def vectorize(F: Dict[str,Any]) -> List[float]:
    v = [
        _clip(F.get("ret_1m",0.0), -0.05, 0.05),
        _clip(F.get("ret_3m",0.0), -0.12, 0.12),
        _clip(F.get("ret_5m",0.0), -0.20, 0.20),

        _clip(F.get("rng_atr",0.0), 0.0, 3.0),
        _clip(F.get("body_pct",0.0), 0.0, 1.0),
        _clip(F.get("wick_ratio",0.0), 0.0, 3.0),

        _clip(F.get("atr_pct",0.0), 0.0, 0.25),
        _clip(F.get("atr7_pct",0.0), 0.0, 0.25),
        _clip(F.get("atr14_pct",0.0), 0.0, 0.25),
        _clip(F.get("atr21_pct",0.0), 0.0, 0.25),
        _clip(F.get("atr50_pct",0.0), 0.0, 0.25),
        _clip(F.get("atr_slope14",0.0), -0.05, 0.05),
        _clip(F.get("atr_ema14_pct",0.0), 0.0, 0.25),

        _clip(F.get("vol_ratio",1.0), 0.0, 6.0),
        _clip(F.get("vol_ma20_ratio",1.0), 0.0, 6.0),
        _clip(F.get("vol_z20",0.0), -4.0, 4.0),
        _clip(F.get("vwap_dev",0.0), -0.03, 0.03),

        _clip(F.get("em_1h_rv",0.0), 0.0, 0.25),
        _clip(F.get("em_1h_atr",0.0), 0.0, 0.25),

        _clip(F.get("skew_20_80",0.0), -1.0, 1.0),

        _trend_to_num(F.get("trend_15m")),
        _trend_to_num(F.get("trend_1h")),
        _trend_to_num(F.get("trend_master")),

        _clip(F.get("spread_bps",0.0), 0.0, 25.0),
        _clip(F.get("depth5bps_k",0.0), 0.0, 500.0),
        _clip(F.get("depth10bps_k",0.0), 0.0, 1000.0),
        _clip(F.get("impact20k_bps",0.0), 0.0, 20.0),

        _clip(F.get("funding_8h",0.0), -0.05, 0.05),
        _clip(F.get("oi_norm",0.0), 0.0, 1.0),
        _clip(F.get("oi_chg_5m_norm",0.0), -0.2, 0.2),
        _clip(F.get("basis_ann",0.0), -0.5, 0.5),
    ]
    return [float(_nan_to(x, 0.0)) for x in v]

# ---------- live feature build ----------
def make_live_fingerprint(df5m, symbol: str, side: str, ctx: Dict[str,Any]) -> Dict[str,Any]:
    import numpy as np
    F = {
        "symbol": symbol.upper(),
        "timeframe": str(ctx.get("timeframe","5m")),
        "side": side.upper(),
        "agent": str(ctx.get("agent","")).strip() or None,
        "ts_open": _now_iso(),
    }
    if df5m is None or len(df5m) < 60:
        F["vec"] = vectorize({})
        return F

    c = float(df5m["close"].iloc[-1]); o = float(df5m["open"].iloc[-1])
    h = float(df5m["high"].iloc[-1]);  l = float(df5m["low"].iloc[-1])
    rng = max(1e-12, h-l)
    body_pct = abs(c-o)/rng
    upper = max(0.0, h-max(c,o)); lower = max(0.0, min(c,o)-l)
    wick_ratio = (max(upper,lower)/rng) if rng>0 else 0.0

    pc = df5m["close"].shift(1)
    tr = np.maximum(df5m["high"]-df5m["low"], np.maximum(abs(df5m["high"]-pc), abs(df5m["low"]-pc)))
    atr7  = float(tr.rolling(7).mean().iloc[-1])
    atr14 = float(tr.rolling(14).mean().iloc[-1])
    atr21 = float(tr.rolling(21).mean().iloc[-1])
    atr50 = float(tr.rolling(50).mean().iloc[-1])
    atr_ema14 = float(tr.ewm(span=14, adjust=False).mean().iloc[-1])
    atr_slope14 = float((tr.rolling(14).mean().diff().iloc[-1] or 0.0) / max(1e-9,c))

    atr = _safe(ctx.get("risk",{}).get("atr"), 0.0) or atr14
    atr_pct = atr / max(1e-9, c)
    atr7_pct, atr14_pct, atr21_pct, atr50_pct = [x/max(1e-9,c) for x in (atr7,atr14,atr21,atr50)]
    atr_ema14_pct = atr_ema14 / max(1e-9, c)

    vol_now = float(df5m["volume"].iloc[-1])
    vol_ma20 = float(df5m["volume"].rolling(20).mean().iloc[-1] or 1.0)
    vol_med30 = float(df5m["volume"].tail(30).median() or 1.0)
    vol_ratio = vol_now / max(1e-9, vol_med30)
    vol_ma20_ratio = vol_now / max(1e-9, vol_ma20)
    vol_std20 = float(df5m["volume"].rolling(20).std().iloc[-1] or 1.0)
    vol_z20 = (vol_now - vol_ma20) / max(1e-9, vol_std20)

    w = min(240, len(df5m))
    pv = (df5m["close"].tail(w) * df5m["volume"].tail(w)).sum()
    vv = max(1e-9, df5m["volume"].tail(w).sum())
    vwap = float(pv / vv)
    vwap_dev = (c - vwap) / max(1e-9, vwap)

    lr = np.log(df5m["close"]).diff()
    rv_per_bar = float(lr.tail(30).std() or 0.0)
    em_1h_rv = _expected_move_from_rv(rv_per_bar, bars_ahead=12)
    em_1h_atr = atr_pct * math.sqrt(12)

    q20 = float(lr.tail(96).quantile(0.2) or 0.0)
    q80 = float(lr.tail(96).quantile(0.8) or 0.0)
    skew_20_80 = _clip((q80 - abs(q20)) / (abs(q80) + abs(q20) + 1e-9), -1.0, 1.0)

    liq = ctx.get("liq", {}) or {}
    spread_bps    = _safe(liq.get("spread_bps"), 0.0)
    depth5bps_k   = _safe(liq.get("depth_5bps_usd"), 0.0) / 1000.0
    depth10bps_k  = _safe(liq.get("depth_10bps_usd"), 0.0) / 1000.0
    impact20k_bps = _safe(liq.get("impact_20k_bps"), 0.0)

    deriv = ctx.get("deriv", {}) or {}
    funding_8h  = _safe(deriv.get("funding_8h"), 0.0)
    oi_usd      = _safe(deriv.get("oi_usd"), 0.0)
    oi_chg_5m   = _safe(deriv.get("oi_chg_5m"), 0.0)
    basis_ann   = _safe(deriv.get("basis_annualized"), 0.0)
    dollar_turnover = float((df5m["close"]*df5m["volume"]).rolling(288).sum().iloc[-1] or 1.0)
    oi_norm = min(1.0, oi_usd / max(1e-9, dollar_turnover))
    oi_chg_5m_norm = _clip(oi_chg_5m / max(1e-9, oi_usd + 1e5), -0.2, 0.2)

    trend_15m = str(ctx.get("trend_15m","SIDEWAYS")).upper()
    trend_1h  = str(ctx.get("trend_1h","SIDEWAYS")).upper()
    trend_master = str(ctx.get("trend_hint","SIDEWAYS")).upper()

    ret_1m = float(df5m["close"].pct_change().iloc[-1] or 0.0)
    ret_3m = float(df5m["close"].pct_change(3).iloc[-1] or 0.0)
    ret_5m = float(df5m["close"].pct_change(5).iloc[-1] or 0.0)
    rng_atr = (h - l) / max(1e-9, atr)

    F.update({
        "price": c,
        "atr": atr,
        "ret_1m": ret_1m, "ret_3m": ret_3m, "ret_5m": ret_5m,
        "rng_atr": rng_atr, "body_pct": body_pct, "wick_ratio": wick_ratio,

        "atr_pct": atr_pct, "atr7_pct": atr7_pct, "atr14_pct": atr14_pct,
        "atr21_pct": atr21_pct, "atr50_pct": atr50_pct,
        "atr_slope14": atr_slope14, "atr_ema14_pct": atr_ema14_pct,

        "vol_ratio": vol_ratio, "vol_ma20_ratio": vol_ma20_ratio,
        "vol_z20": vol_z20, "vwap_dev": vwap_dev,

        "em_1h_rv": em_1h_rv, "em_1h_atr": em_1h_atr,
        "skew_20_80": skew_20_80,

        "trend_15m": trend_15m, "trend_1h": trend_1h, "trend_master": trend_master,

        "spread_bps": spread_bps, "depth5bps_k": depth5bps_k,
        "depth10bps_k": depth10bps_k, "impact20k_bps": impact20k_bps,

        "funding_8h": funding_8h, "oi_norm": oi_norm,
        "oi_chg_5m_norm": oi_chg_5m_norm, "basis_ann": basis_ann,
    })

    hint = ctx.get("order_hint") or {}
    if hint:
        atr_here = max(1e-9, atr)
        F["template"] = {
            "entry_type": hint.get("entry_type","limit"),
            "entry_price": _safe(hint.get("entry"), c),
            "sl_price": _safe(hint.get("sl"), 0.0),
            "tp_price": _safe(hint.get("tp"), 0.0),
            "sl_mult_atr": _safe(hint.get("sl_mult_atr"),
                                 abs(_safe(hint.get("entry"),c)-_safe(hint.get("sl"),c))/atr_here),
            "tp_mult_atr": _safe(hint.get("tp_mult_atr"),
                                 abs(_safe(hint.get("tp"),c)-_safe(hint.get("entry"),c))/atr_here),
            "stop_buf_atr": _safe(hint.get("stop_buf_atr"), 0.10),
        }

    if "exec" in ctx:
        F["exec"] = ctx["exec"]

    F["vec"] = vectorize(F)
    return F

# ---------- index & matching ----------
_index_built = False
index_wins: Dict[str,List[dict]] = {}
index_losses: Dict[str,List[dict]] = {}
_lock = threading.Lock()

def _bucket_key(symbol: str, side: str, timeframe: str) -> str:
    return f"{symbol.upper()}|{side.upper()}|{timeframe}"

def _load_jsonl(path: str) -> List[dict]:
    out = []
    if not os.path.exists(path): return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if line:
                try: out.append(json.loads(line))
                except: pass
    return out

def _add_to_index(row: dict):
    sym = (row.get("symbol") or "").upper()
    tfs = row.get("timeframe") or ["5m"]
    side = (row.get("side") or "").upper()
    tf = tfs[0] if isinstance(tfs, list) else str(tfs)
    key = _bucket_key(sym, side, tf)

    vec = vectorize((row.get("features_open") or {}))
    ts  = row.get("ts_open") or row.get("ts") or row.get("ts_close") or _now_iso()
    age_h = max(0.0, (time.time() - _iso_to_epoch(ts))/3600.0)
    rec = {
        "vec": vec,
        "age_h": age_h,
        "template": row.get("template") or {
            "entry_type":"limit",
            "sl_mult_atr": row.get("sl_mult_atr"),
            "tp_mult_atr": row.get("tp_mult_atr"),
            "stop_buf_atr": 0.10,
        }
    }
    target = index_wins if (row.get("outcome") == "WIN") else index_losses
    arr = target.setdefault(key, [])
    arr.append(rec)
    arr.sort(key=lambda r: r["age_h"])
    if len(arr) > MAX_PER_BUCKET:
        del arr[:-MAX_PER_BUCKET]

def build_indexes() -> None:
    global _index_built, index_wins, index_losses
    with _lock:
        index_wins, index_losses = {}, {}
        for row in _load_jsonl(WIN_PATH):
            row["outcome"] = "WIN"; _add_to_index(row)
        for row in _load_jsonl(LOSS_PATH):
            row["outcome"] = "LOSS"; _add_to_index(row)
        _index_built = True

def _best(index: Dict[str,List[dict]], F_live: dict) -> Tuple[Optional[dict], float]:
    if not _index_built: build_indexes()
    key = _bucket_key(F_live.get("symbol",""), F_live.get("side",""), F_live.get("timeframe","5m"))
    vec = F_live.get("vec") or vectorize(F_live)
    best = None; best_s = 0.0
    for rec in index.get(key, []):
        s = _cosine(vec, rec["vec"]) * _recency_w(rec["age_h"])
        if s > best_s:
            best_s = s; best = rec
    return best, float(best_s)

def find_best_win_match(F_live: dict, side: str):
    F_live = dict(F_live or {}); F_live["side"] = side.upper()
    return _best(index_wins, F_live)

def find_best_loss_match(F_live: dict, side: str):
    F_live = dict(F_live or {}); F_live["side"] = side.upper()
    return _best(index_losses, F_live)

# ---------- persistence on close ----------
def record_fingerprint_on_close(*,
        symbol: str, side: str, timeframe: str, agent: Optional[str],
        entry_price: float, exit_price: float, qty: float, pnl: float,
        ts_open_iso: Optional[str], features_open: Optional[Dict[str,Any]] = None,
        leverage: Optional[float] = None, sl_price: Optional[float] = None,
        tp_price: Optional[float] = None, reason: Optional[float] = None
    ) -> Dict[str,Any]:
    is_win = pnl >= 0.0
    atr_open = _safe((features_open or {}).get("atr"), 0.0)
    sl_mult = tp_mult = None
    if atr_open > 0 and entry_price:
        if sl_price: sl_mult = abs(entry_price - sl_price)/atr_open
        if tp_price: tp_mult = abs(tp_price - entry_price)/atr_open

    row = {
        "symbol": symbol.upper(), "side": side.upper(),
        "timeframe": [timeframe], "agent": agent,
        "ts_open": ts_open_iso or _now_iso(), "ts_close": _now_iso(),
        "entry_price": _safe(entry_price), "exit_price": _safe(exit_price),
        "qty": _safe(qty), "pnl": _safe(pnl), "leverage": _safe(leverage, 0.0),
        "sl_price": _safe(sl_price, 0.0), "tp_price": _safe(tp_price, 0.0),
        "sl_mult_atr": sl_mult, "tp_mult_atr": tp_mult,
        "features_open": features_open or {},
        "template": (features_open or {}).get("template"),
        "exec": (features_open or {}).get("exec"),
        "outcome": "WIN" if is_win else "LOSS",
        "reason": reason or "",
    }
    fid = _jsonl_append(WIN_PATH if is_win else LOSS_PATH, row)
    row["id"] = fid
    try: _add_to_index(row)
    except: pass
    return row

record_fingerprint = record_fingerprint_on_close

# ---------- order synthesis (override) ----------
def order_from_match(win_rec: dict, F_live: dict) -> Dict[str,Any]:
    c = _safe((F_live or {}).get("price"), 0.0)
    live_atr = max(1e-9, _safe((F_live or {}).get("atr"), 0.0))
    em1h_rv = _safe((F_live or {}).get("em_1h_rv"), 0.0)
    em1h_atr = _safe((F_live or {}).get("em_1h_atr"), 0.0)
    em1h = max(em1h_rv, em1h_atr)
    side = (F_live.get("side") or "BUY").upper()

    tmpl = (win_rec or {}).get("template") or {}
    sl_mult = _safe(tmpl.get("sl_mult_atr"), 1.0)
    tp_mult = _safe(tmpl.get("tp_mult_atr"), 2.0)
    stop_buf = _safe(tmpl.get("stop_buf_atr"), 0.10)
    entry_type = tmpl.get("entry_type","limit")

    # Cap TP by expected move envelope
    denom = (live_atr / max(1e-9, c))
    tp_cap = max(0.5, min(tp_mult, (em1h / denom) if denom > 0 else tp_mult))

    if entry_type == "stop":
        entry = c + stop_buf * live_atr if side=="BUY" else c - stop_buf * live_atr
    else:
        entry = c

    if side == "BUY":
        sl = entry - sl_mult * live_atr
        tp = entry + tp_cap * live_atr
    else:
        sl = entry + sl_mult * live_atr
        tp = entry - tp_cap * live_atr

    return {
        "entry_type": "stop" if entry_type=="stop" else "limit",
        "entry": float(entry), "sl": float(sl), "tp": float(tp), "side": side
    }
