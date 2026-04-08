# -*- coding: utf-8 -*-
import aiohttp
import asyncio
import datetime
import time

BASE_URL = "https://api.binance.com"

async def fetch_binance_data():
    url = f"{BASE_URL}/api/v3/ticker/24hr"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()

async def fetch_klines(symbol, interval="15m", limit=100):
    url = f"{BASE_URL}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()

async def get_top_gainers(limit=5, volume_threshold=10000000):
    try:
        data = await fetch_binance_data()
        usdt_pairs = [
            x for x in data
            if x["symbol"].endswith("USDT")
            and not any(stable in x["symbol"] for stable in ["BUSD", "USDC"])
            and float(x["quoteVolume"]) > volume_threshold
        ]
        sorted_pairs = sorted(usdt_pairs, key=lambda x: float(x["priceChangePercent"]), reverse=True)
        top_symbols = [x["symbol"] for x in sorted_pairs[:limit]]

        result = []
        for symbol in top_symbols:
            klines = await fetch_klines(symbol)
            candles = [
                {
                    "time": int(k[0]),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5])
                }
                for k in klines
            ]
            result.append({"symbol": symbol, "data": candles})
        return result

    except Exception as e:
        print(f"[Scanner Error] {e}")
        return []
