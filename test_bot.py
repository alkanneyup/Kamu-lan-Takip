import os
import requests

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

response = requests.post(
    url,
    data={
        "chat_id": CHAT_ID,
        "text": "✅ Kamu İlan Takip sistemi test mesajı."
    },
    timeout=30
)

print("TELEGRAM CEVABI:")
print(response.text)

response.raise_for_status()
