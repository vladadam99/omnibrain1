# -*- coding: utf-8 -*-
# market_scanner_ai.py — OMNIBRAIN Market Scanner AI

from binance.client import Client
import json
import os

class MarketScannerAI:
    def __init__(self):
        with open("config.json") as f:
            config = json.load(f)
        api_key = config["testnet_api_key"] if config.get("use_testnet", True) else config["api_key"]
        api_secret = config["testnet_api_secret"] if config.get("use_testnet", True) else config["api_secret"]

        self.client = Client(api_key, api_secret)
        if config.get("use_testnet", True):
            self.client.API_URL = 'https://testnet.binance.vision/api'

    def get_top_pairs_by_volume(self, quote="USDT", limit=10):
        tickers = self.client.get_ticker()
        volume_map = []
        for t in tickers:
            if t["symbol"].endswith(quote):
                try:
                    vol = float(t["quoteVolume"])
                    volume_map.append((t["symbol"], vol))
                except:
                    continue
        volume_map.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in volume_map[:limit]]

# === Example run ===
if __name__ == "__main__":
    scanner = MarketScannerAI()
    top = scanner.get_top_pairs_by_volume(limit=5)
    print("🔥 Top Pairs:", top)
