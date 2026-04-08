
import os, json

RUNS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bob_runs"))
ACTIVE_FILE = os.path.join(os.path.dirname(__file__), "ACTIVE_RUN.txt")

def _load_json(p):
    with open(p, "r", encoding="utf-8") as f: return json.load(f)

def get_config(selected_run_id=None):
    run_id = selected_run_id or os.environ.get("OMNIBRAIN_RUN_ID")
    if not run_id and os.path.isfile(ACTIVE_FILE):
        with open(ACTIVE_FILE, "r", encoding="utf-8") as f: run_id = f.read().strip()
    if not run_id: return {}
    # find run dir
    run_dir = None
    for name in os.listdir(RUNS_DIR):
        if run_id in name:
            run_dir = os.path.join(RUNS_DIR, name); break
    if not run_dir: return {}
    # load best config
    for cand in (f"best_config_{run_id}.json", "best_config.json"):
        path = os.path.join(run_dir, cand)
        if os.path.isfile(path):
            cfg = _load_json(path)
            (cfg.setdefault("metadata", {}))["run_id"] = run_id
            return cfg
    return {}
