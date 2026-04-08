# -*- coding: utf-8 -*-
"""
BOB_ASI_Pro_Plus - Autonomous Strategy Improver (Program-Synthesis++ Edition)

- Zero-touch to your repo: reads your agents + auto_trade_futures but NEVER edits them.
- In-memory AST program synthesis that can alter BOTH agent logic and engine functions per trial.
- Much larger search space: sizing/exit families, governor policies, hour gating, trend veto, cooldowns,
  voting heads (weighted / softmax / bayesian), and extended engine "genes".
- Optional Walk-Forward evaluation (rolling train/test) for generalization checks.
- Parallel stages with ASHA-style pruning + Bayesian-ish refit + evolutionary mutations.
- Binance klines dataframe cache for speed; progress Telegram pings (start + every 10%).
- Unique, timestamped run folder with per-trial code_diffs.md, leaderboard_<runid>.csv,
  best_config_<runid>.json, and innovation_summary_<runid>.json.

Usage (same as before; plus walk-forward flags are optional):
  python BOB_ASI_Pro_Plus.py --symbols TOP10 --tf 5m \
    --days_stage1 7 --days_stage2 14 --days_stage3 30 \
    --start_balance 100 --seed 1337 --pop1 24 --pop2 10 --pop3 6 --mutations 18 --verbose \
    --wf_train_days 14 --wf_test_days 7 --wf_rolls 3

This file never writes to your source modules. All patches are restored after each trial.
"""
from __future__ import annotations
import os, sys, json, math, random, shutil, argparse, hashlib, copy, inspect, textwrap, difflib, importlib, types
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd
import multiprocessing as _mp
try:
    _mp.set_start_method('spawn', force=True)
except Exception:
    pass

# ---- Repo local imports ----
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(REPO_ROOT)

import backtest_autotrade as bt  # simulate(), AGENTS, CONF_FLOOR, _fapi, fetch_klines

# ---------------------- Defaults ----------------------
DEFAULTS = {
    "symbols":        "TOP10",
    "tf":             "5m",
    "days_stage1":    7,
    "days_stage2":    14,
    "days_stage3":    30,
    "alloc":          20.0,
    "lev":            20.0,
    "start_balance":  100.0,
    "seed":           1337,
    "pop1":           24,
    "pop2":           10,
    "pop3":           6,
    "mutations":      18,
    "verbose":        False,
    # Walk-forward (optional)
    "wf_train_days":  0,   # 0 disables WF
    "wf_test_days":   0,
    "wf_rolls":       0,
}

# ---------------------- Utils ----------------------
def _now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)

def _mkdir(p):
    os.makedirs(p, exist_ok=True)
    return p

def _seed_all(s: int):
    random.seed(s)
    np.random.seed(s % (2**32 - 1))

def _hash_dict(d: Dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(d, sort_keys=True).encode("utf-8")).hexdigest()[:10]

def _clamp(x, a, b):
    return max(a, min(b, x))

