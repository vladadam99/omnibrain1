# -*- coding: utf-8 -*-
# --- portfolio.py ---
import time

class Portfolio:
    def __init__(self, initial_balance=100000.0):
        self.balance = initial_balance
        self.positions = {}  # {symbol: {side, entry_price, qty, timestamp, agent}}
        self.trade_log = []

    def open_position(self, symbol, side, price, qty, agent):
        key = f"{symbol}_{agent}"
        if key in self.positions:
            return False  # Already open
        self.positions[key] = {
            "symbol": symbol,
            "side": side,
            "entry_price": price,
            "qty": qty,
            "timestamp": time.time(),
            "agent": agent
        }
        return True

    def close_position(self, symbol, price, agent):
        key = f"{symbol}_{agent}"
        pos = self.positions.get(key)
        if not pos:
            return None

        pnl = self._calculate_pnl(pos, price)
        self.balance += pnl
        trade = {
            "symbol": symbol,
            "side": pos["side"],
            "entry": pos["entry_price"],
            "exit": price,
            "qty": pos["qty"],
            "pnl": round(pnl, 2),
            "agent": agent,
            "open_time": pos["timestamp"],
            "close_time": time.time()
        }
        self.trade_log.append(trade)
        del self.positions[key]
        return trade

    def get_open_positions(self):
        return list(self.positions.values())

    def get_trades(self):
        return self.trade_log

    def _calculate_pnl(self, pos, exit_price):
        if pos["side"] == "buy":
            return (exit_price - pos["entry_price"]) * pos["qty"]
        else:
            return (pos["entry_price"] - exit_price) * pos["qty"]

    def get_balance(self):
        return round(self.balance, 2)

    def summary(self):
        return {
            "balance": self.get_balance(),
            "open_positions": len(self.positions),
            "closed_trades": len(self.trade_log)
        }
