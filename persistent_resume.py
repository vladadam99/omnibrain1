# -*- coding: utf-8 -*-
# ✅ persistent_resume.py
# This module handles saving, loading, and resuming open trades across bot shutdowns.

import json
import os
from datetime import datetime
from binance.enums import *

POSITIONS_FILE = "open_positions.json"

# Load existing positions

def load_open_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []

# Save all positions

def save_open_positions(positions):
    with open(POSITIONS_FILE, 'w') as f:
        json.dump(positions, f, indent=2)

# Append a new position safely

def add_open_position(symbol, side, entry_price, qty, sl, tp):
    positions = load_open_positions()
    new_pos = {
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "qty": qty,
        "sl": sl,
        "tp": tp,
        "opened": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }
    positions.append(new_pos)
    save_open_positions(positions)

# Remove closed position

def remove_position(symbol):
    positions = load_open_positions()
    updated = [p for p in positions if p['symbol'] != symbol]
    save_open_positions(updated)

# Check if a position exists for symbol

def is_symbol_open(symbol):
    positions = load_open_positions()
    for p in positions:
        if p['symbol'] == symbol:
            return True
    return False

# Called from auto_trade to resume open trades

def check_open_positions(client, send_telegram):
    positions = load_open_positions()
    for pos in positions:
        symbol = pos['symbol']
        side = pos['side']
        qty = float(pos['qty'])
        entry = float(pos['entry_price'])
        sl = float(pos['sl'])
        tp = float(pos['tp'])

        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            current = float(ticker['price'])

            # Determine if exit condition met
            if side == "BUY":
                if current >= tp or current <= sl or current >= entry * 1.03:
                    order = client.order_market_sell(symbol=symbol, quantity=qty)
                    remove_position(symbol)
                    send_telegram(f"✅ Closed BUY {symbol} at {current} | TP/SL/Surge hit.")
            elif side == "SELL":
                if current <= tp or current >= sl or current <= entry * 0.97:
                    order = client.order_market_buy(symbol=symbol, quantity=qty)
                    remove_position(symbol)
                    send_telegram(f"✅ Closed SELL {symbol} at {current} | TP/SL/Surge hit.")

        except Exception as e:
            print(f"[Resume Check Error] {symbol}: {e}")
