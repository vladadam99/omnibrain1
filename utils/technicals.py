# -*- coding: utf-8 -*-
# === technicals.py ===
# Contains utility functions like ATR, SMA, RSI, etc.

from binance.client import Client
import numpy as np

def get_klines(symbol, interval="1m", limit=20):
    client = Client()
    return client.get_klines(symbol=symbol, interval=interval, limit=limit)

def calculate_atr(symbol, interval="1m", period=14):
    klines = get_klines(symbol, interval=interval, limit=period + 1)
    highs = [float(k[2]) for k in klines]
    lows = [float(k[3]) for k in klines]
    closes = [float(k[4]) for k in klines]

    trs = []
    for i in range(1, len(closes)):
        high = highs[i]
        low = lows[i]
        prev_close = closes[i - 1]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    atr = np.mean(trs)
    return round(atr, 4)

# Future: add RSI, SMA, EMA here
