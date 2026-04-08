
# Lightweight control bridge that lets you /list_runs and /use_run <id> from Telegram
# Reads REAL.json with TELEGRAM_TOKEN and TELEGRAM_CHAT_ID
import os, json, time, glob, requests, traceback

RUNS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "bob_runs"))
ACTIVE_FILE = os.path.join(os.path.dirname(__file__), "agents", "ACTIVE_RUN.txt")

def load_creds():
    with open("REAL.json", "r", encoding="utf-8") as f: c=json.load(f)
    return c.get("TELEGRAM_TOKEN"), str(c.get("TELEGRAM_CHAT_ID"))

def send(token, chat, text):
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text}, timeout=10)
    except Exception: pass

def list_runs():
    if not os.path.isdir(RUNS_DIR): return []
    items = []
    for d in sorted(os.listdir(RUNS_DIR), reverse=True)[:20]:
        if os.path.isdir(os.path.join(RUNS_DIR, d)): items.append(d)
    return items

def activate(run_id):
    os.makedirs(os.path.dirname(ACTIVE_FILE), exist_ok=True)
    with open(ACTIVE_FILE, "w", encoding="utf-8") as f: f.write(run_id)

def poll():
    tok, chat = load_creds()
    last_update=None
    send(tok, chat, "🧭 Control bridge ready.\nCommands:\n/list_runs\n/use_run <id>\n/help")
    while True:
        try:
            resp = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates",
                                params={"timeout": 20, "offset": (last_update+1) if last_update else None}, timeout=30).json()
            if not resp.get("ok"): time.sleep(2); continue
            for up in resp["result"]:
                last_update = up["update_id"]
                msg = up.get("message", {}) or {}
                if str(msg.get("chat",{}).get("id"))!=str(chat): continue
                txt = (msg.get("text") or "").strip()
                if not txt: continue
                cmd, *rest = txt.split()
                if cmd == "/help" or cmd == "/menu":
                    send(tok, chat, "Commands:\n/list_runs\n/use_run <id>\n/help")
                elif cmd == "/list_runs":
                    runs = list_runs()
                    send(tok, chat, "Recent runs:\n" + "\n".join(runs) if runs else "No runs yet.")
                elif cmd == "/use_run":
                    rid = rest[0] if rest else ""
                    if not rid: send(tok, chat, "Usage: /use_run <run_id>"); continue
                    activate(rid); send(tok, chat, f"✅ Activated {rid}")
                
elif cmd == "/status":
    try:
        rid = ""
        if os.path.isfile(ACTIVE_FILE):
            with open(ACTIVE_FILE, "r", encoding="utf-8") as _f: rid = _f.read().strip()
        send(tok, chat, f"Status: OK\nActive run: {rid or '(none)'}")
    except Exception as e:
        send(tok, chat, f"Status unavailable: {e}")
elif cmd == "/config":
    try:
        from agents.apex_config import get_config
        cfg = get_config(None) or {}
        send(tok, chat, "Config snippet:\n" + json.dumps(cfg, indent=2, ensure_ascii=False)[:1800])
    except Exception as e:
        send(tok, chat, f"Config unavailable: {e}")
elif cmd == "/positions":
    # Placeholder: integrate with your backend or CSV state as needed
    send(tok, chat, "Positions: (hook into your live state store)")
                else:
                    send(tok, chat, "Unknown. Try /help")
        except Exception as e:
            traceback.print_exc()
            time.sleep(3)

if __name__ == "__main__":
    poll()
