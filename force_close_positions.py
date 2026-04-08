# -*- coding: utf-8 -*-
import json
from omnibrain_utils import (
    get_api_client, load_open_positions,
    save_open_positions, send_telegram_message
)
from datetime import datetime

client = get_api_client()
positions = load_open_positions()

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
    """Round down to the nearest step size."""
    precision = abs(str(step_size)[::-1].find('.'))
    return round(qty - (qty % step_size), precision)

if not positions:
    print("✅ No open positions to close.")
else:
    print(f"🧹 Force closing {len(positions)} open positions...")

    for symbol, pos in positions.items():
        try:
            raw_qty = float(pos['qty'])
            step = get_lot_size(symbol)
            qty = round_qty(raw_qty, step)

            print(f"🔻 Selling {symbol} | Qty: {qty} (step size: {step})")
            order = client.order_market_sell(symbol=symbol, quantity=qty)

            msg = f"🧹 FORCE SELL: {symbol} | Qty: {qty} | Time: {datetime.utcnow().isoformat()}"
            print(msg)
            try:
                send_telegram_message(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, msg)
            except:
                print("⚠️ Could not send Telegram message.")

        except Exception as e:
            print(f"❌ Error selling {symbol}: {e}")

    # Clear all positions after forced exit
    save_open_positions({})
    print("✅ All positions force closed and cleared.")
