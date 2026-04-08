# -*- coding: utf-8 -*-
from datetime import datetime
from omnibrain_utils import (
    get_api_client, send_telegram_message
)

client = get_api_client()

TELEGRAM_TOKEN = "7730563721:AAFYOzMvG_lNRxZRkelyRXxatiePGTN0_5w"
TELEGRAM_CHAT_ID = "1666571558"

def get_lot_size(symbol):
    """Fetch the minimum step size (LOT_SIZE) for a given symbol."""
    info = client.get_symbol_info(symbol)
    for f in info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            return float(f['stepSize'])
    return 0.01  # fallback

def round_qty(qty, step_size):
    """Round down to nearest valid step size."""
    precision = abs(str(step_size)[::-1].find('.'))
    return round(qty - (qty % step_size), precision)

def get_spot_balances():
    balances = client.get_account()['balances']
    return {b['asset']: float(b['free']) for b in balances if float(b['free']) > 0}

spot_balances = get_spot_balances()

print(f"🔍 Found {len(spot_balances)} coins in wallet...")

for asset, qty in spot_balances.items():
    if asset == "USDT":
        continue

    symbol = asset + "USDT"
    try:
        info = client.get_symbol_info(symbol)
        if not info or not info['status'] == "TRADING":
            continue

        step = get_lot_size(symbol)
        qty_rounded = round_qty(qty, step)

        if qty_rounded <= 0:
            continue

        print(f"🧹 Selling {symbol} | Qty: {qty_rounded} (step: {step})")
        order = client.order_market_sell(symbol=symbol, quantity=qty_rounded)

        msg = f"🧹 SOLD {symbol} | Qty: {qty_rounded} | Time: {datetime.utcnow().isoformat()}"
        print(msg)
        try:
            send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, msg)
        except:
            print("⚠️ Telegram failed.")

    except Exception as e:
        print(f"❌ Failed to sell {symbol}: {e}")

print("✅ Force sell by balance complete.")
