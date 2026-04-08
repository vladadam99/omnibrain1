# -*- coding: utf-8 -*-
"""
Backtester for OMNIBRAIN agents.
- Pulls historical klines from Binance futures (public endpoint).
- Replays your live autotrade decision logic offline (agents + vote + risk).
- Supports parameter sweeps for quick TP / max loss / min move etc.
- Saves trades + summary; mirrors runtime semantics closely.

Usage:
  python backtest_autotrade.py --symbols TOP10 --tf 5m --days 30 --verbose
  python backtest_autotrade.py --symbols XPLUSDT,ASTERUSDT --tf 5m --start 2024-08-01 --end 2024-09-01
  python backtest_autotrade.py --symbols TOP10 --days 14 --quick_tp 0.3,0.5,0.7 --sweep 1
"""
from __future__ import annotations
import os, sys, json, time, math, argparse, itertools, csv
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Tuple, Optional

import numpy as np
import pandas as pd
import requests

# ---------- Repo-relative imports ----------
# agents live in ./agents
sys.path.append(os.path.join(os.path.dirname(__file__), "agents"))

# Optional utils: we only use what we need offline
try:
    from omnibrain_utils import calculate_atr as _calc_atr
except Exception:
    _calc_atr = None

# === Load agents exactly like live bot ===
from apex_vwap_pullback      import generate_signal as apex_vwap_pullback
from apex_sweep_reversal     import generate_signal as apex_sweep_reversal
from apex_microburst         import generate_signal as apex_microburst
try:
    from apex_supertrend_adaptive import generate_signal as apex_supertrend_adaptive
    HAS_SUPERTREND = True
except Exception:
    HAS_SUPERTREND = False

try:
    from apex_momentum_pump import generate_signal as apex_momentum_pump
    HAS_MOM_PUMP = True
except Exception:
    HAS_MOM_PUMP = False

AGENTS: List[Tuple[str, Any]] = [
    ("apex_vwap_pullback", apex_vwap_pullback),
    ("apex_sweep_reversal", apex_sweep_reversal),
    ("apex_microburst",    apex_microburst),
]
if HAS_SUPERTREND:
    AGENTS.append(("apex_supertrend_adaptive", apex_supertrend_adaptive))
if HAS_MOM_PUMP:
    AGENTS.append(("apex_momentum_pump", apex_momentum_pump))

# Default per-agent floors (like live)
CONF_FLOOR = {
    "default":                 0.70,
    "apex_vwap_pullback":       0.70,
    "apex_microburst":          0.70,
    "apex_sweep_reversal":      0.70,
    "apex_supertrend_adaptive": 0.70,
    "apex_momentum_pump":       0.75,
}

# ---------- Binance public REST (no keys needed) ----------
BINANCE_FUTURES = "https://fapi.binance.com"

def _fapi(path: str, params: dict, timeout: float = 15.0):
    """GET with light retry/backoff for 429/418/5xx."""
    url = BINANCE_FUTURES + path
    for attempt in range(6):
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code in (418, 429) or r.status_code >= 500:
            time.sleep(0.3 + 0.4 * attempt)
            continue
        r.raise_for_status()
        return r.json()
    # last try raises
    r.raise_for_status()
    return r.json()

def normalize_symbol(sym: str) -> str:
    """Normalize inputs like 'ETH' -> 'ETHUSDT', keep 'XPLUSDT' as-is."""
    s = (sym or "").upper().replace("/", "").replace("PERP", "")
    if s.endswith(("USDT", "BUSD", "USD")):
        return s
    return s + "USDT"

