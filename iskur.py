import logging
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict
from urllib.parse import urljoin

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "tr-TR,tr;q=0.9",
}

RSS_URLS = [
    "https://esube.iskur.gov.tr/Rss/Ilanlar.aspx?tur=kamu",
    "https://www.iskur.gov.tr/rss/kamu-ilanlari",
]

def iskur_ilanlarini_getir() -> List[Dict[str, str]]:
    """İŞKUR kamu RSS kaynaklarını sırayla dener; yinelenen kayıtları ayıklar."""
    ilanlar: List[Dict[str, str]] = []
    gorulen = set()

    with requests.Session() as session:
        session.headers.update(HEADERS)
        for url in RSS_URLS:
            try:
                response = session.get(url, timeout=(6, 15), allow_redirects=True)
                if response.status_code != 200 or len(response.content) < 50:
                    logging.warning("[İŞKUR RSS] HTTP %s: %s", response.status_code, url)
                    continue

                try:
                    root = ET.fromstring(response.content)
                except ET.ParseError as exc:
                    logging.warning("[İŞKUR RSS] XML ayrıştırılamadı (%s): %s", url, exc)
                    continue

                items = root.findall(".//item")
                for item in items:
                    title = (item.findtext("title") or "").strip()
                    link = (item.findtext("link") or "").strip()
                    if not title:
                        continue
                    if link:
                        link = urljoin(response.url, link)
                    key = (link or title).split("#")[0].rstrip("/")
                    if key in gorulen:
                        continue
                    gorulen.add(key)
                    ilanlar.append({
                        "title": title,
                        "link": link,
                        "source": "İŞKUR Kamu",
                    })

                if ilanlar:
                    logging.info("[İŞKUR RSS] %s ilan alındı: %s", len(ilanlar), url)
                    break

            except requests.RequestException as exc:
                logging.warning("[İŞKUR RSS] Bağlantı hatası (%s): %s", url, exc)

    return ilanlar
