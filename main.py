import os
import re
import sys
import json
import html
import hashlib
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, date
from urllib.parse import urljoin
from typing import List, Dict, Tuple, Set, Optional, Any
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    stream=sys.stdout,
    force=True
)

try:
    from iskur import iskur_ilanlarini_getir
except Exception as import_err:
    logging.error(f"iskur.py yüklenirken hata oluştu: {import_err}")
    def iskur_ilanlarini_getir() -> List[Dict[str, str]]:
        return []

USER_PROFILE = {
    "kpss": 80.86227,
    "yas": 29
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}

HABER_VE_KALABALIK_IFADELERI = [
    "haber", "duyuru", "duyurusu", "maaşlar ne kadar", "taban puanlar",
    "bu hafta", "ilan yayımlandı", "şartları açıklandı",
    "kontenjanlar ve başvuru şartları", "bölüm şartı yok",
    "sınav yapılmayacak", "mühendis ve tekniker", "hizmetli, şoför",
    "kura", "mülakat", "sınav sonucu", "sonuçları", "sonucu",
    "tebligat", "takvim", "yerleştirme sonuç", "nihai liste",
    "asıl ve yedek", "komisyon", "dilekçe", "ücret tarifesi", "mevzuat"
]

BASVURU_ILANI_IFADELERI = [
    "alım ilanı", "personel alım", "memur alım", "sözleşmeli alım",
    "alımı", "alacak", "alacaktır", "temini", "başvuru ilanı"
]

def tr_lower(metin: str) -> str:
    if not metin:
        return ""
    donusum = {"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"}
    for eski, yeni in donusum.items():
        metin = metin.replace(eski, yeni)
    return metin.lower()

def generate_id(metin: str) -> str:
    return hashlib.md5(metin.encode("utf-8")).hexdigest()

def load_sent_ids() -> Set[str]:
    if os.path.exists("sent_ids.json"):
        try:
            with open("sent_ids.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception as e:
            logging.error(f"sent_ids.json okuma hatası: {e}")
            return set()
    return set()

def save_sent_ids(sent_ids: Set[str]) -> None:
    try:
        with open("sent_ids.json", "w", encoding="utf-8") as f:
            json.dump(list(sent_ids), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"sent_ids.json kaydetme hatası: {e}")

def send_telegram_messages(green_items: List[str]) -> bool:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    raw_chat_ids = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not raw_chat_ids:
        logging.error("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID bulunamadı!")
        return False

    chat_ids = [cid.strip() for cid in raw_chat_ids.split(",") if cid.strip()]
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    messages: List[str] = []
    current_msg = "📢 <b>YENİ VE AKTİF BAŞVURU İLANLARI</b>\n\n"

    if green_items:
        current_msg += "🟢 <b>SİZE UYGUN AKTİF İLANLAR:</b>\n"
        for item in green_items:
            if len(current_msg) + len(item) + 4 > 3500:
                messages.append(current_msg)
                current_msg = "🟢 <b>SİZE UYGUN AKTİF İLANLAR (Devam):</b>\n"
            current_msg += item + "\n\n"

    if current_msg.strip():
        messages.append(current_msg)

    all_success = True
    for chat_id in chat_ids:
        for msg in messages:
            payload = {
                "chat_id": chat_id,
                "text": msg.strip(),
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            try:
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code != 200:
                    logging.error(f"Telegram API Hatası ({chat_id}): {response.status_code} - {response.text}")
                    all_success = False
            except Exception as e:
                logging.error(f"Telegram mesajı gönderilirken istisna oluştu ({chat_id}): {e}")
                all_success = False

    return all_success

def resmi_gazete_getir() -> List[Dict[str, str]]:
    ilanlar: List[Dict[str, str]] = []
    base_url = "https://www.resmigazete.gov.tr/"
    seen: Set[str] = set()
    try:
        res = requests.get(base_url, headers=HEADERS, timeout=(5, 10), allow_redirects=True)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                href = (a_tag.get("href") or "").strip()
                title = " ".join(a_tag.get_text(" ", strip=True).split())
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                if len(title) < 10 or len(title) > 200:
                    continue
                title_tr = tr_lower(title)
                if any(k in title_tr for k in HABER_VE_KALABALIK_IFADELERI):
                    continue
                if any(k in title_tr for k in BASVURU_ILANI_IFADELERI):
                    full_link = urljoin(res.url, href)
                    if full_link not in seen:
                        seen.add(full_link)
                        ilanlar.append({"title": title, "link": full_link, "source": "Resmî Gazete"})
    except Exception as e:
        logging.error(f"Resmî Gazete hatası: {e}")
    return ilanlar

def _sbb_oturum_olustur() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    })
    return session

def sbb_kamu_ilan_getir() -> List[Dict[str, str]]:
    ilanlar: List[Dict[str, str]] = []
    base_url = "https://kamuilan.sbb.gov.tr/"
    aday_yollar = [
        base_url,
        urljoin(base_url, "ilanlar"),
        urljoin(base_url, "tum-ilanlar"),
    ]
    seen: Set[str] = set()
    session = _sbb_oturum_olustur()

    try:
        ilk_res = session.get(base_url, timeout=(6, 12), allow_redirects=True)
        if ilk_res.status_code == 403:
            logging.warning(
                "SBB Kamu İlan HTTP 403 döndü (WAF/IP/TLS veya tarayıcı doğrulaması engelliyor)."
            )
            return ilanlar

        session.headers.update({
            "Referer": ilk_res.url or base_url,
            "Sec-Fetch-Site": "same-origin",
        })

        for hedef_url in aday_yollar:
            try:
                res = (
                    ilk_res
                    if hedef_url == base_url
                    else session.get(hedef_url, timeout=(6, 12), allow_redirects=True)
                )
                if res.status_code != 20
