#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

ROOT="${1:-$HOME/omnibrain2}"
RUNS=( "$ROOT"/bob_runs/202510* )

if [ ${#RUNS[@]} -eq 0 ]; then
  echo "No runs found under $ROOT/bob_runs/ since 2025-10-01."
  exit 0
fi

for d in $(ls -td "$ROOT"/bob_runs/202510* 2>/dev/null); do
  lb=( "$d"/leaderboard*.csv )
  [ ${#lb[@]} -eq 0 ] && continue
  lb="${lb[0]}"

  best_line=$(awk -F, 'NR>1 && NF>1{print $0}' "$lb" | sort -t, -k2,2nr | head -1)
  [ -z "$best_line" ] && continue
  IFS=',' read -r trial_id score pnl wr pf mdd sharpe sortino <<<"$best_line"

  echo "RUN: $d"
  printf "  best score=%s | pnl=%s | wr=%s | pf=%s | dd=%s | trial=%s\n" "$score" "$pnl" "$wr" "$pf" "$mdd" "$trial_id"

  bjson=( "$d"/best*.json )
  if [ ${#bjson[@]} -gt 0 ] && command -v jq >/dev/null 2>&1; then
    bj="${bjson[0]}"
    # Show a few useful knobs if present in JSON (safe if missing)
    jq -r '
      def getnum(p): (try (getpath(p)) catch null) // null;
      def show(k; v):
        if v==null then empty else "    " + k + ": " + (v|tostring) end;

      (   show("quick_tp";        getnum(["config","quick_tp"]))
        , show("min_move";        getnum(["config","min_move"]))
        , show("max_loss";        getnum(["config","max_loss"]))
        , show("entry_ttl";       getnum(["config","entry_ttl"]))
        , show("max_open";        getnum(["config","max_open"]))
        , show("metrics.pnl_total"; getnum(["metrics","pnl_total"]))
        , show("metrics.winrate";   getnum(["metrics","winrate"]))
        , show("metrics.max_drawdown"; getnum(["metrics","max_drawdown"]))
      ) | select(.!=null)
    ' "$bj" || true
    echo "  best_config: $bj"
  fi
  echo
done
