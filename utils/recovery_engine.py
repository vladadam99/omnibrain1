# -*- coding: utf-8 -*-
# recovery_engine.py

import json
import os

POSITION_FILE = "open_positions.json"

def resume_open_positions(client):
    if not os.path.exists(POSITION_FILE):
        return {}

    try:
        with open(POSITION_FILE, "r") as f:
            positions = json.load(f)
        return positions
    except Exception as e:
        print(f"⚠️ Failed to load open positions: {e}")
        return {}

def save_open_position(symbol, qty, price):
    positions = {}
    if os.path.exists(POSITION_FILE):
        with open(POSITION_FILE, "r") as f:
            positions = json.load(f)
    positions[symbol] = {"qty": qty, "price": price}
    with open(POSITION_FILE, "w") as f:
        json.dump(positions, f, indent=2)

def remove_open_position(symbol):
    if not os.path.exists(POSITION_FILE):
        return
    with open(POSITION_FILE, "r") as f:
        positions = json.load(f)
    if symbol in positions:
        del positions[symbol]
        with open(POSITION_FILE, "w") as f:
            json.dump(positions, f, indent=2)
