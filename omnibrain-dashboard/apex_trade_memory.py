
from __future__ import annotations
# -*- coding: utf-8 -*-
"""
apex_trade_memory.py
--------------------
Persistent trade "fingerprints" for Apex agents.
- Records every trade with a rich feature snapshot (price action, volume, MAs, ATR, breakouts, session, etc.)
- Labels outcomes (TP / SL / TRAIL / TIME / MANUAL) and realized PnL
- Stores to a local SQLite DB and a rolling Parquet (optional) for offline analysis
- Provides a fast k-NN style lookback scorer to influence new signals (neighbor win-rate / confidence multiplier)

No external deps beyond stdlib + numpy + pandas.
"""

import os
import math
import json
import time
import hashlib
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd


# -------------------- Utilities --------------------

def _safe_float(x, d: float = 0.0) -> float:
    try:
        v = float(x)
        if not np.isfinite(v): return d
        return v
    except Exception:
        return d

def _ema(series: pd.Series, span: int) -> float:
    if series is None or len(series) < max(3, span):
        return _safe_float(series.iloc[-1] if len(series) else 0.0)
    return _safe_float(series.ewm(span=span, adjust=False).mean().iloc[-1])

def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if df is None or len(df) < period + 2:
        return 0.0
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return _safe_float(pd.Series(tr).rolling(period).mean().iloc[-1], 0.0)

def _pct(a: float, b: float) -> float:
    if b == 0: return 0.0
    return abs(a/b - 1.0)

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# -------------------- Feature Snapshot --------------------

@dataclass
class FeatureSnapshot:
    # core identifiers
    symbol: str
    agent: str
    timeframe: str
    side: str  # BUY / SELL

    # price + volume at signal/open
    price: float
    open: float
    high: float
    low: float
    volume_now: float
    volume_med30: float

    # ATR/Range
    atr14: float
    bar_range: float
    body: float
    body_ratio: float

    # EMAs (close)
    ema9: float
    ema21: float
    ema50: float

    # EMA slopes (per-bar delta normalized by price)
    ema9_slope: float
    ema21_slope: float
    ema50_slope: float

    # Breakout/pattern context
    prev_hi_6: float
    prev_lo_6: float
    bos_up: int
    bos_dn: int
    consolidation_4_mean_range: float

    # higher TF hints
    trend_15m: str
    trend_1h: str
    trend_master: str

    # session/time
    hour_utc: int
    dow_utc: int

    # risk model at open
    entry_px: float
    sl_px: float
    tp_px: float
    rr: float
    leverage: float
    alloc_usdt: float

    # extras for later analysis
    conf_score: float
    weight: float
    recent_wr: float
    signal_reason: str

    def to_vector(self) -> List[float]:
        """Vector for similarity search (use only numeric, scale-invariant features)."""
        return [
            self._nz(self.body_ratio),
            self._nz(self.bar_range / max(1e-9, self.atr14)),
            self._nz(self.volume_now / max(1e-9, self.volume_med30)),
            self._nz((self.price - self.ema9) / max(1e-9, self.price)),
            self._nz((self.ema9 - self.ema21) / max(1e-9, self.price)),
            self._nz((self.ema21 - self.ema50) / max(1e-9, self.price)),
            self._nz(self.ema9_slope),
            self._nz(self.ema21_slope),
            self._nz(self.ema50_slope),
            float(self.bos_up),
            float(self.bos_dn),
            self._nz(self.consolidation_4_mean_range / max(1e-9, self.atr14)),
            self._nz(self.rr),
            self._nz(self.conf_score),
        ]

    @staticmethod
    def _nz(x: float) -> float:
        if not np.isfinite(x): return 0.0
        return float(x)


