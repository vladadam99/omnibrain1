# -*- coding: utf-8 -*-
import pandas as pd

class MetaGovernor:
    def __init__(self, agent_configs):
        self.agent_configs = agent_configs
        self.agents = [self.create_agent(cfg["name"], cfg["params"]) for cfg in agent_configs]

    def create_agent(self, name, params):
        if name == "MACD_RSI":
            return MACDRSI(name, **params)
        elif name == "SuperTrend":
            return SuperTrend(name, **params)
        elif name == "RSI":
            return RSI(name, **params)
        elif name == "Bollinger":
            return Bollinger(name, **params)
        elif name == "Momentum":
            return Momentum(name, **params)
        elif name == "MACDCross":
            return MACDCross(name, **params)
        elif name == "ADX":
            return ADX(name, **params)
        elif name == "VWAP":
            return VWAP(name, **params)
        else:
            raise ValueError(f"Unknown agent: {name}")

    def evaluate_all(self, df):
        results = []
        for agent in self.agents:
            try:
                signal = agent.evaluate(df)
                results.append({
                    "agent": agent.name,
                    "signal": signal.get("action", "hold"),
                    "confidence": signal.get("confidence", 1.0)
                })
            except Exception as e:
                print(f"[Agent Error] {agent.name} failed: {e}")
        return results

class BaseAgent:
    def __init__(self, name):
        self.name = name

    def evaluate(self, df):
        raise NotImplementedError("Agent must implement evaluate method")

class MACDRSI(BaseAgent):
    def __init__(self, name, macd_fast, macd_slow, rsi_low, rsi_high):
        super().__init__(name)

    def evaluate(self, df):
        return {"action": "buy", "confidence": 1.0}

class SuperTrend(BaseAgent):
    def __init__(self, name, atr_period, multiplier):
        super().__init__(name)

    def evaluate(self, df):
        return {"action": "hold", "confidence": 0.0}

class RSI(BaseAgent):
    def __init__(self, name, window, low, high):
        super().__init__(name)

    def evaluate(self, df):
        return {"action": "sell", "confidence": 1.0}

class Bollinger(BaseAgent):
    def __init__(self, name, window, num_std):
        super().__init__(name)

    def evaluate(self, df):
        return {"action": "hold", "confidence": 0.0}

class Momentum(BaseAgent):
    def __init__(self, name, window):
        super().__init__(name)

    def evaluate(self, df):
        return {"action": "buy", "confidence": 1.0}

class MACDCross(BaseAgent):
    def __init__(self, name, fast, slow):
        super().__init__(name)

    def evaluate(self, df):
        return {"action": "hold", "confidence": 0.0}

class ADX(BaseAgent):
    def __init__(self, name, window, threshold):
        super().__init__(name)

    def evaluate(self, df):
        return {"action": "buy", "confidence": 0.7}

class VWAP(BaseAgent):
    def __init__(self, name, window):
        super().__init__(name)

    def evaluate(self, df):
        return {"action": "hold", "confidence": 0.5}
