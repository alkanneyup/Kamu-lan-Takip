import logging
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9"
}

def iskur_ilanlarini_getir() -> List[Dict[str, str]]:
    """İŞKUR kamu ilanlarını RSS/API kaynaklarından güvenli bir biçimde çeker."""
    ilanlar: List[Dict[str, str]] = []
    
    iskur_urls = [
        "https://esube.iskur.gov.tr/Rss/Ilanlar.aspx?tur=kamu",
        "https://www.iskur.gov.tr/rss/kamu-ilanlari"
    ]

    for url in iskur_urls:
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code == 200 and len(response.content) > 100:
                try:
                    root = ET.fromstring(response.content)
                    for item in root.findall('./channel/item'):
                        title = item.find('title').text if item.find('title') is not None else ''
                        link = item.find('link').text if item.find('link') is not None else ''
                        
                        if title:
                            ilanlar.append({
                                'title': title.strip(),
                                'link': link.strip() if link else '',
                                'source': 'İŞKUR Kamu'
                            })
                    if ilanlar:
                        break
                except ET.ParseError:
                    logging.debug(f"İŞKUR RSS XML Ayrıştırma hatası ({url})")
        except Exception as e:
            logging.debug(f"İŞKUR RSS Bağlantı hatası ({url}): {e}")

    return ilanlar
