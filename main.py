import io
import os
import re
import sys
import json
import html
import hashlib
import logging
from datetime import datetime, date
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple, Set, Optional, Any

import requests
from bs4 import BeautifulSoup

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    stream=sys.stdout,
    force=True,
)

try:
    from iskur import iskur_ilanlarini_getir
except Exception as exc:
    logging.warning("İŞKUR modülü yüklenemedi: %s", exc)

    def iskur_ilanlarini_getir():
        return []


USER_PROFILE = {
    "egitim": "Önlisans",
    "bolum": "Adalet",
    "puan_turu": "P93",
    "kpss": 80.86227,
    "cinsiyet": "Erkek",
    "yas": 30,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

HARIC = [
    "kararname", "kanun", "yönetmelik", "genelge", "tebliğ", "mahkeme",
    "yargıtay", "danıştay", "ihale", "kamulaştırma", "vergi", "görevden alma",
    "siyasi", "ekonomi haberi", "basın açıklaması", "sınav sonucu",
    "mülakat sonucu", "yerleştirme sonucu", "nihai liste", "asıl ve yedek",
    "tebligat", "dilekçe", "ücret tarifesi", "sözlü sınav duyurusu",
    "giriş sınavı", "yazılı sınav duyurusu", "önceki sayı", "sonraki sayı",
    "ana sayfa", "mevzuat bilgi sistemi", "abonelik", "künye", "iletişim",
    "duyuru arşivi", "haberler", "etkinlik", "toplantı",
]

# Başlıkta açıkça göründüğünde detay çekmeden elenecek kadro/alan ifadeleri
BASLIK_ELENEN = [
    "bilişim personeli", "bilgisayar mühendisi", "yazılım mühendisi",
    "elektrik mühendisi", "elektronik mühendisi", "makine mühendisi",
    "inşaat mühendisi", "harita mühendisi", "jeoloji mühendisi",
    "hemşire", "ebe", "eczacı", "diş tabibi", "tabip", "doktor",
    "fizyoterapist", "diyetisyen", "sağlık teknikeri", "röntgen",
    "öğretim görevlisi", "araştırma görevlisi", "profesör", "doçent",
    "avukat", "mimar", "veteriner", "psikolog", "sosyal çalışmacı",
]

ALIM = [
    "personel alım", "personel alımı", "memur alım", "memur alımı",
    "sözleşmeli personel", "sürekli işçi", "geçici işçi", "işçi alımı",
    "kamu personeli alım", "personel temin", "alım ilanı", "personel istihdam",
    "personel alınacaktır", "personel alacaktır",
]

UNVANLAR = [
    "zabıt katibi", "zabıt kâtibi", "infaz ve koruma memuru",
    "infaz koruma memuru", "icra memuru", "icra katibi", "büro personeli",
    "destek personeli", "veri hazırlama ve kontrol işletmeni", "vhki",
    "koruma ve güvenlik görevlisi", "güvenlik görevlisi", "teknisyen",
    "tekniker", "mühendis", "şoför", "hizmetli", "hemşire", "memur",
    "sözleşmeli bilişim personeli", "çözümleyici", "programcı",
    "uzman personel", "öğretim görevlisi", "araştırma görevlisi",
]

KAYNAKLAR = [
    ("https://kariyerkapisi.gov.tr/RSS", "Kariyer Kapısı"),
    ("https://www.resmigazete.gov.tr/", "Resmî Gazete"),
    ("https://kariyerkapisi.gov.tr/", "Kariyer Kapısı"),
]

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def tr_lower(value: str) -> str:
    table = str.maketrans({
        "İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ",
        "Ü": "ü", "Ö": "ö", "Ç": "ç",
    })
    return (value or "").translate(table).lower()


def temizle(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def md5_id(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def json_yukle(path: str, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as file:
            return json.load(file)
    except Exception:
        return default


def json_kaydet(path: str, data) -> None:
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(temp, path)


def aday_baslik_mi(title: str) -> bool:
    t = tr_lower(title)
    if any(word in t for word in HARIC):
        return False
    return any(word in t for word in ALIM) or (
        "alım ilanı" in t and any(word in t for word in UNVANLAR)
    )


def baslik_profil_uygun_mu(title: str) -> Tuple[bool, str]:
    t = tr_lower(title)
    for bad in BASLIK_ELENEN:
        if bad in t:
            return False, f"Başlıkta profil dışı kadro: {bad}"
    return True, ""


def linkleri_cek(url: str, source: str) -> List[Dict[str, str]]:
    results = []
    try:
        response = SESSION.get(url, timeout=(5, 10), allow_redirects=True)
        if response.status_code != 200:
            logging.warning("[%s] HTTP %s: %s", source, response.status_code, url)
            return results

        content_type = response.headers.get("Content-Type", "").lower()
        if "xml" in content_type or "rss" in response.text[:300].lower():
            try:
                root = ET.fromstring(response.content)
                for item in root.findall(".//item"):
                    title = item.findtext("title", default="").strip()
                    link = item.findtext("link", default="").strip()
                    if title and link and aday_baslik_mi(title):
                        results.append({"title": title, "link": link, "source": source})
                if results:
                    return results
            except Exception:
                pass

        soup = BeautifulSoup(response.text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            title = temizle(anchor.get_text(" ", strip=True))
            href = (anchor.get("href") or "").strip()
            if len(title) < 10 or not aday_baslik_mi(title):
                continue
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            full = urljoin(response.url, href)
            if urlparse(full).scheme in ("http", "https"):
                results.append({"title": title, "link": full, "source": source})
    except Exception as exc:
        logging.warning("[%s] Kaynak okunamadı: %s", source, exc)
    return results


def kaynaklari_topla() -> List[Dict[str, str]]:
    all_items = []
    for url, source in KAYNAKLAR:
        all_items.extend(linkleri_cek(url, source))

    try:
        for item in iskur_ilanlarini_getir() or []:
            if not isinstance(item, dict):
                continue
            title = temizle(item.get("title", ""))
            link = (item.get("link") or "").strip()
            if title and aday_baslik_mi(title):
                all_items.append({
                    "title": title,
                    "link": link,
                    "source": item.get("source", "İŞKUR Kamu"),
                })
    except Exception as exc:
        logging.warning("İŞKUR taraması başarısız: %s", exc)

    unique = {}
    for item in all_items:
        key = (item.get("link") or item.get("title", "")).split("#")[0].rstrip("/")
        if key and key not in unique:
            unique[key] = item
    return list(unique.values())


def pdf_metin_oku(pdf_url: str) -> str:
    if not pdf_url or not PdfReader:
        return ""
    try:
        response = SESSION.get(pdf_url, timeout=(6, 15), allow_redirects=True)
        if response.status_code != 200 or not response.content.startswith(b"%PDF"):
            return ""
        reader = PdfReader(io.BytesIO(response.content))
        pages = [page.extract_text() or "" for page in reader.pages[:12]]
        return temizle(" ".join(pages))[:18000]
    except Exception as exc:
        logging.info("[PDF OKUNAMADI] %s | %s", pdf_url, exc)
        return ""


def json_metinine_cevir(value: Any, depth: int = 0) -> str:
    if depth > 12 or value is None:
        return ""
    if isinstance(value, str):
        value = html.unescape(value)
        if "<" in value and ">" in value:
            return temizle(BeautifulSoup(value, "html.parser").get_text(" ", strip=True))
        return " ".join(value.split())
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return " ".join(json_metinine_cevir(x, depth + 1) for x in value)
    if isinstance(value, dict):
        chunks = []
        for key, val in value.items():
            key_text = str(key).replace("_", " ")
            val_text = json_metinine_cevir(val, depth + 1)
            if val_text:
                chunks.append(f"{key_text}: {val_text}")
        return " ".join(chunks)
    return ""


def detay_oku(url: str, browser_page=None) -> Tuple[str, int, str, str]:
    if not url:
        return "", 0, "Bağlantı yok", "BAGLANTI_YOK"

    parts: List[str] = []
    pdf_links: List[str] = []
    captured_api: List[str] = []
    js_errors: List[str] = []
    final_url = url
    status_tag = "OK"

    try:
        resp = SESSION.get(url, timeout=(6, 12), allow_redirects=True)
        final_url = resp.url
        if resp.status_code == 200 and "pdf" not in resp.headers.get("Content-Type", "").lower():
            raw_html = resp.text or ""
            soup = BeautifulSoup(raw_html, "html.parser")
            for el in soup.find_all(["a", "iframe", "embed", "object", "source"]):
                raw = (el.get("href") or el.get("src") or el.get("data") or "").strip()
                if raw and (".pdf" in raw.lower() or "ilan-metni" in raw.lower()):
                    pdf_links.append(urljoin(final_url, raw))
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            parts.append(temizle(soup.get_text(" ", strip=True)))
            for raw in re.findall(
                r"""(?:https?://[^\s"'<>]+|/[A-Za-z0-9_./-]+\.pdf(?:\?[^\s"'<>]*)?)""",
                raw_html,
                flags=re.I,
            ):
                pdf_links.append(urljoin(final_url, raw.rstrip("),;")))

        text_so_far = temizle(" ".join(parts))
        if len(text_so_far) < 400 and browser_page is not None:
            def on_response(response):
                try:
                    ctype = (response.headers.get("content-type") or "").lower()
                    if response.status == 200 and any(k in ctype for k in ("json", "text/html", "text/plain")):
                        body = response.text()
                        if body and len(body) > 40:
                            if body.lstrip().startswith(("{", "[")):
                                conv = json_metinine_cevir(json.loads(body))
                                if conv and len(conv) > 40:
                                    captured_api.append(conv[:25000])
                            elif "getilanpreviewpublic" in response.url.lower() or "getaltilaninfobyilanidpublic" in response.url.lower():
                                captured_api.append(temizle(body)[:25000])
                except Exception:
                    pass

            def on_pageerror(err):
                js_errors.append(str(err))

            browser_page.on("response", on_response)
            browser_page.on("pageerror", on_pageerror)
            try:
                browser_page.goto(final_url, wait_until="domcontentloaded", timeout=15000)
                try:
                    browser_page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                browser_page.wait_for_timeout(1200)
                b_soup = BeautifulSoup(browser_page.content(), "html.parser")
                for el in b_soup.find_all(["a", "iframe", "embed", "object", "source"]):
                    raw = (el.get("href") or el.get("src") or el.get("data") or "").strip()
                    if raw and (".pdf" in raw.lower() or "ilan-metni" in raw.lower()):
                        pdf_links.append(urljoin(browser_page.url, raw))
                for tag in b_soup(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()
                b_text = temizle(b_soup.get_text(" ", strip=True))
                if b_text:
                    parts.append(b_text)
                final_url = browser_page.url
            except Exception as exc:
                status_tag = "AG_ENGELI"
                logging.info("[TARAYICI UYARI] %s | %s", final_url, exc)
            finally:
                try:
                    browser_page.remove_listener("response", on_response)
                    browser_page.remove_listener("pageerror", on_pageerror)
                except Exception:
                    pass

        valid_pdfs = [
            u for u in dict.fromkeys(pdf_links)
            if ".pdf" in u.lower() or "ilan-metni" in u.lower()
        ][:4]
        pdf_texts = [p for u in valid_pdfs if (p := pdf_metin_oku(u))]
        combined = temizle(" ".join(parts + captured_api + pdf_texts))
        if len(combined) <= 160 and (js_errors or status_tag == "AG_ENGELI"):
            status_tag = "AG_ENGELI"
        logging.info(
            "[DETAY ÖZET] URL=%s | UZUNLUK=%s | API=%s | PDF=%s | DURUM=%s",
            final_url, len(combined), len(captured_api), len(valid_pdfs), status_tag,
        )
        return combined[:30000], len(valid_pdfs), final_url, status_tag

    except Exception as exc:
        logging.warning("[DETAY HATASI] %s | %s", url, exc)
        return temizle(" ".join(parts))[:30000], 0, final_url, "HATA"

def tarih_bul(text: str) -> Tuple[str, Optional[date]]:
    t = tr_lower(text)
    patterns = [
        r"(?:son başvuru tarihi|son başvuru|başvuruların son günü|başvuru bitiş tarihi|başvurular .*? tarihine kadar)"
        r"[^0-9]{0,60}([0-3]?\d[./-][01]?\d[./-](?:20)?\d{2})",
        r"(?:son gün)[^0-9]{0,30}([0-3]?\d[./-][01]?\d[./-](?:20)?\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, t, flags=re.I)
        if match:
            raw = match.group(1).replace("/", ".").replace("-", ".")
            for fmt in ("%d.%m.%Y", "%d.%m.%y"):
                try:
                    parsed = datetime.strptime(raw, fmt).date()
                    return parsed.strftime("%d.%m.%Y"), parsed
                except ValueError:
                    pass
    return "Belirtilmemiş", None


def bilgi_cikar(title: str, detail: str) -> Dict[str, Any]:
    text = tr_lower(title + " " + detail)
    position = next((x for x in UNVANLAR if tr_lower(x) in text), "Belirtilmemiş")

    institution = "Belirtilmemiş"
    for source in (title, detail):
        match = re.search(
            r"([A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü0-9\s&().'-]{2,80}?"
            r"(?:Bakanlığı|Üniversitesi|Belediyesi|Genel Müdürlüğü|Başkanlığı|Müdürlüğü|Kurumu))",
            source,
        )
        if match:
            institution = temizle(match.group(1))
            break

    quota = "Belirtilmemiş"
    qmatch = re.search(
        r"(?:toplam\s*)?(?:\d+\s*)?(?:kişilik\s*)?(?:kontenjan|kadro|personel)\D{0,35}(\d{1,4})\s*(?:kişi|personel|memur|işçi|adet)?",
        text,
    )
    if qmatch:
        quota = qmatch.group(1) + " kişi"

    education = "Belirtilmemiş"
    if any(x in text for x in ["önlisans", "ön lisans", "meslek yüksekokulu", "myo"]):
        education = "Önlisans"
    elif any(x in text for x in ["ortaöğretim", "lise mezunu", "lise düzey"]):
        education = "Ortaöğretim"
    elif "lisans" in text or "fakülte mezunu" in text:
        education = "Lisans"

    score_type = "Belirtilmemiş"
    score_match = re.search(r"\b(p93|p94|p3)\b", text)
    if score_match:
        score_type = score_match.group(1).upper()
    elif "kpss" in text:
        score_type = "KPSS (puan türü belirtilmemiş)"

    min_score = None
    score_patterns = [
        r"(?:p93|p94|p3|kpss)[^0-9]{0,35}(\d{2}(?:[,.]\d+)?)",
        r"(?:en az|asgari|taban puan)[^0-9]{0,25}(\d{2}(?:[,.]\d+)?)",
    ]
    for pattern in score_patterns:
        match = re.search(pattern, text)
        if match:
            try:
                value = float(match.group(1).replace(",", "."))
                if 50 <= value <= 100:
                    min_score = value
                    break
            except ValueError:
                pass

    end_text, end_date = tarih_bul(title + " " + detail)

    return {
        "kurum": institution,
        "pozisyon": position,
        "kontenjan": quota,
        "egitim": education,
        "kpss_turu": score_type,
        "taban_puan": min_score,
        "son_basvuru": end_text,
        "son_dt": end_date,
    }


def uygunluk_degerlendir(
    title: str,
    detail: str,
    info: Dict[str, Any],
    profile: Dict[str, Any],
    today: date,
) -> Tuple[str, List[str]]:
    text = tr_lower(title + " " + detail)
    reasons = []

    age_limits = []
    for pattern in [
        r"(\d{2})\s*yaşını\s*doldurmamış",
        r"en fazla\s*(\d{2})\s*yaş",
        r"(\d{2})\s*yaşından\s*gün\s*almamış",
    ]:
        age_limits.extend(int(x) for x in re.findall(pattern, text))
    if age_limits and int(profile["yas"]) >= min(age_limits):
        return "Uygun Değil", ["Yaş şartı karşılanmıyor"]

    gender = tr_lower(profile["cinsiyet"])
    if gender == "erkek" and re.search(r"yalnızca kadın aday|sadece kadın aday|kadın adaylar başvurabilir", text):
        return "Uygun Değil", ["İlan yalnızca kadın aday kabul ediyor"]
    if gender == "kadın" and re.search(r"yalnızca erkek aday|sadece erkek aday|erkek adaylar başvurabilir", text):
        return "Uygun Değil", ["İlan yalnızca erkek aday kabul ediyor"]

    required_education = info["egitim"]
    if required_education != "Belirtilmemiş" and required_education != profile["egitim"]:
        if required_education == "Lisans" and profile["egitim"] == "Önlisans":
            return "Uygun Değil", ["İlan lisans mezuniyeti istiyor"]
        if required_education == "Ortaöğretim" and profile["egitim"] == "Önlisans":
            reasons.append("İlanın önlisans mezunlarını kabul edip etmediği kontrol edilmeli")

    if "adalet" in text:
        reasons.append("Adalet bölüm şartı metinde geçiyor")
    elif re.search(r"\b3001\b", text):
        reasons.append("3001 nitelik kodu bulundu")
    elif any(
        x in text
        for x in ["herhangi bir önlisans", "önlisans programlarının herhangi biri", "önlisans mezunu olmak"]
    ):
        reasons.append("Genel önlisans şartı bulundu")
    elif any(x in text for x in ["belirli bölüm", "ilgili bölüm", "mezunu olmak"]):
        reasons.append("Bölüm şartı ayrıca doğrulanmalı")
    else:
        reasons.append("Bölüm şartı net olarak çıkarılamadı")

    expected_type = tr_lower(profile["puan_turu"])
    actual_type = tr_lower(info["kpss_turu"])
    if actual_type in ("p93", "p94", "p3") and actual_type != expected_type:
        return "Uygun Değil", [f"İstenen KPSS türü {actual_type.upper()}, profil {expected_type.upper()}"]
    if info["taban_puan"] is not None and float(profile["kpss"]) < info["taban_puan"]:
        return "Uygun Değil", ["KPSS puanı ilan taban puanının altında"]
    if actual_type == expected_type:
        reasons.append(f"{expected_type.upper()} puan türü eşleşiyor")
    elif actual_type == "Belirtilmemiş":
        reasons.append("KPSS puan türü doğrulanamadı")

    if info["son_dt"] and info["son_dt"] < today:
        return "Başvuru Süresi Geçmiş", ["Son başvuru tarihi geçmiş"]

    strong_section = (
        "adalet" in text
        or bool(re.search(r"\b3001\b", text))
        or "herhangi bir önlisans" in text
        or "önlisans mezunu olmak" in text
    )
    education_ok = required_education == "Önlisans" or (
        required_education == "Belirtilmemiş" and strong_section
    )
    score_ok = actual_type == expected_type or (
        actual_type == "Belirtilmemiş" and "kpss şartı yoktur" in text
    )

    if education_ok and strong_section and score_ok:
        return "Uygun", reasons
    return "Kontrol Gerekli", reasons


def ilan_degerlendir(
    item: Dict[str, str],
    detail: str,
    status_tag: str,
    today: date,
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    title = temizle(item.get("title", ""))
    link = item.get("link", "")
    source = item.get("source", "Kamu")
    combined = tr_lower(title + " " + detail)

    if any(word in combined for word in HARIC):
        return {"durum": "Elendi", "sebep": "Hariç tutulan içerik"}

    if not aday_baslik_mi(title):
        return {"durum": "Elendi", "sebep": "Başlık gerçek personel alım ilanı değil"}

    title_ok, title_reason = baslik_profil_uygun_mu(title)
    if not title_ok:
        return {"durum": "Elendi", "sebep": title_reason}

    if len(detail.strip()) < 100:
        reason = "Ağ/erişim engeli nedeniyle detay alınamadı" if status_tag == "AG_ENGELI" else "İlan detayına erişilemedi"
        return {"durum": "Kontrol Gerekli", "sebep": reason}

    info = bilgi_cikar(title, detail)
    status, reasons = uygunluk_degerlendir(title, detail, info, profile, today)

    identity = md5_id("|".join([
        tr_lower(title),
        (link or "").split("?")[0].lower(),
        tr_lower(info["kurum"]),
        tr_lower(info["pozisyon"]),
    ]))

    return {
        "durum": status,
        "sebep": "; ".join(reasons) if reasons else status,
        "kimlik": identity,
        "baslik": title,
        "kaynak": source,
        "link": link,
        **{k: v for k, v in info.items() if k != "son_dt"},
    }


def telegram_gonder(messages: List[str]) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids = [x.strip() for x in os.getenv("TELEGRAM_CHAT_ID", "").split(",") if x.strip()]
    if not token or not chat_ids:
        logging.error("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik.")
        return False

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    all_ok = True
    for message in messages:
        for chat_id in chat_ids:
            try:
                response = requests.post(
                    endpoint,
                    json={
                        "chat_id": chat_id,
                        "text": message[:3900],
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=20,
                )
                if response.status_code != 200:
                    logging.error("Telegram gönderim hatası: %s", response.text[:500])
                    all_ok = False
            except Exception as exc:
                logging.error("Telegram bağlantı hatası: %s", exc)
                all_ok = False
    return all_ok


def telegram_mesaji(result: Dict[str, Any]) -> str:
    safe = lambda value: html.escape(str(value or "Belirtilmemiş"))
    link = result.get("link", "")
    link_html = (
        f'<a href="{html.escape(link, quote=True)}">Resmî ilanı aç</a>'
        if link.startswith(("https://", "http://")) else "Bağlantı bulunamadı"
    )
    return (
        "<b>🏛️ PROFİLİNİZE UYGUN KAMU PERSONEL ALIMI</b>\n\n"
        f"<b>Kurum:</b> {safe(result.get('kurum'))}\n"
        f"<b>İlan:</b> {safe(result.get('baslik'))}\n"
        f"<b>Pozisyon:</b> {safe(result.get('pozisyon'))}\n"
        f"<b>Kontenjan:</b> {safe(result.get('kontenjan'))}\n"
        f"<b>Eğitim:</b> {safe(result.get('egitim'))}\n"
        f"<b>KPSS:</b> {safe(result.get('kpss_turu'))}\n"
        f"<b>Son başvuru:</b> {safe(result.get('son_basvuru'))}\n\n"
        f"<b>Profil:</b> 2026 {safe(USER_PROFILE['puan_turu'])} - {USER_PROFILE['kpss']}\n"
        f"<b>Kaynak:</b> {safe(result.get('kaynak'))}\n"
        f"🔗 {link_html}"
    )


def main() -> None:
    today = datetime.now().date()
    logging.info("KAMU İLAN TAKİP V2 BAŞLADI | %s", today.isoformat())

    sent_ids: Set[str] = set(json_yukle("sent_ids.json", []))
    items = kaynaklari_topla()
    logging.info("Toplanan tekil ilan adayı: %s", len(items))

    browser = None
    playwright_manager = None
    page = None
    if sync_playwright:
        try:
            playwright_manager = sync_playwright().start()
            browser = playwright_manager.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="tr-TR",
                viewport={"width": 1440, "height": 1000},
                ignore_https_errors=True,
            )
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            page = context.new_page()
            logging.info("JavaScript destekli tarayıcı hazır.")
        except Exception as exc:
            logging.warning("Tarayıcı başlatılamadı; requests ile devam edilecek: %s", exc)

    new_sent = set(sent_ids)
    pending = []
    messages = []
    counts = {"Uygun": 0, "Kontrol Gerekli": 0, "Elendi": 0, "Başvuru Süresi Geçmiş": 0}
    processed = set()

    try:
        for index, item in enumerate(items, start=1):
            title = item.get("title", "")
            link = item.get("link", "")
            logging.info("[%s/%s] İnceleniyor: %s", index, len(items), title[:150])

            title_ok, title_reason = baslik_profil_uygun_mu(title)
            if not title_ok:
                counts["Elendi"] += 1
                logging.info("[ELENDİ - BAŞLIK] %s | %s", title, title_reason)
                continue

            detail, pdf_count, final_url, status_tag = (
                detay_oku(link, browser_page=page) if link else ("", 0, "", "BAGLANTI_YOK")
            )
            result = ilan_degerlendir(item, detail, status_tag, today, USER_PROFILE)
            status = result["durum"]
            counts[status] = counts.get(status, 0) + 1

            if status in ("Elendi", "Başvuru Süresi Geçmiş"):
                continue

            if status == "Kontrol Gerekli":
                pending.append({
                    "tarih": today.isoformat(),
                    "baslik": title,
                    "link": link,
                    "kaynak": item.get("source", ""),
                    "sebep": result.get("sebep", ""),
                    "detay_uzunlugu": len(detail),
                    "pdf_sayisi": pdf_count,
                    "son_url": final_url,
                })
                logging.info("[KONTROL GEREKLİ] %s | %s", title, result.get("sebep"))
                continue

            identity = result["kimlik"]
            if identity in sent_ids or identity in processed:
                continue
            processed.add(identity)
            messages.append(telegram_mesaji(result))
            new_sent.add(identity)
            logging.info("[UYGUN] %s", title)

    finally:
        if browser:
            browser.close()
        if playwright_manager:
            playwright_manager.stop()

    json_kaydet("kontrol_bekleyen.json", pending)
    logging.info("Özet: %s", counts)
    logging.info("Kontrol bekleyen ilan: %s", len(pending))

    if messages:
        if telegram_gonder(messages):
            json_kaydet("sent_ids.json", sorted(new_sent))
            logging.info("%s uygun ilan Telegram'a gönderildi.", len(messages))
        else:
            logging.error("Telegram gönderimi tamamlanamadı; gönderim kayıtları güncellenmedi.")
    else:
        logging.info("Yeni ve doğrulanmış uygun ilan bulunamadı.")


if __name__ == "__main__":
    main()
