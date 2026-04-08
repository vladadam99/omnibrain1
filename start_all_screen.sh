#!/usr/bin/env bash
set -euo pipefail
cd /root/omnibrain2
mkdir -p logs governor/pids governor/queue governor/state/paper_active

# tiny JSON getter
json_get() { python3 - "$1" "$2" <<'PY'
import json,sys
p,k=sys.argv[1],sys.argv[2]
try: print(json.load(open(p,"r",encoding="utf-8")).get(k,"") or "")
except Exception: print("")
PY
}

REAL_JSON="${REAL_JSON:-governor/REAL.json}"

# Govbot/engine tokens (pulled if present)
export TELEGRAM_GOVBOT_TOKEN="$(json_get "$REAL_JSON" TELEGRAM_GOVBOT_TOKEN)"
export TELEGRAM_GOVBOT_CHAT_ID="$(json_get "$REAL_JSON" TELEGRAM_GOVBOT_CHAT_ID)"
export TELEGRAM_BOT_TOKEN="$(json_get "$REAL_JSON" TELEGRAM_BOT_TOKEN)"
export TELEGRAM_CHAT_ID="$(json_get "$REAL_JSON" TELEGRAM_CHAT_ID)"

# Bob tokens (we just saved)
TELEGRAM_BOB_TOKEN="$(json_get "$REAL_JSON" TELEGRAM_BOB_TOKEN)"
TELEGRAM_BOB_CHAT_ID="$(json_get "$REAL_JSON" TELEGRAM_BOB_CHAT_ID)"

# Fall back if GOVBOT_* missing but generic present
[[ -z "${TELEGRAM_GOVBOT_TOKEN:-}" && -n "${TELEGRAM_BOT_TOKEN:-}" ]] && export TELEGRAM_GOVBOT_TOKEN="$TELEGRAM_BOT_TOKEN"
[[ -z "${TELEGRAM_GOVBOT_CHAT_ID:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]] && export TELEGRAM_GOVBOT_CHAT_ID="$TELEGRAM_CHAT_ID"

# Start the screen
screen -dmS omnibrain

# 1) ENGINE (PAPER only)
screen -S omnibrain -X screen -t engine bash -lc 'PAPER=1 DRY_RUN=1 NO_LIVE=1 nohup /root/venv/bin/python -u auto_trade_futures.py >> logs/engine.log 2>&1'

# 2) GOVBOT (rich /status)
screen -S omnibrain -X screen -t govbot bash -lc 'export TELEGRAM_GOVBOT_TOKEN TELEGRAM_GOVBOT_CHAT_ID; nohup /root/venv/bin/python -u governor/telegram_bot_mini.py >> logs/govbot.log 2>&1'

# 3) API (optional)
screen -S omnibrain -X screen -t api bash -lc 'nohup /root/venv/bin/python -m uvicorn governor.api:app --host 127.0.0.1 --port 8088 >> logs/governor_api.log 2>&1'

# 4) PAPER consumer
screen -S omnibrain -X screen -t consumer bash -lc 'nohup /root/venv/bin/python -u governor/paper_queue_consumer.py >> logs/paper_consumer.log 2>&1'

# 5) BOB: optimize → 2×30d validate → 2d PAPER (with fallback)
screen -S omnibrain -X screen -t bob bash -lc '
  export TELEGRAM_BOT_TOKEN="'"$TELEGRAM_BOB_TOKEN"'" TELEGRAM_CHAT_ID="'"$TELEGRAM_BOB_CHAT_ID"'";
  {
    echo "[PIPE] Trying monolithic pipeline…"
    /root/venv/bin/python -u bob.py run --optimize --notify-interval 10 --validate 30d --validate 30d --paper 2d
  } >> logs/bob.log 2>&1 || {
    echo "[PIPE] Fallback to staged pipeline…" >> logs/bob.log
    /root/venv/bin/python -u bob.py optimize --notify-interval 10 >> logs/bob.log 2>&1
    BEST=$(grep -E "New best so far!|Bob found a new run" -A2 logs/bob.log | grep -Eo "[0-9]{8}_[0-9]{6}" | tail -1)
    echo "[PIPE] BEST=${BEST}" >> logs/bob.log
    /root/venv/bin/python -u bob.py validate --run "${BEST}" --period 30d --passes 2 --notify-interval 10 >> logs/bob.log 2>&1
    /root/venv/bin/python -u bob.py paper --run "${BEST}" --days 2 >> logs/bob.log 2>&1
  }
'

# 6/7/8) Tails
screen -S omnibrain -X screen -t tail-engine bash -lc 'tail -fn 200 logs/engine.log'
screen -S omnibrain -X screen -t tail-govbot  bash -lc 'tail -fn 200 logs/govbot.log'
screen -S omnibrain -X screen -t tail-bob    bash -lc 'tail -fn 200 logs/bob.log'

echo "[OK] screen session 'omnibrain' started. Attach with: screen -r omnibrain"
