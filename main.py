import os
import re
import json
import html
import hashlib
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin


# ============================================================
# AYARLAR
# ============================================================

BASE_URL = "https://kariyerkapisi.gov.tr"

KPSS_PUANI = 76.29
OGRENIM = "onlisans"
BOLUM = "adalet"
CINSIYET = "erkek"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

GONDERILEN_DOSYA = "sent_ids.json"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 "
    "Chrome/120 Safari/537.36"
)


# ============================================================
# NORMALİZASYON
# ============================================================

def normalize(text):
    if not text:
        return ""

    text = html.unescape(str(text))
    text = text.replace("\xa0", " ")

    text = text.lower()

    replacements = {
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# HTTP
# ============================================================

def get_url(url, timeout=30):
    print(f"[HTTP] {url}")

    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
        timeout=timeout,
    )

    print(
        f"[HTTP] {response.status_code} "
        f"| {len(response.content)} byte"
    )

    response.raise_for_status()

    return response


# ============================================================
# RSS ADRESİNİ BUL
# ============================================================

def rss_adresini_bul():
    print("")
    print("=== RSS ADRESİ BULMA ===")

    sayfa_url = BASE_URL + "/RSS/RssLinkiAl"

    response = get_url(sayfa_url)

    page = response.text

    scripts = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        page,
        re.IGNORECASE,
    )

    print(f"[RSS] Script sayısı: {len(scripts)}")

    infrastructure = None

    for script in scripts:
        if "Infrastructure" in script:
            infrastructure = urljoin(
                BASE_URL,
                script,
            )
            break

    if not infrastructure:
        infrastructure = (
            BASE_URL
            + "/js/Infrastructure.enxa2bxk74.js"
        )

    print(
        "[RSS] Infrastructure:",
        infrastructure,
    )

    js_response = get_url(infrastructure)

    js = js_response.text

    # Güncel JS içerisinde RSS/RSS base adresini bulmaya çalış.
    patterns = [
        r'kvkkbaseurl\s*[:=]\s*["\']([^"\']+)',
        r'kvkkbaseurl\s*=\s*["\']([^"\']+)',
    ]

    rss_base = None

    for pattern in patterns:
        match = re.search(
            pattern,
            js,
            re.IGNORECASE,
        )

        if match:
            rss_base = match.group(1)
            break

    if rss_base:
        rss_base = rss_base.rstrip("/") + "/"
        rss_url = rss_base + "RSS"
    else:
        rss_url = BASE_URL + "/RSS"

    print("[RSS] Son RSS adresi:", rss_url)

    return rss_url


# ============================================================
# RSS OKU
# ============================================================

def rss_oku(content):
    print("")
    print("=== RSS OKUMA ===")

    if isinstance(content, bytes):
        content = content.decode(
            "utf-8-sig",
            errors="replace",
        )
    else:
        content = str(content).lstrip("\ufeff")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        print("[HATA] RSS XML okunamadı:")
        print(exc)
        return []

    ilanlar = []

    # --------------------------------------------------------
    # Klasik RSS
    # --------------------------------------------------------

    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        description = item.findtext("description", "")
        guid = item.findtext("guid", "")

        ilanlar.append(
            {
                "title": html.unescape(title or "").strip(),
                "link": (link or "").strip(),
                "description": html.unescape(
                    description or ""
                ).strip(),
                "id": (
                    guid
                    or link
                    or title
                    or ""
                ).strip(),
            }
        )

    # --------------------------------------------------------
    # Atom
    # --------------------------------------------------------

    if not ilanlar:
        namespace = {
            "atom": "http://www.w3.org/2005/Atom"
        }

        for entry in root.findall(
            ".//atom:entry",
            namespace,
        ):
            title = entry.findtext(
                "atom:title",
                "",
                namespace,
            )

            summary = entry.findtext(
                "atom:summary",
                "",
                namespace,
            )

            entry_id = entry.findtext(
                "atom:id",
                "",
                namespace,
            )

            link = ""

            link_element = entry.find(
                "atom:link",
                namespace,
            )

            if link_element is not None:
                link = link_element.attrib.get(
                    "href",
                    "",
                )

            ilanlar.append(
                {
                    "title": html.unescape(
                        title or ""
                    ).strip(),

                    "link": link.strip(),

                    "description": html.unescape(
                        summary or ""
                    ).strip(),

                    "id": (
                        entry_id
                        or link
                        or title
                        or ""
                    ).strip(),
                }
            )

    print(
        f"[RSS] Toplam ilan: {len(ilanlar)}"
    )

    return ilanlar


