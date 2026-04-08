import os, re, time, json, pathlib
LOG = "logs/bob_watch_validator.log"
RUNS = pathlib.Path("bob_runs")
RUNS.mkdir(exist_ok=True)
pathlib.Path("logs").mkdir(exist_ok=True)
pathlib.Path(LOG).touch(exist_ok=True)

rx_done = re.compile(r"^✅\s*Validator done", re.I)
rx_for  = re.compile(r"^(?:For|Trial)\s*:\s*([A-Za-z0-9_]+)", re.I)

def latest_run_dir():
    items = [p for p in RUNS.glob("*_*") if p.is_dir()]
    if not items: return None
    return max(items, key=lambda p: p.stat().st_mtime)

def ensure_aggregate(run_id, trial_hint=None):
    vdir = RUNS / run_id / "validator"
    vdir.mkdir(parents=True, exist_ok=True)
    ap = vdir / "aggregate.json"
    if ap.exists(): return False
    data = {
        "run_id": run_id,
        "trial": trial_hint,
        "pnl": 0.0,
        "winrate": 0.0,
        "profit_factor": 0.0,
        "max_dd": 0.0,
        "trades": 0,
        "source": "backfill",
        "note": "fallback aggregate generated because validator summary was missing"
    }
    ap.write_text(json.dumps(data, indent=2))
    print(f"[backfill] wrote {ap}")
    return True

def follow(path):
    with open(path, "r", errors="ignore") as f:
        f.seek(0, os.SEEK_END)
        buf = []
        last_trial = None
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.4); continue
            buf.append(line)
            m_trial = rx_for.search(line)
            if m_trial:
                last_trial = m_trial.group(1)
            if rx_done.search(line):
                # give validator a moment to write the file
                time.sleep(1.5)
                lrd = latest_run_dir()
                if lrd is None:
                    print("[backfill] no bob_runs/* found"); continue
                run_id = lrd.name
                vdir = lrd / "validator"
                ap = vdir / "aggregate.json"
                if not ap.exists():
                    ensure_aggregate(run_id, last_trial)

if __name__ == "__main__":
    print("[backfill] watching", LOG)
    follow(LOG)
