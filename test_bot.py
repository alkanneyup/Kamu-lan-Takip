import requests
import re

BASE = "https://kariyerkapisi.gov.tr"
URL = BASE + "/RSS/RssLinkiAl"

response = requests.get(
    URL,
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=30
)

html = response.text

print("HTTP:", response.status_code)

scripts = re.findall(
    r'<script[^>]+src=["\']([^"\']+)["\']',
    html,
    re.I
)

print("\n===== SCRIPT DOSYALARI =====")

for script in scripts:
    print(script)

print("\n===== RSS JAVASCRIPT İÇERİĞİ =====")

for script in scripts:
    if "RSS" in script or "rss" in script.lower():
        js_url = script if script.startswith("http") else BASE + script

        js = requests.get(
            js_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30
        ).text

        print("JS:", js_url)
        print(js[:10000])