def extract_snapshot(df5m: pd.DataFrame, symbol: str, agent: str, side: str, ctx: Dict[str, Any], signal: Dict[str, Any]) -> FeatureSnapshot:
    c = _safe_float(df5m["close"].iloc[-1])
    o = _safe_float(df5m["open"].iloc[-1])
    h = _safe_float(df5m["high"].iloc[-1])
    l = _safe_float(df5m["low"].iloc[-1])
    v = _safe_float(df5m["volume"].iloc[-1])
    vmed = _safe_float(df5m["volume"].tail(30).median(), 0.0)

    atr = _atr(df5m, 14)
    rng = max(0.0, h - l)
    body = c - o
    body_ratio = abs(body) / max(1e-12, rng)

    ema9 = _ema(df5m["close"], 9)
    ema21 = _ema(df5m["close"], 21)
    ema50 = _ema(df5m["close"], 50)

    def slope(span: int) -> float:
        ema = _ema(df5m["close"], span)
        ema_prev = _ema(df5m["close"].iloc[:-1], span) if len(df5m) > 1 else ema
        return (ema - ema_prev) / max(1e-9, c)

    ema9_slope = slope(9)
    ema21_slope = slope(21)
    ema50_slope = slope(50)

    prev_hi_6 = _safe_float(df5m["high"].iloc[-6:-1].max(), 0.0) if len(df5m) >= 6 else h
    prev_lo_6 = _safe_float(df5m["low"].iloc[-6:-1].min(), 0.0) if len(df5m) >= 6 else l
    bos_up = int(c > prev_hi_6)
    bos_dn = int(c < prev_lo_6)

    if len(df5m) >= 5:
        recent_ranges = [ _safe_float(df5m["high"].iloc[i] - df5m["low"].iloc[i]) for i in range(-5, -1) ]
        consolidation = float(np.mean(recent_ranges)) if recent_ranges else 0.0
    else:
        consolidation = 0.0

    tm = (ctx.get("timeframe") or "5m")
    t15 = (ctx.get("trend_15m") or "SIDEWAYS").upper()
    t1h = (ctx.get("trend_1h") or "SIDEWAYS").upper()
    tmaster = (ctx.get("trend_hint") or "SIDEWAYS").upper()

    # risk and signal
    entry = _safe_float(signal.get("entry"))
    sl = _safe_float(signal.get("sl_hint"))
    tp = _safe_float(signal.get("tp_hint"))
    R = abs(entry - sl)
    rr = abs(tp - entry) / max(1e-12, R) if R > 0 else 0.0

    now = datetime.utcnow()
    snap = FeatureSnapshot(
        symbol=symbol, agent=agent, timeframe=str(tm), side=side,
        price=c, open=o, high=h, low=l,
        volume_now=v, volume_med30=vmed,
        atr14=atr, bar_range=rng, body=body, body_ratio=body_ratio,
        ema9=ema9, ema21=ema21, ema50=ema50,
        ema9_slope=ema9_slope, ema21_slope=ema21_slope, ema50_slope=ema50_slope,
        prev_hi_6=prev_hi_6, prev_lo_6=prev_lo_6, bos_up=bos_up, bos_dn=bos_dn,
        consolidation_4_mean_range=consolidation,
        trend_15m=t15, trend_1h=t1h, trend_master=tmaster,
        hour_utc=now.hour, dow_utc=now.weekday(),
        entry_px=entry, sl_px=sl, tp_px=tp, rr=rr,
        leverage=_safe_float(ctx.get("leverage", 1.0)),
        alloc_usdt=_safe_float(ctx.get("alloc_usdt", 0.0)),
        conf_score=_safe_float(signal.get("confidence", 0.0)),
        weight=_safe_float(ctx.get("weight", 1.0)),
        recent_wr=_safe_float(ctx.get("recent_wr", 1.0)),
        signal_reason=str(signal.get("reason", ""))[:240],
    )
    return snap


# -------------------- Storage (SQLite) --------------------

