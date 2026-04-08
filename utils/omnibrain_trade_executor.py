# -*- coding: utf-8 -*-
import os, time, hmac, hashlib, requests
from dotenv import load_dotenv
from datetime import datetime
import csv
import math

load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
MODE = os.getenv("MODE", "TEST").upper()
BASE_URL = "https://testnet.binance.vision" if MODE == "TEST" else "https://api.binance.com"

LOG_FILE = "omnibrain_logbook.csv"

def sign_request(params):
    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    signature = hmac.new(API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return signature

def get_price(symbol):
    try:
        res = requests.get(f"{BASE_URL}/api/v3/ticker/price", params={"symbol": symbol})
        return float(res.json()["price"])
    except:
        print("❌ Could not fetch price. Symbol might be wrong or API rejected it.")
        return None

def get_balance(asset="USDT"):
    try:
        timestamp = int(time.time() * 1000)
        params = {"timestamp": timestamp}
        params["signature"] = sign_request(params)
        headers = {"X-MBX-APIKEY": API_KEY}
        res = requests.get(f"{BASE_URL}/api/v3/account", params=params, headers=headers)
        data = res.json()
        for b in data["balances"]:
            if b["asset"] == asset:
                return float(b["free"])
    except:
        print("❌ Failed to fetch balance.")
    return 0.0

def get_lot_size_info(symbol):
    res = requests.get(f"{BASE_URL}/api/v3/exchangeInfo")
    data = res.json()
    for s in data['symbols']:
        if s['symbol'] == symbol.upper():
            for f in s['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    step = float(f['stepSize'])
                    min_qty = float(f['minQty'])
                    return step, min_qty
    return 0.000001, 0.000001

def round_step_size(qty, step):
    precision = int(round(-math.log10(step)))
    return round(qty, precision)

def place_order(symbol, side, qty):
    timestamp = int(time.time() * 1000)
    params = {
        "symbol": symbol.upper(),
        "side": side.upper(),
        "type": "MARKET",
        "quantity": qty,
        "timestamp": timestamp
    }
    params["signature"] = sign_request(params)
    headers = {"X-MBX-APIKEY": API_KEY}
    res = requests.post(f"{BASE_URL}/api/v3/order", params=params, headers=headers)
    return res

def log_trade(symbol, side, qty, price, score=0.0, signal="manual"):
    value = round(qty * price, 2)
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        if not file_exists:
            writer.writerow(['timestamp', 'symbol', 'side', 'qty', 'price', 'value_usdt', 'score', 'signal'])
        writer.writerow([datetime.now(), symbol.upper(), side.upper(), qty, price, value, score, signal])

def run():
    print("\n\U0001f9e0 Welcome to OMNIBRAIN v3 — Bulletproof Auto-Trader")
    print("-----------------------------------------------------")
    symbol = input("Enter symbol (e.g., BTCUSDT): ").upper()
    side = input("Enter side (BUY/SELL): ").upper()
    percent = float(input("Enter % of balance to use (e.g. 2 for 2%): "))

    asset = "USDT" if side == "BUY" else symbol.replace("USDT", "")
    balance = get_balance(asset)
    if balance <= 0:
        print(f"❌ Not enough {asset} balance. You currently hold {balance:.4f} {asset}.")
        return

    price = get_price(symbol)
    if not price:
        return

    amount_usdt = balance * (percent / 100)
    qty = amount_usdt / price if side == "BUY" else amount_usdt
    step, min_qty = get_lot_size_info(symbol)
    qty = round_step_size(qty, step)

    if qty < min_qty:
        print(f"❌ Quantity too small. Must be ≥ {min_qty}")
        return

    print(f"📊 Auto-sizing: {percent}% of {balance:.4f} {asset} = {amount_usdt:.2f} → Qty: {qty}")
    res = place_order(symbol, side, qty)
    if res.status_code == 200:
        print(f"✅ {side} {qty} {symbol} at {price:.2f} [Mode: {MODE}]")
        log_trade(symbol, side, qty, price)
    else:
        print(f"❌ Trade Failed [{res.status_code}]:", res.json())

if __name__ == '__main__':
    run()
