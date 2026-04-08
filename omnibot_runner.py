#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, time, traceback
from pathlib import Path
try:
    import requests
except Exception as e:
    raise SystemExit("`requests` not installed. Run: pip install requests") from e

# Import your reply logic
from omnibrain_telegram_ai import handle_telegram_message

REAL = json.loads(Path("REAL.json").read_text(encoding="utf-8"))
TOKEN = str(REAL["TELEGRAM_TOKEN"]).strip()
ALLOWED_CHAT = str(REAL.get("TELEGRAM_CHAT_ID","")).strip()

BASE = f"https://api.telegram.org/bot{TOKEN}"

def tg(method, **params):
    # use POST for everything; Telegram accepts it
    r = requests.post(f"{BASE}/{method}", data=params, timeout=60)
    r.raise_for_status()
    return r.json()

def send(chat_id, text):
    try:
        tg("sendMessage", chat_id=str(chat_id), text=text)
    except Exception as e:
        print("[send error]", e, flush=True)

def main():
    print("[OmniBot] starting long-poll…", flush=True)
    if ALLOWED_CHAT:
        send(ALLOWED_CHAT, "OmniBot online ✅")

    offset = 0
    while True:
        try:
            resp = tg("getUpdates", timeout=30, offset=offset+1)
            if not resp.get("ok"):
                time.sleep(1)
                continue
            for upd in resp.get("result", []):
                offset = max(offset, int(upd["update_id"]))
                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                text = (msg.get("text") or "").strip()
                if not text or not chat_id:
                    continue

                # simple auth: only your chat id
                if ALLOWED_CHAT and chat_id != ALLOWED_CHAT:
                    send(chat_id, "Unauthorized chat.")
                    continue

                # a couple of quick commands
                if text.lower() in ("/start","/status"):
                    send(chat_id, "OmniBot is running ✅")
                    continue

                # delegate to your logic
                try:
                    reply = handle_telegram_message(chat_id, text)
                except Exception:
                    traceback.print_exc()
                    reply = "Sorry, something went wrong."
                if reply:
                    send(chat_id, reply)
        except Exception as e:
            print("[poll error]", e, flush=True)
            time.sleep(2)

if __name__ == "__main__":
    main()
