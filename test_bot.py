import requests
from bs4 import BeautifulSoup

URL = "https://kariyerkapisi.gov.tr/RSS/RssLinkiAl"

response = requests.get(
    URL,
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=30
)

print("HTTP:", response.status_code)
print("UZUNLUK:", len(response.text))

print("\n--- RSS SAYFASI ---")
print(response.text[:5000])
