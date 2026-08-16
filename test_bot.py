import requests

URL = "https://kariyerkapisi.gov.tr/"

response = requests.get(
    URL,
    headers={
        "User-Agent": "Mozilla/5.0"
    },
    timeout=30
)

print("HTTP:", response.status_code)
print("UZUNLUK:", len(response.text))

print("\n--- SAYFA BAŞLANGICI ---")
print(response.text[:5000])
print("\n--- SAYFA SONU ---")
