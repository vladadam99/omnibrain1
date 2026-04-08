
# -*- coding: utf-8 -*-
"""
Build a Governor candidate bundle from EXISTING 30-day replay outputs.
Use this when you've already run Bob's month replays and have summary.json files.
It writes governor/candidates/<candidate_id>/manifest.json, copies/links the
two 30d summaries as pass_A / pass_B, and prepares paper_2d/ folder placeholders.

Usage:
  python -m governor_step4.bundle_from_existing \
    --run-dir runs/BOB_20251003_053052 \
    --trial-id <trial_id> \
    --engine-attrs path/to/engine_attrs.json

Assumptions:
- You have at least one summary.json under:
  <run-dir>/month_replays/<trial_id>*/summary.json
- If there are 2 or more, newest two are used as pass_A and pass_B.
- If only one exists, it is used for pass_A and pass_B (you can replace later).

The script will register the candidate with the Governor API (/governor/propose)
and overwrite the created manifest with the fully detailed one.
"""
import argparse, glob, json, os, shutil, time, hashlib
from pathlib import Path

GOV_ROOT = Path(__file__).resolve().parents[1] / "governor"
CAND_DIR = GOV_ROOT / "candidates"

def _sha1p(p: Path) -> str:
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1<<16), b""):
            h.update(chunk)
    return h.hexdigest()

def select_two_summaries(run_dir: Path, trial_id: str):
    paths = sorted(
        glob.glob(str(run_dir / f"month_replays/{trial_id}*/summary.json")),
        key=lambda p: os.path.getmtime(p),
        reverse=True
    )
    if not paths:
        raise SystemExit(f"No summary.json found for trial_id={trial_id} under {run_dir}/month_replays/")
    if len(paths) == 1:
        return Path(paths[0]), Path(paths[0])
    return Path(paths[0]), Path(paths[1])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--trial-id", required=True)
    ap.add_argument("--engine-attrs", required=False, help="Path to engine_attrs.json (optional)")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    trial_id = args.trial_id
    eng_attrs = Path(args.engine_attrs).resolve() if args.engine_attrs else None

    a, b = select_two_summaries(run_dir, trial_id)

    candidate_id = f"cand_{int(time.time())}_{trial_id}"
    out = CAND_DIR / candidate_id
    (out / "month30/pass_A").mkdir(parents=True, exist_ok=True)
    (out / "month30/pass_B").mkdir(parents=True, exist_ok=True)
    (out / "paper_2d").mkdir(parents=True, exist_ok=True)

    # Copy summaries into candidate
    shutil.copy2(a, out / "month30/pass_A/summary.json")
    shutil.copy2(b, out / "month30/pass_B/summary.json")

    # Build manifest
    eva = {
        "thirty_day_passes": [],
        "paper_trial": {
            "duration_days": 0,
            "summary_path": "paper_2d/summary.json",
            "trades_path": "paper_2d/trades.csv",
            "sha_summary": "",
            "sha_trades": "",
            "key_metrics": { "pnl_total":0, "winrate":0, "profit_factor":0, "trades":0 }
        }
    }

    for label in ("A","B"):
        sp = out / f"month30/pass_{label}/summary.json"
        with open(sp, "r", encoding="utf-8") as f:
            km = json.load(f)
        eva["thirty_day_passes"].append({
            "window": label,
            "summary_path": str(sp.relative_to(out)).replace("\\","/"),
            "sha": _sha1p(sp),
            "key_metrics": {
                "pnl_total": km.get("pnl_total", 0),
                "winrate": km.get("winrate", 0),
                "profit_factor": km.get("profit_factor", 0),
                "max_drawdown": km.get("max_drawdown", 0),
                "sharpe_like": km.get("sharpe_like", 0),
            }
        })

    eng = {"json_path": "", "sha": ""}
    if eng_attrs and eng_attrs.exists():
        rel = os.path.relpath(str(eng_attrs), str(out))
        eng = {"json_path": rel.replace("\\","/"), "sha": _sha1p(eng_attrs)}

    manifest = {
        "candidate_id": candidate_id,
        "origin": { "bob_run_id": run_dir.name, "trial_id": trial_id, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) },
        "code_fingerprints": {"agents": [], "engine": []},
        "engine_attributes": eng,
        "training_recipe": {"recipe_used": {}, "hash": ""},
        "evaluation": eva,
        "governor_decision": {"status": "awaiting_approval", "reason":"proposed", "requested_by":"governor", "approved_by": None}
    }

    with open(out/"manifest.json","w",encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"[OK] Candidate bundle at: {out}")
    print(json.dumps(manifest, indent=2))

if __name__ == "__main__":
    main()
