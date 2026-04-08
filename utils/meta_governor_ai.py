# -*- coding: utf-8 -*-
# meta_governor_ai.py - OMNIBRAIN MetaGovernor AI Core

import json
from datetime import datetime
from backtest_engine import strategy_map, fetch_ohlc
from optimizer_ai import OptimizerAI
from memory_ai import MemoryAI
from trade_executor_ai import TradeExecutorAI
from market_scanner_ai import MarketScannerAI
from sentiment_ai import SentimentAI
from oco_guardian_ai import OCOGuardianAI

# === Agent Performance Store ===
agent_stats = {}

# === Agent Manager ===
class MetaGovernorAI:
    def __init__(self):
        self.active_agents = list(strategy_map.keys())
        self.performance_log = {}
        self.risk_pause_list = set()
        self.daily_limit = 3
        self.drawdown_threshold = -50
        self.optimizer = OptimizerAI()
        self.memory = MemoryAI()
        self.executor = TradeExecutorAI()
        self.market_scanner = MarketScannerAI()
        self.sentiment = SentimentAI()
        self.guardian = OCOGuardianAI()

    def evaluate_agent(self, name, result):
        pnl = result.get("total_pnl", 0)
        win_rate = result.get("win_rate", 0)
        self.performance_log[name] = {
            "pnl": pnl,
            "win_rate": win_rate,
            "timestamp": datetime.utcnow().isoformat()
        }

        if pnl < self.drawdown_threshold:
            print(f"🔒 Agent {name} paused due to drawdown")
            self.risk_pause_list.add(name)
            self.memory.update_memory(name, False)
        else:
            if name in self.risk_pause_list:
                print(f"✅ Agent {name} reactivated")
                self.risk_pause_list.remove(name)
            self.memory.update_memory(name, True)

    def get_active_agents(self):
        return [a for a in self.active_agents if a not in self.risk_pause_list]

    def run_daily_backtests(self, symbol="BTCUSDT", interval="1h", lookback="30 day ago UTC"):
        report = {}
        df = fetch_ohlc(symbol, interval, lookback)

        # Optimization first (e.g. RSI)
        best_rsi = self.optimizer.optimize_rsi_strategy(symbol, interval, lookback)
        print("🔧 Optimizer best RSI config:", best_rsi)

        sentiment_report = self.sentiment.fetch_sentiment()
        mood = "neutral"
        if sentiment_report:
            positives = sum(1 for n in sentiment_report if n["sentiment"] == "positive")
            negatives = sum(1 for n in sentiment_report if n["sentiment"] == "negative")
            if positives > negatives:
                mood = "positive"
            elif negatives > positives:
                mood = "negative"
        print(f"🧠 Market sentiment: {mood}")

        if mood == "negative":
            print("❌ Market sentiment too negative, skipping trades.")
            return report

        for agent in self.get_active_agents():
            try:
                strategy = strategy_map[agent]
                result = strategy(df.copy())
                self.evaluate_agent(agent, result)
                report[agent] = result

                if result["win_rate"] > 0.6 and result["total_pnl"] > 0:
                    print(f"⚡ Auto-trading signal: {agent}")
                    response = self.executor.execute(agent=agent, signal="buy", symbol=symbol, qty=0.01)
                    if response.get("status") == "success":
                        # Apply OCO risk protection
                        price = float(df["close"].iloc[-1])
                        self.guardian.place_oco_trade(
                            symbol=symbol,
                            side="sell",
                            qty=0.01,
                            tp_price=round(price * 1.01, 2),
                            sl_price=round(price * 0.99, 2)
                        )
            except Exception as e:
                report[agent] = {"error": str(e)}

        return report

# === Singleton Init ===
meta_ai = MetaGovernorAI()

def daily_agent_update():
    print("🧠 Running daily agent update...")
    report = meta_ai.run_daily_backtests()
    with open("daily_agent_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("📈 Daily performance saved -> daily_agent_report.json")
