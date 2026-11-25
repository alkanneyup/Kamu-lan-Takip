import os
import re
import sys
import json
import html
import hashlib
import logging
import requests
import io
import time
from datetime import datetime, date
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple, Set, Optional, Any

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

# Kullanıcı profili: KPSS puanı 2026 P93 puanıdır.
USER_PROFILE = {
    "egitim": "Önlisans",
    "bolum": "Adalet",
    "puan_turu": "P93",
    "kpss": 80.86227,
    "cinsiyet": "Erkek",
    "yas": 29,
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
    table = str.maketrans({"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ",
                           "Ü": "ü", "Ö": "ö", "Ç": "ç"})
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


def linkleri_cek(url: str, source: str) -> List[Dict[str, str]]:
    results = []
    try:
        response = SESSION.get(url, timeout=(5, 12), allow_redirects=True)
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
        response = SESSION.get(pdf_url, timeout=(6, 20), allow_redirects=True)
        if response.status_code != 200 or not response.content.startswith(b"%PDF"):
            return ""
        reader = PdfReader(io.BytesIO(response.content))
        pages = []
        for page in reader.pages[:12]:
            pages.append(page.extract_text() or "")
        return temizle(" ".join(pages))[:18000]
    except Exception as exc:
        logging.info("[PDF OKUNAMADI] %s | %s", pdf_url, exc)
        return ""


def json_metinine_cevir(value: Any, depth: int = 0): 
-> str:
    """API JSON yanıtlarındaki ilan alanlarını okunabilir metne dönüştürür."""
    if depth > 12 or value is None:
        return ""
    if isinstance(value, str):
        value = html.unescape(value)
        # HTML taşıyan API alanlarını düz metne çevir.
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


def detay_oku(url: str, browser_page=None) -> Tuple[str, int, str]:
    if not url:
        return "", 0, "Bağlantı yok"

    parts: List[str] = []
    pdf_links: List[str] = []
    final_url = url
    browser_diagnostics: List[Dict[str, Any]] = []

    try:
        # İlk olarak hafif HTTP isteği: PDF ve sunucu tarafında render edilen sayfaları yakalar.
        response = SESSION.get(url, timeout=(7, 18), allow_redirects=True)
        final_url = response.url
        ctype = response.headers.get("Content-Type", "").lower()
        if response.status_code == 200 and "pdf" not in ctype:
            soup = BeautifulSoup(response.text, "html.parser")

            for element in soup.find_all(["a", "iframe", "embed", "object", "source"]):
                raw = element.get("href") or element.get("src") or element.get("data") or ""
                if raw.strip():
                    full = urljoin(final_url, raw.strip())
                    if ".pdf" in full.lower() or "ilan-metni" in full.lower():
                        pdf_links.append(full)

            # Sayfa içindeki başlangıç JSON'u ve ilanla ilgili metin alanları.
            for script in soup.find_all("script"):
                script_text = script.string or script.get_text(" ", strip=True)
                if script_text and any(k in tr_lower(script_text) for k in
                                       ["personel", "ilan", "basvuru", "başvuru", "kadro"]):
                    parts.append(temizle(script_text[:50000]))

            for tag in soup(["style", "nav", "header", "footer"]):
                tag.decompose()
            parts.append(temizle(soup.get_text(" ", strip=True)))

            for raw in re.findall(
                r"""(?:https?://[^\s"'<>]+|/[A-Za-z0-9_./-]+\.pdf(?:\?[^\s"'<>]*)?)""",
                response.text, flags=re.I
            ):
                full = urljoin(final_url, raw.rstrip("),;"))
                if ".pdf" in full.lower():
                    pdf_links.append(full)
        elif response.status_code != 200:
            logging.warning("[DETAY HTTP %s] %s", response.status_code, url)

        text = temizle(" ".join(parts))

        # Kariyer Kapısı SPA: sadece görünen HTML'i değil, sayfanın çağırdığı API yanıtlarını da izle.
        if len(text) < 450 and browser_page is not None:
            captured_api_text: List[str] = []
            captured_urls: List[str] = []

            def response_yakala(api_response):
                try:
                    api_url = api_response.url
                    status = api_response.status
                    headers = api_response.headers
                    content_type = headers.get("content-type", "").lower()
                    browser_diagnostics.append({
                        "url": api_url[:500],
                        "status": status,
                        "content_type": content_type[:120],
                    })
                    if len(browser_diagnostics) > 60:
                        return
                    if status < 200 or status >= 400:
                        return
                    if "pdf" in content_type or ".pdf" in api_url.lower():
                        captured_urls.append(api_url)
                        return
                    if any(x in content_type for x in ["json", "text", "html", "javascript"]):
                        body = api_response.text()
                        if not body:
                            return
                        for raw in re.findall(
                            r"""(?:https?://[^\s"'<>]+|/[A-Za-z0-9_./-]+\.pdf(?:\?[^\s"'<>]*)?)""",
                            body, flags=re.I
                        ):
                            full = urljoin(api_url, raw.rstrip("),;"))
                            if ".pdf" in full.lower():
                                captured_urls.append(full)
                        # JSON cevaplarını alan-değer biçiminde düz metne çevir.
                        if "json" in content_type or body.lstrip().startswith(("{", "[")):
                            try:
                                payload = json.loads(body)
                                converted = json_metinine_cevir(payload)
                                if converted:
                                    captured_api_text.append(converted[:50000])
                            except Exception:
                                pass
                        elif any(word in tr_lower(body) for word in
                                 ["personel", "başvuru", "basvuru", "ilan", "kadro", "kpss", "önlisans"]):
                            captured_api_text.append(temizle(body[:50000]))
                except Exception as exc:
                    logging.debug("[API YANIT OKUMA] %s", exc)

            browser_page.on("response", response_yakala)
            try:
                browser_page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    browser_page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    # Uzun yaşayan bağlantılar networkidle'ı engelleyebilir.
                    pass
                try:
                    browser_page.wait_for_function(
                        "document.body && document.body.innerText && document.body.innerText.length > 250",
                        timeout=7000
                    )
                except Exception:
                    pass
                browser_page.wait_for_timeout(2500)

                browser_html = browser_page.content()
                browser_soup = BeautifulSoup(browser_html, "html.parser")
                for element in browser_soup.find_all(["a", "iframe", "embed", "object", "source"]):
                    raw = element.get("href") or element.get("src") or element.get("data") or ""
                    if raw:
                        full = urljoin(browser_page.url, raw)
                        if ".pdf" in full.lower() or "ilan-metni" in full.lower():
                            pdf_links.append(full)

                # Sayfanın görünür metni; script ve gezinme alanları hariç.
                for tag in browser_soup(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()
                browser_text = temizle(browser_soup.get_text(" ", strip=True))
                if len(browser_text) > len(text):
                    text = browser_text
                if captured_api_text:
                    parts.append(" ".join(captured_api_text))
                if browser_text:
                    parts.append(browser_text)
                final_url = browser_page.url

                logging.info(
                    "[TARAYICI TEŞHİS] URL=%s | SAYFA_METNİ=%s | API_YANITI=%s | İSTEK=%s",
                    final_url, len(browser_text), len(captured_api_text), len(browser_diagnostics)
                )
                for diag in browser_diagnostics:
                    logging.info("[AĞ] %s | HTTP %s | %s",
                                 diag.get("url", ""), diag.get("status", ""),
                                 diag.get("content_type", ""))
            except Exception as exc:
                logging.warning("[TARAYICI DETAY HATASI] %s | %s", url, exc)
            finally:
                try:
                    browser_page.remove_listener("response", response_yakala)
                except Exception:
                    pass

            pdf_links.extend(captured_urls)

        unique_pdfs = list(dict.fromkeys(pdf_links))[:5]
        pdf_texts = []
        for pdf_url in unique_pdfs:
            content = pdf_metin_oku(pdf_url)
            if content:
                pdf_texts.append(content)

        combined = temizle(" ".join([text, " ".join(parts), " ".join(pdf_texts)]))
        if len(combined) < 450:
            logging.warning(
                "[DETAY KISA] URL=%s | SON_URL=%s | METIN=%s | PDF=%s | API_IZI=%s",
                url, final_url, len(combined), len(unique_pdfs), len(browser_diagnostics)
            )
            # Teşhis için kısa HTML metnini logla; token/çerez gibi başlıklar kesinlikle yazılmaz.
            if browser_page is not None:
                try:
                    snippet = temizle(browser_page.locator("body").inner_text(timeout=2000))[:700]
                    logging.warning("[SAYFA GÖRÜNEN İÇERİK] %s", snippet)
                except Exception:
                    pass
        return combined[:30000], len(unique_pdfs), final_url

    except Exception as exc:
        logging.exception("[DETAY OKUMA HATASI] %s | %s", url, exc)
        return temizle(" ".join(parts))[:30000], len(list(dict.fromkeys(pdf_links))), final_url

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
            source
        )
        if match:
            institution = temizle(match.group(1))
            break

    quota = "Belirtilmemiş"
    qmatch = re.search(
        r"(?:toplam\s*)?(?:\d+\s*)?(?:kişilik\s*)?(?:kontenjan|kadro|personel)\D{0,35}(\d{1,4})\s*(?:kişi|personel|memur|işçi|adet)?",
        text
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


def uygunluk_degerlendir(title: str, detail: str, info: Dict[str, Any],
                         profile: Dict[str, Any], today: date) -> Tuple[str, List[str]]:
    text = tr_lower(title + " " + detail)
    reasons = []

    # Yaş sınırı
    age_limits = []
    for pattern in [
        r"(\d{2})\s*yaşını\s*doldurmamış",
        r"en fazla\s*(\d{2})\s*yaş",
        r"(\d{2})\s*yaşından\s*gün\s*almamış",
    ]:
        age_limits.extend(int(x) for x in re.findall(pattern, text))
    if age_limits and int(profile["yas"]) > min(age_limits):
        return "Uygun Değil", ["Yaş şartı karşılanmıyor"]

# Cinsiyet şartı yalnızca açık ve kesin ifade varsa uygulanır.
    gender = tr_lower(profile["cinsiyet"])
    if gender == "erkek" and re.search(r"yalnızca kadın aday|sadece kadın aday|kadın adaylar başvurabilir", text):
        return "Uygun Değil", ["İlan yalnızca kadın aday kabul ediyor"]
    if gender == "kadın" and re.search(r"yalnızca erkek aday|sadece erkek aday|erkek adaylar başvurabilir", text):
        return "Uygun Değil", ["İlan yalnızca erkek aday kabul ediyor"]

    # Eğitim şartı: ilanda yalnızca lisans/ortaöğretim isteniyorsa önlisans profili elenir.
    required_education = info["egitim"]
    if required_education != "Belirtilmemiş" and required_education != profile["egitim"]:
        if required_education == "Lisans" and profile["egitim"] == "Önlisans":
            return "Uygun Değil", ["İlan lisans mezuniyeti istiyor"]
        if required_education == "Ortaöğretim" and profile["egitim"] == "Önlisans":
            reasons.append("İlanın önlisans mezunlarını kabul edip etmediği kontrol edilmeli")

    # Bölüm şartı
    if "adalet" in text:
        reasons.append("Adalet bölüm şartı metinde geçiyor")
    elif re.search(r"\b3001\b", text):
        reasons.append("3001 nitelik kodu bulundu")
    elif any(x in text for x in ["herhangi bir önlisans", "önlisans programlarının herhangi biri",
                                  "önlisans mezunu olmak"]):
        reasons.append("Genel önlisans şartı bulundu")
    elif any(x in text for x in ["belirli bölüm", "ilgili bölüm", "mezunu olmak"]):
        reasons.append("Bölüm şartı ayrıca doğrulanmalı")
    else:
        reasons.append("Bölüm şartı net olarak çıkarılamadı")

    # KPSS puan türü ve taban puanı
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

    # Başvuru süresi
    if info["son_dt"] and info["son_dt"] < today:
        return "Başvuru Süresi Geçmiş", ["Son başvuru tarihi geçmiş"]

    # Tam uygunluk için bölüm + eğitim + puan türü teyidi gerekir.
    strong_section = ("adalet" in text or bool(re.search(r"\b3001\b", text))
                      or "herhangi bir önlisans" in text
                      or "önlisans mezunu olmak" in text)
    education_ok = required_education == "Önlisans" or (
        required_education == "Belirtilmemiş" and strong_section
    )
    score_ok = actual_type == expected_type or (
        actual_type == "Belirtilmemiş" and "kpss şartı yoktur" in text
    )

    if education_ok and strong_section and score_ok:
        return "Uygun", reasons
    return "Kontrol Gerekli", reasons


def ilan_degerlendir(item: Dict[str, str], detail: str, today: date,
                     profile: Dict[str, Any]) -> Dict[str, Any]:
    title = temizle(item.get("title", ""))
    link = item.get("link", "")
    source = item.get("source", "Kamu")
    combined = tr_lower(title + " " + detail)

    if any(word in combined for word in HARIC):
        return {"durum": "Elendi", "sebep": "Hariç tutulan içerik"}

    if not aday_baslik_mi(title):
        return {"durum": "Elendi", "sebep": "Başlık gerçek personel alım ilanı değil"}

    if len(detail.strip()) < 100:
        return {"durum": "Kontrol Gerekli", "sebep": "İlan detayına erişilemedi"}

    info = bilgi_cikar(title, detail)
    status, reasons = uygunluk_degerlendir(title, detail, info, profile, today)

    identity = md5_id("|".join([
        tr_lower(title), (link or "").split("?")[0].lower(),
        tr_lower(info["kurum"]), tr_lower(info["pozisyon"])
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
            browser = playwright_manager.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="tr-TR",
                viewport={"width": 1440, "height": 1000},
                ignore_https_errors=True,
            )
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

            detail, pdf_count, final_url = detay_oku(link, browser_page=page) if link else ("", 0, "")
            result = ilan_degerlendir(item, detail, today, USER_PROFILE)
            status = result["durum"]
            counts[status] = counts.get(status, 0) + 1

            if status == "Elendi" or status == "Başvuru Süresi Geçmiş":
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
