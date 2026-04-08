# -*- coding: utf-8 -*-
# strategy_core.py

def macd_strategy(prices):
    # Placeholder logic
    return "buy", 85

def rsi_strategy(prices):
    return "hold", 70

def nova_fractal_strategy(prices):
    return "buy", 96  # Simulated cosmic signal

# Dictionary of strategy agents
strategy_agents = {
    "MACD": macd_strategy,
    "RSI": rsi_strategy,
    "NOVA_FRACTAL": nova_fractal_strategy,
}
