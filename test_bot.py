import requests

URL = "https://kariyerkapisi.gov.tr/isealim"

response = requests.get(
    URL,
    headers={
        "User-Agent": "Mozilla/5.0"
    },
    timeout=30
)

print("HTTP:", response.status_code)
print("HTML:", len(response.text))

print("\n--- SAYFA İÇERİĞİ ---")
print(response.text[:15000])
