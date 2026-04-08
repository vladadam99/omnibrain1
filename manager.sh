#!/usr/bin/env bash
set -euo pipefail

BOT_NAME="omnibrain3"
PROJECT_DIR="/root/omnibrain3"
BOT_SCRIPT="auto_trade_futures.py"
LOG_FILE="$PROJECT_DIR/bot.log"
VENV_ACTIVATE="$PROJECT_DIR/venv/bin/activate"

start_bot() {
  echo "[OMNIBRAIN3] Starting new session..."
  cd "$PROJECT_DIR"
  # pre-create the log so tail never fails
  touch "$LOG_FILE"
  screen -dmS "$BOT_NAME" bash -lc "source \"$VENV_ACTIVATE\" && python \"$BOT_SCRIPT\" 2>&1 | tee -a \"$LOG_FILE\""
  echo "[OMNIBRAIN3] Bot started in screen session '$BOT_NAME'"
}

stop_bot() {
  echo "[OMNIBRAIN3] Stopping session..."
  screen -S "$BOT_NAME" -X quit || true
  echo "[OMNIBRAIN3] Session '$BOT_NAME' killed"
}

wipe_sessions () {
  echo "[OMNIBRAIN3] Killing ALL omnibrain3 sessions..."
  screen -ls | grep omnibrain2 | awk '{print $1}' | xargs -r -n1 -I{} screen -S {} -X quit
  echo "[OMNIBRAIN3] Done. Active sessions now:"
  screen -ls || true
}

show_logs() {
  if screen -list | grep -q "$BOT_NAME"; then
    screen -r "$BOT_NAME"
  else
    echo "[OMNIBRAIN3] No active '$BOT_NAME' session."
  fi
}

show_sessions() { echo "[OMNIBRAIN3] Listing all screen sessions:"; screen -ls; }
restart_bot() { stop_bot; sleep 1; start_bot; }

menu() {
  clear
  cat <<MENU
====================================
        OMNIBRAIN 3 MANAGER
====================================
1. Start bot
2. Restart bot
3. Stop bot
4. Show bot logs (screen -r)
5. Show all screen sessions
6) Kill ALL omnibrain3 sessions
7. Exit
------------------------------------
MENU
  read -rp "Choose an option: " choice
  case "$choice" in
    1) start_bot ;;
    2) restart_bot ;;
    3) stop_bot ;;
    4) show_logs ;;
    5) show_sessions ;;
    6) wipe_sessions ;;
    7) echo "Bye"; exit 0 ;;
    *) echo "Invalid choice"; sleep 1 ;;
  esac
}

# CLI mode
if [[ "${1:-}" != "" ]]; then
  case "$1" in
    start) start_bot ;;
    stop) stop_bot ;;
    restart) restart_bot ;;
    logs) show_logs ;;
    sessions) show_sessions ;;
    wipe) wipe_dead ;;
    *) echo "Usage: $0 {start|stop|restart|logs|sessions|wipe}"; exit 1 ;;
  esac
  exit 0
fi

# Interactive menu
while true; do
  menu
  read -rp "Press Enter to return to menu..." _
done
