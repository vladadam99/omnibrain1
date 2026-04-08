# -*- coding: utf-8 -*-
from binance.client import Client
from datetime import datetime
import os

API_KEY = "JrmriJa8Ck2nxsexkoqNdK7rh101Jj0QyzgzgM42WEtmqSpiPShcSJ0vjx7Ke5fG"
API_SECRET = "FS0d68EUeXGVCN6AO38a1pBC9KHPUKXEZdNLN8JFEVBi81qQ8gAug9zuWuONUePL"

client = Client(API_KEY, API_SECRET)

print("🔍 Checking live Binance Spot account...\n")

# 🪙 USDT Balance
usdt = client.get_asset_balance(asset='USDT')
print(f"💰 USDT Balance: {usdt['free']} available")

# 🧾 Recent Spot Trades
symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT']
for symbol in symbols:
    trades = client.get_my_trades(symbol=symbol)
    if trades:
        print(f"\n📜 Trade History for {symbol}:")
        for t in trades[-5:]:  # show last 5
            time_str = datetime.fromtimestamp(t['time']/1000).strftime("%Y-%m-%d %H:%M:%S")
            print(f" - {time_str}: {'BUY' if t['isBuyer'] else 'SELL'} {t['qty']} @ {t['price']}")
    else:
        print(f"\n⚠️ No recent trades for {symbol}")
