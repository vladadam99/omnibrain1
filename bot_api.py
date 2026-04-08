# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify, abort
from functools import wraps
import os
import pandas as pd

# --- Import your bot's functions & state loaders here ---
from omnibrain_utils import (
    load_open_positions, 
    get_futures_balance, 
    get_top_futures_gainers, 
    get_unrealized_pnl, 
    save_open_positions, 
    log_trade_to_csv,
    calculate_atr
)

# Import agent stats and other globals from your bot:
try:
    from agent_globals import agent_stats, daily_realized_pnl, daily_trade_count, config_globals
except ImportError:
    # Fallback if not modularized, use dummy globals or read from disk
    import pickle
    import datetime
    import json

    def load_agent_stats():
        if os.path.exists('agent_stats.pkl'):
            with open('agent_stats.pkl', 'rb') as f:
                return pickle.load(f)
        return {}

    agent_stats = load_agent_stats()
    daily_realized_pnl = 0
    daily_trade_count = 0
    # Example config, replace with your actual config loader
    config_globals = {
        "LEVERAGE": 20,
        "MIN_TRADE_USDT": 5,
        "MAX_PORTFOLIO_SIZE": 3,
        "TP_QUICK_PROFIT": 0.99,
        "CONFIDENCE_THRESHOLD": 0.7,
        # Add more as needed...
    }

# Helper to load trade history
def load_trade_history():
    fname = 'trades.csv'
    if os.path.exists(fname):
        df = pd.read_csv(fname)
        return df.to_dict(orient="records")
    return []

# Helper to fetch OHLCV (dummy version)
def fetch_ohlcv(symbol, interval="1m", limit=60):
    # Replace with your real fetch_ohlcv
    try:
        from main_bot_file import fetch_ohlcv as real_fetch_ohlcv
        return real_fetch_ohlcv(symbol, interval, limit).to_dict(orient="records")
    except Exception:
        # Return dummy data
        return [{"timestamp": "2025-08-07T20:22:33Z", "open": 1, "high": 2, "low": 1, "close": 1.5, "volume": 1000}]
    
# Helper to get current price (dummy version)
def get_current_price(symbol):
    try:
        from main_bot_file import client
        return float(client.mark_price(symbol=symbol)["markPrice"])
    except Exception:
        return 0.0

API_KEY = os.environ.get("BOT_API_KEY", "demo-key")  # Change for production!

app = Flask(__name__)

def require_api_key(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        key = request.headers.get("Authorization", "").replace("Bearer ", "")
        if key != API_KEY:
            abort(401)
        return func(*args, **kwargs)
    return wrapper

@app.route("/status")
@require_api_key
def status():
    # Expanded status with stats, config, etc.
    return jsonify({
        "balance": get_futures_balance(),
        "open_positions": load_open_positions(),
        "daily_pnl": daily_realized_pnl,
        "trade_count": daily_trade_count,
        "agent_stats": agent_stats,
        "config": config_globals,
    })

@app.route("/positions")
@require_api_key
def positions():
    return jsonify(load_open_positions())

@app.route("/agents")
@require_api_key
def agents():
    return jsonify(agent_stats)

@app.route("/performance")
@require_api_key
def performance():
    # Compute win/loss, winrate, and daily pnl
    stats = agent_stats
    total_wins = sum(stats[a].get('wins', 0) for a in stats)
    total_losses = sum(stats[a].get('losses', 0) for a in stats)
    winrate = total_wins / max(1, total_wins + total_losses)
    return jsonify({
        "daily_pnl": daily_realized_pnl,
        "trade_count": daily_trade_count,
        "total_wins": total_wins,
        "total_losses": total_losses,
        "winrate": winrate,
        "agent_stats": stats,
    })

@app.route("/trade_history")
@require_api_key
def trade_history():
    return jsonify(load_trade_history())

@app.route("/chart_data")
@require_api_key
def chart_data():
    symbol = request.args.get("symbol")
    interval = request.args.get("interval", "1m")
    data = fetch_ohlcv(symbol, interval)
    return jsonify(data)

@app.route("/market_data")
@require_api_key
def market_data():
    symbol = request.args.get("symbol")
    price = get_current_price(symbol)
    return jsonify({"symbol": symbol, "price": price})

@app.route("/config", methods=["GET", "POST"])
@require_api_key
def config():
    if request.method == "GET":
        return jsonify(config_globals)
    else:
        data = request.json
        param = data.get("param")
        value = data.get("value")
        config_globals[param] = value
        return jsonify({"status": "ok", "param": param, "value": value})

@app.route("/command", methods=["POST"])
@require_api_key
def command():
    data = request.json
    action = data.get("action")
    result = {"status": "unknown"}
    try:
        if action == "pause":
            # Implement your pause logic, e.g. set a global flag or call a function
            result = {"status": "paused"}
        elif action == "resume":
            # Implement your resume logic
            result = {"status": "resumed"}
        elif action == "force_close":
            symbol = data.get("symbol")
            open_pos = load_open_positions()
            if symbol in open_pos:
                # Implement your close_position logic here
                del open_pos[symbol]
                save_open_positions(open_pos)
                result = {"status": f"closed {symbol}"}
            else:
                result = {"error": f"{symbol} not found"}
        elif action == "set_threshold":
            agent = data.get("agent")
            value = data.get("value")
            if agent in agent_stats:
                agent_stats[agent]["threshold"] = value
                # Optionally save agent_stats to disk
                with open('agent_stats.pkl', 'wb') as f:
                    pickle.dump(agent_stats, f)
                result = {"status": f"threshold set for {agent}", "value": value}
            else:
                result = {"error": f"Unknown agent {agent}"}
        elif action == "set_config":
            param = data.get("param")
            value = data.get("value")
            config_globals[param] = value
            result = {"status": f"config {param} set", "value": value}
        else:
            result = {"error": "unknown command"}
    except Exception as e:
        result = {"error": str(e)}
    return jsonify(result)

# (Optional) Add WebSocket for real-time data -- use Flask-SocketIO if needed.

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)