# -*- coding: utf-8 -*-
import os
import csv
from datetime import datetime

PNL_LOG_FILE = "pnl_log.csv"

def log_trade_pnl(symbol, pnl):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.exists(PNL_LOG_FILE)

    with open(PNL_LOG_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(["timestamp", "symbol", "pnl"])
        writer.writerow([now, symbol, round(pnl, 2)])

def get_daily_pnl():
    if not os.path.exists(PNL_LOG_FILE):
        return 0.0

    today = datetime.now().strftime("%Y-%m-%d")
    total = 0.0

    with open(PNL_LOG_FILE, mode="r") as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row["timestamp"].startswith(today):
                try:
                    total += float(row["pnl"])
                except:
                    pass
    return round(total, 2)
