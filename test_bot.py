import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

URL = "https://kariyerkapisi.gov.tr/"

response = requests.get(
    URL,
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=30
)

print("HTTP:", response.status_code)

soup = BeautifulSoup(response.text, "html.parser")

print("\n--- KARIYER KAPISI BAĞLANTILARI ---")

for link in soup.find_all("a", href=True):
    href = urljoin(URL, link["href"])
    text = link.get_text(" ", strip=True)

    if "isealim" in href.lower() or "ilan" in href.lower():
        print("YAZI:", text)
        print("ADRES:", href)
        print("---")