class TradeMemory:
    def __init__(self, db_path: str = "apex_trade_memory.sqlite", parquet_path: Optional[str] = None):
        self.db_path = db_path
        self.parquet_path = parquet_path  # optional rolling append

        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            trade_id TEXT PRIMARY KEY,
            symbol TEXT,
            agent TEXT,
            timeframe TEXT,
            side TEXT,
            opened_at TEXT,
            closed_at TEXT,
            outcome TEXT,           -- TP / SL / TRAIL / TIME / MANUAL
            close_reason TEXT,
            entry_px REAL,
            sl_px REAL,
            tp_px REAL,
            qty REAL,
            leverage REAL,
            alloc_usdt REAL,
            rr REAL,
            conf_score REAL,
            pnl_usdt REAL,
            features_json TEXT,
            ctx_json TEXT
        )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_trades_agent ON trades(agent)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_trades_outcome ON trades(outcome)')
        conn.commit()
        conn.close()

    @staticmethod
    def _fingerprint_hash(snap: FeatureSnapshot) -> str:
        # Hash a stable subset rounded to avoid float noise
        feats = snap.to_vector()
        key = "|".join(f"{x:.6f}" for x in feats) + f"|{snap.side}|{snap.agent}|{snap.timeframe}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()

    def record_open(self, snap: FeatureSnapshot, qty: float, ctx_extra: Dict[str, Any]) -> str:
        trade_id = self._fingerprint_hash(snap) + f":{int(time.time()*1000)}"
        row = {
            "trade_id": trade_id,
            "symbol": snap.symbol,
            "agent": snap.agent,
            "timeframe": snap.timeframe,
            "side": snap.side,
            "opened_at": _utc_now_iso(),
            "closed_at": None,
            "outcome": None,
            "close_reason": None,
            "entry_px": snap.entry_px,
            "sl_px": snap.sl_px,
            "tp_px": snap.tp_px,
            "qty": float(qty),
            "leverage": snap.leverage,
            "alloc_usdt": snap.alloc_usdt,
            "rr": snap.rr,
            "conf_score": snap.conf_score,
            "pnl_usdt": None,
            "features_json": json.dumps(asdict(snap)),
            "ctx_json": json.dumps(ctx_extra or {}),
        }
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        cols = ",".join(row.keys())
        qs = ",".join(["?"]*len(row))
        c.execute(f"INSERT INTO trades ({cols}) VALUES ({qs})", list(row.values()))
        conn.commit()
        conn.close()

        # Optional Parquet rolling append
        if self.parquet_path:
            try:
                df = pd.DataFrame([row])
                if os.path.exists(self.parquet_path):
                    df.to_parquet(self.parquet_path, engine="pyarrow", append=True)
                else:
                    df.to_parquet(self.parquet_path, engine="pyarrow")
            except Exception:
                pass  # parquet is optional

        return trade_id

    def record_close(self, trade_id: str, outcome: str, close_reason: str, pnl_usdt: float):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            UPDATE trades SET closed_at=?, outcome=?, close_reason=?, pnl_usdt=?
            WHERE trade_id=?
        """, (_utc_now_iso(), str(outcome), str(close_reason), float(pnl_usdt), trade_id))
        conn.commit()
        conn.close()

    def fetch_history(self, symbol: Optional[str]=None, agent: Optional[str]=None, limit: int=1000) -> pd.DataFrame:
        conn = sqlite3.connect(self.db_path)
        q = "SELECT * FROM trades WHERE 1=1"
        params = []
        if symbol:
            q += " AND symbol=?"
            params.append(symbol)
        if agent:
            q += " AND agent=?"
            params.append(agent)
        q += " ORDER BY opened_at DESC LIMIT ?"
        params.append(int(limit))
        df = pd.read_sql_query(q, conn, params=params)
        conn.close()
        return df

    # -------------------- kNN Lookback Scorer --------------------

    def _rows_to_vectors(self, df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        vecs, labels = [], []
        for _, r in df.iterrows():
            try:
                f = json.loads(r["features_json"])
            except Exception:
                continue
            # Only use completed (labeled) trades
            if not r.get("outcome"):
                continue
            snap = FeatureSnapshot(**{k: f[k] for k in FeatureSnapshot.__annotations__.keys()})
            vecs.append(snap.to_vector())
            labels.append(1.0 if str(r["outcome"]).upper() == "TP" else 0.0)  # 1=win, 0=not-win
        if not vecs:
            return np.zeros((0,14), dtype=float), np.zeros((0,), dtype=float)
        return np.array(vecs, dtype=float), np.array(labels, dtype=float)

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        num = float(np.dot(a, b))
        den = float(np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12
        return num / den

    def neighbor_winrate(self, snap: FeatureSnapshot, k: int = 50, symbol_scope: Optional[str] = None, agent_scope: Optional[str] = None) -> Dict[str, Any]:
        df = self.fetch_history(symbol=symbol_scope, agent=agent_scope, limit=5000)
        X, y = self._rows_to_vectors(df)
        q = np.array(snap.to_vector(), dtype=float)
        if X.shape[0] == 0:
            return {"n": 0, "wr": None, "mult": 1.0}

        # cosine similarities
        sims = (X @ q) / (np.linalg.norm(X, axis=1) * (np.linalg.norm(q) + 1e-12) + 1e-12)
        idx = np.argsort(-sims)[:min(k, len(sims))]
        wr = float(np.mean(y[idx])) if len(idx) else None

        # Convert WR to a gentle multiplier (0.8 .. 1.2)
        mult = 1.0
        if wr is not None:
            mult = 0.8 + 0.4 * max(0.0, min(1.0, wr))  # 0.8 at 0% WR, 1.2 at 100% WR
        return {"n": int(len(idx)), "wr": wr, "mult": float(mult)}


# -------------------- Integration helpers --------------------

def on_order_open(memory: TradeMemory, df5m: pd.DataFrame, symbol: str, agent: str, side: str,
                  ctx: Dict[str, Any], signal: Dict[str, Any], qty: float, ctx_extra: Optional[Dict[str, Any]] = None) -> str:
    snap = extract_snapshot(df5m, symbol, agent, side, ctx, signal)
    trade_id = memory.record_open(snap, qty=qty, ctx_extra=ctx_extra or {})
    return trade_id

def on_order_close(memory: TradeMemory, trade_id: str, outcome: str, close_reason: str, pnl_usdt: float) -> None:
    memory.record_close(trade_id, outcome=outcome, close_reason=close_reason, pnl_usdt=pnl_usdt)

def pre_trade_adjust_conf(memory: TradeMemory, df5m: pd.DataFrame, symbol: str, agent: str, side: str,
                          ctx: Dict[str, Any], signal: Dict[str, Any], scope_same_agent: bool = True) -> Tuple[float, Dict[str, Any]]:
    """Compute neighbor WR multiplier and return adjusted confidence + debug info."""
    snap = extract_snapshot(df5m, symbol, agent, side, ctx, signal)
    scope_agent = agent if scope_same_agent else None
    info = memory.neighbor_winrate(snap, k=50, symbol_scope=None, agent_scope=scope_agent)
    base_conf = float(signal.get("confidence", 0.0))
    adj_conf = max(0.0, min(0.99, base_conf * info.get("mult", 1.0)))
    return adj_conf, {"neighbor_info": info, "base_conf": base_conf, "adj_conf": adj_conf}
