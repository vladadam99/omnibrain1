# -*- coding: utf-8 -*-
# binance_trade.py - OMNIBRAIN Binance Trading Core

import json
from binance.client import Client
from binance.enums import *

# === Load config ===
with open("config.json") as f:
    config = json.load(f)

USE_TESTNET = config.get("use_testnet", True)
API_KEY = config["testnet_api_key"] if USE_TESTNET else config["api_key"]
API_SECRET = config["testnet_api_secret"] if USE_TESTNET else config["api_secret"]

# === Setup Binance client ===
client = Client(API_KEY, API_SECRET)
if USE_TESTNET:
    client.API_URL = 'https://testnet.binance.vision/api'

# === Live Order Function ===
def place_order(symbol, side, order_type, quantity, price=None, stop_price=None):
    params = {
        "symbol": symbol,
        "side": SIDE_BUY if side == "buy" else SIDE_SELL,
        "type": order_type,
        "quantity": quantity,
    }

    if order_type == ORDER_TYPE_LIMIT:
        params["price"] = str(price)
        params["timeInForce"] = TIME_IN_FORCE_GTC

    if order_type == ORDER_TYPE_STOP_LOSS_LIMIT:
        params["price"] = str(price)
        params["stopPrice"] = str(stop_price)
        params["timeInForce"] = TIME_IN_FORCE_GTC

    if order_type == ORDER_TYPE_OCO:
        # Requires custom handling: returns dict with 2 orders
        return client.create_oco_order(
            symbol=symbol,
            side=params["side"],
            quantity=quantity,
            price=str(price),
            stopPrice=str(stop_price),
            stopLimitPrice=str(stop_price),
            stopLimitTimeInForce=TIME_IN_FORCE_GTC
        )

    return client.create_order(**params)

# === Fetch Account Info ===
def get_open_orders(symbol=None):
    return client.get_open_orders(symbol=symbol) if symbol else client.get_open_orders()

def cancel_order(symbol, order_id):
    return client.cancel_order(symbol=symbol, orderId=order_id)


def get_account():
    return client.get_account()

def get_position(symbol):
    trades = client.get_my_trades(symbol=symbol)
    return trades[-1] if trades else None
