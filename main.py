# -*- coding: utf-8 -*-
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import json, os
from fastapi.responses import JSONResponse
from omnibrain_utils_futures import load_open_positions, get_futures_balance
from binance.client import Client

# Load API keys
if os.path.exists("REAL.json"):
    with open("REAL.json", "r") as f:
        keys = json.load(f)
else:
    keys = {"API_KEY": "", "API_SECRET": ""}

client = Client(keys["API_KEY"], keys["API_SECRET"])

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

@app.get("/api/ping")
async def ping():
    return {"status": "ok"}

@app.get("/api/futures/open_positions")
async def get_open_positions():
    positions = load_open_positions()
    return {"open_positions": positions}

@app.get("/api/futures/pnl")
async def get_pnl():
    pnl_data = []
    try:
        for pos in load_open_positions().values():
            symbol = pos['symbol']
            side = pos['side']
            entry = pos['entry_price']
            qty = float(pos['qty'])

            mark = float(client.futures_mark_price(symbol=symbol)['markPrice'])
            diff = (mark - entry) if side == "buy" else (entry - mark)
            pnl = diff * qty

            pnl_data.append({
                "symbol": symbol,
                "entry_price": entry,
                "current_price": mark,
                "qty": qty,
                "side": side,
                "pnl": round(pnl, 2),
                "confidence": pos.get("confidence", 0),
                "time_open": pos.get("timestamp", 0)
            })
    except Exception as e:
        return {"error": str(e)}

    return {"pnl": pnl_data}

@app.get("/api/futures/config")
async def config():
    return {
        "leverage": 20,
        "margin_mode": "ISOLATED",
        "strategy": "multi-agent-vote",
        "sl_tp_mode": "ATR: TP=2.5x, SL=1.2x",
        "confidence_threshold": 0.85,
        "time_limit_minutes": 60
    }

if __name__ == "__main__":
    uvicorn.run("main:app", port=8000, reload=True)
