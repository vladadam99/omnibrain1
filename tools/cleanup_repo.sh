#!/usr/bin/env bash
set -euo pipefail

# OMNIBRAIN cleanup helper
# Removes bulky build/cache artifacts and duplicate engine variants.
# Safe: does NOT touch fingerprints, trade memory, or your core engine.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[cleanup] repo: $ROOT_DIR"

# Bulky regenerable folders
for d in .bt_cache node_modules bob_runs backtests; do
  if [[ -d "$d" ]]; then
    echo "[cleanup] removing folder: $d"
    rm -rf "$d"
  fi
done

# Duplicate/variant engine copies (keep only auto_trade_futures.py)
for f in auto_trade_futures_BADENC.py auto_trade_futures_UTF8.py; do
  if [[ -f "$f" ]]; then
    echo "[cleanup] removing file: $f"
    rm -f "$f"
  fi
done

# Python caches anywhere
echo "[cleanup] removing __pycache__ / *.pyc"
find . -type d -name "__pycache__" -prune -exec rm -rf {} + || true
find . -type f -name "*.pyc" -delete || true

echo "[cleanup] done"

cat <<'NEXT'

NEXT STEPS (optional):
  1) Review changes:
     git status

  2) If everything looks good:
     git add -A
     git commit -m "cleanup: remove bulky artifacts and duplicate engine variants"
     git push

NOTE:
  - This script intentionally does NOT remove fingerprints_* or trade_memory.*
  - It also does not remove secrets; keep those out of git via your own local ignore.
NEXT
