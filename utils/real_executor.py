# -*- coding: utf-8 -*-
import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv
from binance.client import Client
from config_loader import load_config
from meta_governor import MetaGovernor
from modules.sensory_matrix import SensoryMatrix

load_dotenv()

TESTNET_API_KEY = os.getenv("BINANCE_API_KEY")
TESTNET_SECRET_KEY = os.getenv("BINANCE_API_SECRET")

client = Client(TESTNET_API_KEY, TESTNET_SECRET_KEY)
client.API_URL = 'https://testnet.binance.vision/api'

# New function to post updates to the backend
def post_update(price, signals, trades):
    try:
        requests.post("http://localhost:8000/update", json={
            "price": price,
            "signals": signals,
            "trades": trades
        })
    except Exception as e:
        print(f"[POST ERROR] Failed to update backend: {e}")

def run_real_trader():
    cfg = load_config()
    symbol = cfg["symbol"]
    interval = cfg["interval"]
    qty = float(cfg["binance"]["trade_qty"])

    agents_enabled = [k for k, v in cfg["agents"].items() if v]
    agent_configs = [{"name": name, "params": {}} for name in agents_enabled]
    governor = MetaGovernor(agent_configs)
    open_trades = {a["name"]: None for a in governor.agents}
    trade_log = []

    print(f"[REAL EXECUTION - TESTNET] {symbol} @ {interval} | Qty: {qty} | Agents: {agents_enabled}")

    while True:
        try:
            sm = SensoryMatrix(symbol=symbol, interval=interval, lookback="100 bars")
            df = sm.get_data()

            if df is None or len(df) < 50:
                print("Waiting for enough data...")
                time.sleep(60)
                continue

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            latest_price = float(df["close"].iloc[-1])
            signals = governor.evaluate_all(df)

            print(f"\n[{ts}] Price: {latest_price:.2f} | Signals: {signals}")

            for s in signals:
                agent = s["agent"]
                signal = s["signal"]
                reason = s.get("reason", "")

                if signal == "buy" and open_trades[agent] is None:
                    print(f">>> [{agent}] TESTNET BUY @ {latest_price:.2f} | Reason: {reason}")
                    client.order_market_buy(symbol=symbol, quantity=qty)
                    open_trades[agent] = {"side": "buy", "entry": latest_price, "time": ts}

                elif signal == "sell" and open_trades[agent] is None:
                    print(f">>> [{agent}] TESTNET SELL @ {latest_price:.2f} | Reason: {reason}")
                    client.order_market_sell(symbol=symbol, quantity=qty)
                    open_trades[agent] = {"side": "sell", "entry": latest_price, "time": ts}

                elif signal == "buy" and open_trades[agent] and open_trades[agent]["side"] == "sell":
                    pnl = open_trades[agent]["entry"] - latest_price
                    print(f"<<< [{agent}] EXIT SELL → BUY @ {latest_price:.2f} | PnL: {pnl:.2f}")
                    client.order_market_buy(symbol=symbol, quantity=qty)
                    trade_log.append({
                        "agent": agent,
                        "side": "sell",
                        "entry": open_trades[agent]["entry"],
                        "exit": latest_price,
                        "pnl": round(pnl, 2)
                    })
                    open_trades[agent] = {"side": "buy", "entry": latest_price, "time": ts}

                elif signal == "sell" and open_trades[agent] and open_trades[agent]["side"] == "buy":
                    pnl = latest_price - open_trades[agent]["entry"]
                    print(f"<<< [{agent}] EXIT BUY → SELL @ {latest_price:.2f} | PnL: {pnl:.2f}")
                    client.order_market_sell(symbol=symbol, quantity=qty)
                    trade_log.append({
                        "agent": agent,
                        "side": "buy",
                        "entry": open_trades[agent]["entry"],
                        "exit": latest_price,
                        "pnl": round(pnl, 2)
                    })
                    open_trades[agent] = {"side": "sell", "entry": latest_price, "time": ts}

            # Send updates to backend dashboard
            post_update(latest_price, signals, trade_log)

        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(60)

        time.sleep(60)

if __name__ == "__main__":
    run_real_trader()
