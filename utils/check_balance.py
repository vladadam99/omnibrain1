# -*- coding: utf-8 -*-
import os, time, hmac, hashlib, requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
BASE_URL = "https://testnet.binance.vision"

def sign_request(params):
    q = '&'.join([f"{k}={v}" for k, v in params.items()])
    sig = hmac.new(API_SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
    return sig

def get_balance(asset="USDT"):
    url = BASE_URL + "/api/v3/account"
    params = {"timestamp": int(time.time()*1000)}
    params["signature"] = sign_request(params)
    headers = {"X-MBX-APIKEY": API_KEY}
    r = requests.get(url, headers=headers, params=params)
    if r.status_code == 200:
        for b in r.json()["balances"]:
            if b["asset"] == asset:
                return float(b["free"])
        return 0.0
    else:
        print("❌ Error fetching balance:", r.json())
        return None

bal = get_balance("USDT")
print(f"💰 Your USDT balance: {bal}")
