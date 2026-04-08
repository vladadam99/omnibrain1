# -*- coding: utf-8 -*-
"""
Agent sanity runner for Omnibrain.

Usage:
  python agent_sanity_check.py --symbol ASTERUSDT --tf 5m --limit 1200 --verbose
  python agent_sanity_check.py --symbol ASTERUSDT --tf 5m --limit 1200 --verbose --loose
  python agent_sanity_check.py --symbol KAITOUSDT --agents momentum,microburst --verbose

Notes:
- Agents are loaded from ./agents/*.py
- Uses Binance Futures public klines (no auth)
- 'Loose' mode relaxes gates via context for testing (does NOT edit agent files)
"""

import os, sys, argparse, time, json, types, tokenize, requests
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

BINANCE_FAPI = "https://fapi.binance.com"

# ---------------------- tolerant module loader ----------------------
def load_module_from_path(name: str, path: str):
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            return mod
    except UnicodeDecodeError:
        pass
    except Exception as e:
        print(f"- {name}: import error -> {e}")
        return None
    try:
        try:
            with tokenize.open(path) as f:
                src = f.read()
        except Exception:
            raw = open(path, "rb").read()
            src = raw.decode("utf-8", errors="replace")
        trans = {
            "\u2018": "'", "\u2019": "'", "\u201C": '"', "\u201D": '"',
            "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00A0": " ",
        }
        for k, v in trans.items():
            src = src.replace(k, v)
        mod = types.ModuleType(name)
        mod.__file__ = path
        code = compile(src, path, "exec")
        exec(code, mod.__dict__)
        return mod
    except Exception as e:
        print(f"- {name}: tolerant import failed -> {e}")
        return None

