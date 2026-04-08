# -*- coding: utf-8 -*-
"""
Simple governor loop (Step 1): watches candidates, guardrails, and mode.
In Step 2 it will drive paper runs and call /promote after Telegram approval.
"""
from pathlib import Path
import time, json, yaml, requests

ROOT = Path(__file__).resolve().parent
CFG = ROOT / "config"
CAND = ROOT / "candidates"

API = "http://127.0.0.1:8088"  # where you run FastAPI (uvicorn governor.api:app --port 8088)

def load_yaml(p): 
    with p.open("r", encoding="utf-8") as f: return yaml.safe_load(f)

def read_json(p): 
    with p.open("r", encoding="utf-8") as f: return json.load(f)

def post(path, payload): 
    return requests.post(API + path, json=payload, timeout=10).json()

def kpis_ok(summary: dict, gates: dict):
    return (summary.get("profit_factor",0) >= gates["min_profit_factor"] and
            summary.get("winrate",0) >= gates["min_winrate"] and
            summary.get("max_drawdown",1) <= gates["max_drawdown_frac"] and
            summary.get("pnl_total",0) >= gates.get("min_pnl_total",0) and
            summary.get("sharpe_like",0) >= gates.get("min_sharpe_like",0))

def run():
    while True:
        guard = load_yaml(CFG / "guardrails.yaml")
        # In Step 2, we’ll notify Telegram here and orchestrate paper runs.
        for cand_dir in sorted(CAND.glob("cand_*")):
            manp = cand_dir / "manifest.json"
            if not manp.exists(): continue
            man = read_json(manp)
            if man["governor_decision"]["status"] != "awaiting_approval": 
                continue
            passes = man.get("evaluation",{}).get("thirty_day_passes",[])
            if guard["promotion"]["require_two_30d_passes"] and len(passes) >= 2:
                a_ok = kpis_ok(passes[0]["key_metrics"], guard["gates"]["backtest"])
                b_ok = kpis_ok(passes[1]["key_metrics"], guard["gates"]["backtest"])
                if a_ok and b_ok:
                    # start paper (Step 1: set mode; Step 2 will kick the engine)
                    post("/governor/paper/start", {"candidate_id": man["candidate_id"], "days": guard["promotion"]["paper_duration_hours"] // 24})
        time.sleep(15)

if __name__ == "__main__":
    run()
