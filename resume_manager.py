# -*- coding: utf-8 -*-
# resume_manager.py

import json
import os
from datetime import datetime

RESUME_FILE = "open_positions.json"

class ResumeManager:
    def __init__(self):
        self.positions = self.load()

    def load(self):
        if not os.path.exists(RESUME_FILE):
            return {}
        try:
            with open(RESUME_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {}

    def save(self):
        with open(RESUME_FILE, 'w') as f:
            json.dump(self.positions, f, indent=2)

    def add_position(self, symbol, agent, entry_price, side, qty, confidence, sl, tp):
        self.positions[symbol] = {
            "agent": agent,
            "entry_price": entry_price,
            "side": side,
            "qty": qty,
            "confidence": confidence,
            "sl": sl,
            "tp": tp,
            "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.save()

    def remove_position(self, symbol):
        if symbol in self.positions:
            del self.positions[symbol]
            self.save()

    def get_all(self):
        return self.positions

    def get(self, symbol):
        return self.positions.get(symbol)

    def update_sl_tp(self, symbol, sl=None, tp=None):
        if symbol in self.positions:
            if sl is not None:
                self.positions[symbol]['sl'] = sl
            if tp is not None:
                self.positions[symbol]['tp'] = tp
            self.save()

    def mark_pnl_and_exit_time(self, symbol, pnl):
        if symbol in self.positions:
            self.positions[symbol]['exit_time'] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            self.positions[symbol]['pnl'] = pnl
            self.save()
