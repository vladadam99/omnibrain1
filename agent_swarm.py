# -*- coding: utf-8 -*-
from agents.macd_agent import macd_signal
from agents.rsi_agent import rsi_signal
from agents.supertrend_agent import supertrend_signal
from agents.vortex_cosmic_agent import vortex_cosmic_signal
from agents.pulse_warp_agent import pulse_warp_signal

def get_all_signals(symbol, data):
    agents = [
        macd_signal,
        rsi_signal,
        supertrend_signal,
        vortex_cosmic_signal,
        pulse_warp_signal
    ]

    signals = {}

    for agent in agents:
        try:
            signal = agent(symbol, data)  # ✅ Pass both symbol and data
            signals[agent] = signal
        except Exception as e:
            print(f"[Agent Error] {agent.__name__}: {e}")
            signals[agent] = None

    return signals
