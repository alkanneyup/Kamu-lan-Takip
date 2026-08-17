print("### MAIN.PY BAŞLADI ###", flush=True)
import os
import re
import json
import html
import hashlib
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin


# ============================================================
# KULLANICI PROFİLİ
# ============================================================

BASE_URL = "https://kariyerkapisi.gov.tr"

KPSS_PUANI = 76.29
OGRENIM = "onlisans"
BOLUM = "adalet"
CINSIYET = "erkek"

# Doğum tarihi: 01.01.1997
DOGUM_YILI = 1997

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

GONDERILEN_DOSYA = "sent_ids.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120 Safari/537.36"
)


# ============================================================
# GENEL YARDIMCI FONKSİYONLAR
# ============================================================

def normalize(text):
    if not text:
        return ""

    text = html.unescape(str(text))
    text = text.replace("\xa0", " ")
    text = text.lower()

    ceviri = str.maketrans({
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
        "İ": "i",
        "Ğ": "g",
        "Ü": "u",
        "Ş": "s",
        "Ö": "o",
        "Ç": "c",
    })

    text = text.translate(ceviri)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def temizle_html(text):
    if not text:
        return ""

    text = html.unescape(text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def get_url(url):
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=30
    )

    response.raise_for_status()

    return response


# ============================================================
# RSS ADRESİNİ BUL
# ============================================================

def rss_adresini_bul():

    print("Kariyer Kapısı RSS sayfası okunuyor...")

    sayfa_url = BASE_URL + "/RSS/RssLinkiAl"

    response = get_url(sayfa_url)

    scriptler = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        response.text,
        re.IGNORECASE
    )

    infrastructure = None

    for script in scriptler:
        if "Infrastructure" in script:
            infrastructure = urljoin(BASE_URL, script)
            break

    if not infrastructure:
        infrastructure = (
            BASE_URL
            + "/js/Infrastructure.enxa2bxk74.js"
        )

    print("Infrastructure:", infrastructure)

    try:
        js = get_url(infrastructure).text
    except Exception:
        js = ""

    # Farklı JS yazım şekillerine tolerans
    eslesmeler = [
        r'kvkkbaseurl\s*[:=]\s*["\']([^"\']+)',
        r'kvkkbaseurl\s*=\s*["\']([^"\']+)',
        r'kvkkbaseurl\s*:\s*["\']([^"\']+)',
    ]

    rss_base = None

    for pattern in eslesmeler:
        match = re.search(pattern, js, re.I)

        if match:
            rss_base = match.group(1)
            break

    if not rss_base:
        rss_base = BASE_URL + "/"

    if not rss_base.endswith("/"):
        rss_base += "/"

    return rss_base + "RSS"


# ============================================================
# RSS PARSE
# ============================================================

def parse_rss(content):

    if isinstance(content, bytes):
        content = content.decode(
            "utf-8-sig",
            errors="replace"
        )
    else:
        content = str(content).lstrip("\ufeff")

    root = ET.fromstring(content)

    ilanlar = []

    # --------------------------------------------------------
    # RSS
    # --------------------------------------------------------

    for item in root.findall(".//item"):

        def txt(tag):
            value = item.findtext(tag, "")
            return temizle_html(value)

        title = txt("title")
        link = txt("link")
        description = txt("description")
        guid = txt("guid")
        pubdate = txt("pubDate")

        if not title and not description:
            continue

        ilan_id = guid or link or title

        ilanlar.append({
            "id": ilan_id.strip(),
            "title": title.strip(),
            "link": link.strip(),
            "description": description.strip(),
            "date": pubdate.strip(),
        })

    # --------------------------------------------------------
    # ATOM
    # --------------------------------------------------------

    if not ilanlar:

        ns = {
            "atom": "http://www.w3.org/2005/Atom"
        }

        for entry in root.findall(
            ".//atom:entry",
            ns
        ):

            title = temizle_html(
                entry.findtext(
                    "atom:title",
                    "",
                    ns
                )
            )

            summary = temizle_html(
                entry.findtext(
                    "atom:summary",
                    "",
                    ns
                )
            )

            entry_id = entry.findtext(
                "atom:id",
                "",
                ns
            )

            link = ""

            link_el = entry.find(
                "atom:link",
                ns
            )

            if link_el is not None:
                link = link_el.attrib.get(
                    "href",
                    ""
                )

            ilanlar.append({
                "id": (
                    entry_id
                    or link
                    or title
                ).strip(),

                "title": title.strip(),

                "link": link.strip(),

                "description": summary.strip(),

                "date": ""
            })

    return ilanlar


