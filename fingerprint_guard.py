
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json, os, math, threading
from typing import Dict, Any, Tuple, Optional, List

def _canon_agent_list(agent_list: str) -> str:
    if not agent_list:
        return ""
    parts = [p.strip() for p in agent_list.split(",") if p and p.strip()]
    parts = sorted(set(parts))
    return ",".join(parts)

def _bucket(value: float, step: float) -> float:
    if step <= 0:
        return round(value, 6)
    return round(step * round(float(value) / step), 6)

def _safe_get(d: Dict[str, Any], *keys, default=None):
    cur = d
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur

class FingerprintGuard:
    def __init__(self,
                 memory_path: str,
                 atr_bucket_step: float = 0.05,
                 recent_days: int = 21,
                 partial_enable: bool = True,
                 partial_win_thresh: float = 0.85,
                 partial_block_thresh: float = 0.85):
        self.path = os.path.abspath(memory_path)
        self.atr_bucket_step = atr_bucket_step
        self.recent_days = recent_days
        self.partial_enable = partial_enable
        self.partial_win_thresh = partial_win_thresh
        self.partial_block_thresh = partial_block_thresh
        self._lock = threading.Lock()
        self._mtime = None
        self._index = {"WIN": {}, "LOSS": {}}
        self._events: List[Dict[str, Any]] = []
        self._load()

    def decide(self, cand: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        self._refresh_if_needed()
        key = self._make_key(cand)
        win_hits = self._index["WIN"].get(key, 0)
        loss_hits = self._index["LOSS"].get(key, 0)

        if loss_hits > 0:
            return "block", {"reason": "exact_loss_match", "exact": True, "win_hits": win_hits, "loss_hits": loss_hits, "similar_win": 0.0, "similar_loss": 1.0}
        if win_hits > 0:
            return "force_allow", {"reason": "exact_win_match", "exact": True, "win_hits": win_hits, "loss_hits": loss_hits, "similar_win": 1.0, "similar_loss": 0.0}

        if self.partial_enable:
            sw = self._best_similarity(cand, outcome="WIN")
            sl = self._best_similarity(cand, outcome="LOSS")
            if sl >= self.partial_block_thresh and sl > sw:
                return "block", {"reason": "partial_loss_similarity", "exact": False, "win_hits": 0, "loss_hits": 0, "similar_win": sw, "similar_loss": sl}
            if sw >= self.partial_win_thresh and sw > sl:
                return "allow", {"reason": "partial_win_similarity", "exact": False, "win_hits": 0, "loss_hits": 0, "similar_win": sw, "similar_loss": sl}

        return "skip", {"reason": "no_match", "exact": False, "win_hits": 0, "loss_hits": 0, "similar_win": 0.0, "similar_loss": 0.0}

    def stats(self) -> Dict[str, Any]:
        self._refresh_if_needed()
        return {"win_keys": len(self._index["WIN"]), "loss_keys": len(self._index["LOSS"]), "events": len(self._events), "path": self.path}

    def make_candidate(self, *, symbol: str, side: str, agent_list: str, timeframe: str,
                       t15: str, t1h: str, master: str, atr: float, vol_class: str) -> Dict[str, Any]:
        return {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "agent": _canon_agent_list(agent_list),
            "timeframe": str(timeframe),
            "trend": {"t15": t15, "t1h": t1h, "master": master},
            "features": {"atr": float(atr), "vol_class": vol_class},
        }

    def _refresh_if_needed(self):
        try:
            m = os.path.getmtime(self.path)
        except FileNotFoundError:
            return
        if self._mtime is None or m != self._mtime:
            self._load()

    def _load(self):
        events: List[Dict[str, Any]] = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        events.append(obj)
                    except Exception:
                        continue
        except FileNotFoundError:
            pass

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.recent_days)
        win_idx, loss_idx = {}, {}
        for e in events:
            if (e.get("event") or e.get("type")) not in ("CLOSE", "close", "Close"):
                continue
            ts_str = e.get("ts") or e.get("timestamp")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z","+00:00")) if ts_str else None
            except Exception:
                ts = None
            if ts and ts < cutoff:
                continue

            res = (e.get("outcome") or e.get("result") or "").upper()
            if not res:
                try:
                    pnl = float(e.get("realized_pnl", 0.0))
                    res = "WIN" if pnl >= 0 else "LOSS"
                except Exception:
                    continue

            key = self._make_key(e)
            if not key:
                continue

            if res == "WIN":
                win_idx[key] = win_idx.get(key, 0) + 1
            elif res == "LOSS":
                loss_idx[key] = loss_idx.get(key, 0) + 1

        self._events = events
        self._index = {"WIN": win_idx, "LOSS": loss_idx}
        try:
            self._mtime = os.path.getmtime(self.path)
        except FileNotFoundError:
            self._mtime = None

    def _make_key(self, e: Dict[str, Any]) -> Optional[str]:
        sym = (_safe_get(e, "symbol") or "").upper()
        side = (_safe_get(e, "side") or "").upper()
        agent = _canon_agent_list(_safe_get(e, "agent") or "")
        tf = str(_safe_get(e, "timeframe", default=""))
        trend = _safe_get(e, "trend", default={}) or {}
        t15 = (trend.get("t15") or "").upper()
        t1h = (trend.get("t1h") or "").upper()
        mast = (trend.get("master") or trend.get("master_trend") or "").upper()

        feat = _safe_get(e, "features", default={}) or {}
        volc = (feat.get("vol_class") or "").upper()
        atr = feat.get("atr")
        try:
            atr_b = _bucket(float(atr), self.atr_bucket_step) if atr is not None else None
        except Exception:
            atr_b = None

        if not (sym and side and tf and mast):
            return None

        return "|".join([sym, side, agent, tf, t15, t1h, mast, volc, str(atr_b)])

    def _best_similarity(self, cand: Dict[str, Any], outcome: str) -> float:
        target = "WIN" if outcome.upper().startswith("W") else "LOSS"
        if target not in self._index:
            return 0.0
        sym = cand.get("symbol","").upper()
        side = cand.get("side","").upper()
        agent = _canon_agent_list(cand.get("agent",""))
        tf = str(cand.get("timeframe",""))
        trend = cand.get("trend",{}) or {}
        t15 = (trend.get("t15") or "").upper()
        t1h = (trend.get("t1h") or "").upper()
        mast = (trend.get("master") or "").upper()
        feat = cand.get("features",{}) or {}
        volc = (feat.get("vol_class") or "").upper()
        atr = feat.get("atr")
        try:
            atr_b = _bucket(float(atr), self.atr_bucket_step) if atr is not None else None
        except Exception:
            atr_b = None

        best = 0.0
        for k in self._index[target].keys():
            parts = k.split("|")
            score = 0
            score += 1 if parts[0] == sym else 0
            score += 1 if parts[1] == side else 0
            score += 1 if parts[2] == agent else 0
            score += 1 if parts[3] == tf else 0
            score += 1 if parts[4] == t15 else 0
            score += 1 if parts[5] == t1h else 0
            score += 2 if parts[6] == mast else 0
            score += 1 if parts[7] == volc else 0
            score += 1 if parts[8] == str(atr_b) else 0
            best = max(best, score / 10.0)
        return best
