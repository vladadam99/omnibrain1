# -*- coding: utf-8 -*-
import time
import pandas as pd
from datetime import datetime
from config_loader import load_config
from meta_governor import MetaGovernor
from modules.sensory_matrix import SensoryMatrix
from binance_connector import BinanceTrader

def run_live():
    cfg = load_config()
    symbol = cfg["symbol"]
    interval = cfg["interval"]
    agents_enabled = [k for k, v in cfg["agents"].items() if v]
    trader = BinanceTrader(symbol=symbol)

    agent_configs = [{"name": name, "params": {}} for name in agents_enabled]
    governor = MetaGovernor(agent_configs)
    open_trades = {a["name"]: None for a in governor.agents}
    trade_log = []

    print(f"[LIVE MODE] Monitoring {symbol} ({interval}) | Agents: {agents_enabled}")

    while True:
        try:
            sm = SensoryMatrix(symbol=symbol, interval=interval, lookback="100 bars")
            df = sm.get_data()

            if df is None or len(df) < 50:
                print("Waiting for enough data...")
                time.sleep(60)
                continue

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            latest_price = df["close"].iloc[-1]
            signals = governor.evaluate_all(df)

            print(f"\n[{now}] Price: {latest_price:.2f} | Signals: {signals}")

            for sig in signals:
                agent = sig["agent"]
                signal = sig["signal"]
                reason = sig.get("reason", "")

                # ENTRY
                if signal == "buy" and open_trades[agent] is None:
                    trader.execute_market_order("BUY")
                    open_trades[agent] = {"side": "buy", "entry": latest_price, "time": now}
                    print(f">>> [{agent}] BUY @ {latest_price:.2f} | Reason: {reason}")

                elif signal == "sell" and open_trades[agent] is None:
                    trader.execute_market_order("SELL")
                    open_trades[agent] = {"side": "sell", "entry": latest_price, "time": now}
                    print(f">>> [{agent}] SELL @ {latest_price:.2f} | Reason: {reason}")

                # EXIT + REVERSE
                elif signal == "buy" and open_trades[agent] and open_trades[agent]["side"] == "sell":
                    entry = open_trades[agent]["entry"]
                    pnl = entry - latest_price
                    trader.execute_market_order("BUY")
                    print(f"<<< [{agent}] EXIT SELL @ {latest_price:.2f} | PnL: {pnl:.2f}")
                    trade_log.append({
                        "agent": agent, "side": "sell", "entry": entry, "exit": latest_price,
                        "pnl": round(pnl, 2), "open_time": open_trades[agent]["time"], "close_time": now
                    })
                    open_trades[agent] = {"side": "buy", "entry": latest_price, "time": now}

                elif signal == "sell" and open_trades[agent] and open_trades[agent]["side"] == "buy":
                    entry = open_trades[agent]["entry"]
                    pnl = latest_price - entry
                    trader.execute_market_order("SELL")
                    print(f"<<< [{agent}] EXIT BUY @ {latest_price:.2f} | PnL: {pnl:.2f}")
                    trade_log.append({
                        "agent": agent, "side": "buy", "entry": entry, "exit": latest_price,
                        "pnl": round(pnl, 2), "open_time": open_trades[agent]["time"], "close_time": now
                    })
                    open_trades[agent] = {"side": "sell", "entry": latest_price, "time": now}

        except KeyboardInterrupt:
            print("🛑 Stopping live trading...")
            break
        except Exception as e:
            print(f"[ERROR] {e}")

        time.sleep(60)

    pd.DataFrame(trade_log).to_csv("live_trades_log.csv", index=False)
    print("✅ Saved live trades to live_trades_log.csv")

if __name__ == "__main__":
    run_live()
