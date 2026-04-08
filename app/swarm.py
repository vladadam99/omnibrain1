# -*- coding: utf-8 -*-
import pandas as pd
from ta.trend import MACD
from ta.momentum import RSIIndicator

class MACDAgent:
    def __init__(self, name: str, symbol: str, df: pd.DataFrame,
                 *, fast: int = 12, slow: int = 26, signal: int = 9):
        self.name   = name
        self.symbol = symbol
        self.df     = df
        self.fast   = fast
        self.slow   = slow
        self.signal = signal

    def decide(self, step: int) -> int:
        # slice up to current step, convert to 1D Series
        series = pd.Series(self.df['Close'].iloc[:step+1].to_numpy().flatten())
        ind = MACD(
            close=series,
            window_fast=self.fast,
            window_slow=self.slow,
            window_sign=self.signal
        )
        diff = ind.macd_diff().iloc[-1]
        return 1 if diff > 0 else 0

class RSIAgent:
    def __init__(self, name: str, symbol: str, df: pd.DataFrame,
                 *, lower: float = 30, upper: float = 70):
        self.name   = name
        self.symbol = symbol
        self.df     = df
        self.lower  = lower
        self.upper  = upper

    def decide(self, step: int) -> int:
        series = pd.Series(self.df['Close'].iloc[:step+1].to_numpy().flatten())
        latest = RSIIndicator(close=series).rsi().iloc[-1]
        if latest < self.lower: return  1
        if latest > self.upper: return -1
        return 0

class SwarmManager:
    def __init__(self, agents: list, price_dfs: dict[str, pd.DataFrame]):
        self.agents = agents
        # precompute returns arrays
        self.returns = {
            sym: df['Close'].pct_change().fillna(0).to_numpy()
            for sym, df in price_dfs.items()
        }
        self.weight_history      = {a.name: [] for a in agents}
        self.performance_history = []

    def allocate(self, decisions: dict[str, int]) -> dict[str, float]:
        total = sum(abs(v) for v in decisions.values()) or 1
        return {name: sig/total for name, sig in decisions.items()}

    def run(self):
        n = len(next(iter(self.returns.values())))
        cum = 0.0
        for t in range(n):
            # 1) get signals
            decs = {a.name: a.decide(t) for a in self.agents}
            # 2) to weights
            wts = self.allocate(decs)
            for name, w in wts.items():
                self.weight_history[name].append(w)
            # 3) portfolio return
            port = sum(wts[a.name] * self.returns[a.symbol][t] for a in self.agents)
            cum += float(port)
            # 4) record cumulative P&L per agent
            self.performance_history.append({a.name: cum for a in self.agents})
