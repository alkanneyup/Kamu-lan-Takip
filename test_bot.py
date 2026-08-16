import requests
import re
from urllib.parse import urljoin

BASE_URL = "https://kariyerkapisi.gov.tr"
URL = BASE_URL + "/isealim"

response = requests.get(
    URL,
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=30
)

html = response.text

print("HTTP:", response.status_code)
print("HTML:", len(html))

# Sayfadaki bütün bağlantıları bul
links = re.findall(r'href=["\']([^"\']+)["\']', html, re.I)

print("\n===== İLGİLİ BAĞLANTILAR =====")

for link in links:
    full_url = urljoin(BASE_URL, link)

    if any(x in full_url.lower() for x in [
        "ilan",
        "isealim",
        "basvuru",
        "api"
    ]):
        print(full_url)

# Sayfadaki script dosyalarını bul
scripts = re.findall(
    r'<script[^>]+src=["\']([^"\']+)["\']',
    html,
    re.I
)

print("\n===== JAVASCRIPT DOSYALARI =====")

for script in scripts:
    print(urljoin(BASE_URL, script))

# İlgili endpoint ifadelerini bul
print("\n===== ENDPOINT İPUÇLARI =====")

patterns = [
    r'["\']([^"\']*/api/[^"\']*)["\']',
    r'["\']([^"\']*ilan[^"\']*)["\']',
    r'["\']([^"\']*basvuru[^"\']*)["\']',
    r'["\']([^"\']*isealim[^"\']*)["\']'
]

found = set()

for pattern in patterns:
    for match in re.findall(pattern, html, re.I):
        found.add(match)

for item in sorted(found):
    print(item)
