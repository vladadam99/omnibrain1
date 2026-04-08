# -*- coding: utf-8 -*-
# --- binance_connector.py ---
import time
import hmac
import hashlib
import requests
import urllib.parse
import os
from config_loader import load_config

class BinanceConnector:
    def __init__(self):
        config = load_config()
        self.use_testnet = config.get("use_testnet", True)

        self.base_url = (
            "https://testnet.binance.vision" if self.use_testnet
            else "https://api.binance.com"
        )

        self.api_key = config["binance"]["api_key"]
        self.api_secret = config["binance"]["api_secret"]

    def _sign(self, params):
        query = urllib.parse.urlencode(params)
        signature = hmac.new(
            self.api_secret.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()
        return f"{query}&signature={signature}"

    def place_order(self, symbol, side, quantity, order_type="MARKET"):
        try:
            endpoint = "/api/v3/order"
            url = self.base_url + endpoint
            timestamp = int(time.time() * 1000)

            params = {
                "symbol": symbol,
                "side": side.upper(),
                "type": order_type,
                "quantity": quantity,
                "timestamp": timestamp
            }

            headers = {"X-MBX-APIKEY": self.api_key}
            signed_query = self._sign(params)
            response = requests.post(f"{url}?{signed_query}", headers=headers)
            return response.json()
        except Exception as e:
            return {"error": str(e)}
