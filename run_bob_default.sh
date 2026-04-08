#!/usr/bin/env bash
set -euo pipefail
cd /root/omnibrain2
screen -S BOB -dm bash -lc '
  source venv/bin/activate && \
  flock -n /tmp/bob.lock \
  python BOB_ASI_Pro_Plus.py \
    --symbols TOP10 --tf 5m \
    --days_stage1 1 --days_stage2 2 --days_stage3 3 \
    --start_balance 100 --alloc 20 --lev 10 \
    --pop1 6 --pop2 3 --pop3 2 --mutations 3 \
    --seed 1337
'
echo "BOB started in detached screen session: BOB"