def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """
    Robust USDT-M perpetual klines using /fapi/v1/klines (NOT continuousKlines).
    Chunks long ranges (limit 1500), stepping by closeTime+1ms.
    """
    sym = normalize_symbol(symbol)
    rows: List[list] = []
    cur = int(start_ms)
    limit = 1500
    while True:
        batch = _fapi("/fapi/v1/klines", {
            "symbol": sym,
            "interval": interval,
            "startTime": cur,
            "endTime": int(end_ms),
            "limit": limit,
        })
        if not batch:
            break
        rows.extend(batch)
        last_close = int(batch[-1][6])  # closeTime
        nxt = last_close + 1
        if nxt >= end_ms or len(batch) < limit:
            break
        time.sleep(0.06)  # be nice
        cur = nxt

    if not rows:
        return pd.DataFrame(columns=["open","high","low","close","volume"])

    df = pd.DataFrame(rows, columns=[
        "open_time","open","high","low","close","volume","close_time",
        "qav","n","taker_base","taker_quote","i"
    ])
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    # force float
    for col in ("open","high","low","close","volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[["open","high","low","close","volume"]].astype(float).dropna()
    return df

def fetch_top10_symbols(min_quote_vol_usd: float = 300_000_000) -> List[str]:
    """
    Top 10 USDT-M by 24h quote volume. Returns normalized symbols.
    """
    data = _fapi("/fapi/v1/ticker/24hr", {})
    pairs = []
    for row in data:
        sym = row.get("symbol") or ""
        if not sym.endswith("USDT"):
            continue
        vol_q = float(row.get("quoteVolume", 0) or 0.0)
        if vol_q >= min_quote_vol_usd:
            pairs.append((sym, vol_q))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return [normalize_symbol(s) for s,_ in pairs[:10]]

# ---------- Indicators ----------
def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    if _calc_atr:
        try:
            return pd.Series(_calc_atr(df, window=n), index=df.index)
        except Exception:
            pass
    # local ATR
    if len(df) < n + 2:
        return pd.Series(index=df.index, dtype=float)
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n).mean()

def trend_label_from_emas(df: pd.DataFrame, fast=9, slow=21) -> str:
    if df is None or len(df) < slow + 2:
        return "SIDEWAYS"
    ef, es = ema(df["close"], fast), ema(df["close"], slow)
    if ef.iloc[-1] > es.iloc[-1] * 1.0003:
        return "UP"
    if ef.iloc[-1] * 1.0003 < es.iloc[-1]:
        return "DOWN"
    return "SIDEWAYS"

# ---------- Voting (same spirit as live, but static weights=1.0 offline) ----------
def smart_vote(signals: Dict[str, Dict[str, Any]], tf: str) -> Optional[Tuple[str,float,List]]:
    col = []
    for an, sig in signals.items():
        s = sig.get(tf) if tf in sig else sig
        if s and s.get("side") in ("BUY","SELL"):
            eff_conf = float(s.get("confidence", 0.0)) * 1.0  # offline weight=1
            col.append((an, s["side"], eff_conf, s))
    if not col:
        return None
    sum_buy = sum(c for _,side,c,_ in col if side=="BUY")
    sum_sell= sum(c for _,side,c,_ in col if side=="SELL")
    winner = "BUY" if sum_buy >= sum_sell else "SELL"
    used = [(an,c,s) for (an,side,c,s) in col if side==winner]
    avg_conf = float(np.mean([c for _,c,_ in used])) if used else 0.0
    return winner, avg_conf, used

# ---------- Trade Engine (offline) ----------
class Position:
    def __init__(self, side: str, entry: float, qty: float, sl: float, tp: float,
                 tf: str, symbol: str, agent: str, features: Dict[str,Any], ttl_bars: int):
        self.side = side
        self.entry = entry
        self.qty = qty
        self.sl = sl
        self.tp = tp
        self.tf = tf
        self.symbol = symbol
        self.agent = agent
        self.features = features or {}
        self.open_ts = None
        self.best_px = entry
        self.trail_armed = False
        self.entry_ttl = ttl_bars
        self.bars_alive = 0

