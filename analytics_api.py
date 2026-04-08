# -*- coding: utf-8 -*-
# --- analytics_api.py ---
import json
import os
from fastapi import APIRouter
from datetime import datetime

router = APIRouter()

TRADE_LOG_PATH = "trade_log.json"  # adjust if your path is different

@router.get("/analytics")
def get_analytics():
    if not os.path.exists(TRADE_LOG_PATH):
        return {
            "total_pnl": 0,
            "win_rate": 0,
            "agent_stats": {},
            "equity_curve": []
        }

    with open(TRADE_LOG_PATH, "r") as f:
        trades = json.load(f)

    total_pnl = 0
    wins = 0
    losses = 0
    equity_curve = []
    agent_stats = {}
    equity = 1000  # starting capital

    for t in trades:
        pnl = float(t.get("pnl", 0))
        agent = t.get("agent", "Unknown")
        time = t.get("exit_time") or t.get("time") or datetime.now().isoformat()

        if agent not in agent_stats:
            agent_stats[agent] = {"wins": 0, "losses": 0, "pnl": 0.0}

        agent_stats[agent]["pnl"] += pnl

        if pnl >= 0:
            wins += 1
            agent_stats[agent]["wins"] += 1
        else:
            losses += 1
            agent_stats[agent]["losses"] += 1

        total_pnl += pnl
        equity += pnl
        equity_curve.append({"time": time, "equity": equity})

    total_trades = wins + losses
    win_rate = round(wins / total_trades, 4) if total_trades > 0 else 0

    return {
        "total_pnl": round(total_pnl, 2),
        "win_rate": win_rate,
        "agent_stats": agent_stats,
        "equity_curve": equity_curve
    }
