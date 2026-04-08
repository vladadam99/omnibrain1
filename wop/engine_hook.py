
# -*- coding: utf-8 -*-
"""Engine Hook: mode-aware Telegram prefix and broker selector.
STEP 2: Import this in your runner to ensure PAPER/LIVE tagging and broker selection.
"""
from pathlib import Path
import yaml

CFG = Path(__file__).resolve().parent / "config"

def current_mode() -> str:
    try:
        modes = yaml.safe_load((CFG/"modes.yaml").read_text(encoding="utf-8")) or {}
        return str(modes.get("mode","PAPER")).upper()
    except Exception:
        return "PAPER"

def tg_prefix() -> str:
    return "[PAPER]" if current_mode()=="PAPER" else "[LIVE]"
