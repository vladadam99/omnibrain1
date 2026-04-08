
# -*- coding: utf-8 -*-
"""PaperBroker: identical interface to a live broker, but with virtual balance.
This is STEP 2 piece: used by the governor to run a 48h paper shadow that mirrors live decisions.
It keeps fills & PnL deterministic from incoming OHLCV marks.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from pathlib import Path
import time, json, math

@dataclass
class Position:
    symbol: str
    side: str   # LONG/SHORT
    qty: float
    entry_price: float
    unrealized: float = 0.0

@dataclass
class PaperBroker:
    balance_usdt: float = 1000.0
    fee_bps: float = 7.5  # 0.075% (Binance futures default taker ~7.5bps)
    slippage_bps: float = 1.0
    positions: Dict[str, Position] = field(default_factory=dict)
    trades_path: Optional[str] = None

    def _now_iso(self):
        import datetime as _dt
        return _dt.datetime.utcnow().replace(microsecond=0).isoformat()+"Z"

    def _log_trade(self, row: Dict[str, Any]):
        if not self.trades_path:
            return
        newfile = not Path(self.trades_path).exists()
        with open(self.trades_path, "a", encoding="utf-8") as f:
            if newfile:
                f.write("time,symbol,action,side,price,qty,agent,pnl,note\n")
            f.write(",".join([
                row.get("time", self._now_iso()),
                row.get("symbol",""),
                row.get("action",""),
                row.get("side",""),
                f"{float(row.get('price',0)):.8f}",
                f"{float(row.get('qty',0)):.6f}",
                row.get("agent",""),
                f"{float(row.get('pnl',0)):.2f}",
                row.get("note","")
            ]) + "\n")

    def mark(self, symbol: str, price: float):
        # Update unrealized PnL
        pos = self.positions.get(symbol)
        if not pos: return
        direction = 1 if pos.side.upper()=="LONG" else -1
        pos.unrealized = direction * (price - pos.entry_price) * pos.qty

    def place_market(self, symbol: str, side: str, qty: float, price: float, agent: str = "unknown"):
        # Apply slippage/fees
        slip = price * (self.slippage_bps/10000.0) * (1 if side.upper()=="BUY" else -1)
        px = price + slip
        fee = abs(px * qty) * (self.fee_bps/10000.0)
        # Open/augment position (netting, one net position per symbol)
        existing = self.positions.get(symbol)
        if existing and ((existing.side=="LONG" and side.upper()=="BUY") or (existing.side=="SHORT" and side.upper()=="SELL")):
            # add to same direction
            new_qty = existing.qty + qty
            existing.entry_price = (existing.entry_price*existing.qty + px*qty) / max(1e-9, new_qty)
            existing.qty = new_qty
        elif existing:
            # reduce or flip
            direction = 1 if existing.side=="LONG" else -1
            reduce_qty = min(existing.qty, qty)
            realized = direction * (px - existing.entry_price) * reduce_qty
            self.balance_usdt += realized - fee
            self._log_trade({"symbol":symbol,"action":"CLOSE","side":side.upper(),"price":px,"qty":reduce_qty,"agent":agent,"pnl":realized,"note":"paper close"})
            if abs(existing.qty - reduce_qty) < 1e-9:
                del self.positions[symbol]
            else:
                existing.qty -= reduce_qty
                # If qty bigger, open reverse for remainder
                rem = qty - reduce_qty
                if rem > 1e-9:
                    new_side = "LONG" if side.upper()=="BUY" else "SHORT"
                    self.positions[symbol] = Position(symbol,new_side,rem,px,0.0)
        else:
            new_side = "LONG" if side.upper()=="BUY" else "SHORT"
            self.positions[symbol] = Position(symbol,new_side,qty,px,0.0)

        self.balance_usdt -= fee
        self._log_trade({"symbol":symbol,"action":"OPEN","side":side.upper(),"price":px,"qty":qty,"agent":agent,"pnl":0.0,"note":"paper open"})

    def close_market(self, symbol: str, price: float, agent: str = "unknown"):
        pos = self.positions.get(symbol)
        if not pos: return 0.0
        fee = abs(price * pos.qty) * (self.fee_bps/10000.0)
        direction = 1 if pos.side.upper()=="LONG" else -1
        realized = direction * (price - pos.entry_price) * pos.qty
        self.balance_usdt += realized - fee
        self._log_trade({"symbol":symbol,"action":"CLOSE","side":"SELL" if pos.side=="LONG" else "BUY","price":price,"qty":pos.qty,"agent":agent,"pnl":realized,"note":"paper close all"})
        del self.positions[symbol]
        return realized - fee

    def equity(self, marks: Dict[str,float]|None=None) -> float:
        eq = self.balance_usdt
        if marks:
            for s,p in marks.items():
                pos = self.positions.get(s)
                if pos:
                    direction = 1 if pos.side=="LONG" else -1
                    eq += direction * (p - pos.entry_price) * pos.qty
        return eq
