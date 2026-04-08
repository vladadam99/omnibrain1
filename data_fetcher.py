import os
import time
import requests
import pandas as pd
from datetime import datetime

DATA_FOLDER = "data"
if not os.path.exists(DATA_FOLDER):
    os.makedirs(DATA_FOLDER)

BASE_URL = "https://api.binance.com/api/v3/klines"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT", "RNDRUSDT"]  # Add more
LIMIT = 1000  # max per request
INTERVAL = "1h"

def fetch_ohlcv(symbol, interval="1h", limit=1000):
    url = f"{BASE_URL}?symbol={symbol}&interval={interval}&limit={limit}"
    response = requests.get(url)
    if response.status_code != 200:
        print(f"❌ Failed to fetch {symbol}: {response.text}")
        return None

    data = response.json()
    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "num_trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df

def save_csv(symbol):
    df = fetch_ohlcv(symbol, INTERVAL, LIMIT)
    if df is not None:
        path = os.path.join(DATA_FOLDER, f"{symbol}.csv")
        df.to_csv(path, index=False)
        print(f"✅ Saved {symbol} to {path}")
    time.sleep(1)  # avoid rate limit

if __name__ == "__main__":
    for sym in SYMBOLS:
        save_csv(sym)
