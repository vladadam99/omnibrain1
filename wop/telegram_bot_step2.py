
# -*- coding: utf-8 -*-
"""Telegram router (STEP 2): adds explicit approval phrase and paper prompts.
Integrate into your update loop. All messages are prefixed with [PAPER]/[LIVE].
"""
import os, requests, yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = ROOT / "config"
API = "http://127.0.0.1:8088"

BOT_TOKEN = os.getenv("TG_BOT_TOKEN") or (yaml.safe_load((CFG/"telegram.yaml").read_text(encoding="utf-8")).get("token") if (CFG/"telegram.yaml").exists() else None)
CHAT_ID   = os.getenv("TG_CHAT_ID") or (yaml.safe_load((CFG/"telegram.yaml").read_text(encoding="utf-8")).get("chat_id") if (CFG/"telegram.yaml").exists() else None)

def mode():
    try:
        md = yaml.safe_load((CFG/"modes.yaml").read_text(encoding="utf-8"))
        return str(md.get("mode","PAPER")).upper()
    except Exception:
        return "PAPER"

def prefix(): return "[PAPER]" if mode()=="PAPER" else "[LIVE]"

def send(msg):
    if not (BOT_TOKEN and CHAT_ID): return
    text = f"{prefix()} {msg}"
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": text})

def approve(candidate_id: str, phrase: str):
    if phrase.strip().upper() != f"YES LIVE {candidate_id}".upper():
        send(f"Approval phrase mismatch. Reply exactly: YES LIVE {candidate_id}")
        return
    r = requests.post(API+"/governor/promote", json={"candidate_id": candidate_id, "force": False}, timeout=10)
    r.raise_for_status()
    send(f"Promoted {candidate_id} to LIVE.")
