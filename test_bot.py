import requests
import re

URL = "https://kariyerkapisi.gov.tr/"

response = requests.get(
    URL,
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=30
)

html = response.text

print("HTTP:", response.status_code)
print("HTML:", len(html))

print("\n--- İLGİLİ SATIRLAR ---")

for line in html.splitlines():
    line_lower = line.lower()

    if any(x in line_lower for x in [
        "api/",
        "api.",
        "ilan",
        "job",
        "announcement",
        "isealim"
    ]):
        print(line.strip()[:1000])