# ---------------------- data utilities ----------------------
def fetch_klines(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    url = f"{BINANCE_FAPI}/fapi/v1/klines"
    params = {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}
    r = requests.get(url, params=params, timeout=12)
    r.raise_for_status()
    data = r.json()
    cols = [
        "open_time","open","high","low","close","volume",
        "close_time","qav","trades","tbb","tbq","ignore"
    ]
    df = pd.DataFrame(data, columns=cols)
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df[["open","high","low","close","volume","open_time","close_time"]].reset_index(drop=True)

def _ema(s: pd.Series, span: int) -> float:
    if s is None or len(s) < max(3, span):
        return float(s.iloc[-1]) if len(s) else 0.0
    return float(s.ewm(span=span, adjust=False).mean().iloc[-1])

def _atr(df: pd.DataFrame, n: int = 14) -> float:
    if df is None or len(df) < n + 2:
        return 0.0
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = pd.Series(tr).rolling(n).mean().iloc[-1]
    return float(atr) if np.isfinite(atr) else 0.0

def trend_hint_from_df(df: pd.DataFrame) -> str:
    if df is None or len(df) < 30:
        return "SIDEWAYS"
    ema9 = df["close"].ewm(span=9, adjust=False).mean()
    ema21 = df["close"].ewm(span=21, adjust=False).mean()
    up = ema9.iloc[-1] > ema21.iloc[-1]
    s_now = ema21.iloc[-1]
    s_prev = ema21.iloc[-11] if len(ema21) > 11 else ema21.iloc[0]
    slope_up = (s_now - s_prev) > 0
    slope_dn = (s_now - s_prev) < 0
    if up and slope_up:
        return "UP"
    if (not up) and slope_dn:
        return "DOWN"
    return "SIDEWAYS"

# ---------------------- agent registry ----------------------
DEFAULT_AGENT_FILES = {
    "momentum":   ("apex_momentum_pump",       "apex_momentum_pump.py"),
    "microburst": ("apex_microburst",          "apex_microburst.py"),
    "supertrend": ("apex_supertrend_adaptive", "apex_supertrend_adaptive.py"),
    "sweep":      ("apex_sweep_reversal_v2",   "apex_sweep_reversal_v2.py"),
    "vwap":       ("apex_vwap_pullback",       "apex_vwap_pullback.py"),
}

def discover_agents(agents_dir: str, wanted: Optional[List[str]] = None):
    agents = []
    to_use = wanted or list(DEFAULT_AGENT_FILES.keys())
    for key in to_use:
        mod_name, fname = DEFAULT_AGENT_FILES.get(key, (None, None))
        if not mod_name:
            print(f"! unknown agent key '{key}', skipping")
            continue
        full = os.path.join(agents_dir, fname)
        if not os.path.isfile(full):
            print(f"! missing file: {full}")
            continue
        mod = load_module_from_path(mod_name, full)
        if not mod or not hasattr(mod, "generate_signal"):
            print(f"! failed to load or no generate_signal(): {fname}")
            continue
        agents.append((key, mod))
    return agents

# ---------------------- ctx wiring ----------------------
def base_conf_map(loose: bool) -> Dict[str, float]:
    # baseline thresholds; --loose relaxes ~0.05
    d = {
        "momentum":   0.70,
        "microburst": 0.80,
        "supertrend": 0.72,
        "sweep":      0.75,
        "vwap":       0.78,
    }
    if loose:
        for k in d:
            d[k] = max(0.50, d[k] - 0.05)
    return d

def agent_specific_params(agent_key: str, loose: bool, symbol: str) -> Dict[str, Any]:
    """Return a params dict merged into ctx for specific agents when --loose is ON."""
    if not loose:
        return {}
    if agent_key == "microburst":
        return {
            "params": {
                "USE_STOP": False,
                "VOL_SURGE": 1.02,    # easier volume confirmation
                "EXP_MIN_ATR": 0.50,  # slightly easier expansion
                "COOLDOWN_BARS": 1
            }
        }
    if agent_key == "vwap":
        # widen distance window around VWAP so it can act in trends during tests
        return {
            "only_win_mode": False,          # allow exploration
            "min_band_dist": 0.12,
            "max_band_dist": 2.00,           # was ~1.0–1.2; allow further away in tests
            "min_quality": 0.65,
            "min_ev_r": 0.12
        }
    if agent_key == "supertrend":
        # no special loosening beyond conf; band/cross logic is internal
        return {}
    if agent_key == "momentum":
        return {
            "min_expected_move": 0.005
        }
    if agent_key == "sweep":
        return {
            "min_expected_move": 0.006
        }
    return {}

def build_ctx(symbol: str, df5m: pd.DataFrame, df15: pd.DataFrame, df1h: pd.DataFrame, agent_key: str, loose: bool) -> Dict[str, Any]:
    conf_map = base_conf_map(loose)
    min_move = 0.004 if loose else 0.007
    atr14 = _atr(df5m, 14)
    ctx = {
        "timeframe": "5m",
        "conf_threshold": conf_map.get(agent_key, 0.75),
        "min_expected_move": min_move,
        "weight": 1.0,
        "recent_wr": 1.0,
        "trend_hint": trend_hint_from_df(df1h),
        "trend_15m": trend_hint_from_df(df15),
        "trend_1h": trend_hint_from_df(df1h),
        "risk": {"atr": atr14},
    }
    # merge loose params
    extra = agent_specific_params(agent_key, loose, symbol)
    ctx.update(extra)
    return ctx

# ---------------------- runner ----------------------
def run_agents(symbol: str, tf: str, limit: int, agents_dir: str, agent_keys: Optional[List[str]], verbose: bool, loose: bool):
    df5m = fetch_klines(symbol, tf, min(1500, max(120, limit)))
    df15 = fetch_klines(symbol, "15m", 600)
    df1h = fetch_klines(symbol, "1h", 600)

    for d in (df5m, df15, df1h):
        for c in ("open","high","low","close","volume"):
            if c not in d:
                raise RuntimeError("Dataframe missing OHLCV columns.")

    agents = discover_agents(agents_dir, agent_keys)
    if not agents:
        print("No agents loaded. Check agents directory and names.")
        return 2

    print(f"\nSymbol={symbol}  TF={tf}  Bars={len(df5m)}")
    print(f"Trends:  15m={trend_hint_from_df(df15)}  1h={trend_hint_from_df(df1h)}  (hint={trend_hint_from_df(df1h)})")
    print("-"*70)

    exit_code = 0
    for key, mod in agents:
        try:
            ctx = build_ctx(symbol, df5m, df15, df1h, key, loose)
            sig = mod.generate_signal(df5m.copy(), symbol, ctx)
            name = getattr(mod, "NAME", key)
            if sig is None:
                print(f"[{name:<24}] -> NO SIGNAL (veto or conditions not met)")
                continue

            side = sig.get("side")
            conf = sig.get("confidence", float("nan"))
            entry = sig.get("entry")
            sl = sig.get("sl") or sig.get("sl_hint")
            tp = sig.get("tp") or sig.get("tp_hint")
            entry_type = sig.get("entry_type", "market")
            reason = sig.get("reason", "")

            rr = None
            try:
                if side and entry is not None and sl is not None and tp is not None:
                    risk = abs(entry - sl)
                    if risk > 0:
                        rr = abs((tp - entry) / risk)
            except Exception:
                rr = None

            rr_txt = f"{rr:.2f}" if rr is not None else "nan"
            print(f"[{name:<24}] side={side} conf={conf:.3f} entry_type={entry_type} "
                  f"entry={entry:.6f} sl={sl:.6f} tp={tp:.6f} rr~={rr_txt}")
            if verbose and reason:
                print(f"    reason: {reason}")
        except requests.HTTPError as e:
            print(f"[{key}] HTTP error: {e}")
            exit_code = 3
        except Exception as e:
            print(f"[{key}] error: {e}")
            exit_code = 4
    return exit_code

# ---------------------- CLI ----------------------
def parse_args():
    p = argparse.ArgumentParser(description="Run all agents on recent data and print their decisions.")
    p.add_argument("--symbol", required=True, help="e.g. ASTERUSDT")
    p.add_argument("--tf", default="5m", help="Binance kline interval (default: 5m)")
    p.add_argument("--limit", type=int, default=1200, help="Number of bars to fetch (default: 1200)")
    p.add_argument("--agents", default="", help="Comma list: momentum,microburst,supertrend,sweep,vwap (default: all)")
    p.add_argument("--agents-dir", default=os.path.join(os.path.dirname(__file__), "agents"),
                   help="Directory where agent .py files live (default: ./agents)")
    p.add_argument("--verbose", action="store_true", help="Print each agent's reason string")
    p.add_argument("--loose", action="store_true", help="Relax gates/thresholds via ctx for test purposes")
    return p.parse_args()

def main():
    args = parse_args()
    keys = None
    if args.agents.strip():
        keys = [k.strip() for k in args.agents.split(",") if k.strip()]
    agents_dir = os.path.abspath(args.agents_dir)
    if not os.path.isdir(agents_dir):
        print(f"Agents directory not found: {agents_dir}")
        sys.exit(1)
    code = run_agents(args.symbol.upper(), args.tf, args.limit, agents_dir, keys, args.verbose, args.loose)
    sys.exit(code)

if __name__ == "__main__":
    main()
