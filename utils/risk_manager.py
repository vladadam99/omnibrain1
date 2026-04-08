# -*- coding: utf-8 -*-
# risk_manager.py
import json
from datetime import datetime

class RiskManager:
    def __init__(self, config_path="config.json"):
        # Load risk parameters from config file
        with open(config_path, "r") as f:
            conf = json.load(f)

        # Capital and risk settings
        self.starting_capital       = conf.get("starting_capital", 10000)
        self.risk_per_trade         = conf.get("risk_per_trade", 0.01)
        self.atr_multiplier         = conf.get("atr_multiplier", 1.5)
        self.max_daily_drawdown     = conf.get("max_daily_drawdown", 0.02)
        self.max_consecutive_losses = conf.get("max_consecutive_losses", 3)

        # Runtime tracking
        self.daily_capital_start = self.starting_capital
        self.daily_losses        = 0
        self.consecutive_losses  = 0
        self.last_trade_date     = None

    def check_limits(self, capital, atr, current_datetime=None):
        """
        Return True if trading is allowed under risk limits, False otherwise.
        """
        today = (current_datetime.date()
                 if current_datetime else datetime.now().date())
        if self.last_trade_date != today:
            self.daily_capital_start = capital
            self.daily_losses       = 0
            self.consecutive_losses = 0
        self.last_trade_date = today

        # 1) Daily drawdown check
        if capital < self.daily_capital_start * (1 - self.max_daily_drawdown):
            return False
        # 2) Consecutive loss check
        if self.consecutive_losses >= self.max_consecutive_losses:
            return False
        return True

    def size_order(self, capital, atr):
        """
        Calculate position size based on risk per trade and ATR-based stop.
        """
        risk_amount = capital * self.risk_per_trade
        stop_distance = atr * self.atr_multiplier
        if stop_distance <= 0:
            return 0
        return risk_amount / stop_distance

    def record_trade_result(self, pnl):
        """
        Update internal counters after a trade outcome.
        """
        if pnl < 0:
            self.daily_losses       += abs(pnl)
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
