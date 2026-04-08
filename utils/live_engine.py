# -*- coding: utf-8 -*-
import time
import pandas as pd
from meta_governor import MetaGovernor
from modules.sensory_matrix import SensoryMatrix
from trade_executor import TradeExecutor
from position_manager import PositionManager

# === CONFIG ===
PAIR = "BTCUSDT"
INTERVAL = "1m"
LOOKBACK = "200 minutes"  # fetch last 200 candles
LOOP_INTERVAL = 60  # seconds

# === AGENT CONFIGS ===
agent_configs = [
    {"name": "MACD_RSI",       "params": {"macd_fast": 8, "macd_slow": 30, "rsi_low": 60, "rsi_high": 20}},
    {"name": "Momentum",       "params": {"window": 10}},
    {"name": "Bollinger",      "params": {"window": 20, "num_std": 2}},
    {"name": "RSI",            "params": {"window": 14, "low": 30, "high": 70}},
    {"name": "MACDCross",      "params": {"fast": 12, "slow": 26}},
    {"name": "ADX",            "params": {"window": 14, "threshold": 25}},
    {"name": "VWAP",           "params": {"window": 20}},
]

# === INIT COMPONENTS ===
governor = MetaGovernor(agent_configs)
executor = TradeExecutor(paper_mode=True)  # Real mode later
positions = PositionManager()

print("[Live Engine] Starting live engine...")
last_timestamp = None

while True:
    try:
        sm = SensoryMatrix(PAIR, INTERVAL, LOOKBACK)
        df = sm.get_data()

        if df.empty:
            print("[Live Engine] No data returned.")
            time.sleep(LOOP_INTERVAL)
            continue

        latest_time = df.index[-1]
        if latest_time == last_timestamp:
            print(f"[Live Engine] No new candle yet @ {latest_time}.")
            time.sleep(LOOP_INTERVAL)
            continue

        last_timestamp = latest_time
        print(f"\n=== New Candle @ {latest_time} ===")

        signals = governor.evaluate_all(df)
        price = float(df.iloc[-1]["close"])

        for s in signals:
            agent = s["agent"]
            signal = s["signal"]
            reason = s.get("reason", "")
            print(f"[{agent}] Signal: {signal} | Reason: {reason}")

            # Check current position state
            current = positions.get(agent)

            # Entry logic
            if signal == "buy" and current is None:
                executor.buy(agent, PAIR, price)
                positions.open(agent, "buy", price)

            elif signal == "sell" and current is None:
                executor.sell(agent, PAIR, price)
                positions.open(agent, "sell", price)

            # Exit logic
            elif signal == "buy" and current and current["side"] == "sell":
                executor.close(agent, PAIR, price)
                pnl = current["entry"] - price
                positions.close(agent)
                print(f"[{agent}] EXIT SELL at {price} | PnL: {pnl:.2f}")

            elif signal == "sell" and current and current["side"] == "buy":
                executor.close(agent, PAIR, price)
                pnl = price - current["entry"]
                positions.close(agent)
                print(f"[{agent}] EXIT BUY at {price} | PnL: {pnl:.2f}")

    except Exception as e:
        print(f"[Live Engine] ERROR: {e}")

    time.sleep(LOOP_INTERVAL)
