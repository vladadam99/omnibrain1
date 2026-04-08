# -*- coding: utf-8 -*-
# utils/binance_utils.py
from binance.client import Client
from binance.enums import *
import math

# You should have loaded the Binance client elsewhere and passed it in here

def get_balance(client, asset="USDT"):
    try:
        balance = client.get_asset_balance(asset=asset)
        return float(balance['free'])
    except Exception as e:
        print("[Balance Error]", e)
        return 0

def get_position_size(balance, price, risk_percent=1):
    risk_amount = balance * (risk_percent / 100)
    qty = risk_amount / price
    return round(qty, 5)

def adjust_sl_tp(entry_price, side, atr):
    sl = entry_price - (1.2 * atr) if side == "LONG" else entry_price + (1.2 * atr)
    tp = entry_price + (2.5 * atr) if side == "LONG" else entry_price - (2.5 * atr)
    return round(sl, 6), round(tp, 6)

def execute_trade(client, symbol, side, qty):
    try:
        order = client.order_market(
            symbol=symbol,
            side=SIDE_BUY if side == "LONG" else SIDE_SELL,
            quantity=qty
        )
        print(f"✅ Executed {side} {symbol} x {qty}")
        return order
    except Exception as e:
        print(f"[Order Error] {symbol}", e)
        return None
