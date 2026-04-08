# -*- coding: utf-8 -*-
# oco_guardian_ai.py — OMNIBRAIN Trade Guardian AI (TP/SL Manager)

from binance_trade import place_order

class OCOGuardianAI:
    def __init__(self):
        pass

    def place_oco_trade(self, symbol, side, qty, tp_price, sl_price):
        try:
            print(f"🛡️ Placing OCO order: {side.upper()} {qty} {symbol} | TP: {tp_price}, SL: {sl_price}")
            response = place_order(
                symbol=symbol,
                side=side,
                order_type="OCO",
                quantity=qty,
                price=tp_price,
                stop_price=sl_price
            )
            print("✅ OCO order placed:", response)
            return {"status": "ok", "order": response}
        except Exception as e:
            print("❌ OCO placement failed:", str(e))
            return {"status": "error", "message": str(e)}

# === Example ===
if __name__ == "__main__":
    guardian = OCOGuardianAI()
    guardian.place_oco_trade(symbol="BTCUSDT", side="sell", qty=0.01, tp_price=2675, sl_price=2620)
