# -*- coding: utf-8 -*-
import os
import json
import time
import schedule
import multiprocessing
import pandas as pd
import numpy as np
from datetime import datetime
from binance.client import Client
import requests

from agents import macd_agent, rsi_agent, vwap_agent, supertrend_agent, breakout_agent, cosmic_agent

# === CONFIG ===
API_KEY = ""  # Only needed for private endpoints
API_SECRET = ""
INTERVAL = "1h"
LIMIT = 500
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT", "RNDRUSDT"]

# === AGENTS ===
AGENTS = {
    "MACD": macd_agent,
    "RSI": rsi_agent,
    "VWAP": vwap_agent,
    "SUPERTREND": supertrend_agent,
    "BREAKOUT": breakout_agent,
    "COSMIC": cosmic_agent,
}

DATA_FOLDER = "data"
MEMORY_FILE = "optimizer_memory.json"
EXPORT_CSV = "optimizer_results.csv"
client = Client(API_KEY, API_SECRET)


# === Telegram Integration ===
def send_telegram_message(message):
    try:
        with open("REAL.json") as f:
            creds = json.load(f)
        token = creds["TELEGRAM_TOKEN"]
        chat_id = creds["TELEGRAM_CHAT_ID"]
    except Exception as e:
        print(f"⚠️ Could not load Telegram credentials: {e}")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": message}
    try:
        requests.post(url, data=data)
        print("📤 Telegram alert sent.")
    except Exception as e:
        print(f"❌ Failed to send Telegram alert: {e}")


# === OMNIBRAIN Integration ===
def send_omnibrain_best_agents(memory):
    try:
        payload = {"agents": memory}
        url = "http://localhost:8000/api/optimizer/update"  # Update this URL if needed
        r = requests.post(url, json=payload)
        if r.status_code == 200:
            print("🛰️ OMNIBRAIN updated with best agents.")
        else:
            print(f"⚠️ OMNIBRAIN response: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"❌ Failed to send update to OMNIBRAIN: {e}")


# === Data Functions ===
def fetch_and_save_ohlcv(symbol, interval="1h", limit=500):
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'num_trades',
            'taker_buy_base_vol', 'taker_buy_quote_vol', 'ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].astype(float)
        os.makedirs(DATA_FOLDER, exist_ok=True)
        df.to_csv(os.path.join(DATA_FOLDER, f"{symbol}.csv"), index=False)
        print(f"📥 Updated {symbol} data")
    except Exception as e:
        print(f"❌ Failed to fetch {symbol}: {e}")


def load_price_data(symbol):
    path = os.path.join(DATA_FOLDER, f"{symbol}.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    return df


def simulate_trade(entry_price, exit_price, side, sl, tp):
    if side == "buy":
        if sl and exit_price < sl:
            return (sl - entry_price) / entry_price
        if tp and exit_price > tp:
            return (tp - entry_price) / entry_price
        return (exit_price - entry_price) / entry_price
    elif side == "sell":
        if sl and exit_price > sl:
            return (entry_price - sl) / entry_price
        if tp and exit_price < tp:
            return (entry_price - tp) / entry_price
        return (entry_price - exit_price) / entry_price
    return 0


def backtest_agent(agent_name, agent_module, symbol):
    df = load_price_data(symbol)
    if df is None or len(df) < 100:
        return None

    trades = []
    for i in range(50, len(df) - 1):
        window = df.iloc[:i]
        signal = agent_module.generate_signal(window.copy(), symbol)
        if not signal or signal.get("confidence", 0) < 0.8:
            continue

        entry_price = df.iloc[i]['close']
        next_price = df.iloc[i + 1]['close']
        atr = window['high'].rolling(14).max().iloc[-1] - window['low'].rolling(14).min().iloc[-1]
        tp = entry_price + 2.5 * atr if signal['side'] == 'buy' else entry_price - 2.5 * atr
        sl = entry_price - 1.2 * atr if signal['side'] == 'buy' else entry_price + 1.2 * atr

        pnl = simulate_trade(entry_price, next_price, signal['side'], sl, tp)
        trades.append({
            "symbol": symbol,
            "agent": agent_name,
            "entry_price": entry_price,
            "exit_price": next_price,
            "side": signal['side'],
            "confidence": signal['confidence'],
            "pnl": pnl,
            "timestamp": df.index[i + 1].isoformat()
        })

    return trades


def optimize_symbol(symbol):
    results = []
    for agent_name, agent_module in AGENTS.items():
        trades = backtest_agent(agent_name, agent_module, symbol)
        if not trades:
            continue
        df = pd.DataFrame(trades)
        avg_pnl = df['pnl'].mean()
        winrate = (df['pnl'] > 0).mean()
        confidence = df['confidence'].mean()
        results.append({
            "symbol": symbol,
            "agent": agent_name,
            "trades": len(df),
            "winrate": round(winrate, 3),
            "avg_pnl": round(avg_pnl, 5),
            "confidence": round(confidence, 3)
        })
    return results


def save_memory(memory):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)


# === Full Optimizer Pipeline ===
def run_optimizer():
    print(f"\n🔄 Fetching live data at {datetime.now().isoformat()}")
    for sym in SYMBOLS:
        fetch_and_save_ohlcv(sym, interval=INTERVAL, limit=LIMIT)

    print("🧠 Running backtests and optimization...")
    memory = {}

    with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as pool:
        results = pool.map(optimize_symbol, SYMBOLS)

    flat_results = [item for sublist in results if sublist for item in sublist]
    df = pd.DataFrame(flat_results)

    if not df.empty:
        df.to_csv(EXPORT_CSV, index=False)
        for _, row in df.iterrows():
            key = f"{row['symbol']}::{row['agent']}"
            memory[key] = {
                "winrate": row['winrate'],
                "avg_pnl": row['avg_pnl'],
                "confidence": row['confidence'],
                "trades": int(row['trades'])
            }
        save_memory(memory)
        print(f"✅ Saved {len(memory)} optimized results to {MEMORY_FILE} and CSV.")

        # Send alerts
        top = sorted(memory.items(), key=lambda x: x[1]['winrate'], reverse=True)[:5]
        summary = "📊 Optimizer Top Agents:\n"
        for key, val in top:
            summary += f"{key}: {val['winrate']*100:.1f}% win, {val['avg_pnl']*100:.2f}% PnL\n"

        send_telegram_message(summary)
        send_omnibrain_best_agents(memory)


# === Scheduler Loop ===
def main_loop():
    print(f"\n⏰ Running OptimizerAI cycle at {datetime.now().isoformat()}")
    run_optimizer()


if __name__ == "__main__":
    print("🚀 OptimizerAI v3 - LIVE + SCHEDULED + TELEGRAM + OMNIBRAIN")
    schedule.every(1).hours.do(main_loop)
    main_loop()  # Run once immediately

    while True:
        schedule.run_pending()
        time.sleep(30)
