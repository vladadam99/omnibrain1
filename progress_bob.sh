#!/usr/bin/env bash
set -euo pipefail

cd /root/omnibrain2

# Pick latest run dir and latest log
RUNDIR="$(ls -td bob_runs/* 2>/dev/null | head -1 || true)"
LOG="$(ls -t bob_*.log 2>/dev/null | head -1 || true)"

if [ -z "$RUNDIR" ]; then
  echo "No bob_runs/ found yet."
  exit 1
fi

# Completed trials (sum of all leaderboard_* files, skipping headers)
DONE=$(cat "$RUNDIR"/leaderboard_* 2>/dev/null | awk 'NR>1 && NF>0{c++} END{print c+0}')

# Try to detect totals from the log line: "pop=96/36/14 muts=48"
TOTAL=""
if [ -n "$LOG" ] && grep -qE 'pop=[0-9]+/[0-9]+/[0-9]+' "$LOG"; then
  POPS=$(grep -m1 -Eo 'pop=[0-9]+/[0-9]+/[0-9]+' "$LOG" | cut -d= -f2)
  Muts=$(grep -m1 -Eo 'muts=[0-9]+' "$LOG" | cut -d= -f2 || echo 0)
  P1=$(echo "$POPS" | cut -d/ -f1); P2=$(echo "$POPS" | cut -d/ -f2); P3=$(echo "$POPS" | cut -d/ -f3)
  TOTAL=$((P1+P2+P3+Muts))
fi

# Fallback if not found (edit if you run a different profile)
if [ -z "${TOTAL:-}" ] || [ "$TOTAL" -le 0 ]; then
  TOTAL=194
fi

# Compute percent
if [ "$TOTAL" -gt 0 ]; then
  PCT=$(awk -v d="$DONE" -v t="$TOTAL" 'BEGIN{if(t>0) printf "%.1f", 100*d/t; else print "0.0"}')
else
  PCT="0.0"
fi

# Best-so-far (score, pnl, wr) from leaderboard
BEST_LINE=$(awk -F, 'NR>1 && $2!="" {print $0}' "$RUNDIR"/leaderboard_* 2>/dev/null | sort -t, -k2,2nr | head -1 || true)
if [ -n "$BEST_LINE" ]; then
  IFS=',' read -r trial_id score pnl wr pf mdd sharpe sortino <<<"$BEST_LINE"
  BEST_SUMMARY=$(printf "best score=%.2f pnl=%.2f wr=%.3f dd=%.2f pf=%.2f" "$score" "$pnl" "$wr" "$mdd" "$pf")
else
  BEST_SUMMARY="best: (not yet)"
fi

# Symbols (from start line in log) if available
SYMS="(unknown)"
if [ -n "$LOG" ] && grep -q 'Using symbols:' "$LOG"; then
  SYMS=$(grep -m1 'Using symbols:' "$LOG" | sed 's/.*Using symbols: //')
fi

MSG=$(printf "BOB progress: %s\nRun: %s\nDone: %d / %d (%s%%)\n%s\n" "$SYMS" "$RUNDIR" "$DONE" "$TOTAL" "$PCT" "$BEST_SUMMARY")
echo "$MSG"

# If env has BOB_TG_TOKEN + BOB_TG_CHAT, also send to Telegram
if [ -n "${BOB_TG_TOKEN:-}" ] && [ -n "${BOB_TG_CHAT:-}" ]; then
  curl -s -X POST "https://api.telegram.org/bot${BOB_TG_TOKEN}/sendMessage" \
       -d chat_id="${BOB_TG_CHAT}" \
       --data-urlencode text="$MSG" >/dev/null || true
fi
