# -*- coding: utf-8 -*-
"""
Telegram command router (Step 1).
Reads/writes governor files and calls API. Adds [PAPER]/[LIVE] prefix everywhere.
"""
import os, json, yaml, time, requests
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = ROOT / "config"
API = "http://127.0.0.1:8088"

BOT_TOKEN = os.getenv("TG_BOT_TOKEN") or (yaml.safe_load((CFG/"telegram.yaml").read_text(encoding="utf-8")).get("token"))
CHAT_ID   = os.getenv("TG_CHAT_ID") or (yaml.safe_load((CFG/"telegram.yaml").read_text(encoding="utf-8")).get("chat_id"))

def mode_prefix():
    modes = yaml.safe_load((CFG/"modes.yaml").read_text(encoding="utf-8"))
    return "[PAPER]" if str(modes.get("mode","PAPER")).upper()=="PAPER" else "[LIVE]"

def send(msg):
    prefix = mode_prefix()
    text = f"{prefix} {msg}"
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": text})

def api(path, payload=None):
    r = requests.post(API+path, json=(payload or {}), timeout=10)
    r.raise_for_status()
    return r.json()

def cmd_mode(arg):
    arg = arg.strip().upper()
    if arg in ("PAPER","LIVE"):
        api("/governor/mode", {"mode": arg})
        send(f"Mode switched to {arg}.")
    else:
        send("Usage: /mode PAPER|LIVE")

def cmd_propose(run_id, trial_id):
    res = api("/governor/propose", {"bob_run_id": run_id, "trial_id": trial_id})
    send(f"Proposed candidate {res.get('candidate_id')} from run {run_id} / {trial_id}. 2×30d checks will be verified.")

def cmd_approve(candidate_id):
    res = api("/governor/promote", {"candidate_id": candidate_id, "force": False})
    send(f"Promoted {candidate_id} to LIVE.")

def cmd_status():
    res = requests.get(API+"/governor/status", timeout=10).json()
    send(f"Status: mode={res.get('mode')}")

# Hook this into your existing Telegram update loop (you already send messages now).
# Commands (examples):
# /mode PAPER
# /mode LIVE
# /propose 20251003_053052 trial_0007
# /approve cand_...
# /status
