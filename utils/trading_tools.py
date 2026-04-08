# -*- coding: utf-8 -*-
import requests
import json
import numpy as np
import time

from binance.client import Client
from binance.enums import *

with open("REAL.txt") as f:
    keys = json.load(f)

client = Client(keys["API_KEY"], keys["API_SECRET"])

def get_balance(asset="USDT"):
    balance = client.get_asset_balance(asset=asset)
    return float(balance['free']) if balance else 0.0

def get_position_size(usdt_balance, confidence):
    fraction = min(1.0, confidence / 100)
    return round(usdt_balance * fraction, 2)

def adjust_sl_tp(data, side):
    atr = np.std(data['close'].diff().dropna())  # basic volatility proxy
    last_price = data['close'].iloc[-1]

    sl = last_price - (1.5 * atr) if side == "LONG" else last_price + (1.5 * atr)
    tp = last_price + (2.5 * atr) if side == "LONG" else last_price - (2.5 * atr)

    return round(sl, 4), round(tp, 4)

def execute_trade(symbol, side, quantity):
    try:
        if side == "LONG":
            order = client.order_market_buy(symbol=symbol, quoteOrderQty=quantity)
        else:
            order = client.order_market_sell(symbol=symbol, quoteOrderQty=quantity)
        print(f"✅ Executed {side} order on {symbol}: {quantity} USDT")
    except Exception as e:
        print(f"[Trade Error] {symbol}: {e}")

def send_telegram_message(msg):
    try:
        with open("REAL.txt") as f:
            keys = json.load(f)
        token = keys["TELEGRAM_TOKEN"]
        chat_id = keys["TELEGRAM_CHAT_ID"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": msg}
        requests.post(url, data=payload)
    except Exception as e:
        print(f"[Telegram Error] {e}")
