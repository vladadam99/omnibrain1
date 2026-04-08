# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime

EQUITY_FILE = "equity_history.json"

def update_equity(symbol, equity):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entry = {"time": now, "symbol": symbol, "equity": equity}

    # Load existing data
    if os.path.exists(EQUITY_FILE):
        with open(EQUITY_FILE, 'r') as f:
            data = json.load(f)
    else:
        data = []

    # Append new entry
    data.append(entry)

    # Save back
    with open(EQUITY_FILE, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"✅ Equity updated: {entry}")