# ============================================================
# GÖNDERİLEN İLANLAR
# ============================================================

def gonderilenleri_oku():

    if not os.path.exists(GONDERILEN_DOSYA):
        return set()

    try:
        with open(
            GONDERILEN_DOSYA,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        return set(data)

    except Exception:
        return set()


def gonderilenleri_kaydet(ids):

    with open(
        GONDERILEN_DOSYA,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            sorted(ids),
            f,
            ensure_ascii=False,
            indent=2
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
# İLAN TÜRÜ / POZİSYON
# ============================================================

def pozisyon_uygun_mu(text):

    # Adalet mezunu açısından doğrudan anlamlı pozisyonlar
    uygun_pozisyonlar = [
        "zabit katibi",
        "zabıt katibi",
        "katip",
        "icra katibi",
        "icra memuru",
        "icra mudur yardimcisi",
        "icra mudurlugu",
        "memur",
        "bilgisayar isletmeni",
        "veri hazirlama",
        "veri hazırlama",
        "vhki",
        "yazı işleri",
        "yazi isleri",
        "büro personeli",
        "buro personeli",
        "büro görevlisi",
        "buro gorevlisi",
        "destek personeli",
        "personel",
    ]

    # Önce bariz biçimde teknik/uzmanlık isteyen alanları ayıkla
    teknik_alanlar = [
        "bilgisayar muhendis",
        "yazilim muhendis",
        "elektrik elektronik muhendis",
        "makine muhendis",
        "endustri muhendis",
        "mimar",
        "eczaci",
        "hemsire",
        "saglik teknikeri",
        "laborant",
        "biyolog",
        "psikolog",
        "sosyal calismaci",
        "ogretmen",
        "avukat",
        "hukuk musaviri",
        "uzman yardimcisi",
        "mali hizmetler uzman",
        "muhendis",
    ]

    for kelime in teknik_alanlar:

        if kelime in text:

            # İlan aynı zamanda doğrudan Adalet mezununu
            # kabul ettiğini söylüyorsa daha sonra manuel
            # incelemeye bırakılabilir.
            if (
                "adalet mezunu" not in text
                and "adalet programi" not in text
            ):
                return False

    for kelime in uygun_pozisyonlar:

        if kelime in text:
            return True

    return False


# ============================================================
# ÖĞRENİM ŞARTI
# ============================================================

def egitim_sarti(text):

    # Açıkça lise ve altı ile sınırlıysa önlisans mezununa
    # uygun kabul etmiyoruz.
    lise_only = [
        "en az lise",
        "lise veya dengi",
        "ortaogretim",
        "ortaogretim mezunu",
    ]

    onlisans_ifadeleri = [
        "onlisans",
        "on lisans",
        "yuksekokul",
        "meslek yuksekokulu",
        "myo",
    ]

    adalet_ifadeleri = [
        "adalet programi",
        "adalet bolumu",
        "adalet mezunu",
        "adalet onlisans",
        "adalet on lisans",
    ]

    # Doğrudan Adalet kabulü
    if any(x in text for x in adalet_ifadeleri):
        return "UYGUN"

    # Önlisans açıkça geçiyorsa
    if any(x in text for x in onlisans_ifadeleri):
        return "UYGUN"

    # Lisans ve üzeri zorunluysa
    lisans_zorunlu = [
        "lisans mezunu",
        "en az lisans",
        "lisans mezun",
        "dort yillik",
        "4 yillik",
    ]

    if any(x in text for x in lisans_zorunlu):

        # Adalet önlisansının ayrıca kabul edildiği belirtilmişse
        if "adalet" in text and (
            "onlisans" in text
            or "on lisans" in text
        ):
            return "UYGUN"

        return "UYGUN_DEGIL"

    # Sadece lise olduğu açıkça belirtiliyorsa
    if any(x in text for x in lise_only):

        # İlanda ayrıca önlisans kabulü varsa
        if "onlisans" in text or "on lisans" in text:
            return "UYGUN"

        return "UYGUN_DEGIL"

    # Öğrenim bilgisi bulunamıyorsa manuel
    return "BELIRSIZ"


# ============================================================
# KPSS ANALİZİ
# ============================================================

def kpss_analiz(text):

    if "kpss" not in text:
        return {
            "var": False,
            "puan": None,
            "uygun": True,
            "aciklama": "KPSS şartı tespit edilmedi"
        }

    # Örnek:
    # KPSS P93 70
    # KPSS'den en az 70
    # KPSS 70 puan
    # KPSSP93 60
    desenler = [

        r"kpss.{0,80}?en az\s*(\d{2}(?:[.,]\d+)?)",

        r"kpss.{0,80}?(?:puanindan|puanından|puani|puanı)"
        r".{0,20}?(?:en az|asgari|minimum)?\s*"
        r"(\d{2}(?:[.,]\d+)?)",

        r"kpss\s*p\d{2}.{0,40}?"
        r"(\d{2}(?:[.,]\d+)?)",

        r"kpss.{0,40}?(\d{2}(?:[.,]\d+)?)"
    ]

    adaylar = []

    for pattern in desenler:

        for match in re.finditer(
            pattern,
            text,
            re.I
        ):

            try:

                puan = float(
                    match.group(1).replace(
                        ",",
                        "."
                    )
                )

                if 50 <= puan <= 100:
                    adaylar.append(puan)

            except Exception:
                pass

    if not adaylar:

        return {
            "var": True,
            "puan": None,
            "uygun": True,
            "aciklama": "KPSS şartı var, taban puan otomatik tespit edilemedi"
        }

    # İlandaki en yüksek olası taban puanı esas al
    taban = max(adaylar)

    return {
        "var": True,
        "puan": taban,
        "uygun": KPSS_PUANI >= taban,
        "aciklama": (
            f"KPSS taban {taban:g}, "
            f"aday {KPSS_PUANI:g}"
        )
    }


# ============================================================
# CİNSİYET
# ============================================================

def cinsiyet_analiz(text):

    erkek = [
        "erkek aday",
        "erkek olmak",
        "erkek personel",
        "sadece erkek",
    ]

    kadin = [
        "kadin aday",
        "kadın aday",
        "kadin olmak",
        "kadın olmak",
        "kadin personel",
        "kadın personel",
        "sadece kadin",
        "sadece kadın",
    ]

    if any(x in text for x in erkek):

        return {
            "durum": "ERKEK",
            "uygun": CINSIYET == "erkek"
        }

    if any(x in text for x in kadin):

        return {
            "durum": "KADIN",
            "uygun": CINSIYET == "kadin"
        }

    return {
        "durum": "BELIRTILMEMIS",
        "uygun": True
    }


# ============================================================
# YAŞ ANALİZİ
# ============================================================

def yas_analiz(text):

    # "35 yaşını doldurmamış olmak"
    match = re.search(
        r"(\d{2})\s*yasini\s*doldurmamis",
        text
    )

    if match:

        limit = int(match.group(1))
        yas = 2026 - DOGUM_YILI

        return {
            "durum": f"{limit} yaş altı",
            "uygun": yas < limit
        }

    # "35 yaşından gün almamış"
    match = re.search(
        r"(\d{2})\s*yasindan\s*gun\s*almamis",
        text
    )

    if match:

        limit = int(match.group(1))
        yas = 2026 - DOGUM_YILI

        return {
            "durum": f"{limit} yaşından gün almamış",
            "uygun": yas < limit
        }

    # "35 yaşını geçmemiş"
    match = re.search(
        r"(\d{2})\s*yasini\s*gecmemis",
        text
    )

    if match:

        limit = int(match.group(1))
        yas = 2026 - DOGUM_YILI

        return {
            "durum": f"{limit} yaş sınırı",
            "uygun": yas <= limit
        }

    return {
        "durum": "BELIRTILMEMIS",
        "uygun": True
    }


# ============================================================
# ADALET BÖLÜMÜ ANALİZİ
# ============================================================

def bolum_analiz(text):

    adalet_ifadeleri = [
        "adalet programi",
        "adalet bolumu",
        "adalet mezunu",
        "adalet onlisans",
        "adalet on lisans",
    ]

    if any(x in text for x in adalet_ifadeleri):
        return "UYGUN"

    # İlanda genel önlisans kabulü varsa ancak bölüm
    # belirtilmemişse otomatik olarak kesin uygun saymıyoruz.
    if (
        "onlisans" in text
        or "on lisans" in text
    ):
        return "BELIRSIZ"

    return "BELIRSIZ"


# ============================================================
# BAŞVURU DURUMU
# ============================================================

def ilan_analiz_et(ilan):

    text = ilan_metni(ilan)

    nedenler = []

    # 1. Pozisyon
    pozisyon = pozisyon_uygun_mu(text)

    if not pozisyon:
        return {
            "durum": "BASVURAMAZSIN",
            "neden": "Pozisyon Adalet mezunu profiline uygun görünmüyor.",
            "kpss": kpss_analiz(text),
            "cinsiyet": cinsiyet_analiz(text),
            "yas": yas_analiz(text),
        }

    # 2. Eğitim
    egitim = egitim_sarti(text)

    if egitim == "UYGUN_DEGIL":

        return {
            "durum": "BASVURAMAZSIN",
            "neden": "Öğrenim şartı uygun değil.",
            "kpss": kpss_analiz(text),
            "cinsiyet": cinsiyet_analiz(text),
            "yas": yas_analiz(text),
        }

    # 3. Bölüm
    bolum = bolum_analiz(text)

    # 4. KPSS
    kpss = kpss_analiz(text)

    if not kpss["uygun"]:

        return {
            "durum": "BASVURAMAZSIN",
            "neden": kpss["aciklama"],
            "kpss": kpss,
            "cinsiyet": cinsiyet_analiz(text),
            "yas": yas_analiz(text),
        }

    # 5. Cinsiyet
    cinsiyet = cinsiyet_analiz(text)

    if not cinsiyet["uygun"]:

        return {
            "durum": "BASVURAMAZSIN",
            "neden": "Cinsiyet şartı uygun değil.",
            "kpss": kpss,
            "cinsiyet": cinsiyet,
            "yas": yas_analiz(text),
        }

    # 6. Yaş
    yas = yas_analiz(text)

    if not yas["uygun"]:

        return {
            "durum": "BASVURAMAZSIN",
            "neden": "Yaş şartı uygun değil.",
            "kpss": kpss,
            "cinsiyet": cinsiyet,
            "yas": yas,
        }

    # Bölüm kesin değilse manuel inceleme
    if bolum == "BELIRSIZ":

        return {
            "durum": "MANUEL_INCELEME",
            "neden": (
                "Pozisyon ve genel şartlar uygun görünüyor "
                "ancak Adalet bölüm şartı kesin tespit edilemedi."
            ),
            "kpss": kpss,
            "cinsiyet": cinsiyet,
            "yas": yas,
        }

    # Her şey uygun
    return {
        "durum": "BASVURABILIRSIN",
        "neden": "Tespit edilen şartlar profilinle uyumlu.",
        "kpss": kpss,
        "cinsiyet": cinsiyet,
        "yas": yas,
    }


# ============================================================
# TELEGRAM
# ============================================================

def telegram_gonder(mesaj):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:

        print(
            "Telegram bilgileri bulunamadı."
        )

        return False

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
        timeout=30
    )

    if response.status_code != 200:

        print(
            "Telegram HTTP:",
            response.status_code
        )

        print(
            response.text[:1000]
        )

        return False

    return True


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def telegram_mesaji(ilan, analiz):

    kpss = analiz["kpss"]
    cinsiyet = analiz["cinsiyet"]
    yas = analiz["yas"]

    if kpss["var"]:

        if kpss["puan"] is not None:
            kpss_text = (
                f"Var — taban {kpss['puan']:g}, "
                f"sen {KPSS_PUANI:g}"
            )
        else:
            kpss_text = (
                "Var — puan otomatik tespit edilemedi"
            )

    else:

        kpss_text = "Şart tespit edilmedi"

    mesaj = (
        "🚨 BAŞVURABİLECEĞİN KAMU İLANI\n\n"
        f"🏛️ {ilan['title']}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🎓 Öğrenim: {OGRENIM}\n"
        f"⚖️ Bölüm: {BOLUM}\n"
        f"📊 KPSS: {kpss_text}\n"
        f"👤 Cinsiyet: {cinsiyet['durum']}\n"
        f"🎂 Yaş: {yas['durum']}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 {analiz['neden']}\n\n"
        f"🔗 {ilan['link']}"
    )

    return mesaj


# ============================================================
# İLAN ID
# ============================================================

def kesin_id(ilan):

    if ilan.get("id"):
        return ilan["id"]

    veri = (
        ilan.get("title", "")
        + ilan.get("link", "")
        + ilan.get("description", "")
    )

    return hashlib.sha256(
        veri.encode("utf-8")
    ).hexdigest()


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    print("")
    print("=" * 50)
    print("KAMU İLAN TAKİP BAŞLIYOR")
    print("KPSS puanı:", KPSS_PUANI)
    print("Öğrenim:", OGRENIM)
    print("Bölüm:", BOLUM)
    print("Cinsiyet:", CINSIYET)
    print("Doğum yılı:", DOGUM_YILI)
    print("=" * 50)

    # --------------------------------------------------------
    # RSS
    # -----------------------------------------------
