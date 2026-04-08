
# -*- coding: utf-8 -*-
"""Build a candidate bundle (manifest + attrs + two 30d summaries).
Call from your BOB run after selecting a trial_id.
"""
from __future__ import annotations
from pathlib import Path
import json, hashlib, time

ROOT = Path(__file__).resolve().parent
CAND = ROOT / "candidates"

def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def build_candidate_bundle(bob_run_id: str, trial_id: str, summary_A: Path, summary_B: Path, engine_attrs_json: Path, diffs_dir: Path|None=None) -> Path:
    cid = f"cand_{int(time.time())}_{trial_id}"
    out = CAND / cid
    out.mkdir(parents=True, exist_ok=True)
    # Copy or reference files (for now, just reference paths to keep it simple)
    manifest = {
        "candidate_id": cid,
        "origin": {"bob_run_id": bob_run_id, "trial_id": trial_id, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "code_fingerprints": {"agents": [], "engine": []},
        "engine_attributes": {"json_path": str(engine_attrs_json), "sha": _sha1(engine_attrs_json) if engine_attrs_json.exists() else ""},
        "training_recipe": {"recipe_used": {}, "hash": ""},
        "evaluation": {
            "thirty_day_passes": [
                {"window": "A", "summary_path": str(summary_A), "sha": _sha1(summary_A) if summary_A.exists() else "", "key_metrics": json.load(open(summary_A)) if summary_A.exists() else {}},
                {"window": "B", "summary_path": str(summary_B), "sha": _sha1(summary_B) if summary_B.exists() else "", "key_metrics": json.load(open(summary_B)) if summary_B.exists() else {}},
            ],
            "paper_trial": {"duration_days": 0, "summary_path": "", "trades_path": "", "sha_summary": "", "sha_trades": "", "key_metrics": {"pnl_total":0, "winrate":0, "profit_factor":0, "trades":0}}
        },
        "governor_decision": {"status":"awaiting_approval","reason":"proposed","requested_by":"governor","approved_by":None}
    }
    with open(out/"manifest.json","w",encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return out