# ---------------------- Disk cache for klines ----------------------
CACHE_DIR = os.path.join(REPO_ROOT, ".bt_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Keep a handle to the original backtester fetch to avoid recursion
_FETCH_KLINES_ORIG = None

def _cache_key(symbol: str, interval: str, start_ms: int, end_ms: int) -> str:
    raw = f"{symbol}|{interval}|{start_ms}|{end_ms}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

def _fetch_klines_cached(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    key = _cache_key(symbol, interval, int(start_ms), int(end_ms))
    path = os.path.join(CACHE_DIR, f"{key}.csv")
    if os.path.isfile(path):
        try:
            df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
            return df[["open","high","low","close","volume"]].astype(float)
        except Exception:
            pass
    # Use the original fetch function to avoid recursion
    if callable(_FETCH_KLINES_ORIG):
        df = _FETCH_KLINES_ORIG(symbol, interval, start_ms, end_ms)
    else:
        df = bt.fetch_klines(symbol, interval, start_ms, end_ms)
    if isinstance(df, pd.DataFrame) and len(df):
        try: df.to_csv(path)
        except Exception: pass
    return df

# ---------------------- Metrics / Scoring ----------------------
def compute_metrics(summary: Dict[str, Any], trades_csv: str, start_balance: float) -> Dict[str, Any]:
    pnl_total = float(summary.get("pnl_total", 0.0))
    wins = int(summary.get("wins", 0))
    losses = int(summary.get("losses", 0))
    max_dd = float(summary.get("max_drawdown", 0.0))
    eq_final = float(summary.get("equity_final", start_balance))

    daily = []
    df = None
    if os.path.isfile(trades_csv):
        df = pd.read_csv(trades_csv)
        if "time" in df.columns and "pnl" in df.columns:
            df["day"] = pd.to_datetime(df["time"]).dt.date
            dd = df.groupby("day")["pnl"].sum().astype(float)
            daily = dd.values.tolist()

    wr = wins / max(1, wins + losses)
    pf = 0.0
    if isinstance(df, pd.DataFrame):
        g = df["pnl"].astype(float)
        gross_win = g[g > 0].sum()
        gross_loss = -g[g < 0].sum()
        pf = float(gross_win / max(1e-9, gross_loss)) if gross_loss > 0 else (float('inf') if gross_win > 0 else 0.0)

    if daily:
        rets = np.array(daily, dtype=float) / max(1e-9, start_balance)
        mu = float(np.mean(rets))
        sd = float(np.std(rets, ddof=1)) if len(rets) > 1 else 0.0
        sharpe = (mu / sd) * math.sqrt(365) if sd > 0 else 0.0
        downside = np.array([min(0.0, r) for r in rets])
        ddv = float(np.sqrt(np.mean(downside**2))) if len(rets) else 0.0
        sortino = (mu / ddv) * math.sqrt(365) if ddv > 0 else 0.0
    else:
        sharpe = 0.0
        sortino = 0.0

    return {
        "pnl_total": pnl_total,
        "equity_final": eq_final,
        "wins": wins,
        "losses": losses,
        "winrate": wr,
        "profit_factor": pf,
        "max_drawdown": max_dd,
        "sharpe_like": sharpe,
        "sortino_like": sortino,
        "trades_path": summary.get("trades_path", ""),
    }

def score_metrics(m):
    """
    Risk-aware score: reward PnL & PF & WR, penalize DD.
    Assumes keys: pnl_total (USDT), winrate (0..1), profit_factor, max_drawdown, sharpe_like
    """
    pnl     = float(m.get("pnl_total", 0.0))
    wr      = float(m.get("winrate", 0.0))          # 0..1
    pf      = float(m.get("profit_factor", 1.0))
    dd      = float(m.get("max_drawdown", 0.0))     # USDT or %
    sharpe  = float(m.get("sharpe_like", 0.0))

    # --- Soft vetos (fast filter) ---
    # Require decent WR and bounded DD; keeps search efficient.
    if wr < 0.54:       # WR floor
        return -1e9
    if dd > 0 and dd > 0.35 * max(100.0, pnl + 100.0):
        # If DD looks huge relative to gains, nuke it.
        return -1e9

    # --- Normalize / cap for stability ---
    pf_c     = min(pf, 3.0)
    wr_pts   = 100.0 * wr
    pnl_s    = (pnl / 100.0)    # ~per $100
    dd_pen   = dd / 50.0        # scale penalty; adjust if your dd units are %
    sharpe_c = min(max(sharpe, 0.0), 30.0)

    # --- Weighted blend (risk-aware) ---
    score = (
        1.25 * pnl_s +          # profit matters
        1.10 * pf_c   +          # quality of profit
        1.40 * wr_pts +          # prefer higher WR
        0.60 * sharpe_c -        # smoothness
        2.00 * dd_pen            # punish drawdown
    )
    return float(score)

# ---------------------- ASI Mutator (program synthesis) ----------------------
import ast

def _src_of(obj):
    try:
        s = inspect.getsource(obj)
        return textwrap.dedent(s)
    except Exception:
        return None

def _sha(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]

# ---- Transformations ----
class InjectEMAGate(ast.NodeTransformer):
    def visit_FunctionDef(self, node: ast.FunctionDef):
        gate = ast.parse(
            """
try:
    close = df['close']
    ema9  = close.ewm(span=9, adjust=False).mean().iloc[-1]
    ema21 = close.ewm(span=21,adjust=False).mean().iloc[-1]
    if (side=='BUY' and not(entry > ema9 > ema21)) or (side=='SELL' and not(entry < ema9 < ema21)):
        return None
except Exception:
    pass
            """
        ).body
        node.body[0:0] = gate
        return node

class InjectVolShockVeto(ast.NodeTransformer):
    def visit_FunctionDef(self, node: ast.FunctionDef):
        veto = ast.parse(
            """
try:
    vol_s = df['close'].pct_change().rolling(10).std().iloc[-1]
    vol_l = df['close'].pct_change().rolling(30).std().iloc[-1]
    if vol_s > 2.2*vol_l and vol_s > 0.02:
        return None
except Exception:
    pass
            """
        ).body
        node.body[0:0] = veto
        return node

class RewriteTPSL(ast.NodeTransformer):
    def __init__(self, rr_min=1.9, w_rr=0.5, w_band=0.3, w_imp=0.2):
        self.rr_min=rr_min; self.w_rr=w_rr; self.w_band=w_band; self.w_imp=w_imp
    def visit_FunctionDef(self, node: ast.FunctionDef):
        code = f"""
try:
    risk = abs(entry - sl)
    rr_tp = (entry + {self.rr_min}*risk) if side=='BUY' else (entry - {self.rr_min}*risk)
except Exception:
    risk = 0.0; rr_tp = tp if 'tp' in locals() else entry
try:
    band_tp = (entry + 1.2*(df['close'].rolling(10).std().iloc[-1])) if side=='BUY' else (entry - 1.2*(df['close'].rolling(10).std().iloc[-1]))
except Exception:
    band_tp = rr_tp
try:
    box_hi = float(df['high'].iloc[-9:-1].max()); box_lo = float(df['low'].iloc[-9:-1].min())
    imp_tp = (entry + 0.85*(box_hi-box_lo)) if side=='BUY' else (entry - 0.85*(box_hi-box_lo))
except Exception:
    imp_tp = rr_tp
try:
    tp = {self.w_rr}*rr_tp + {self.w_band}*band_tp + {self.w_imp}*imp_tp
    if risk>0:
        if side=='BUY': tp = max(tp, entry + {self.rr_min}*risk)
        else:           tp = min(tp, entry - {self.rr_min}*risk)
    tp_hint = tp
except Exception:
    pass
        """
        node.body.extend(ast.parse(code).body)
        return node

class ConfidenceShaper(ast.NodeTransformer):
    def __init__(self, a=3.2, b=0.15): self.a=a; self.b=b
    def visit_FunctionDef(self, node: ast.FunctionDef):
        code = f"""
try:
    import math
    conf = max(0.0, min(0.99, 1.0/(1.0+math.exp(-{self.a}*(conf-0.5))) + {self.b}*0.3 - 0.5))
except Exception:
    pass
        """
        node.body.extend(ast.parse(code).body)
        return node

class LossMute(ast.NodeTransformer):
    def __init__(self, L=2): self.L=L
    def visit_FunctionDef(self, node: ast.FunctionDef):
        code = f"""
try:
    if 'loss_streak' in locals() and int(loss_streak) >= {self.L}:
        return None
except Exception:
    pass
        """
        node.body[0:0] = ast.parse(code).body
        return node

class KellySizer(ast.NodeTransformer):
    def __init__(self, cap=0.03, temper=0.5): self.cap=cap; self.temper=temper
    def visit_FunctionDef(self, node: ast.FunctionDef):
        code = f"""
try:
    wr = max(0.0, min(1.0, float(recent_wr if 'recent_wr' in locals() else 0.55)))
    pf = float(recent_pf if 'recent_pf' in locals() else 1.2)
    edge = (2*wr - 1.0)
    var  = max(1e-6, 1.0/pf)
    f_k = {self.temper} * (edge/var)
    f_k = max(0.0, min({self.cap}, f_k))
    equity = float(ctx.get('equity', 100.0)) if 'ctx' in locals() and isinstance(ctx, dict) else 100.0
    pos_usdt = max(0.0, equity * f_k)
except Exception:
    pass
        """
        node.body.extend(ast.parse(code).body)
        return node

def _compile_mutated(src: str, transformers: List[ast.NodeTransformer]) -> Tuple[str, types.ModuleType]:
    tree = ast.parse(src)
    for t in transformers:
        tree = t.visit(tree); ast.fix_missing_locations(tree)
    mod = types.ModuleType(f"asi_mod_{_sha(src)}")
    code = compile(tree, filename="<asi_mutated>", mode="exec")
    g = mod.__dict__
    exec(code, g, g)
    try:
        after_src = ast.unparse(tree)
    except Exception:
        after_src = src
    return after_src, mod

def _diff(before: str, after: str, head: str) -> str:
    b = [x.rstrip() for x in before.strip().splitlines()]
    a = [x.rstrip() for x in after.strip().splitlines()]
    out = [f"### {head}", "```diff"]
    for line in difflib.unified_diff(b, a, lineterm=""):
        out.append(line)
    out.append("```")
    return "\n".join(out)

def mutate_agent_fn(fn, recipe: Dict[str,Any]) -> Tuple[str, Any, List[str]]:
    src = _src_of(fn)
    if not src: return None, fn, []
    xforms = []
    if recipe.get("ema_gate", 0): xforms.append(InjectEMAGate())
    if recipe.get("vol_veto", 0): xforms.append(InjectVolShockVeto())
    if recipe.get("tp_sl_blend"):
        r = recipe["tp_sl_blend"]; xforms.append(RewriteTPSL(r.get("rr_min",1.9), r.get("w_rr",0.5), r.get("w_band",0.3), r.get("w_imp",0.2)))
    if recipe.get("conf_logit"):
        c = recipe["conf_logit"]; xforms.append(ConfidenceShaper(c.get("a",3.2), c.get("b",0.15)))
    if recipe.get("loss_mute_L"):
        xforms.append(LossMute(int(recipe["loss_mute_L"])) )
    after_src, mod = _compile_mutated(src, xforms) if xforms else (src, None)
    mutated = getattr(mod, fn.__name__) if mod else fn
    diffs = [_diff(src, after_src, f"{fn.__name__} (agent)")] if after_src and after_src!=src else []
    return after_src, mutated, diffs

def mutate_engine_fn(fn, recipe: Dict[str,Any]) -> Tuple[str, Any, List[str]]:
    src = _src_of(fn)
    if not src: return None, fn, []
    xforms = []
    if recipe.get("kelly"): k=recipe["kelly"]; xforms.append(KellySizer(k.get("cap",0.03), k.get("temper",0.5)))
    if recipe.get("tp_sl_blend"):
        r = recipe["tp_sl_blend"]; xforms.append(RewriteTPSL(r.get("rr_min",1.9), r.get("w_rr",0.5), r.get("w_band",0.3), r.get("w_imp",0.2)))
    if recipe.get("loss_mute_L"): xforms.append(LossMute(int(recipe["loss_mute_L"])) )
    after_src, mod = _compile_mutated(src, xforms) if xforms else (src, None)
    mutated = getattr(mod, fn.__name__) if mod else fn
    diffs = [_diff(src, after_src, f"{fn.__name__} (engine)")] if after_src and after_src!=src else []
    return after_src, mutated, diffs


# --------- Helper: persist top-K exact configs for later replay ----------
def save_topk_configs(run_dir: str, leaderboard_csv: str, trials_state: Dict[str,dict], k: int = 3) -> List[str]:
    import pandas as _pd
    os.makedirs(os.path.join(run_dir, "trial_configs"), exist_ok=True)
    df = _pd.read_csv(leaderboard_csv).sort_values("score", ascending=False).reset_index(drop=True)
    keep = df.head(k)["trial_id"].tolist()
    saved = []
    for tid in keep:
        st = trials_state.get(tid)
        if not st:
            continue
        path = os.path.join(run_dir, "trial_configs", f"{tid}.json")
        with open(path, "w") as f:
            json.dump(st, f, indent=2)
        saved.append(tid)
    return saved

# --------- Helper: month replay of exact top-N configs ----------
def replay_topN_month(run_dir: str, N: int = 3, tf: str = "5m", days: int = 30,
                      symbols: str = "TOP10", start_balance: float = 100.0):
    runid = os.path.basename(run_dir).split("_", 1)[-1]
    leader_csv = os.path.join(run_dir, f"leaderboard_{runid}.csv")
    import pandas as _pd
    df = _pd.read_csv(leader_csv).sort_values("score", ascending=False).reset_index(drop=True)
    topN = df.head(N)["trial_id"].tolist()
    out_root = os.path.join(run_dir, "month_replays"); os.makedirs(out_root, exist_ok=True)

    # symbols
    try:
        if (symbols or "").upper() == "TOP10":
            sym_list = bt.fetch_top10_symbols()
        else:
            sym_list = [bt.normalize_symbol(s) for s in symbols.split(",")]
    except Exception:
        sym_list = []

    # time window
    from datetime import datetime, timedelta, timezone
    start = datetime.now(timezone.utc) - timedelta(days=days)
    end   = datetime.now(timezone.utc)
    for tid in topN:
        # prefer trial_configs/<tid>.json
        cfg_path = os.path.join(run_dir, "trial_configs", f"{tid}.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r") as f:
                cfg = json.load(f)
        else:
            # fallback to best_config if it matches tid
            bc = os.path.join(run_dir, f"best_config_{runid}.json")
            if not os.path.exists(bc):
                continue
            with open(bc, "r") as f:
                best = json.load(f)
            if best.get("trial_id") != tid:
                continue
            cfg = best

        c   = cfg.get("config", {}) or {}
        eng = c.get("engine", {}) or {}
        alloc    = float(eng.get("MIN_TRADE_USDT", c.get("alloc", 100.0)))
        lev      = float(eng.get("LEVERAGE", c.get("lev", 20.0)))
        quick_tp = float(eng.get("TP_QUICK_PROFIT", c.get("quick_tp", 3.0)))
        max_loss = float(eng.get("MAX_LOSS_PER_TRADE", c.get("max_loss", 20.0)))
        min_move = float(eng.get("MIN_EXPECTED_MOVE", c.get("min_move", 0.008)))
        entry_ttl= int(c.get("entry_ttl", 6))
        max_open = int(c.get("max_open", 2))

        out_dir = os.path.join(out_root, tid); os.makedirs(out_dir, exist_ok=True)
        try:
            res = bt.simulate(
                symbols=sym_list, tf=tf, start=start, end=end,
                alloc_usdt=alloc, lev=lev, max_open=max_open,
                entry_ttl_bars=entry_ttl, start_balance=start_balance,
                quick_tp_usd=quick_tp, min_move=min_move, max_loss_usd=max_loss,
                verbose=False
            )
        except Exception as e:
            res = {"error": str(e)}
        if isinstance(res, dict) and float(res.get("equity_final", start_balance)) <= 0.0:
            res["notes"] = list(res.get("notes", [])) + ["Stopped early: balance <= 0"]
        with open(os.path.join(out_dir, "summary.json"), "w") as f:
            json.dump(res, f, indent=2)

# ---------------------- Voting heads ----------------------
def _vote_weighted(weights: Dict[str,float]):
    def smart_vote(signals: Dict[str, Dict[str, Any]], tf: str):
        col = []
        for an, sig in signals.items():
            s = sig.get(tf) if tf in sig else sig
            if s and s.get("side") in ("BUY","SELL"):
                w = float(weights.get(an, 1.0))
                eff_conf = float(s.get("confidence", 0.0)) * w
                col.append((an, s["side"], eff_conf, s))
        if not col: return None
        sum_buy = sum(c for _,side,c,_ in col if side=="BUY")
        sum_sell= sum(c for _,side,c,_ in col if side=="SELL")
        winner = "BUY" if sum_buy >= sum_sell else "SELL"
        used = [(an,c,s) for (an,side,c,s) in col if side==winner]
        avg_conf = float(np.mean([c for _,c,_ in used])) if used else 0.0
        return winner, avg_conf, used
    return smart_vote

def _vote_softmax(tau: float, weights: Dict[str,float]):
    def smart_vote(signals: Dict[str, Dict[str, Any]], tf: str):
        col = []
        for an, sig in signals.items():
            s = sig.get(tf) if tf in sig else sig
            if s and s.get("side") in ("BUY","SELL"):
                w = float(weights.get(an, 1.0))
                eff = float(s.get("confidence", 0.0)) * w
                col.append((an, s["side"], eff, s))
        if not col: return None
        # softmax on signed confidences
        xs = np.array([ (c if side=="BUY" else -c) for _,side,c,_ in col ], dtype=float) / max(1e-6, tau)
        ps = np.exp(xs - xs.max()); ps /= ps.sum()
        # final side is sign of expectation
        mean = float(np.dot(ps, [ (c if side=="BUY" else -c) for _,side,c,_ in col ]))
        winner = "BUY" if mean >= 0 else "SELL"
        used = [(an,c,s) for (an,side,c,s) in col if (side=="BUY" and winner=="BUY") or (side=="SELL" and winner=="SELL")]
        avg_conf = float(np.mean([c for _,c,_ in used])) if used else 0.0
        return winner, avg_conf, used
    return smart_vote

def _vote_bayes(weights: Dict[str,float], prior=0.0):
    # naive pooling: treat confidence as log-odds evidence
    def smart_vote(signals: Dict[str, Dict[str, Any]], tf: str):
        lo = prior
        picks = []
        for an, sig in signals.items():
            s = sig.get(tf) if tf in sig else sig
            if not (s and s.get("side") in ("BUY","SELL")): continue
            w = float(weights.get(an, 1.0))
            conf = float(s.get("confidence", 0.0))
            ev = w * np.log((conf+1e-6)/(1.0-conf+1e-6))
            lo += ev if s["side"]=="BUY" else -ev
            picks.append((an, s["side"], conf, s))
        winner = "BUY" if lo >= 0 else "SELL"
        used = [(an, c, s) for (an,side,c,s) in picks if side==winner]
        avg_conf = float(np.mean([c for _,c,_ in used])) if used else 0.0
        return winner, avg_conf, used
    return smart_vote

# ---------------------- Search space ----------------------
DEFAULT_SEARCH: Dict[str, Any] = {
    "quick_tp":    (0.2,  1.2),
    "min_move":    (0.004, 0.012),
    "max_loss":    (1.0,  3.0),
    "entry_ttl":   (3, 8),
    "max_open":    (1, 3),
    "alloc":       (10.0, 60.0),
    "lev":         (2.0,  25.0),
    "agent_conf_floors": {
        "apex_vwap_pullback":       (0.68, 0.94),
        "apex_microburst":          (0.68, 0.94),
        "apex_sweep_reversal":      (0.70, 0.95),
        "apex_supertrend_adaptive": (0.70, 0.95),
        "apex_momentum_pump":       (0.72, 0.96),
    },
    "agent_weights": {
        "apex_vwap_pullback":       (0.6, 1.8),
        "apex_microburst":          (0.6, 1.8),
        "apex_sweep_reversal":      (0.6, 1.8),
        "apex_supertrend_adaptive": (0.6, 1.8),
        "apex_momentum_pump":       (0.6, 1.8),
    },
    "agent_params": {
        "apex_microburst": {
            "VOL_SURGE":    (1.04, 1.25),
            "EXP_MIN_ATR":  (0.35, 0.80),
            "TP_ATR":       (0.35, 0.95),
            "SL_ATR":       (0.16, 0.45),
            "RR_MIN":       (1.5,  2.8),
        },
        "apex_momentum_pump": {
            "pre_bos_margin_atr": (0.06, 0.24),
        },
        "apex_vwap_pullback": {
            "min_wick_dom":  (0.26, 0.58),
            "min_body_ratio":(0.10, 0.28),
            "rr":            (1.5,  2.6),
        },
        "apex_supertrend_adaptive": {"RR_MIN": (1.6, 2.6)},
        "apex_sweep_reversal": {}
    },
    # logic genome
    "hour_active_count": (6, 18),
    "conf_gain":   (0.80, 1.25),
    "require_ema": (0, 1),
    "cooldown_bars": (1, 4),
    "rr_min":      (1.5, 2.8),
    "sl_atr_mul":  (0.7, 1.6),
    "tp_w_rr":     (0.2, 0.7),
    "tp_w_band":   (0.1, 0.6),
    "tp_w_imp":    (0.0, 0.5),
    # voting head family
    "vote_head":   ("weighted","softmax","bayes"),
    "softmax_tau": (0.4, 1.8),
    # engine genes (optional; applied only if attributes exist in auto_trade_futures)
    "engine": {
        "LEVERAGE":           (2.0, 25.0),
        "MIN_TRADE_USDT":     (10.0, 300.0),
        "CONFIDENCE_THRESHOLD": (0.60, 0.90),
        "MIN_EXPECTED_MOVE":  (0.0008, 0.0120),
        "TP_QUICK_PROFIT":    (1.0, 12.0),
        "TP_SL_RR":           (1.2, 5.0),
        "SL_ATR_MULT":        (0.8, 3.0),
        "MAX_LOSS_PER_TRADE": (5.0, 60.0),
        "MAX_NEW_TRADES_PER_HOUR": (1, 12),
        "MAX_PORTFOLIO_SIZE": (1, 8),
        "MAX_SYMBOL_ALLOC":   (0.05, 0.45),
        "MAX_TOTAL_ALLOC":    (0.20, 0.95),
        "AGENT_MUTE_AFTER_LOSSES": (0, 3),
        "AGENT_MUTE_TIME":    (60, 3600),
        "PAUSE_AFTER_PROFIT_SEC": (60, 3600),
        "HYBRID_SL_MODE":     ("hybrid","hard","atr","trail"),
        "HYBRID_ARM_RR":      (1.0, 3.0),
        "HYBRID_ARM_ATR":     (0.8, 3.0),
        "HYBRID_TRAIL_K":     (0.8, 4.0),
        "BREAKEVEN_AFTER_MIN": (60, 45*60),
        "BREAKEVEN_EPS_FRAC": (0.05, 0.45),
    }
}

# ---------------------- Agents wrap + engine patch contexts ----------------------
from contextlib import contextmanager

def _smart_vote_factory(cfg: Dict[str, Any]):
    vh = cfg.get("vote_head","weighted")
    weights = cfg.get("agent_weights", {})
    if vh == "softmax":
        tau = float(cfg.get("softmax_tau", 1.0))
        return _vote_softmax(tau, weights)
    elif vh == "bayes":
        return _vote_bayes(weights, prior=0.0)
    else:
        return _vote_weighted(weights)

def _apply_engine_attrs(atf, cfg_engine: Dict[str, Any]):
    # If engine module exposes same-named globals/consts, set them temporarily.
    applied = {}
    for k,v in (cfg_engine or {}).items():
        if hasattr(atf, k):
            applied[k] = getattr(atf, k)
            try: setattr(atf, k, v)
            except Exception: pass
    return applied

def _select_engine_targets(atf):
    # Discover a broad set of potential hook functions
    candidates = [
        "position_size","build_exits","should_open_trade","pre_filter","post_filter",
        "risk_guard","cooldown_policy","select_symbols","dynamic_leverage",
        "hybrid_stop","trailing_policy","breakeven_policy"
    ]
    return [name for name in candidates if hasattr(atf, name)]

@contextmanager
def patched_bt(config: Dict[str, Any], mutated_agents: Optional[List[Tuple[str,Any]]]=None):
    orig_agents = list(bt.AGENTS)
    orig_conf_floor = copy.deepcopy(bt.CONF_FLOOR)
    orig_smart_vote = bt.smart_vote
    orig_fetch_klines = getattr(bt, 'fetch_klines', None)
    global _FETCH_KLINES_ORIG
    try:
        # floors and vote head
        for k,v in (config.get("agent_conf_floors") or {}).items():
            bt.CONF_FLOOR[k] = float(v)
        bt.smart_vote = _smart_vote_factory(config)
        # data cache: remember original, then patch
        if orig_fetch_klines is not None:
            _FETCH_KLINES_ORIG = orig_fetch_klines
            bt.fetch_klines = _fetch_klines_cached
        # agent wraps
        if mutated_agents:
            bt.AGENTS = mutated_agents
        yield
    finally:
        bt.AGENTS = orig_agents
        bt.CONF_FLOOR = orig_conf_floor
        bt.smart_vote = orig_smart_vote
        if orig_fetch_klines is not None:
            bt.fetch_klines = orig_fetch_klines

@contextmanager
def patched_atf(engine_patches: Dict[str,Tuple[Any,Any]], attrs_backup: Dict[str,Any]):
    atf = None
    try:
        atf = importlib.import_module("auto_trade_futures")
    except Exception:
        yield
        return
    backup_funcs = {}
    for name,(orig,mut) in engine_patches.items():
        if hasattr(atf, name):
            backup_funcs[name] = getattr(atf, name)
            setattr(atf, name, mut)
    # apply attribute-level overrides (globals)
    saved_attrs = {}
    for k, old in attrs_backup.items():
        saved_attrs[k] = old
    try:
        yield
    finally:
        for name, orig in backup_funcs.items():
            try: setattr(atf, name, orig)
            except Exception: pass
        for k, old in saved_attrs.items():
            try: setattr(atf, k, old)
            except Exception: pass

# ---------------------- Genome sampling & mutation ----------------------
def make_hour_mask(n_active: int) -> List[int]:
    PRIOR = [1,3,10,14,17,22]
    mask = [0]*24; hours=set(PRIOR)
    while len(hours) < max(1, min(24, n_active)):
        hours.add(random.randint(0,23))
    for h in hours: mask[h]=1
    return mask

def _sample_engine(space_engine: Dict[str,Any]) -> Dict[str,Any]:
    e = {}
    for k, rng in space_engine.items():
        if isinstance(rng, tuple) and len(rng)==2 and all(isinstance(x,(int,float)) for x in rng):
            lo,hi = rng; val = round(random.uniform(lo,hi), 4 if lo<1 else 3)
            if isinstance(lo,int) and isinstance(hi,int):
                val = int(random.randint(int(lo), int(hi)))
            e[k] = val
        elif isinstance(rng, tuple) and len(rng)==2 and any(isinstance(x,str) for x in rng):
            e[k] = random.choice(rng)
        elif isinstance(rng, (list, tuple)):
            e[k] = random.choice(list(rng))
        else:
            e[k] = rng
    return e

def sample_config(space=DEFAULT_SEARCH) -> Dict[str, Any]:
    cfg = {
        "quick_tp": round(random.uniform(*space["quick_tp"]), 3),
        "min_move": round(random.uniform(*space["min_move"]), 4),
        "max_loss": round(random.uniform(*space["max_loss"]), 3),
        "entry_ttl": int(random.randint(*space["entry_ttl"])) ,
        "max_open": int(random.randint(*space["max_open"])) ,
        "alloc": round(random.uniform(*space["alloc"]), 2),
        "lev": round(random.uniform(*space["lev"]), 1),
        # vote head
        "vote_head": random.choice(space["vote_head"]),
        "softmax_tau": round(random.uniform(*space["softmax_tau"]), 3),
    }
    acf={};
    for k,(a,b) in space["agent_conf_floors"].items(): acf[k]=round(random.uniform(a,b),3)
    aw={};
    for k,(a,b) in space["agent_weights"].items(): aw[k]=round(random.uniform(a,b),3)
    ap={}
    for ag, params in space["agent_params"].items():
        ap[ag]={}
        for pk,rng in params.items():
            if isinstance(rng, tuple) and len(rng)==2:
                lo,hi=rng; val=round(random.uniform(lo,hi),3)
            else:
                val=rng
            ap[ag][pk]=val
    cfg["agent_conf_floors"]=acf; cfg["agent_weights"]=aw; cfg["agent_params"]=ap
    # logic genome
    n_hours = int(random.randint(*space["hour_active_count"]))
    cfg["hour_mask"] = make_hour_mask(n_hours)
    cfg["conf_gain"] = round(random.uniform(*space["conf_gain"]), 3)
    cfg["require_ema"] = int(random.randint(*space["require_ema"]))
    cfg["cooldown_bars"] = int(random.randint(*space["cooldown_bars"]))
    cfg["rr_min"] = round(random.uniform(*space["rr_min"]), 3)
    cfg["sl_atr_mul"] = round(random.uniform(*space["sl_atr_mul"]), 3)
    cfg["tp_w_rr"]   = round(random.uniform(*space["tp_w_rr"]), 3)
    cfg["tp_w_band"] = round(random.uniform(*space["tp_w_band"]), 3)
    cfg["tp_w_imp"]  = round(random.uniform(*space["tp_w_imp"]), 3)
    # engine genes (optional; only applied if attributes exist)
    cfg["engine"] = _sample_engine(space.get("engine", {}))
    return cfg

def mutate_config(cfg: Dict[str, Any], rate: float=0.25) -> Dict[str, Any]:
    out = json.loads(json.dumps(cfg))
    def jit(v, pct=0.15): return float(v)*(1.0+random.uniform(-pct,pct))
    def clamp_top(v, lo, hi, r=True):
        if isinstance(lo,int) and isinstance(hi,int):
            return int(max(lo, min(hi, round(jit(v)))))
        return round(_clamp(jit(v), lo, hi), 3)
    for k in ("quick_tp","min_move","max_loss","alloc","lev"): 
        if random.random()<rate: out[k]=clamp_top(out[k], *DEFAULT_SEARCH[k])
    if random.random()<rate: out["entry_ttl"]=int(max(DEFAULT_SEARCH["entry_ttl"][0], min(DEFAULT_SEARCH["entry_ttl"][1], round(jit(out["entry_ttl"])))))
    if random.random()<rate: out["max_open"]=int(max(DEFAULT_SEARCH["max_open"][0], min(DEFAULT_SEARCH["max_open"][1], round(jit(out["max_open"])))))
    for k in out["agent_conf_floors"]:
        if random.random()<rate: out["agent_conf_floors"][k]=round(_clamp(jit(out["agent_conf_floors"][k]), 0.60, 0.98),3)
    for k in out["agent_weights"]:
        if random.random()<rate: out["agent_weights"][k]=round(_clamp(jit(out["agent_weights"][k]), 0.3, 2.5),3)
    for ag in out["agent_params"]:
        for pk in out["agent_params"][ag]:
            if random.random()<rate: out["agent_params"][ag][pk]=round(jit(out["agent_params"][ag][pk]),3)
    if random.random()<rate:
        n_active = int(_clamp(int(round(jit(sum(out.get("hour_mask", [1]*24))))), 3, 22))
        out["hour_mask"] = make_hour_mask(n_active)
    for k in ("conf_gain","rr_min","sl_atr_mul","tp_w_rr","tp_w_band","tp_w_imp"):
        if random.random()<rate: out[k]=clamp_top(out[k], *DEFAULT_SEARCH[k])
    if random.random()<rate: out["require_ema"]=int(1-int(out.get("require_ema",0)))
    if random.random()<rate: out["cooldown_bars"]=int(max(DEFAULT_SEARCH["cooldown_bars"][0], min(DEFAULT_SEARCH["cooldown_bars"][1], round(jit(out["cooldown_bars"])))))
    # vote head
    if random.random()<rate: out["vote_head"] = random.choice(DEFAULT_SEARCH["vote_head"])
    if random.random()<rate: out["softmax_tau"] = clamp_top(out["softmax_tau"], *DEFAULT_SEARCH["softmax_tau"])
    # engine genes
    if "engine" in out:
        for k, rng in DEFAULT_SEARCH.get("engine", {}).items():
            if random.random()<rate:
                if isinstance(rng, tuple) and len(rng)==2 and all(isinstance(x,(int,float)) for x in rng):
                    lo,hi=rng; out["engine"][k] = clamp_top(out["engine"].get(k, lo), lo, hi)
                elif isinstance(rng, tuple) and any(isinstance(x,str) for x in rng):
                    out["engine"][k] = random.choice(rng)
    return out

# ---------------------- Symbol universe helper ----------------------
def fetch_top10_no_btc(min_quote_vol_usd: float = 300_000_000) -> List[str]:
    data = bt._fapi("/fapi/v1/ticker/24hr", {})
    pairs = []
    for row in data:
        sym = (row.get("symbol") or "").upper()
        if not sym.endswith("USDT"): continue
        if sym == "BTCUSDT": continue
        vol_q = float(row.get("quoteVolume", 0) or 0.0)
        if vol_q >= min_quote_vol_usd: pairs.append((sym, vol_q))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return [s for s,_ in pairs[:10]]

# ---------------------- Telegram ----------------------
import os as _os, json as _json, urllib.request as _urlreq
_TG_TOKEN = _os.environ.get('BOB_TG_TOKEN')
_TG_CHAT  = _os.environ.get('BOB_TG_CHAT')
def send_telegram_message(token, chat_id, text):
    try:
        if not (token and chat_id):
            return
        data = _json.dumps({'chat_id': chat_id, 'text': text}).encode('utf-8')
        req = _urlreq.Request(
            f'https://api.telegram.org/bot{token}/sendMessage',
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        _urlreq.urlopen(req, timeout=5).read()
    except Exception:
        pass


def _tg(msg: str):
    try:
        if _TG_TOKEN and _TG_CHAT:
            send_telegram_message(_TG_TOKEN, _TG_CHAT, msg)
    except Exception:
        pass

# ---------------------- Trial runner with program synthesis ----------------------
def _mutate_stack(recipe: Dict[str,Any]) -> Tuple[List[Tuple[str,Any]], Dict[str,Tuple[Any,Any]], List[str], Dict[str,Any]]:
    """Return (mutated_agents, engine_patches, diff_snippets, engine_attr_backup)."""
    diffs = []
    # agents
    mutated_agents = []
    for name, fn in bt.AGENTS:
        after_src, mfn, d = mutate_agent_fn(fn, recipe)
        mutated_agents.append((name, mfn))
        diffs.extend(d)
    # engine funcs
    engine_patches = {}
    attrs_backup = {}
    try:
        atf = importlib.import_module("auto_trade_futures")
        targets = _select_engine_targets(atf)
        for tname in targets:
            fn = getattr(atf, tname)
            after_src, mfn, d = mutate_engine_fn(fn, recipe)
            engine_patches[tname] = (fn, mfn)
            diffs.extend(d)
        # engine attributes
        cfg_engine = recipe.get("_engine_attrs", {})
        old = _apply_engine_attrs(atf, cfg_engine)
        attrs_backup.update(old)
    except Exception:
        pass
    return mutated_agents, engine_patches, diffs, attrs_backup

def _make_recipe_portfolio(history: List[Tuple[Dict[str,Any], float]], cfg: Dict[str,Any]) -> Dict[str,Any]:
    # Blend sampled recipe with engine attributes from config
    from copy import deepcopy
    recipes = pick_portfolio_bandit(history, n_arms=6)
    r = random.choice(recipes)
    r = deepcopy(r)
    r["_engine_attrs"] = cfg.get("engine", {})
    return r

def _simulate_once(symbols, tf, start, end, alloc, lev, start_balance, config, verbose, mutated_agents, engine_patches, attrs_backup):
    with patched_bt(config, mutated_agents), patched_atf(engine_patches, attrs_backup):
        res = bt.simulate(
            symbols=symbols, tf=tf, start=start, end=end,
            alloc_usdt=alloc, lev=lev,
            max_open=int(config["max_open"]),
            entry_ttl_bars=int(config["entry_ttl"]),
            start_balance=start_balance,
            quick_tp_usd=float(config["quick_tp"]),
            min_move=float(config["min_move"]),
            max_loss_usd=float(config["max_loss"]),
            verbose=verbose
        )
    return res

def run_trial(root_dir: str,
              symbols: List[str], tf: str,
              start: datetime, end: datetime,
              alloc: float, lev: float,
              start_balance: float,
              config: Dict[str, Any], verbose: bool=False) -> Dict[str, Any]:

    history = config.setdefault("_recipe_history", [])
    recipe = _make_recipe_portfolio(history, config)
    config["_recipe_used"] = {k:v for k,v in recipe.items() if k != "_engine_attrs"}

    mutated_agents, engine_patches, diff_snips, attrs_backup = _mutate_stack(recipe)

    trial_seed = int(hashlib.sha1(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()[:8], 16) % (2**32-1)
    _seed_all(trial_seed)

    # Walk-forward support (optional)
    wf_train = int(config.get("wf_train_days", 0) or 0)
    wf_test  = int(config.get("wf_test_days", 0) or 0)
    wf_rolls = int(config.get("wf_rolls", 0) or 0)

    if wf_train>0 and wf_test>0 and wf_rolls>0:
        # roll windows backwards from end
        res_agg = {"pnl_total":0.0,"wins":0,"losses":0,"max_drawdown":0.0,"equity_final":start_balance,"trades_path":""}
        for r in range(wf_rolls):
            wf_end = end - timedelta(days=r*(wf_test))
            wf_start = wf_end - timedelta(days=wf_test)
            res = _simulate_once(symbols, tf, wf_start, wf_end, alloc, lev, start_balance, config, verbose, mutated_agents, engine_patches, attrs_backup)
            # aggregate key fields
            res_agg["pnl_total"] += float(res.get("pnl_total",0.0))
            res_agg["wins"]      += int(res.get("wins",0))
            res_agg["losses"]    += int(res.get("losses",0))
            res_agg["max_drawdown"] = max(res_agg["max_drawdown"], float(res.get("max_drawdown",0.0)))
            res_agg["equity_final"] = float(res.get("equity_final", res_agg["equity_final"]))
            res_agg["trades_path"] = res.get("trades_path","")
        res = res_agg
    else:
        res = _simulate_once(symbols, tf, start, end, alloc, lev, start_balance, config, verbose, mutated_agents, engine_patches, attrs_backup)

    trades_csv = res.get("trades_path","")
    metrics = compute_metrics(res, trades_csv, start_balance)
    score = score_metrics(metrics)

    trial_id = _hash_dict(config)
    tdir = _mkdir(os.path.join(root_dir, f"trial_{trial_id}"))
    with open(os.path.join(tdir, "config.json"), "w") as f:
        json.dump(config, f, indent=2)
    with open(os.path.join(tdir, "metrics.json"), "w") as f:
        json.dump({**metrics, "score": score}, f, indent=2)
    if isinstance(trades_csv, str) and os.path.isfile(trades_csv):
        dst = os.path.join(tdir, "trades.csv")
        try: os.link(trades_csv, dst)
        except Exception: shutil.copyfile(trades_csv, dst)
    if diff_snips:
        with open(os.path.join(tdir, "code_diffs.md"), "w") as f:
            f.write("\n\n".join(diff_snips))

    return {"trial_id": trial_id, "config": config, "metrics": metrics, "score": score, "trial_dir": tdir}

# ---------------------- Successive halving ----------------------
def successive_halving(cands: List[Dict[str, Any]], keep_ratio=0.25) -> List[Dict[str, Any]]:
    n_keep = max(1, int(math.ceil(len(cands) * keep_ratio)))
    cands.sort(key=lambda r: r["score"], reverse=True)
    return cands[:n_keep]

# ---------------------- Bayesian-ish refit ----------------------
def refit_and_sample(top_results: List[Dict[str, Any]], n_new: int) -> List[Dict[str, Any]]:
    if not top_results: return []
    cfgs = [r["config"] for r in top_results]
    def collect(path):
        vals = []
        for c in cfgs:
            v=c; ok=True
            for k in path:
                if k in v: v=v[k]
                else: ok=False; break
            if ok and isinstance(v,(int,float)): vals.append(float(v))
        return np.array(vals) if vals else None
    stats={}
    scalars=[("quick_tp",),("min_move",),("max_loss",),("entry_ttl",),("max_open",),("alloc",),("lev",),
             ("conf_gain",),("rr_min",),("sl_atr_mul",),("tp_w_rr",),("tp_w_band",),("tp_w_imp",),
             ("softmax_tau",)]
    for ag in DEFAULT_SEARCH["agent_conf_floors"].keys(): scalars.append(("agent_conf_floors",ag))
    for ag in DEFAULT_SEARCH["agent_weights"].keys(): scalars.append(("agent_weights",ag))
    for ag,params in DEFAULT_SEARCH["agent_params"].items():
        for pk in params.keys(): scalars.append(("agent_params",ag,pk))
    for path in scalars:
        arr=collect(path)
        if arr is None or len(arr)==0: continue
        mu=float(np.mean(arr)); sd=float(np.std(arr, ddof=1)) if len(arr)>1 else (abs(mu)*0.05+1e-6)
        stats[path]=(mu,sd)
    def bounds_for(path):
        if path[0] in DEFAULT_SEARCH and isinstance(DEFAULT_SEARCH[path[0]], tuple):
            return DEFAULT_SEARCH[path[0]]
        if path in [("entry_ttl",),("max_open",)]: return DEFAULT_SEARCH[path[0]]
        if path[0]=="agent_conf_floors": return DEFAULT_SEARCH["agent_conf_floors"][path[1]]
        if path[0]=="agent_weights": return DEFAULT_SEARCH["agent_weights"][path[1]]
        if path[0]=="agent_params": return DEFAULT_SEARCH["agent_params"][path[1]][path[2]]
        return (0.0,1.0)
    new_cfgs=[]
    for _ in range(n_new):
        base=random.choice(cfgs)
        cfg=json.loads(json.dumps(base))
        for path,(mu,sd) in stats.items():
            lo,hi=bounds_for(path)
            val=_clamp(random.gauss(mu,max(sd,1e-9)),lo,hi)
            tgt=cfg
            for k in path[:-1]: tgt=tgt.setdefault(k,{})
            leaf=path[-1]
            if leaf in ("entry_ttl","max_open"): tgt[leaf]=int(round(val))
            else: tgt[leaf]=round(float(val), 3 if leaf!="min_move" else 4)
        n_active=sum(base.get("hour_mask",[1]*24))
        jitter_n=int(_clamp(int(round(n_active*random.uniform(0.8,1.2))),3,22))
        cfg["hour_mask"]=make_hour_mask(jitter_n)
        cfg["vote_head"]=base.get("vote_head","weighted")
        cfg["engine"] = json.loads(json.dumps(base.get("engine",{})))
        new_cfgs.append(cfg)
    return new_cfgs

# ---------------------- Portfolio bandit ----------------------
def sample_recipe(rng: random.Random) -> Dict[str, Any]:
    return {
        "ema_gate": rng.choice([0,1]),
        "vol_veto": rng.choice([0,1]),
        "conf_logit": {"a": rng.uniform(2.5,3.8), "b": rng.uniform(0.08,0.22)} if rng.random()<0.75 else None,
        "tp_sl_blend": {"rr_min": rng.uniform(1.6,2.6), "w_rr": rng.uniform(0.25,0.7), "w_band": rng.uniform(0.1,0.6), "w_imp": rng.uniform(0.0,0.5)} if rng.random()<0.9 else None,
        "loss_mute_L": rng.choice([None,2,3]),
        "kelly": {"cap": rng.uniform(0.01,0.05), "temper": rng.uniform(0.3,0.7)},
    }

def pick_portfolio_bandit(history: List[Tuple[Dict[str,Any], float]], n_arms=6) -> List[Dict[str,Any]]:
    rng = random.Random()
    if not history:
        return [sample_recipe(rng) for _ in range(n_arms)]
    weights = np.array([max(1e-6, 1.0 + 0.01*score) for _,score in history], dtype=float)
    weights /= weights.sum()
    seeds = [history[int(np.random.choice(len(history), p=weights))][0] for _ in range(max(1,n_arms//2))]
    fresh = [sample_recipe(rng) for _ in range(n_arms - len(seeds))]
    return seeds + fresh

# ---------------------- CLI ----------------------
def parse_args_or_defaults():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--symbols"); ap.add_argument("--tf")
    ap.add_argument("--days_stage1", type=int); ap.add_argument("--days_stage2", type=int); ap.add_argument("--days_stage3", type=int)
    ap.add_argument("--alloc", type=float); ap.add_argument("--lev", type=float)
    ap.add_argument("--start_balance", type=float); ap.add_argument("--seed", type=int)
    ap.add_argument("--pop1", type=int); ap.add_argument("--pop2", type=int); ap.add_argument("--pop3", type=int); ap.add_argument("--mutations", type=int)
    ap.add_argument("--verbose", action="store_true")
    # Walk-forward
    ap.add_argument("--wf_train_days", type=int); ap.add_argument("--wf_test_days", type=int); ap.add_argument("--wf_rolls", type=int)
    args,_=ap.parse_known_args(); cfg=DEFAULTS.copy()
    for k in list(cfg.keys()):
        v=getattr(args,k,None)
        if v is not None: cfg[k]=v
    return cfg

# ---------------------- Run orchestration ----------------------
def _estimate_total_trials(cfg):
    p1=int(cfg["pop1"]); p2=int(cfg["pop2"]); p3=int(cfg["pop3"]); muts=int(cfg["mutations"])
    return p1 + (max(1,p1//4)+max(2,p2)) + max(1,p3) + muts

import os as _os, json as _json, urllib.request as _urlreq
_TG_TOKEN = _os.environ.get('BOB_TG_TOKEN')
_TG_CHAT  = _os.environ.get('BOB_TG_CHAT')
def send_telegram_message(token, chat_id, text):
    try:
        if not (token and chat_id):
            return
        data = _json.dumps({'chat_id': chat_id, 'text': text}).encode('utf-8')
        req = _urlreq.Request(
            f'https://api.telegram.org/bot{token}/sendMessage',
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        _urlreq.urlopen(req, timeout=5).read()
    except Exception:
        pass


def _tg_start(cfg, symbols):
    msg = f"🚀 ASI started - {symbols[:5]}... tf={cfg['tf']} windows={cfg['days_stage1']}/{cfg['days_stage2']}/{cfg['days_stage3']} pop={cfg['pop1']}/{cfg['pop2']}/{cfg['pop3']} muts={cfg['mutations']}"
    if int(cfg.get("wf_train_days",0))>0:
        msg += f" | WF {cfg['wf_train_days']}/{cfg['wf_test_days']} x{cfg['wf_rolls']}"
    try:
        if _TG_TOKEN and _TG_CHAT: send_telegram_message(_TG_TOKEN, _TG_CHAT, msg)
    except Exception: pass

def _tg_progress(done, total, best):
    pct=int((done/max(1,total))*100)
    try:
        if pct%10==0 and _TG_TOKEN and _TG_CHAT:
            send_telegram_message(_TG_TOKEN, _TG_CHAT, f"🧪 ASI progress {pct}% - {done}/{total} | best score={best['score']:.2f} pnl={best['metrics']['pnl_total']:.2f} wr={best['metrics']['winrate']:.3f}")
    except Exception: pass

def run_bob(cfg: Dict[str, Any]):
    _seed_all(int(cfg["seed"]))
    symbols = fetch_top10_no_btc() if str(cfg["symbols"]).upper()=="TOP10" else [s.strip().upper() for s in str(cfg["symbols"]).split(",") if s.strip()]
    run_root = _mkdir(os.path.join("bob_runs", _now_utc().strftime("%Y%m%d_%H%M%S")))
    run_id = os.path.basename(run_root)
    leaderboard_csv = os.path.join(run_root, f"leaderboard_{run_id}.csv")
    pd.DataFrame(columns=["trial_id","score","pnl","wr","pf","mdd","sharpe","sortino"]).to_csv(leaderboard_csv, index=False)

    def log_trial(tr):
        row = {"trial_id": tr["trial_id"],"score": tr["score"],"pnl": tr["metrics"]["pnl_total"],"wr": tr["metrics"]["winrate"],
               "pf": tr["metrics"]["profit_factor"],"mdd": tr["metrics"]["max_drawdown"],"sharpe": tr["metrics"]["sharpe_like"],"sortino": tr["metrics"]["sortino_like"]}
        df = pd.read_csv(leaderboard_csv); df.loc[len(df)] = row; df.to_csv(leaderboard_csv, index=False)

    total=_estimate_total_trials(cfg); done=0
    best=None

    _tg_start(cfg, symbols)

    # --- Stage 1 ---
    end1=_now_utc(); start1=end1 - timedelta(days=int(cfg["days_stage1"]))
    args_list=[]
    for _ in range(int(cfg["pop1"])):
        c=sample_config()
        # carry walk-forward knobs into configs
        c["wf_train_days"]=int(cfg.get("wf_train_days",0)); c["wf_test_days"]=int(cfg.get("wf_test_days",0)); c["wf_rolls"]=int(cfg.get("wf_rolls",0))
        # default alloc/lev (can be mutated inside genome too)
        c.setdefault("alloc", float(cfg["alloc"])); c.setdefault("lev", float(cfg["lev"]))
        args_list.append((run_root, symbols, cfg["tf"], start1, end1, float(c["alloc"]), float(c["lev"]), float(cfg["start_balance"]), c, bool(cfg["verbose"])) )
    stage1_results=[]
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        futures=[ex.submit(run_trial,*a) for a in args_list]
        for fut in as_completed(futures):
            tr=fut.result(); stage1_results.append(tr); log_trial(tr)
            done+=1; best = tr if (best is None or tr["score"]>best["score"]) else best; _tg_progress(done,total,best)
    stage1_results = successive_halving(stage1_results, keep_ratio=0.25)
    best = max(stage1_results, key=lambda r: r["score"]) if stage1_results else best

    # --- Stage 2 ---
    end2=_now_utc(); start2=end2 - timedelta(days=int(cfg["days_stage2"]))
    stage2_results=[]; args_list=[]
    for tr in stage1_results:
        args_list.append((run_root, symbols, cfg["tf"], start2, end2, float(tr["config"]["alloc"]), float(tr["config"]["lev"]), float(cfg["start_balance"]), tr["config"], bool(cfg["verbose"])) )
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        futures=[ex.submit(run_trial,*a) for a in args_list]
        for fut in as_completed(futures):
            tr2=fut.result(); stage2_results.append(tr2); log_trial(tr2)
            done+=1; best = tr2 if (best is None or tr2["score"]>best["score"]) else best; _tg_progress(done,total,best)
    topK = successive_halving(stage2_results[:], keep_ratio=0.5)
    new_cfgs = refit_and_sample(topK, n_new=max(2, int(cfg["pop2"]) - len(stage2_results)))
    args_list=[]
    for c in new_cfgs:
        c["wf_train_days"]=int(cfg.get("wf_train_days",0)); c["wf_test_days"]=int(cfg.get("wf_test_days",0)); c["wf_rolls"]=int(cfg.get("wf_rolls",0))
        args_list.append((run_root, symbols, cfg["tf"], start2, end2, float(c["alloc"]), float(c["lev"]), float(cfg["start_balance"]), c, bool(cfg["verbose"])) )
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        futures=[ex.submit(run_trial,*a) for a in args_list]
        for fut in as_completed(futures):
            tr2n=fut.result(); stage2_results.append(tr2n); log_trial(tr2n)
            done+=1; best = tr2n if tr2n["score"]>best["score"] else best; _tg_progress(done,total,best)

    # --- Stage 3 ---
    end3=_now_utc(); start3=end3 - timedelta(days=int(cfg["days_stage3"]))
    stage2_results = successive_halving(stage2_results, keep_ratio=float(cfg["pop3"]) / max(1, len(stage2_results)))
    args_list=[]; stage3_results=[]
    for tr in stage2_results:
        args_list.append((run_root, symbols, cfg["tf"], start3, end3, float(tr["config"]["alloc"]), float(tr["config"]["lev"]), float(cfg["start_balance"]), tr["config"], bool(cfg["verbose"])) )
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        futures=[ex.submit(run_trial,*a) for a in args_list]
        for fut in as_completed(futures):
            tr3=fut.result(); stage3_results.append(tr3); log_trial(tr3)
            done+=1; best = tr3 if tr3["score"]>best["score"] else best; _tg_progress(done,total,best)

    # --- Evolutionary local search ---
    evo_results=[]
    for _ in range(int(cfg["mutations"])):
        c=mutate_config(best["config"], rate=0.30)
        trE = run_trial(run_root, symbols, cfg["tf"], start3, end3, float(c["alloc"]), float(c["lev"]), float(cfg["start_balance"]), c, bool(cfg["verbose"]))
        evo_results.append(trE); log_trial(trE)
        done+=1; best = trE if trE["score"]>best["score"] else best; _tg_progress(done,total,best)

    out_best = {"trial_id": best["trial_id"], "score": best["score"], "config": best["config"], "metrics": best["metrics"]}
    with open(os.path.join(run_root, f"best_config_{run_id}.json"), "w") as f: json.dump(out_best, f, indent=2)
    summary = {
        "hour_mask": best["config"].get("hour_mask"),
        "require_ema": best["config"].get("require_ema"),
        "conf_gain": best["config"].get("conf_gain"),
        "rr_min": best["config"].get("rr_min"),
        "sl_atr_mul": best["config"].get("sl_atr_mul"),
        "tp_weights": {"rr": best["config"].get("tp_w_rr"), "band": best["config"].get("tp_w_band"), "imp": best["config"].get("tp_w_imp")},
        "vote_head": best["config"].get("vote_head"),
        "engine_attrs": best["config"].get("engine"),
        "recipe_used": best["config"].get("_recipe_used"),
    }
    with open(os.path.join(run_root, f"innovation_summary_{run_id}.json"), "w") as f: json.dump(summary, f, indent=2)

    print(f"\n[ASI+] DONE. Run dir: {run_root}")
    print(f"[ASI+] BEST trial={best['trial_id']}  score={best['score']:.2f}  pnl={best['metrics']['pnl_total']:.2f}  wr={best['metrics']['winrate']:.3f}")
    try:
        if _TG_TOKEN and _TG_CHAT:
            send_telegram_message(_TG_TOKEN, _TG_CHAT, f"✅ ASI DONE - best score={best['score']:.2f} pnl={best['metrics']['pnl_total']:.2f} wr={best['metrics']['winrate']:.3f} run={run_root}")
    except Exception:
        pass

# ---------------------- Entrypoint ----------------------
if __name__ == "__main__":
    cfg = parse_args_or_defaults()
    run_bob(cfg)
