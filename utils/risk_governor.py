# -*- coding: utf-8 -*-
# === risk_governor.py ===
import json, os

RISK_FILE = "risk_state.json"

def check_risk_limits():
    if os.path.exists(RISK_FILE):
        with open(RISK_FILE, "r") as f:
            state = json.load(f)
        if state["loss_streak"] >= 3 or state["daily_loss"] >= 50:
            print("[RISK] Limits breached. Cooling down.")
            return False
    return True

def update_risk_state(symbol, qty, entry_price, side):
    pnl = -3.0  # Placeholder for real PnL calc
    state = {"loss_streak": 0, "daily_loss": 0}

    if os.path.exists(RISK_FILE):
        with open(RISK_FILE, "r") as f:
            state = json.load(f)

    if pnl < 0:
        state["loss_streak"] += 1
        state["daily_loss"] += abs(pnl)
    else:
        state["loss_streak"] = 0

    with open(RISK_FILE, "w") as f:
        json.dump(state, f)

    print(f"[RISK] Updated state: {state}")
