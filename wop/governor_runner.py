
# -*- coding: utf-8 -*-
"""
Start the engine in PAPER for a specific candidate.
- Sets mode to PAPER
- Exports PAPER_TRADES_PATH to candidate_dir/paper_2d/trades.csv
- Starts your engine main loop (importing auto_trade_futures)
Stop it with Ctrl+C; summarize and write paper_2d/summary.json externally.
"""
import os, sys, time, json
from pathlib import Path
import yaml

def set_mode_paper():
    cfg = Path(__file__).resolve().parent / "config"
    (cfg/"modes.yaml").parent.mkdir(parents=True, exist_ok=True)
    with open(cfg/"modes.yaml","w",encoding="utf-8") as f:
        yaml.safe_dump({"mode":"PAPER"}, f, sort_keys=False, allow_unicode=True)

def main():
    if len(sys.argv) < 2:
        print("Usage: python governor_runner.py <candidate_dir>")
        sys.exit(2)
    cand = Path(sys.argv[1]).resolve()
    p2d = cand / "paper_2d"
    p2d.mkdir(parents=True, exist_ok=True)
    trades_csv = p2d / "trades.csv"
    os.environ["PAPER_TRADES_PATH"] = str(trades_csv)
    set_mode_paper()
    print(f"[Governor] PAPER run starting for: {cand}")
    print(f"[Governor] Logging trades to: {trades_csv}")

    import auto_trade_futures  # engine module; ensure it imports omnibrain_utils_governor

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("[Governor] PAPER run stopped by user.")

if __name__ == "__main__":
    main()
