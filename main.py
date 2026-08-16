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

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

GONDERILEN_DOSYA = "sent_ids.json"

USER_AGENT = "Kamu-Ilan-Takip/1.0"


# ============================================================
# HTTP
# ============================================================

def get_url(url):

    headers = {
        "User-Agent": USER_AGENT
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    return response


# ============================================================
# RSS ADRESİ
# ============================================================

def rss_adresini_bul():

    print("Kariyer Kapısı RSS sayfası okunuyor...")

    rss_sayfasi = (
        BASE_URL
        + "/RSS/RssLinkiAl"
    )

    response = get_url(
        rss_sayfasi
    )

    html_text = response.text

    scriptler = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        html_text,
        re.IGNORECASE
    )

    infrastructure_url = None

    for script in scriptler:

        if "Infrastructure" in script:

            infrastructure_url = urljoin(
                BASE_URL,
                script
            )

            break

    if infrastructure_url is None:

        infrastructure_url = (
            BASE_URL
            + "/js/Infrastructure.enxa2bxk74.js"
        )

    print(
        "Infrastructure:",
        infrastructure_url
    )

    js_response = get_url(
        infrastructure_url
    )

    js = js_response.text

    eslesme = re.search(
        r'kvkkbaseurl\s*[:=]\s*["\']([^"\']+)',
        js,
        re.IGNORECASE
    )

    if eslesme:

        rss_base = eslesme.group(1)

    else:

        rss_base = (
            BASE_URL
            + "/"
        )

    if not rss_base.endswith("/"):

        rss_base += "/"

    return rss_base + "RSS"


# ============================================================
# RSS OKUMA
# ============================================================

def rss_oku(content):

    if isinstance(content, bytes):

        content = content.decode(
            "utf-8-sig",
            errors="replace"
        )

    else:

        content = content.lstrip(
            "\ufeff"
        )

    root = ET.fromstring(
        content
    )

    ilanlar = []

    # --------------------------------------------------------
    # RSS
    # --------------------------------------------------------

    for item in root.findall(
        ".//item"
    ):

        title = item.findtext(
            "title",
            ""
        )

        link = item.findtext(
            "link",
            ""
        )

        description = item.findtext(
            "description",
            ""
        )

        guid = item.findtext(
            "guid",
            ""
        )

        ilan_id = (
            guid
            or link
            or title
            or ""
        ).strip()

        ilanlar.append(
            {
                "id": ilan_id,
                "title": html.unescape(
                    title or ""
                ).strip(),
                "description": html.unescape(
                    description or ""
                ).strip(),
                "link": (
                    link or ""
                ).strip()
            }
        )

    # --------------------------------------------------------
    # ATOM
    # --------------------------------------------------------

    if not ilanlar:

        namespace = {
            "atom":
            "http://www.w3.org/2005/Atom"
        }

        entries = root.findall(
            ".//atom:entry",
            namespace
        )

        for entry in entries:

            title = entry.findtext(
                "atom:title",
                "",
                namespace
            )

            summary = entry.findtext(
                "atom:summary",
                "",
                namespace
            )

            entry_id = entry.findtext(
                "atom:id",
                "",
                namespace
            )

            link = ""

            link_element = entry.find(
                "atom:link",
                namespace
            )

            if link_element is not None:

                link = link_element.attrib.get(
                    "href",
                    ""
                )

            ilan_id = (
                entry_id
                or link
                or title
                or ""
            ).strip()

            ilanlar.append(
                {
                    "id": ilan_id,
                    "title": html.unescape(
                        title or ""
                    ).strip(),
                    "description": html.unescape(
                        summary or ""
                    ).strip(),
                    "link": link.strip()
                }
            )

    return ilanlar


# ============================================================
# NORMALİZASYON
# ============================================================

def normalize(text):

    text = text.lower()

    karakterler = {
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c"
    }

    for eski, yeni in karakterler.items():

        text = text.replace(
            eski,
            yeni
        )

    return text