def simulate(
    symbols: List[str],
    tf: str,
    start: datetime,
    end: datetime,
    alloc_usdt: float,
    lev: float,
    max_open: int,
    entry_ttl_bars: int,
    start_balance: float,
    quick_tp_usd: float,
    min_move: float,
    max_loss_usd: float,
    verbose: bool = False,
) -> Dict[str, Any]:

    out_dir = os.path.join("backtests", f"backtest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(out_dir, exist_ok=True)
    trades_path = os.path.join(out_dir, "trades.csv")
    with open(trades_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time","symbol","action","side","price","qty","agent","pnl","note"])

    equity = start_balance
    open_positions: Dict[str, Position] = {}
    pnl_total = 0.0
    wins = losses = 0
    peak_equity = start_balance
    max_dd = 0.0

    # Preload HTF windows for all symbols
    cache5m  = {}
    cache15m = {}
    cache1h  = {}
    for sym in symbols:
        df5  = fetch_klines(sym, tf, int(start.timestamp()*1000), int(end.timestamp()*1000))
        if len(df5) < 200:  # skip dead
            continue
        df15 = fetch_klines(sym, "15m", int(start.timestamp()*1000)-86400000, int(end.timestamp()*1000))
        df1h = fetch_klines(sym, "1h",  int(start.timestamp()*1000)-86400000, int(end.timestamp()*1000))
        cache5m[sym]  = df5
        cache15m[sym] = df15
        cache1h[sym]  = df1h

    # Build joint 5m timeline
    all_times = sorted(set(t for df in cache5m.values() for t in df.index))
    if verbose:
        print(f"[BT] Symbols={len(symbols)} bars={len(all_times)} window={start} -> {end}")

    def _append_trade(ts, sym, action, side, price, qty, agent, pnl, note):
        with open(trades_path, "a", newline="") as f:
            csv.writer(f).writerow([ts.isoformat(), sym, action, side, f"{price:.8f}", f"{qty:.6f}", agent, f"{pnl:.2f}", note])

    # Replay
    for ts in all_times:
        # update positions first (TP/SL/Quick TP / trailing)
        for sym in list(open_positions.keys()):
            if sym not in cache5m:
                continue
            df = cache5m[sym]
            if ts not in df.index:
                continue
            row = df.loc[ts]
            pos = open_positions[sym]
            pos.bars_alive += 1
            px_high, px_low, px_close = float(row["high"]), float(row["low"]), float(row["close"])
            atr_now_series = atr(df.loc[:ts].tail(60))
            atr_now = float(atr_now_series.iloc[-1]) if len(atr_now_series) else 0.0

            # quick TP / hard stop (USD)
            if pos.side == "BUY":
                intrabar_sl_hit = px_low  <= pos.sl
                intrabar_tp_hit = px_high >= pos.tp
                live_pnl = (px_close - pos.entry) * pos.qty
            else:
                intrabar_sl_hit = px_high >= pos.sl
                intrabar_tp_hit = px_low  <= pos.tp
                live_pnl = (pos.entry - px_close) * pos.qty

            # Quick TP
            if live_pnl >= quick_tp_usd:
                equity += live_pnl
                pnl_total += live_pnl
                if live_pnl >= 0:
                    wins += 1
                else:
                    losses += 1
                _append_trade(ts, sym, "CLOSE", pos.side, px_close, pos.qty, pos.agent, live_pnl, "QuickTP")
                del open_positions[sym]
                continue

            # Hard USD stop
            if live_pnl <= -max_loss_usd:
                equity += live_pnl
                pnl_total += live_pnl
                if live_pnl >= 0:
                    wins += 1
                else:
                    losses += 1
                _append_trade(ts, sym, "CLOSE", pos.side, px_close, pos.qty, pos.agent, live_pnl, "HardUSDStop")
                del open_positions[sym]
                continue

            # Exchange-style TP/SL by price
            if intrabar_tp_hit or intrabar_sl_hit:
                exit_px = pos.tp if intrabar_tp_hit else pos.sl
                exit_pnl = (exit_px - pos.entry) * pos.qty if pos.side=="BUY" else (pos.entry - exit_px) * pos.qty
                equity += exit_pnl
                pnl_total += exit_pnl
                if exit_pnl >= 0:
                    wins += 1
                else:
                    losses += 1
                _append_trade(ts, sym, "CLOSE", pos.side, exit_px, pos.qty, pos.agent, exit_pnl, "TP" if intrabar_tp_hit else "SL")
                del open_positions[sym]
                continue

            # Hybrid (arm & trail)  mirrors your live defaults
            init_risk = abs(pos.entry - pos.sl)
            mfe = (px_close - pos.entry) if pos.side=="BUY" else (pos.entry - px_close)
            if not pos.trail_armed:
                if atr_now > 0 and mfe >= max(1.5 * init_risk, 1.5 * atr_now):
                    pos.trail_armed = True

            if pos.trail_armed and atr_now > 0:
                step = 2.0 * atr_now
                if pos.side == "BUY":
                    pos.best_px = max(pos.best_px, px_close)
                    pos.sl = max(pos.sl, pos.best_px - step)
                else:
                    pos.best_px = min(pos.best_px, px_close)
                    pos.sl = min(pos.sl, pos.best_px + step)

            # Simple BE time guard after ~8 bars
            if pos.bars_alive > 8 and atr_now > 0:
                be_eps = 0.22 * atr_now
                be = pos.entry - be_eps if pos.side=="BUY" else pos.entry + be_eps
                if (pos.side=="BUY" and pos.sl < be) or (pos.side=="SELL" and pos.sl > be):
                    pos.sl = be

        # Free slots to open new trades
        if len(open_positions) >= max_open:
            # still update equity curve
            peak_equity = max(peak_equity, equity)
            max_dd = max(max_dd, (peak_equity - equity))
            continue

        # agent scan per symbol at this bar
        for sym in symbols:
            if sym not in cache5m:
                continue
            df5 = cache5m[sym]
            if ts not in df5.index:
                continue
            # Need at least 60 bars of history before ts
            i = df5.index.get_loc(ts)
            if isinstance(i, slice) or i < 60:
                continue
            window5 = df5.iloc[:i+1]  # inclusive current bar

            # HTF contexts aligned to ts
            df15 = cache15m[sym]
            df1h = cache1h[sym]
            t15_slice = df15.loc[:ts]
            t1h_slice = df1h.loc[:ts]
            t15 = trend_label_from_emas(t15_slice.tail(240)) if len(t15_slice) else "SIDEWAYS"
            t1h = trend_label_from_emas(t1h_slice.tail(240)) if len(t1h_slice) else "SIDEWAYS"
            # Master hint = merge(1h, 15m)
            trend_hint = t1h if t1h != "SIDEWAYS" else t15

            # Build agent ctx (mirrors live)
            ctx = {
                "timeframe": tf,
                "trend_hint": t15 if t15 == t1h else trend_hint,
                "trend_15m": t15,
                "trend_1h": t1h,
                "weight": 1.0,
                "recent_wr": 1.0,
                "conf_threshold": CONF_FLOOR.get("default", 0.70),
                "min_expected_move": float(min_move),
                "risk": {"atr": float(atr(window5).iloc[-1] or 0.0)},
                "last_price": float(window5["close"].iloc[-1]),
            }

            # Call agents
            signals: Dict[str, Dict[str,Any]] = {}
            for an, fn in AGENTS:
                thr = CONF_FLOOR.get(an, CONF_FLOOR["default"])
                ctx["conf_threshold"] = thr
                try:
                    sig = fn(window5, sym, ctx)
                except TypeError:
                    # Very old signature
                    try:
                        sig = fn({tf: window5}, sym)
                    except Exception:
                        sig = None
                except Exception:
                    sig = None
                if sig and isinstance(sig, dict) and sig.get("side") in ("BUY","SELL"):
                    signals[an] = sig

            if not signals:
                continue

            res = smart_vote(signals, tf)
            if not res:
                continue
            side, avg_conf, used = res

            # Take the *first* agent in the winning set for SL/TP semantics (highest conf)
            chosen_agent, eff_conf, sig = max(used, key=lambda x: x[1])
            entry_type = sig.get("entry_type", "limit")
            entry      = float(sig.get("entry", window5["close"].iloc[-1]))
            entry_stop = sig.get("entry_stop")  # might be None
            sl = float(sig.get("sl") or sig.get("sl_hint") or 0.0)
            tp = float(sig.get("tp") or sig.get("tp_hint") or 0.0)

            # Expected move guard (same concept as live)
            if entry and tp and abs(tp - entry) / max(1e-9, entry) < float(min_move):
                continue

            # Entry modelling:
            px_close = float(window5["close"].iloc[-1])
            fill_px = None
            ttl = entry_ttl_bars
            ts_fill = ts
            if entry_type == "stop" and entry_stop is not None:
                future = df5.iloc[i+1:i+1+ttl]
                if len(future) == 0:
                    continue
                if side == "BUY":
                    hit = future[future["high"] >= float(entry_stop)]
                    if len(hit):
                        fill_px = float(entry_stop)
                        ts_fill = hit.index[0]
                    else:
                        continue
                else:
                    hit = future[future["low"] <= float(entry_stop)]
                    if len(hit):
                        fill_px = float(entry_stop)
                        ts_fill = hit.index[0]
                    else:
                        continue
            else:
                fill_px = entry if entry else px_close
                ts_fill = ts

            if fill_px <= 0:
                continue
            qty = (alloc_usdt * lev) / fill_px  # leveraged qty

            # SL/TP defaults if agent omitted
            if not sl or not tp:
                a_series = atr(window5)
                a = float(a_series.iloc[-1]) if len(a_series) else 0.0
                if a <= 0:
                    continue
                base_rr = 2.0
                if side == "BUY":
                    sl = fill_px - 1.0 * a
                    tp = fill_px + base_rr * (fill_px - sl)
                else:
                    sl = fill_px + 1.0 * a
                    tp = fill_px - base_rr * (sl - fill_px)

            # Final place
            pos = Position(side, fill_px, qty, sl, tp, tf, sym, chosen_agent, sig, entry_ttl_bars)
            pos.open_ts = ts_fill
            open_positions[sym] = pos
            _append_trade(ts_fill, sym, "OPEN", side, fill_px, qty, chosen_agent, 0.0, f"conf={avg_conf:.3f}")

        # equity curve / drawdown
        peak_equity = max(peak_equity, equity)
        max_dd = max(max_dd, (peak_equity - equity))

    # basic PF calc (sum winners / abs(sum losers))
    wins_sum = 0.0
    losses_sum = 0.0
    wins_count = 0
    losses_count = 0
    total_nonzero = 0
    try:
        dftr = pd.read_csv(trades_path)
        closed = dftr[dftr["action"]=="CLOSE"].copy()
        closed["pnl"] = closed["pnl"].astype(float)
        wins_sum = float(closed.loc[closed["pnl"] > 0, "pnl"].sum())
        losses_sum = float(closed.loc[closed["pnl"] < 0, "pnl"].sum())
        wins_count = int((closed["pnl"] > 0).sum())
        losses_count = int((closed["pnl"] < 0).sum())
        total_nonzero = int((closed["pnl"] != 0).sum())
    except Exception:
        pass
    profit_factor = (wins_sum / max(1e-9, abs(losses_sum))) if losses_sum < 0 else (1.0 if wins_sum > 0 else 0.0)

    summary = {
        "symbols": symbols,
        "tf": tf,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "trades_path": trades_path,
        "equity_final": equity,
        "pnl_total": float(wins_sum + losses_sum) if (wins_sum or losses_sum) else float(pnl_total),
        "wins": wins_count,
        "losses": losses_count,
        "winrate": float(wins_count / max(1, total_nonzero)) if total_nonzero else 0.0,
        "profit_factor": float(profit_factor),
        "max_drawdown": float(max_dd),
        "open_left": list(open_positions.keys())
    }
    if summary.get("equity_final", start_balance) <= 0:
        summary["notes"] = ["Stopped early: balance <= 0"]
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    return summary

# ---------- CLI & sweep ----------
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", required=True,
                   help="Comma list (e.g. XPLUSDT,ASTERUSDT) or 'TOP10'")
    p.add_argument("--tf", default="5m")
    p.add_argument("--days", type=int, default=None, help="If set, overrides start/end.")
    p.add_argument("--start", type=str, default=None, help="YYYY-MM-DD (UTC)")
    p.add_argument("--end", type=str, default=None, help="YYYY-MM-DD (UTC)")
    p.add_argument("--alloc", type=float, default=20.0, help="USDT per trade (margin).")
    p.add_argument("--lev", type=float, default=20.0, help="Leverage.")
    p.add_argument("--quick_tp", type=str, default="0.5", help="USDT (or comma list for sweep).")
    p.add_argument("--min_move", type=str, default="0.007", help="Fractional (or comma list).")
    p.add_argument("--max_loss", type=str, default="2.5", help="USDT hard loss per trade (or comma list).")
    p.add_argument("--max_open", type=int, default=2)
    p.add_argument("--entry_ttl", type=int, default=6, help="Bars to wait for stop-entry trigger.")
    p.add_argument("--start_balance", type=float, default=100.0)
    p.add_argument("--sweep", type=int, default=0, help="1 to enable grid over quick_tp,min_move,max_loss")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()

def to_list_or_single(s: str, cast=float) -> List[float]:
    if "," in s:
        return [cast(x.strip()) for x in s.split(",") if x.strip()]
    return [cast(s)]

def main():
    args = parse_args()
    # symbol list
    if args.symbols.upper() == "TOP10":
        symbols = fetch_top10_symbols()
    else:
        symbols = [normalize_symbol(x.strip()) for x in args.symbols.split(",") if x.strip()]

    # time window
    if args.days is not None:
        end = datetime.now(timezone.utc).replace(microsecond=0, second=0)
        start = end - timedelta(days=int(args.days))
    else:
        if not args.start or not args.end:
            print("Provide --days OR --start + --end", file=sys.stderr)
            sys.exit(2)
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        end   = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)

    quick_tp_list = to_list_or_single(args.quick_tp, float)
    min_move_list = to_list_or_single(args.min_move, float)
    max_loss_list = to_list_or_single(args.max_loss, float)

    if args.sweep:
        sweep_rows = []
        for qt, mm, ml in itertools.product(quick_tp_list, min_move_list, max_loss_list):
            print(f"[SWEEP] quick_tp={qt} min_move={mm} max_loss={ml}")
            res = simulate(
                symbols=symbols, tf=args.tf, start=start, end=end,
                alloc_usdt=args.alloc, lev=args.lev,
                max_open=args.max_open, entry_ttl_bars=args.entry_ttl,
                start_balance=args.start_balance,
                quick_tp_usd=qt, min_move=mm, max_loss_usd=ml,
                verbose=args.verbose
            )
            sweep_rows.append({
                "quick_tp": qt, "min_move": mm, "max_loss": ml,
                "pnl_total": res["pnl_total"],
                "wr": res["winrate"], "pf": res["profit_factor"],
                "mdd": res["max_drawdown"], "equity_final": res["equity_final"],
                "wins": res["wins"], "losses": res["losses"]
            })
        out_dir = os.path.join("backtests", "sweep_results")
        os.makedirs(out_dir, exist_ok=True)
        out_csv = os.path.join(out_dir, f"sweep_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv")
        pd.DataFrame(sweep_rows).to_csv(out_csv, index=False)
        print(f"[SWEEP] saved -> {out_csv}")
    else:
        res = simulate(
            symbols=symbols, tf=args.tf, start=start, end=end,
            alloc_usdt=args.alloc, lev=args.lev,
            max_open=args.max_open, entry_ttl_bars=args.entry_ttl,
            start_balance=args.start_balance,
            quick_tp_usd=quick_tp_list[0], min_move=min_move_list[0], max_loss_usd=max_loss_list[0],
            verbose=args.verbose
        )
        print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
