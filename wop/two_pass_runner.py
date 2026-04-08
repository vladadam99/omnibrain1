# -*- coding: utf-8 -*-
"""
two_pass_runner.py — Run TWO 30-day replays for a specific trial and build a Governor candidate.

It will:
  1) Run PASS A on the most recent 30 days (now-30d .. now)
  2) Run PASS B on the prior 30 days   (now-60d .. now-30d)
  3) Write a complete candidate bundle under governor/candidates/<candidate_id>/
     - month30/pass_A/summary.json
     - month30/pass_B/summary.json
     - paper_2d/ (empty placeholders)
     - manifest.json (awaiting_approval)

It attempts these execution paths in order:
  (a) Use BOB replay by trial:  replay_one_month(run_dir, trial_id, tf, days, outdir)
  (b) Shim BOB replay_topN_month by crafting a temporary leaderboard with only trial_id (N=1)
  (c) Call backtest_autotrade_UPG.simulate(...) directly with the trial config injected

Usage:
  python -m governor_step4.two_pass_runner \
    --run-dir runs/BOB_20251003_053052 \
    --trial-id trial_0007 \
    --tf 5m \
    --days 30
"""
from __future__ import annotations
import argparse, os, sys, json, time, shutil, glob, uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone

GOV = Path(__file__).resolve().parents[1] / "governor"
CAND = GOV / "candidates"

def _now_utc():
    return datetime.now(timezone.utc)

def _date_range(days: int, offset_days: int=0):
    end = _now_utc() - timedelta(days=offset_days)
    start = end - timedelta(days=days)
    return start, end

def _iso(ts: datetime):
    return ts.replace(microsecond=0).isoformat()

def _read_json(p: Path):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_json(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def _ensure_candidate(run_dir: Path, trial_id: str) -> Path:
    cid = f"cand_{int(time.time())}_{trial_id}"
    out = CAND / cid
    (out / "month30/pass_A").mkdir(parents=True, exist_ok=True)
    (out / "month30/pass_B").mkdir(parents=True, exist_ok=True)
    (out / "paper_2d").mkdir(parents=True, exist_ok=True)
    manifest = {
        "candidate_id": cid,
        "origin": {"bob_run_id": run_dir.name, "trial_id": trial_id, "created_utc": _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")},
        "code_fingerprints": {"agents": [], "engine": []},
        "engine_attributes": {"json_path": "", "sha": ""},
        "training_recipe": {"recipe_used": {}, "hash": ""},
        "evaluation": {
            "thirty_day_passes": [],
            "paper_trial": {
                "duration_days": 0,
                "summary_path": "paper_2d/summary.json",
                "trades_path": "paper_2d/trades.csv",
                "sha_summary": "",
                "sha_trades": "",
                "key_metrics": { "pnl_total":0, "winrate":0, "profit_factor":0, "trades":0 }
            }
        },
        "governor_decision": {"status": "awaiting_approval", "reason": "proposed", "requested_by": "governor", "approved_by": None}
    }
    _write_json(out/"manifest.json", manifest)
    return out

def _try_bob_direct(run_dir: Path, trial_id: str, tf: str, days: int, outdir: Path, label: str) -> bool:
    try:
        import BOB_ASI_Pro_Plus_SANDBOX_UPG as bob
    except Exception:
        return False
    fn = getattr(bob, "replay_one_month", None)
    if fn:
        try:
            print(f"[two_pass] Calling BOB.replay_one_month({trial_id}, days={days}) for {label}")
            fn(str(run_dir), trial_id, tf, days, str(outdir))
            return (outdir/"summary.json").exists()
        except Exception as e:
            print("[two_pass] BOB.replay_one_month failed:", e)
    fnN = getattr(bob, "replay_topN_month", None)
    if fnN:
        try:
            tmp = run_dir / f"leaderboard_{uuid.uuid4().hex}.csv"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("trial_id,score
")
                f.write(f"{trial_id},999999
")
            print(f"[two_pass] Using BOB.replay_topN_month shim with temp leaderboard {tmp.name}")
            os.environ["BOB_LEADERBOARD_PATH"] = str(tmp)
            outdir.mkdir(parents=True, exist_ok=True)
            fnN(str(run_dir), N=1, tf=tf, days=days)
            candidates = list((run_dir/"month_replays").glob(f"{trial_id}*/summary.json"))
            if candidates:
                shutil.copy2(candidates[0], outdir/"summary.json")
                return True
        except Exception as e:
            print("[two_pass] BOB.replay_topN_month shim failed:", e)
    return False

def _try_backtester(run_dir: Path, trial_id: str, tf: str, days: int, outdir: Path, label: str) -> bool:
    try:
        import backtest_autotrade_UPG as bt
    except Exception as e:
        print("[two_pass] backtest_autotrade_UPG import failed:", e)
        return False
    start, end = _date_range(days, offset_days=(0 if label=="A" else days))
    try:
        if hasattr(bt, "simulate_trial"):
            summ = bt.simulate_trial(trial_id=trial_id, tf=tf, start=_iso(start), end=_iso(end))
        elif hasattr(bt, "simulate"):
            summ = bt.simulate(trial_id=trial_id, tf=tf, start=_iso(start), end=_iso(end))
        else:
            print("[two_pass] No suitable simulate function found in backtest_autotrade_UPG.")
            return False
        _write_json(outdir/"summary.json", summ if isinstance(summ, dict) else {})
        return True
    except Exception as e:
        print("[two_pass] backtester execution failed:", e)
        return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--trial-id", required=True)
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    trial_id = args.trial_id
    tf = args.tf
    days = args.days

    out = _ensure_candidate(run_dir, trial_id)
    print(f"[two_pass] Candidate directory: {out}")

    a_dir = out / "month30/pass_A"
    a_ok = _try_bob_direct(run_dir, trial_id, tf, days, a_dir, label="A") or            _try_backtester(run_dir, trial_id, tf, days, a_dir, label="A")
    if not a_ok:
        print("[two_pass] PASS A failed; please run your month replay manually and place summary.json into", a_dir)
        sys.exit(2)

    b_dir = out / "month30/pass_B"
    b_ok = _try_bob_direct(run_dir, trial_id, tf, days, b_dir, label="B") or            _try_backtester(run_dir, trial_id, tf, days, b_dir, label="B")
    if not b_ok:
        print("[two_pass] PASS B failed; please run your month replay manually and place summary.json into", b_dir)
        sys.exit(2)

    manp = out / "manifest.json"
    man = _read_json(manp)
    for label, d in (("A", a_dir), ("B", b_dir)):
        try:
            km = _read_json(d/"summary.json")
        except Exception:
            km = {}
        man["evaluation"]["thirty_day_passes"].append({
            "window": label,
            "summary_path": str((d/"summary.json").relative_to(out)).replace("\","/"),
            "sha": "",
            "key_metrics": {
                "pnl_total": km.get("pnl_total", 0),
                "winrate": km.get("winrate", 0),
                "profit_factor": km.get("profit_factor", 0),
                "max_drawdown": km.get("max_drawdown", 0),
                "sharpe_like": km.get("sharpe_like", 0)
            }
        })
    _write_json(manp, man)
    print(f"[two_pass] DONE. Bundle ready at: {out}")

if __name__ == "__main__":
    main()
