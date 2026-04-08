# -*- coding: utf-8 -*-
# --- OMNIBRAIN SENTINEL MODULE (UPDATED with TELEGRAM COMMANDS) ---

import os
import json
import time
import pandas as pd
from datetime import datetime, timezone
import threading
import requests

SENTINEL_LOG_FILE = "sentinel_log.csv"
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""

def set_telegram_credentials(token, chat_id):
    global TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    TELEGRAM_TOKEN = token
    TELEGRAM_CHAT_ID = chat_id

def log_trade(trade):
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": trade.get("symbol", ""),
        "side": trade.get("side", ""),
        "entry_price": trade.get("entry_price", 0),
        "exit_price": trade.get("exit_price", 0),
        "pnl_pct": trade.get("pnl_pct", 0),
        "confidence": trade.get("confidence", 0),
        "agent": trade.get("agent", ""),
        "volume": trade.get("volume", 0),
        "volatility_24h": trade.get("volatility_24h", 0),
        "trend": trade.get("trend", ""),
        "market_condition": trade.get("market_condition", "")
    }
    file_exists = os.path.isfile(SENTINEL_LOG_FILE)
    df = pd.DataFrame([row])
    df.to_csv(SENTINEL_LOG_FILE, mode='a', header=not file_exists, index=False)

def send_telegram_message(msg):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
            requests.post(url, data=payload)
        except Exception as e:
            print(f"[SENTINEL TELEGRAM ERROR] {e}")

def get_today_trades():
    if not os.path.exists(SENTINEL_LOG_FILE):
        return pd.DataFrame()
    df = pd.read_csv(SENTINEL_LOG_FILE)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df_today = df[df['timestamp'].dt.date == datetime.now(timezone.utc).date()]
    return df_today

def generate_summary():
    df = get_today_trades()
    if df.empty:
        return "📭 No trades logged today."
    total = len(df)
    wins = len(df[df['pnl_pct'] > 0])
    losses = len(df[df['pnl_pct'] <= 0])
    win_rate = 100 * wins / total if total else 0
    avg_pnl = df['pnl_pct'].mean()
    profit_usd = ((df['exit_price'] - df['entry_price']) * df['volume']).sum()
    return (
        f"\U0001F4CA Sentinel Summary:\n"
        f"Trades: {total}\n"
        f"\u2705 Wins: {wins} | \u274C Losses: {losses}\n"
        f"\U0001F3C6 Winrate: {win_rate:.1f}%\n"
        f"\U0001F4B0 Avg PnL: {avg_pnl:.2f}%\n"
        f"\U0001F4C8 Profit: {profit_usd:.2f} USDT"
    )

def top_agents():
    df = get_today_trades()
    if df.empty:
        return "📭 No agent trades today."
    agents = df.groupby("agent")["pnl_pct"].mean().sort_values(ascending=False).head(5)
    return "\U0001F9E0 Top Agents:\n" + "\n".join([f"{a}: {p:.2f}%" for a, p in agents.items()])

def top_coins():
    df = get_today_trades()
    if df.empty:
        return "📭 No coin trades today."
    coins = df.groupby("symbol")["pnl_pct"].mean().sort_values(ascending=False).head(5)
    return "\U0001FA99 Top Coins:\n" + "\n".join([f"{s}: {p:.2f}%" for s, p in coins.items()])

def telegram_command_listener():
    last_update_id = None
    help_msg = (
        "\U0001F916 Sentinel Commands:\n"
        "/sent or /help - Show this list\n"
        "/sentinel - System status (PnL, wins, losses)\n"
        "/report - Daily trade summary\n"
        "/wins - Number of winning trades\n"
        "/losses - Number of losing trades\n"
        "/summary - Winrate, avg PnL, count\n"
        "/top_agents - Top performing agents\n"
        "/top_coins - Top coins today\n"
        "/pnl - Total PnL % and USDT"
    )

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            params = {"timeout": 10, "offset": last_update_id + 1 if last_update_id else None}
            resp = requests.get(url, params=params)
            data = resp.json()

            if "result" not in data:
                continue

            for update in data["result"]:
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id"))
                text = msg.get("text", "").strip()

                if chat_id != str(TELEGRAM_CHAT_ID):
                    continue

                if text in ["/sent", "/help"]:
                    send_telegram_message(help_msg)
                elif text == "/sentinel":
                    try:
                        df = get_today_trades()
                        wins = len(df[df["pnl_pct"] > 0])
                        losses = len(df[df["pnl_pct"] <= 0])
                        total = len(df)
                        pnl_usdt = ((df["exit_price"] - df["entry_price"]) * df["volume"]).sum() if total > 0 else 0

                        msg = f"""🛰️ *SENTINEL STATUS*

🔄 Trades today: {total}
📊 Daily PnL: {pnl_usdt:.2f} USDT
✅ Wins: {wins} | ❌ Losses: {losses}

Use /summary or /top_agents"""
                        send_telegram_message(msg)
                    except Exception as e:
                        send_telegram_message(f"⚠️ Error: /sentinel failed\n{str(e)}")

                elif text == "/report":
                    send_telegram_message(generate_summary())
                elif text == "/wins":
                    wins = len(get_today_trades().loc[lambda df: df["pnl_pct"] > 0])
                    send_telegram_message(f"✅ Wins today: {wins}")
                elif text == "/losses":
                    losses = len(get_today_trades().loc[lambda df: df["pnl_pct"] <= 0])
                    send_telegram_message(f"❌ Losses today: {losses}")
                elif text == "/summary":
                    send_telegram_message(generate_summary())
                elif text == "/top_agents":
                    send_telegram_message(top_agents())
                elif text == "/top_coins":
                    send_telegram_message(top_coins())
                elif text == "/pnl":
                    df = get_today_trades()
                    if df.empty:
                        send_telegram_message("📭 No trades today.")
                    else:
                        total = ((df["exit_price"] - df["entry_price"]) * df["volume"]).sum()
                        avg_pct = df["pnl_pct"].mean()
                        send_telegram_message(f"💰 Total PnL: {avg_pct:.2f}% | {total:.2f} USDT")

        except Exception as e:
            print(f"[SENTINEL COMMAND ERROR] {e}")
        time.sleep(3)


# To start listening from main

def start_telegram_listener():
    threading.Thread(target=telegram_command_listener, daemon=True).start()