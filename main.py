        if len(text) < 450 and browser_page is not None:
            def on_response(api_resp):
                nonlocal api_count, err_count
                try:
                    st_code = api_resp.status
                    a_url = api_resp.url
                    ctype = api_resp.headers.get("content-type", "").lower()
                    if st_code >= 400:
                        err_count += 1
                        logging.warning("[AĞ HATA] HTTP %s | %s", st_code, a_url[:200])
                        return
                    if any(
                        a_url.lower().split("?")[0].endswith(ext)
                        for ext in (".css", ".js", ".woff2", ".png", ".jpg", ".svg", ".ico")
                    ):
                        return
                    if "google-analytics" in a_url or "googletagmanager" in a_url:
                        return
                    if "pdf" in ctype or ".pdf" in a_url.lower():
                        pdf_links.append(a_url)
                        return

                    body = api_resp.text()
                    if not body:
                        return
                    for raw in re.findall(
                        r"""(?:https?://[^\s"'<>]+|/[A-Za-z0-9_./-]+\.pdf(?:\?[^\s"'<>]*)?)""",
                        body,
                        flags=re.I,
                    ):
                        pdf_links.append(urljoin(a_url, raw.rstrip("),;")))

                    stripped = body.lstrip()
                    if "json" in ctype or stripped.startswith(("{", "[")):
                        try:
                            conv = json_metinine_cevir(json.loads(body))
                            if conv and len(conv) > 40:
                                api_count += 1
                                api_texts.append(conv[:30000])
                                if len(api_previews) < 2:
                                    api_previews.append(f"{a_url[:160]} -> {conv[:220]}")
                        except Exception:
                            pass
                except Exception:
                    pass

            browser_page.on("response", on_response)
            try:
                browser_page.goto(url, wait_until="domcontentloaded", timeout=15000)
                try:
                    browser_page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass
                try:
                    browser_page.wait_for_function(
                        "() => { const t = (document.body && document.body.innerText || '').trim(); "
                        "return t.length > 220 && !t.startsWith('Kariyer Kapısı İlan Numarası'); }",
                        timeout=7000,
                    )
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
                if len(b_text) > len(text):
                    text = b_text
                if api_texts:
                    parts.append(" ".join(api_texts))
                if b_text:
                    parts.append(b_text)
                final_url = browser_page.url
                logging.info(
                    "[TEŞHİS] URL=%s | METİN=%s | API=%s | HATA=%s",
                    final_url, len(b_text), api_count, err_count,
                )
                if len(b_text) < 500 and not api_texts:
                    logging.info("[METİN ÖNİZLEME] %s", b_text[:300])
                    for prev in api_previews:
                        logging.info("[API ÖNİZLEME] %s", prev)
            finally:
                try:
                    browser_page.remove_listener("response", on_response)
                except Exception:
                    pass
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


