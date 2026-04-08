# -*- coding: utf-8 -*-
from binance.client import Client

class TradeExecutor:
    def __init__(self, api_key, api_secret, testnet=True):
        self.client = Client(api_key, api_secret)
        if testnet:
            self.client.API_URL = "https://testnet.binance.vision/api"

    def place_order(self, symbol, side, quantity, order_type="MARKET"):
        try:
            order = self.client.create_order(
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity
            )
            return order
        except Exception as e:
            print(f"Trade order failed: {e}")
            return None
