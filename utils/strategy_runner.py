# -*- coding: utf-8 -*-
import asyncio
from binance.client import Client
import numpy as np
import talib
import logging

logger = logging.getLogger("StrategyRunner")

class StrategyRunner:
    def __init__(self, agents):
        self.agents = agents
        self.client = Client()  # Use your keys elsewhere
        self.ohlc_cache = {}

    async def fetch_market_data(self, symbol: str):
        # For cosmic speed, cache and reuse short interval data
        try:
            klines = self.client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=50)
        except Exception as e:
            logger.error(f"Error fetching klines for {symbol}: {e}")
            return {}

        closes = np.array([float(k[4]) for k in klines])
        highs = np.array([float(k[2]) for k in klines])
        lows = np.array([float(k[3]) for k in klines])
        volumes = np.array([float(k[5]) for k in klines])

        if len(closes) < 35:
            return {}

        macd, signal, hist = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
        rsi = talib.RSI(closes, timeperiod=14)
        viper_plus = talib.PLUS_DI(highs, lows, closes, timeperiod=14)
        viper_minus = talib.MINUS_DI(highs, lows, closes, timeperiod=14)
        momentum = talib.MOM(closes, timeperiod=10)
        volume_spike = (volumes[-1] - np.mean(volumes[-10:])) / np.mean(volumes[-10:])

        market_data = {
            "macd": macd[-1],
            "signal": signal[-1],
            "hist": hist[-1],
            "rsi": rsi[-1],
            "vortex_positive": viper_plus[-1],
            "vortex_negative": viper_minus[-1],
            "momentum": momentum[-1],
            "volume_spike": volume_spike,
        }
        return market_data
