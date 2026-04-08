
# -*- coding: utf-8 -*-
"""
Tiny CLI to toggle PAPER/LIVE.
Usage:
  python governor_step3/mode_toggle.py PAPER
  python governor_step3/mode_toggle.py LIVE
"""
import sys
from pathlib import Path
import yaml

CFG = Path(__file__).resolve().parents[1] / "governor" / "config" / "modes.yaml"

def main():
    if len(sys.argv) != 2 or sys.argv[1].upper() not in ("PAPER","LIVE"):
        print("Usage: python governor_step3/mode_toggle.py PAPER|LIVE")
        sys.exit(2)
    mode = sys.argv[1].upper()
    CFG.parent.mkdir(parents=True, exist_ok=True)
    with open(CFG, "w", encoding="utf-8") as f:
        yaml.safe_dump({"mode": mode}, f, sort_keys=False, allow_unicode=True)
    print(f"Mode set to {mode}. File: {CFG}")

if __name__ == "__main__":
    main()