def detay_oku(url: str, browser_page=None) -> Tuple[str, int, str]:
    if not url:
        return "", 0, "Bağlantı yok"

    parts: List[str] = []
    pdf_links: List[str] = []
    final_url = url
    api_texts: List[str] = []
    api_previews: List[str] = []
    api_count = 0
    err_count = 0

    try:
        resp = SESSION.get(url, timeout=(6, 14), allow_redirects=True)
        final_url = resp.url
        if resp.status_code == 200 and "pdf" not in resp.headers.get("Content-Type", "").lower():
            soup = BeautifulSoup(resp.text, "html.parser")
            for el in soup.find_all(["a", "iframe", "embed", "object", "source"]):
                raw = (el.get("href") or el.get("src") or el.get("data") or "").strip()
                if raw and (".pdf" in raw.lower() or "ilan-metni" in raw.lower()):
                    pdf_links.append(urljoin(final_url, raw))
            for sc in soup.find_all("script"):
                st = sc.string or sc.get_text(" ", strip=True)
                if st and any(k in tr_lower(st) for k in ["personel", "ilan", "basvuru", "başvuru", "kadro"]):
                    parts.append(temizle(st[:30000]))
            for tag in soup(["style", "nav", "header", "footer"]):
                tag.decompose()
            parts.append(temizle(soup.get_text(" ", strip=True)))
            for raw in re.findall(
                r"""(?:https?://[^\s"'<>]+|/[A-Za-z0-9_./-]+\.pdf(?:\?[^\s"'<>]*)?)""",
                resp.text,
                flags=re.I,
            ):
                pdf_links.append(urljoin(final_url, raw.rstrip("),;")))

        text = temizle(" ".join(parts))

        if len(text) < 450 and browser_page is not None:
            def on_response(api_resp):
                nonlocal api_count, err_count
                try:
                    st_code = api_resp.status
                    a_url = api_resp.url
                    ctype = api_resp.headers.get("content-type", "").lower()
                    if st_code >= 400:
                        err_count += 1
                        logging.warning("[AĞ HATA] HTTP %s | %s", st_code, a_url[:200])
                        return
                    if any(
                        a_url.lower().split("?")[0].endswith(ext)
                        for ext in (".css", ".js", ".woff2", ".png", ".jpg", ".svg", ".ico")
                    ):
                        return
                    if "google-analytics" in a_url or "googletagmanager" in a_url:
                        return
                    if "pdf" in ctype or ".pdf" in a_url.lower():
                        pdf_links.append(a_url)
                        return

                    body = api_resp.text()
                    if not body:
                        return
                    for raw in re.findall(
                        r"""(?:https?://[^\s"'<>]+|/[A-Za-z0-9_./-]+\.pdf(?:\?[^\s"'<>]*)?)""",
                        body,
                        flags=re.I,
                    ):
                        pdf_links.append(urljoin(a_url, raw.rstrip("),;")))

                    stripped = body.lstrip()
                    if "json" in ctype or stripped.startswith(("{", "[")):
                        try:
                            conv = json_metinine_cevir(json.loads(body))
                            if conv and len(conv) > 40:
                                api_count += 1
                                api_texts.append(conv[:30000])
                                if len(api_previews) < 2:
                                    api_previews.append(f"{a_url[:160]} -> {conv[:220]}")
                        except Exception:
                            pass
                except Exception:
                    pass

            browser_page.on("response", on_response)
            try:
                browser_page.goto(url, wait_until="domcontentloaded", timeout=15000)
                try:
                    browser_page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass
                try:
                    browser_page.wait_for_function(
                        "() => { const t = (document.body && document.body.innerText || '').trim(); "
                        "return t.length > 220 && !t.startsWith('Kariyer Kapısı İlan Numarası'); }",
                        timeout=7000,
                    )
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
                if len(b_text) > len(text):
                    text = b_text
                if api_texts:
                    parts.append(" ".join(api_texts))
                if b_text:
                    parts.append(b_text)
                final_url = browser_page.url
                logging.info(
                    "[TEŞHİS] URL=%s | METİN=%s | API=%s | HATA=%s",
                    final_url, len(b_text), api_count, err_count,
                )
                if len(b_text) < 500 and not api_texts:
                    logging.info("[METİN ÖNİZLEME] %s", b_text[:300])
                    for prev in api_previews:
                        logging.info("[API ÖNİZLEME] %s", prev)
            finally:
                try:
                    browser_page.remove_listener("response", on_response)
                except Exception:
                    pass

        unique_pdfs = list(dict.fromkeys(pdf_links))[:4]
        pdf_texts = [p for u in unique_pdfs if (p := pdf_metin_oku(u))]
        combined = temizle(" ".join([text, " ".join(parts), " ".join(pdf_texts)]))
        return combined[:30000], len(unique_pdfs), final_url

    except Exception as exc:
        logging.warning("[DETAY HATASI] %s | %s", url, exc)
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
    if info["t