# ============================================================
# İLAN ID
# ============================================================

def ilan_id(ilan):
    mevcut = ilan.get("id", "").strip()

    if mevcut:
        return mevcut

    veri = (
        ilan.get("title", "")
        + ilan.get("link", "")
        + ilan.get("description", "")
    )

    return hashlib.sha256(
        veri.encode("utf-8")
    ).hexdigest()


# ============================================================
# GÖNDERİLENLER
# ============================================================

def gonderilenleri_oku():
    if not os.path.exists(GONDERILEN_DOSYA):
        return set()

    try:
        with open(
            GONDERILEN_DOSYA,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if isinstance(data, list):
            return set(str(x) for x in data)

        return set()

    except Exception as exc:
        print(
            "[UYARI] sent_ids.json okunamadı:",
            exc,
        )
        return set()


def gonderilenleri_kaydet(ids):
    with open(
        GONDERILEN_DOSYA,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            sorted(ids),
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# İLAN METNİ
# ============================================================

def ilan_metni(ilan):
    return normalize(
        ilan.get("title", "")
        + " "
        + ilan.get("description", "")
    )


# ============================================================
# BÖLÜM KONTROLÜ
# ============================================================

def bolum_kontrol(text):
    """
    Adalet mezununa doğrudan uygun olabilecek ifadeleri arar.
    """

    adalet_ifadeleri = [
        "adalet",
        "adalet programi",
        "adalet bolumu",
        "adalet onlisans",
        "adalet on lisans",
        "adalet mezunu",
        "adalet programindan mezun",
    ]

    return any(
        ifade in text
        for ifade in adalet_ifadeleri
    )


# ============================================================
# ÖĞRENİM KONTROLÜ
# ============================================================

def onlisans_kontrol(text):
    ifadeler = [
        "onlisans",
        "on lisans",
        "on lisans mezunu",
        "onlisans mezunu",
        "onlisans program",
        "on lisans program",
    ]

    return any(
        ifade in text
        for ifade in ifadeler
    )


# ============================================================
# KPSS KONTROLÜ
# ============================================================

def kpss_bilgisi(text):
    """
    Sonuç:
        {
            "var": True/False,
            "taban": sayı veya None
        }
    """

    if "kpss" not in text:
        return {
            "var": False,
            "taban": None,
        }

    # Örnekler:
    #
    # KPSS P93 70
    # KPSS P93 puan türünden en az 70
    # KPSS'den 70
    # KPSS 60
    #
    patternler = [
        r"kpss.{0,100}?(\d{2}(?:[.,]\d+)?)",
        r"en az\s+(\d{2}(?:[.,]\d+)?)\s*(?:puan)?",
        r"(\d{2}(?:[.,]\d+)?)\s*(?:puanindan|puanından)",
    ]

    adaylar = []

    for pattern in patternler:
        for match in re.finditer(
            pattern,
            text,
            re.IGNORECASE,
        ):
            try:
                sayi = float(
                    match.group(1).replace(
                        ",",
                        ".",
                    )
                )

                if 40 <= sayi <= 100:
                    adaylar.append(sayi)

            except Exception:
                pass

    if not adaylar:
        return {
            "var": True,
            "taban": None,
        }

    # En yüksek sayı genellikle taban puan için
    # daha anlamlıdır.
    return {
        "var": True,
        "taban": max(adaylar),
    }


# ============================================================
# CİNSİYET
# ============================================================

def cinsiyet_kontrol(text):
    """
    İlanda sadece kadın şartı varsa erkek başvuramaz.
    Sadece erkek şartı varsa erkek başvurabilir.
    Cinsiyet belirtilmemişse uygun kabul edilir.
    """

    kadin = any(
        ifade in text
        for ifade in [
            "sadece kadin",
            "yalnizca kadin",
            "kadın aday",
            "kadin aday",
        ]
    )

    erkek = any(
        ifade in text
        for ifade in [
            "sadece erkek",
            "yalnizca erkek",
            "erkek aday",
        ]
    )

    if CINSIYET == "erkek" and kadin and not erkek:
        return False, "Sadece kadın aday"

    if CINSIYET == "kadin" and erkek and not kadin:
        return False, "Sadece erkek aday"

    return True, "Cinsiyet engeli yok"


# ============================================================
# YAŞ KONTROLÜ
# ============================================================

def yas_kontrol(text):
    """
    Kullanıcının doğum tarihi 01.01.1997 olduğundan,
    2026 yılı itibarıyla yaklaşık 29 yaşındadır.

    Açık bir yaş sınırı bulunursa kontrol edilir.
    """

    yas = 29

    # Örnek:
    # 30 yaşını doldurmamış olmak
    # 35 yaşını doldurmamış olmak
    # 30 yaşından gün almamış olmak

    patterns = [
        r"(\d{2})\s*yasini\s*doldurmamis",
        r"(\d{2})\s*yasini\s*doldurmamis",
        r"(\d{2})\s*yasindan\s*kucuk",
        r"(\d{2})\s*yasindan\s*buyuk",
        r"(\d{2})\s*yas\s*ve",
    ]

    for pattern in patterns:
        matches = re.findall(
            pattern,
            text,
        )

        for value in matches:
            try:
                limit = int(value)

                if "doldurmamis" in text:
                    if yas >= limit:
                        return False, (
                            f"{limit} yaş sınırı"
                        )

                if "yasindan kucuk" in text:
                    if yas >= limit:
                        return False, (
                            f"{limit} yaşından küçük olma şartı"
                        )

            except Exception:
                pass

    return True, "Yaş engeli tespit edilmedi"


# ============================================================
# KAPALI İLAN
# ============================================================

def basvuru_kontrol(text):
    kapananlar = [
        "basvurular sona ermistir",
        "basvuru sona ermistir",
        "basvuru suresi dolmustur",
        "basvuruya kapalidir",
        "son basvuru tarihi gecmistir",
    ]

    for ifade in kapananlar:
        if ifade in text:
            return False

    return True


# ============================================================
# İLAN ANALİZİ
# ============================================================

def ilan_analiz(ilan):
    text = ilan_metni(ilan)

    sonuc = {
        "durum": "BASVURAMAZ",
        "neden": [],
        "kpss": None,
        "taban": None,
    }

    # --------------------------------------------------------
    # Adalet
    # --------------------------------------------------------

    if not bolum_kontrol(text):
        sonuc["neden"].append(
            "Adalet bölümü şartı tespit edilmedi"
        )
        return sonuc

    # --------------------------------------------------------
    # Önlisans
    # --------------------------------------------------------

    if not onlisans_kontrol(text):
        sonuc["neden"].append(
            "Önlisans şartı tespit edilmedi"
        )

    # --------------------------------------------------------
    # KPSS
    # --------------------------------------------------------

    kpss = kpss_bilgisi(text)

    sonuc["kpss"] = kpss["var"]
    sonuc["taban"] = kpss["taban"]

    if kpss["var"] and kpss["taban"] is not None:
        if kpss["taban"] > KPSS_PUANI:
            sonuc["neden"].append(
                f"KPSS taban puanı {kpss['taban']} "
                f"(puanınız {KPSS_PUANI})"
            )
            return sonuc

    # --------------------------------------------------------
    # Cinsiyet
    # --------------------------------------------------------

    cinsiyet_ok, cinsiyet_neden = cinsiyet_kontrol(
        text
    )

    if not cinsiyet_ok:
        sonuc["neden"].append(
            cinsiyet_neden
        )
        return sonuc

    # --------------------------------------------------------
    # Yaş
    # --------------------------------------------------------

    yas_ok, yas_neden = yas_kontrol(
        text
    )

    if not yas_ok:
        sonuc["neden"].append(
            yas_neden
        )
        return sonuc

    # --------------------------------------------------------
    # Başvuru
    # --------------------------------------------------------

    if not basvuru_kontrol(text):
        sonuc["neden"].append(
            "Başvuru süresi geçmiş/kapalı"
        )
        return sonuc

    # --------------------------------------------------------
    # Belirsizlik
    # --------------------------------------------------------

    if (
        kpss["var"]
        and kpss["taban"] is None
    ):
        sonuc["durum"] = "MANUEL_INCELEME"
        sonuc["neden"].append(
            "KPSS şartı var ancak taban puan "
            "otomatik tespit edilemedi"
        )
        return sonuc

    # Önlisans metinde açıkça yoksa
    # ama Adalet şartı varsa manuel kontrol.
    if not onlisans_kontrol(text):
        sonuc["durum"] = "MANUEL_INCELEME"
        sonuc["neden"].append(
            "Adalet şartı var fakat öğrenim "
            "seviyesi açık değil"
        )
        return sonuc

    sonuc["durum"] = "UYGUN"

    return sonuc


# ============================================================
# TELEGRAM
# ============================================================

def telegram_gonder(mesaj):
    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN bulunamadı"
        )

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID bulunamadı"
        )

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mesaj,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )

    print(
        "[TELEGRAM]",
        response.status_code,
    )

    if not response.ok:
        print(
            "[TELEGRAM HATA]",
            response.text,
        )

    response.raise_for_status()


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def telegram_mesaji(ilan, analiz):
    aciklama = ilan.get(
        "description",
        "",
    )

    if len(aciklama) > 2500:
        aciklama = (
            aciklama[:2500]
            + "..."
        )

    durum = analiz["durum"]

    if analiz["kpss"]:
        if analiz["taban"] is not None:
            kpss_text = (
                f"Var | Taban: {analiz['taban']}"
            )
        else:
            kpss_text = (
                "Var | Taban otomatik tespit edilemedi"
            )
    else:
        kpss_text = "KPSS şartı tespit edilmedi"

    neden = "\n".join(
        "• " + x
        for x in analiz["neden"]
    )

    return (
        "🔔 KAMU İLAN TAKİP\n\n"
        f"📌 {ilan.get('title', '')}\n\n"
        f"🎯 Durum: {durum}\n"
        f"🎓 Öğrenim: {OGRENIM}\n"
        f"⚖️ Bölüm: {BOLUM}\n"
        f"👤 Cinsiyet: {CINSIYET}\n"
        f"📊 KPSS: {kpss_text}\n"
        f"🧑 Yaş: 29\n\n"
        f"🔎 Analiz:\n{neden or 'Şartlar uygun görünüyor.'}\n\n"
        f"📝 Açıklama:\n{aciklama}\n\n"
        f"🔗 {ilan.get('link', '')}"
    )


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    print("")
    print("=" * 50)
    print("KAMU İLAN TAKİP BAŞLIYOR")
    print(f"KPSS puanı: {KPSS_PUANI}")
    print(f"Öğrenim: {OGRENIM}")
    print(f"Bölüm: {BOLUM}")
    print(f"Cinsiyet: {CINSIYET}")
    print("=" * 50)

    # --------------------------------------------------------
    # ENV KONTROL
    # --------------------------------------------------------

    print("")
    print("=== ORTAM KONTROLÜ ===")

    print(
        "TELEGRAM_TOKEN:",
        "VAR" if TELEGRAM_TOKEN else "YOK",
    )

    print(
        "TELEGRAM_CHAT_ID:",
        "VAR" if TELEGRAM_CHAT_ID else "YOK",
    )

    if not TELEGRAM_TOKEN:
        print(
            "[HATA] TELEGRAM_TOKEN yok."
        )
        return

    if not TELEGRAM_CHAT_ID:
        print(
            "[HATA] TELEGRAM_CHAT_ID yok."
        )
        return

    # --------------------------------------------------------
    # RSS
    # --------------------------------------------------------

    try:
        rss_url = rss_adresini_bul()

        response = get_url(
            rss_url
        )

    except Exception as exc:
        print("")
        print("!!! RSS HATASI !!!")
        print(exc)
        return

    # --------------------------------------------------------
    # RSS PARSE
    # --------------------------------------------------------

    ilanlar = rss_oku(
        response.content
    )

    if not ilanlar:
        print("")
        print(
            "[HATA] Hiç ilan okunamadı."
        )
        return

    # ----
# ============================================================
# PROGRAMI BAŞLAT
# ============================================================

if __name__ == "__main__":
    main()
