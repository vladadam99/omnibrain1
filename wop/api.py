# -*- coding: utf-8 -*-
"""
Minimal FastAPI surface for Governor control.
Non-invasive: uses files under governor/ to manage candidates and mode.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
import json, yaml, shutil, time

ROOT = Path(__file__).resolve().parent
CFG = ROOT / "config"
CAND = ROOT / "candidates"
PROM = ROOT / "promoted"
SCHEMA = ROOT / "manifest_schema.json"

app = FastAPI(title="OmniBrain Governor API", version="1.0")

def load_yaml(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_yaml(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

def read_json(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def write_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

class ProposeBody(BaseModel):
    bob_run_id: str
    trial_id: str
    bundle_path: str | None = None

class ModeBody(BaseModel):
    mode: str  # PAPER or LIVE

class PromoteBody(BaseModel):
    candidate_id: str
    force: bool = False

class PaperStartBody(BaseModel):
    candidate_id: str
    days: int = 2

class PaperStopBody(BaseModel):
    candidate_id: str

class LimitsBody(BaseModel):
    updates: dict

@app.get("/governor/status")
def governor_status(candidate_id: str | None = None):
    modes = load_yaml(CFG / "modes.yaml")
    status = {"mode": modes.get("mode","PAPER")}
    if candidate_id:
        man = CAND / candidate_id / "manifest.json"
        if not man.exists():
            raise HTTPException(404, f"candidate {candidate_id} not found")
        status["candidate"] = read_json(man)
    return status

@app.post("/governor/mode")
def governor_mode(body: ModeBody):
    mode = body.mode.upper()
    if mode not in ("PAPER","LIVE"):
        raise HTTPException(400, "mode must be PAPER or LIVE")
    save_yaml(CFG / "modes.yaml", {"mode": mode})
    return {"ok": True, "mode": mode}

@app.post("/governor/limits")
def governor_limits(body: LimitsBody):
    limits = load_yaml(CFG / "limits.yaml") or {}
    limits.update(body.updates or {})
    save_yaml(CFG / "limits.yaml", limits)
    return {"ok": True, "limits": limits}

@app.post("/governor/propose")
def governor_propose(body: ProposeBody):
    # In Step 2, Bob will write a fully-formed candidate folder.
    # For now we register the intent and create a placeholder candidate folder.
    cid = f"cand_{int(time.time())}_{body.trial_id}"
    target = CAND / cid
    target.mkdir(parents=True, exist_ok=True)
    manifest = {
        "candidate_id": cid,
        "origin": { "bob_run_id": body.bob_run_id, "trial_id": body.trial_id, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) },
        "code_fingerprints": {"agents": [], "engine": []},
        "engine_attributes": {"json_path": "engine_attrs.json", "sha": ""},
        "training_recipe": {"recipe_used": {}, "hash": ""},
        "evaluation": { "thirty_day_passes": [], "paper_trial": { "duration_days": 0, "summary_path": "", "trades_path": "", "sha_summary": "", "sha_trades": "", "key_metrics": { "pnl_total":0, "winrate":0, "profit_factor":0, "trades":0 } } },
        "governor_decision": {"status": "awaiting_approval", "reason": "proposed", "requested_by": "governor", "approved_by": None}
    }
    write_json(target / "manifest.json", manifest)
    return {"ok": True, "candidate_id": cid}

@app.post("/governor/paper/start")
def governor_paper_start(body: PaperStartBody):
    # Flip to PAPER and mark intent in manifest; Step 2 will run the actual paper engine.
    modes = {"mode": "PAPER"}
    save_yaml(CFG / "modes.yaml", modes)
    manpath = CAND / body.candidate_id / "manifest.json"
    if not manpath.exists():
        raise HTTPException(404, "candidate not found")
    man = read_json(manpath)
    man.setdefault("evaluation", {}).setdefault("paper_trial", {})["duration_days"] = body.days
    write_json(manpath, man)
    return {"ok": True, "candidate_id": body.candidate_id, "mode": "PAPER"}

@app.post("/governor/paper/stop")
def governor_paper_stop(body: PaperStopBody):
    # Placeholder to mark end of paper window
    manpath = CAND / body.candidate_id / "manifest.json"
    if not manpath.exists():
        raise HTTPException(404, "candidate not found")
    man = read_json(manpath)
    man["governor_decision"]["reason"] = "paper finished"
    write_json(manpath, man)
    return {"ok": True}

@app.post("/governor/promote")
def governor_promote(body: PromoteBody):
    cand = CAND / body.candidate_id
    if not cand.exists():
        raise HTTPException(404, "candidate not found")
    (PROM / "live_current").parent.mkdir(parents=True, exist_ok=True)
    # replace symlink
    link = PROM / "live_current"
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(cand)
    # flip to LIVE
    save_yaml(CFG / "modes.yaml", {"mode": "LIVE"})
    # mark manifest
    manpath = cand / "manifest.json"
    man = read_json(manpath)
    man["governor_decision"]["status"] = "approved"
    man["governor_decision"]["reason"] = "promoted to live"
    write_json(manpath, man)
    return {"ok": True, "live_candidate": body.candidate_id, "mode": "LIVE"}
