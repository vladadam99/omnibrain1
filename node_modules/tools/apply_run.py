
import sys, os
ACTIVE_FILE = os.path.join("agents", "ACTIVE_RUN.txt")
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/apply_run.py <run_id>")
        raise SystemExit(1)
    rid = sys.argv[1].strip()
    os.makedirs(os.path.dirname(ACTIVE_FILE), exist_ok=True)
    with open(ACTIVE_FILE, "w", encoding="utf-8") as f: f.write(rid)
    print(f"Activated {rid} for OMNIBRAIN.")