# ============================================================
# DAHA ÖNCE GÖNDERİLENLER
# ============================================================

def gonderilenleri_oku():

    if not os.path.exists(
        GONDERILEN_DOSYA
    ):

        return set()

    try:

        with open(
            GONDERILEN_DOSYA,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )

        return set(data)

    except Exception:

        return set()


def gonderilenleri_kaydet(
    gonderilenler
):

    with open(
        GONDERILEN_DOSYA,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            sorted(
                gonderilenler
            ),
            file,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# KPSS PUANINI BUL
# ============================================================

def kpss_taban_puani_bul(text):

    temiz = normalize(
        text
    )

    # "KPSS 70"
    eslesme = re.search(
        r"kpss.{0,40}?(?:puan|puanı|puani)?[^0-9]{0,10}(\d{2}(?:[.,]\d+)?)",
        temiz
    )

    if eslesme:

        try:

            return float(
                eslesme.group(1).replace(
                    ",",
                    "."
                )
            )

        except ValueError:

            pass

    # "en az 70 KPSS"
    eslesme = re.search(
        r"(?:en az|minimum|min|taban).{0,30}?(\d{2}(?:[.,]\d+)?).{0,30}?kpss",
        temiz
    )

    if eslesme:

        try:

            return float(
                eslesme.group(1).replace(
                    ",",
                    "."
                )
            )

        except ValueError:

            pass

    return None


# ============================================================
# EĞİTİM DÜZEYİ
# ============================================================

def onlisans_ilan_mi(text):

    temiz = normalize(
        text
    )

    ifadeler = [

        "onlisans",

        "on lisans",

        "on-lisans",

        "on lisans mezunu",

        "2 yillik",

        "iki yillik",

        "meslek yuksekokulu",

        "myo"
    ]

    for ifade in ifadeler:

        if ifade in temiz:

            return True

    return False


# ============================================================
# ADALET İLE İLGİLİ Mİ?
# ============================================================

def adalet_ile_ilgili_mi(text):

    temiz = normalize(
        text
    )

    kelimeler = [

        "adalet",

        "hukuk",

        "icra",

        "icra mudurlugu",

        "icra mudur",

        "katip",

        "zabit katibi",

        "zabita katibi",

        "yazi isleri",

        "mahkeme",

        "adalet bakanligi",

        "infaz"
    ]

    for kelime in kelimeler:

        if kelime in temiz:

            return True

    return False


# ============================================================
# İLAN UYGUNLUK KONTROLÜ
# ============================================================

def ilan_uygun_mu(ilan):

    baslik = ilan[
        "title"
    ]

    aciklama = ilan[
        "description"
    ]

    text = normalize(
        baslik
        + " "
        + aciklama
    )

    # --------------------------------------------------------
    # KPSS TABAN PUANI
    # --------------------------------------------------------

    taban = kpss_taban_puani_bul(
        text
    )

    if taban is not None:

        print(
            "KPSS taban puanı:",
            taban,
            "-",
            baslik
        )

        if taban > KPSS_PUANI:

            return False

    # --------------------------------------------------------
    # ADALET / HUKUK İLANLARI
    # --------------------------------------------------------

    if adalet_ile_ilgili_mi(
        text
    ):

        return True

    # --------------------------------------------------------
    # ÖNLİSANS İLANLARI
    # --------------------------------------------------------

    if onlisans_ilan_mi(
        text
    ):

        return True

    # --------------------------------------------------------
    # "HERHANGİ BİR ÖNLİSANS"
    # --------------------------------------------------------

    genel_onlisans = [

        "herhangi bir onlisans",

        "herhangi bir on lisans",

        "herhangi bir onlisans programindan",

        "herhangi bir on lisans programindan",

        "onlisans mezunu olmak"
    ]

    for ifade in genel_onlisans:

        if ifade in text:

            return True

    return False


# ============================================================
# TELEGRAM
# ============================================================

def telegram_gonder(
    mesaj
):

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    data = {

        "chat_id":
            TELEGRAM_CHAT_ID,

        "text":
            mesaj,

        "disable_web_page_preview":
            False
    }

    response = requests.post(
        url,
        data=data,
        timeout=30
    )

    print(
        "Telegram HTTP:",
        response.status_code
    )

    response.raise_for_status()


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def telegram_mesaji(
    ilan
):

    aciklama = ilan[
        "description"
    ]

    if len(aciklama) > 2500:

        aciklama = (
            aciklama[:2500]
            + "..."
        )

    mesaj = (

        "🔔 YENİ UYGUN KAMU İLANI\n\n"

        "📌 "
        + ilan["title"]
        + "\n\n"

        "📝 "
        + aciklama
        + "\n\n"

        "🔗 "
        + ilan["link"]
    )

    return mesaj


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    print("")
    print(
        "======================================"
    )

    print(
        "KAMU İLAN TAKİP BAŞLIYOR"
    )

    print(
        "KPSS puanı:",
        KPSS_PUANI
    )

    print(
        "======================================"
    )

    # --------------------------------------------------------
    # RSS
    # --------------------------------------------------------

    rss_url = rss_adresini_bul()

    print(
        "RSS:",
        rss_url
    )

    response = get_url(
        rss_url
    )

    print(
        "RSS HTTP:",
        response.status_code
    )

    print(
        "RSS uzunluğu:",
        len(response.content)
    )

    # --------------------------------------------------------
    # İLANLAR
    # --------------------------------------------------------

    ilanlar = rss_oku(
        response.content
    )

    print(
        "Toplam ilan:",
        len(ilanlar)
    )

    # --------------------------------------------------------
    # GÖNDERİLENLER
    # --------------------------------------------------------

    gonderilenler = (
        gonderilenleri_oku()
    )

    yeni_gonderilenler = set(
        gonderilenler
    )

    uygun_sayisi = 0

    telegram_sayisi = 0

    # --------------------------------------------------------
    # TARAMA
    # --------------------------------------------------------

    for ilan in ilanlar:

        if not ilan["id"]:

            ham = (
                ilan["title"]
                + ilan["description"]
                + ilan["link"]
            )

            ilan["id"] = hashlib.sha256(
                ham.encode(
                    "utf-8"
                )
            ).hexdigest()

        if ilan["id"] in gonderilenler:

            continue

        uygun = ilan_uygun_mu(
            ilan
        )

        if not uygun:

            continue

        uygun_sayisi += 1

        print("")
        print(
            "======================================"
        )

        print(
            "UYGUN İLAN"
        )

        print(
            "Başlık:",
            ilan["title"]
        )

        print(
            "Link:",
            ilan["link"]
        )

        print(
            "======================================"
        )

        try:

            mesaj = telegram_mesaji(
                ilan
            )

            telegram_gonder(
                mesaj
            )

            yeni_gonderilenler.add(
                ilan["id"]
            )

            telegram_sayisi += 1

            print(
                "Telegram mesajı gönderildi."
            )

        except Exception as hata:

            print(
                "Telegram gönderim hatası:"
            )

            print(
                hata
            )

    # --------------------------------------------------------
    # KAYDET
    # --------------------------------------------------------

    gonderilenleri_kaydet(
        yeni_gonderilenler
    )

    # --------------------------------------------------------
    # SONUÇ
    # --------------------------------------------------------

    print("")
    print(
        "======================================"
    )

    print(
        "TARAMA TAMAMLANDI"
    )

    print(
        "Toplam ilan:",
        len(ilanlar)
    )

    print(
        "Uygun yeni ilan:",
        uygun_sayisi
    )

    print(
        "Telegram'a gönderilen:",
        telegram_sayisi
    )

    print(
        "======================================"
    )


# ============================================================
# BAŞLAT
# ============================================================

if __name__ == "__main__":

    main()
