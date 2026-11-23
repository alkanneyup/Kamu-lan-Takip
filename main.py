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
except Exception:
    def iskur_ilanlarini_getir() -> List[Dict[str, str]]:
        return []

KPSS_PUANI = 80.86227

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}

HARIC_IFADELER = [
    "haber", "sınav sonucu", "sonuçları", "kura", "mülakat",
    "nihai liste", "asıl ve yedek", "tebligat", "dilekçe"
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
        except Exception:
            return set()
    return set()

def save_sent_ids(sent_ids: Set[str]) -> None:
    with open("sent_ids.json", "w", encoding="utf-8") as f:
        json.dump(list(sent_ids), f, ensure_ascii=False, indent=2)

def telegram_gonder(items: List[str]) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_ids = [c.strip() for c in (os.getenv("TELEGRAM_CHAT_ID") or "").split(",") if c.strip()]
    if not token or not chat_ids:
        logging.error("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik.")
        return False

    metin = "📢 <b>UYGUN BAŞVURU İLANLARI</b>\n\n" + "\n\n".join(items)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for cid in chat_ids:
        r = requests.post(
            url,
            json={"chat_id": cid, "text": metin[:4000], "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10
        )
        if r.status_code != 200:
            logging.error(f"Telegram hatası ({cid}): {r.text}")
            ok = False
    return ok

def _linkleri_topla(url: str, kaynak: str, session: Optional[requests.Session] = None) -> List[Dict[str, str]]:
    sonuc: List[Dict[str, str]] = []
    seen: Set[str] = set()
    client = session if session else requests
    r = client.get(url, headers=None if session else HEADERS, timeout=(4, 7), allow_redirects=True)
    if r.status_code != 200:
        logging.warning(f"[{kaynak}] HTTP {r.status_code}")
        return sonuc
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        baslik = " ".join(a.get_text(" ", strip=True).split())
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")) or len(baslik) < 8:
            continue
        if any(h in tr_lower(baslik) for h in HARIC_IFADELER):
            continue
        full_url = urljoin(r.url, href)
        if full_url not in seen:
            seen.add(full_url)
            sonuc.append({"title": baslik, "link": full_url, "source": kaynak})
    return sonuc

def kaynaklari_topla() -> List[Dict[str, str]]:
    tum: List[Dict[str, str]] = []

    try:
        tum.extend(_linkleri_topla("https://www.resmigazete.gov.tr/", "Resmî Gazete"))
    except Exception as e:
        logging.error(f"Resmî Gazete hatası: {e}")

    try:
        sbb = requests.Session()
        sbb.headers.update({
            **HEADERS,
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        })
        tum.extend(_linkleri_topla("https://kamuilan.sbb.gov.tr/", "SBB Kamu İlan", session=sbb))
        sbb.close()
    except Exception as e:
        logging.error(f"SBB hatası: {e}")

    try:
        r = requests.get("https://kariyerkapisi.gov.tr/RSS", headers=HEADERS, timeout=(4, 7))
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            for item in root.findall("./channel/item"):
                t = (item.find("title").text or "").strip() if item.find("title") is not None else ""
                l = (item.find("link").text or "").strip() if item.find("link") is not None else ""
                if t and l and not any(h in tr_lower(t) for h in HARIC_IFADELER):
                    tum.append({"title": t, "link": l, "source": "Kariyer Kapısı"})
        tum.extend(_linkleri_topla("https://kariyerkapisi.gov.tr/", "Kariyer Kapısı"))
    except Exception as e:
        logging.error(f"Kariyer Kapısı hatası: {e}")

    try:
        tum.extend(iskur_ilanlarini_getir() or [])
    except Exception as e:
        logging.error(f"İŞKUR hatası: {e}")

    return tum

def _json_metin(obj: Any) -> str:
    if isinstance(obj, str):
        return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", obj)).split())
    if isinstance(obj, dict):
        return " ".join(_json_metin(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(_json_metin(v) for v in obj)
    return ""

def detay_oku(url: str) -> str:
    parcalar: List[str] = []
    try:
        m = re.search(r"i=([a-f0-9-]+)", url, re.IGNORECASE)
        if m and "kariyerkapisi" in url:
            guid = m.group(1)
            for api in [
                f"https://kariyerkapisi.gov.tr/RSS/IlanDetayGetir?id={guid}",
                f"https://kariyerkapisi.gov.tr/IlanDetay/Getir?id={guid}"
            ]:
                try:
                    ar = requests.get(api, headers=HEADERS, timeout=(3, 5))
                    if ar.status_code == 200:
                        try:
                            parcalar.append(_json_metin(ar.json()))
                        except Exception:
                            parcalar.append(" ".join(html.unescape(re.sub(r"<[^>]+>", " ", ar.text)).split()))
                except Exception:
                    continue

        r = requests.get(url, headers=HEADERS, timeout=(3, 5), allow_redirects=True)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            parcalar.append(" ".join(soup.get_text(" ", strip=True).split()))
    except Exception:
        pass
    return " ".join(p for p in parcalar if p)[:15000]

def sart_uygun_mu(baslik: str, detay: str, bugun: date) -> Tuple[bool, str, str]:
    metin = tr_lower(baslik + " " + detay)
    if any(h in metin for h in HARIC_IFADELER):
        return False, "", ""

    tarih_bul = re.findall(
        r"(?:son başvuru|son gün|başvuru bitiş|tarihine kadar)\D*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})",
        detay,
        re.IGNORECASE
    )
    deadline_notu = "Tarih detayda"
    if tarih_bul:
        for fmt in ("%d.%m.%Y", "%d.%m.%y"):
            try:
                dt = datetime.strptime(tarih_bul[0].replace("/", ".").replace("-", "."), fmt).date()
                if dt < bugun:
                    return False, "", ""
                deadline_notu = f"Son: {dt.strftime('%d.%m.%Y')}"
                break
            except ValueError:
                continue

    profil = ""
    if "hemşire" in metin and ("lisans" in metin or "hemşirelik" in metin):
        profil = "Hemşirelik (Lisans)"
    elif any(k in metin for k in [
        "adalet", "zabıt katibi", "katip", "mübaşir", "icra katibi",
        "infaz koruma", "3001", "önlisans", "ön lisans", "p93", "büro personeli"
    ]):
        profil = "Adalet / Önlisans"

    if not profil:
        return False, "", ""

    puanlar = re.findall(r"(?:kpss|p93|p3|p94|taban puan)\D*([5-9][0-9](?:[\.,][0-9]+)?)", metin)
    for p in puanlar:
        try:
            taban = float(p.replace(",", "."))
            if 50.0 <= taban <= 100.0 and KPSS_PUANI < taban:
                return False, "", ""
        except ValueError:
            continue

    return True, profil, deadline_notu

def main() -> None:
    bugun = datetime.now().date()
    logging.info(f"ŞART TARAMASI BAŞLADI ({bugun})")

    sent_ids = load_sent_ids()
    new_ids = set(sent_ids)
    adaylar = kaynaklari_topla()

    tekil: List[Dict[str, str]] = []
    gorulen: Set[str] = set()
    for a in adaylar:
        uid = generate_id(a.get("link") or a.get("title", ""))
        if uid not in gorulen:
            gorulen.add(uid)
            tekil.append(a)

    logging.info(f"İncelenecek tekil bağlantı sayısı: {len(tekil)}")
    uygunlar: List[str] = []

    for ilan in tekil:
        baslik = ilan.get("title", "")
        link = ilan.get("link", "")
        kaynak = ilan.get("source", "Kaynak")
        uid = generate_id(link or baslik)
        if uid in sent_ids:
            continue

        detay = detay_oku(link) if link else ""
        ok, profil, deadline = sart_uygun_mu(baslik, detay, bugun)
        if ok:
            logging.info(f"[{kaynak}] [{profil}] -> {baslik} ({deadline})")
            uygunlar.append(
                f"• <b>[{html.escape(kaynak)}]</b> [{html.escape(profil)}]\n"
                f"  <a href='{html.escape(link, quote=True)}'>{html.escape(baslik)}</a>\n"
                f"  📌 <i>{html.escape(deadline)}</i>"
            )
            new_ids.add(uid)

    if uygunlar:
        if telegram_gonder(uygunlar):
            save_sent_ids(new_ids)
            logging.info(f"{len(uygunlar)} uygun ilan gönderildi.")
    else:
        logging.info("Şartlara uyan aktif ilan bulunamadı.")

if __name__ == "__main__":
    main()
