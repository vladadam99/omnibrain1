# -*- coding: utf-8 -*-
# trade_executor_ai.py — OMNIBRAIN Live Trade Execution AI

from binance_trade import place_order
from memory_ai import MemoryAI
from datetime import datetime
import csv

class TradeExecutorAI:
    def __init__(self):
        self.memory = MemoryAI()

    def execute(self, agent, signal, symbol, price=None, qty=1.0, order_type="MARKET", stop_price=None):
        confidence = self.memory.get_confidence(agent)
        scaled_qty = round(qty * confidence, 5)

        print(f"🚀 Executing trade | Agent: {agent} | Signal: {signal} | Qty: {scaled_qty} | Confidence: {confidence}")

        try:
            response = place_order(
                symbol=symbol,
                side=signal,
                order_type=order_type,
                quantity=scaled_qty,
                price=price,
                stop_price=stop_price
            )
            print("✅ Order placed:", response)
            self.log_trade(agent, signal, symbol, price, scaled_qty, 0.0)
            return {"status": "success", "order": response}
        except Exception as e:
            print("❌ Order failed:", str(e))
            return {"status": "error", "message": str(e)}

    def log_trade(self, agent, signal, symbol, price, qty, pnl):
        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": agent,
            "signal": signal,
            "price": price or 0,
            "qty": qty,
            "pnl": pnl
        }
        file = "trade_log.csv"
        is_new = not os.path.exists(file)
        with open(file, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if is_new:
                writer.writeheader()
            writer.writerow(row)
        print(f"📝 Trade logged for {agent}")

# === Example ===
if __name__ == "__main__":
    executor = TradeExecutorAI()
    executor.execute(agent="RSI_2", signal="buy", symbol="BTCUSDT", qty=0.01)
