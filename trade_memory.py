import json

# -*- coding: utf-8 -*-
"""
TradeMemory
-----------
Lightweight JSONL-based fingerprint store.
Each saved row = {"id": "...", "ts": "...", "symbol": "...", "side": "BUY/SELL",
                  "result": "TP/SL/EXIT", "pnl": float, "features": {...}, "agent": "...",
                  "entry": ..., "exit": ..., "tp": ..., "sl": ..., "leverage": ..., "timeframe": "5m", "extras": {...} }
Counts and last_id are computed on demand.
"""
from __future__ import annotations
import os, json, time, hashlib, datetime, threading

class TradeMemory:
    def __init__(self, path: str):
        self.path = os.path.abspath(os.path.join(os.path.dirname(__file__), path))
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, "w", encoding="utf-8") as f:
                pass  # create empty file

    def _new_id(self, payload: dict) -> str:
        h = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:10]
        ts = int(time.time())
        return f"{ts}-{h}"

    def save(self, payload: dict) -> str:
        """Append payload as a JSONL row. Returns fingerprint id."""
        row = dict(payload)
        if "id" not in row:
            row["id"] = self._new_id(row)
        if "ts" not in row:
            row["ts"] = datetime.datetime.utcnow().isoformat()
        line = json.dumps(row, ensure_ascii=False)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return row["id"]

    def stats(self):
        """Compute wins/losses/total quickly by streaming the file."""
        wins = losses = others = 0
        total = 0
        last_id = None
        if not os.path.exists(self.path):
            return {"wins": 0, "losses": 0, "others": 0, "total": 0, "last_id": None}
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    obj = json.loads(line)
                    last_id = obj.get("id", last_id)
                    res = (obj.get("result") or obj.get("outcome") or "").upper()
                    if res in ("TP", "TAKE_PROFIT", "WIN"):
                        wins += 1
                    elif res in ("SL", "STOP_LOSS", "LOSS"):
                        losses += 1
                    else:
                        others += 1
                except Exception:
                    others += 1
        return {"wins": wins, "losses": losses, "others": others, "total": total, "last_id": last_id}
