# -*- coding: utf-8 -*-
import requests

def send_telegram_message(message):
    try:
        with open("TELEGRAM.txt", "r") as f:
            token = f.readline().strip()
            chat_id = f.readline().strip()

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message}
        response = requests.post(url, data=payload)

        if response.status_code != 200:
            print(f"❌ Telegram error: {response.text}")
        else:
            print("✅ Telegram alert sent.")
    except Exception as e:
        print(f"⚠️ Telegram exception: {e}")
