# -*- coding: utf-8 -*-
# --- web_api.py ---
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from modules.sensory_matrix import SensoryMatrix
from meta_governor import MetaGovernor
from config_loader import load_config
from analytics_api import get_analytics
from backtest_api import router as backtest_router
import uvicorn
import asyncio
from datetime import datetime

app = FastAPI()

# === Enable frontend (React) to connect ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Initialize system core ===
cfg = load_config()
symbol = cfg["symbol"]
interval = cfg["interval"]
enabled_agents = [k for k, v in cfg["agents"].items() if v]
agent_configs = [{"name": name, "params": {}} for name in enabled_agents]
governor = MetaGovernor(agent_configs)
open_trades = {a["name"]: None for a in governor.agents}

# === Include Backtest API Router ===
app.include_router(backtest_router)

# === Routes ===

@app.get("/price")
def get_latest_price():
    sm = SensoryMatrix(symbol, interval, lookback="100 bars")
    df = sm.get_data()
    if df is None or len(df) < 50:
        return {"price": None}
    return {"price": float(df["close"].iloc[-1])}


@app.get("/signals")
def get_signals():
    sm = SensoryMatrix(symbol, interval, lookback="100 bars")
    df = sm.get_data()
    if df is None or len(df) < 50:
        return {"signals": []}
    signals = governor.evaluate_all(df)
    return {"signals": signals}


@app.get("/trades")
def get_open_trades():
    return {"open_trades": open_trades}


@app.get("/rankings")
def get_rankings():
    return {"rankings": governor.rank_agents(key="pnl")}


@app.get("/analytics")
def analytics_endpoint():
    return get_analytics()


@app.post("/toggle-agent")
async def toggle_agent(request: Request):
    data = await request.json()
    agent_name = data.get("agent")
    enable = data.get("enable", True)

    if agent_name in open_trades:
        if enable:
            governor.enable_agent(agent_name)
        else:
            governor.disable_agent(agent_name)
        return {"status": "ok", "agent": agent_name, "enabled": enable}

    return {"status": "error", "message": "Unknown agent"}


# === Manual Trade Execution ===
@app.post("/manual-trade")
async def manual_trade(request: Request):
    data = await request.json()
    agent = data.get("agent")
    side = data.get("side", "buy")
    price = float(data.get("price", 11458))  # fallback dummy price
    quantity = float(data.get("quantity", 1))
    mode = data.get("mode", "market")

    if agent not in open_trades:
        return {"status": "error", "message": "Unknown agent"}

    trade = {
        "agent": agent,
        "side": side.lower(),
        "entry": price,
        "quantity": quantity,
        "mode": mode,
        "time": datetime.now().isoformat(),
        "manual": True
    }

    open_trades[agent] = trade
    return {"status": "ok", "trade": trade}


# === WebSocket: Real-time Price Stream ===
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            sm = SensoryMatrix(symbol, interval, lookback="100 bars")
            df = sm.get_data()
            price = float(df["close"].iloc[-1]) if df is not None and len(df) >= 50 else None
            await websocket.send_json({"price": price})
            await asyncio.sleep(1)
    except Exception as e:
        print("WebSocket closed:", str(e))
        await websocket.close()


# === Launch server ===
if __name__ == "__main__":
    uvicorn.run("web_api:app", host="0.0.0.0", port=8000, reload=True)
