# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime

EQUITY_FILE = "equity_history.json"

def update_equity(equity_info):
    """
    Save updated equity with timestamp to file.
    Expects a dict: {"symbol": "USDT", "equity": 123.45}
    """
    if not isinstance(equity_info, dict):
        print("[Equity Tracker Error] equity_info must be a dict")
        return

    record = {
        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": equity_info.get("symbol", "USDT"),
        "equity": equity_info.get("equity", 0)
    }

    if os.path.exists(EQUITY_FILE):
        with open(EQUITY_FILE, "r") as f:
            history = json.load(f)
    else:
        history = []

    history.append(record)

    with open(EQUITY_FILE, "w") as f:
        json.dump(history, f, indent=2)

    print("✅ Equity updated:", record)
