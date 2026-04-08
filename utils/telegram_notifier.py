# -*- coding: utf-8 -*-
# telegram_notifier.py

import requests

TELEGRAM_TOKEN = "7730563721:AAFYOzMvG_lNRxZRkelyRXxatiePGTN0_5w"
TELEGRAM_CHAT_ID = "1666571558"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"[TELEGRAM ERROR] {response.text}")
    except Exception as e:
        print(f"[TELEGRAM EXCEPTION] {e}")
