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
# RSS ADRESİNİ BUL
# ============================================================

def rss_adresini_bul():

    print("Kariyer Kapısı RSS sayfası okunuyor...")

    rss_sayfasi = BASE_URL + "/RSS/RssLinkiAl"

    response = get_url(rss_sayfasi)

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

        print(
            "Infrastructure dosyası bulunamadı."
        )

        # Daha önce tespit ettiğimiz dosyayı kullan
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

    # kvkkbaseurl değerini bul
    eslesme = re.search(
        r'kvkkbaseurl\s*[:=]\s*["\']([^"\']+)',
        js,
        re.IGNORECASE
    )

    if eslesme:

        rss_base = eslesme.group(1)

    else:

        # Kariyer Kapısı'nın mevcut yapısı
        rss_base = BASE_URL + "/"

    if not rss_base.endswith("/"):

        rss_base += "/"

    rss_url = rss_base + "RSS"

    return rss_url


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
    # RSS FORMAT
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

        ilan = {

            "title": html.unescape(
                title or ""
            ).strip(),

            "link": (
                link or ""
            ).strip(),

            "description": html.unescape(
                description or ""
            ).strip(),

            "id": (
                guid
                or link
                or title
                or ""
            ).strip()
        }

        ilanlar.append(
            ilan
        )

    # --------------------------------------------------------
    # ATOM FORMAT
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

            ilan = {

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
                ).strip()
            }

            ilanlar.append(
                ilan
            )

    return ilanlar


# ============================================================
# DAHA ÖNCE GÖNDERİLEN İLANLAR
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
# TÜRKÇE NORMALİZASYON
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
# İLAN UYGUNLUK KONTROLÜ
# ============================================================

def ilan_uygun_mu(ilan):

    text = normalize(
        ilan["title"]
        + " "
        + ilan["description"]
    )

    # --------------------------------------------------------
    # ADALET / HUKUK ALANI
    # --------------------------------------------------------

    alanlar = [

        "adalet",

        "hukuk",

        "icra",

        "katip",

        "zabit katibi",

        "zabita katibi",

        "yazi isleri",

        "mahkeme",

        "icra mudurlugu",

        "icra mudur",

        "adalet bakanligi"
    ]

    alan_uygun = False

    for kelime in alanlar:

        if kelime in text:

            alan_uygun = True

            break

    if not alan_uygun:

        return False

    # --------------------------------------------------------
    # ÖNLİSANS / ADALET
    # --------------------------------------------------------

    egitimler = [

        "onlisans",

        "on lisans",

        "adalet programi",

        "adalet bolumu",

        "adalet mezunu"
    ]

    egitim_uygun = False

    for kelime in egitimler:

        if kelime in text:

            egitim_uygun = True

            break

    # --------------------------------------------------------
    # KPSS
    # --------------------------------------------------------

    kpss_var = "kpss" in text

    if not egitim_uygun and not kpss_var:

        return False

    # --------------------------------------------------------
    # TABAN PUAN KONTROLÜ
    # --------------------------------------------------------

    # Burada karmaşık regex kullanmıyoruz.
    #
    # Örneğin:
    # "KPSS 70 puan"
    # "KPSS'den en az 70"
    #
    # gibi ifadelerde 70 değerini yakalamaya çalışıyoruz.

    sayilar = re.findall(
        r"\b\d{2}(?:[.,]\d+)?\b",
        text
    )

    for sayi in sayilar:

        try:

            puan = float(
                sayi.replace(
                    ",",
                    "."
                )
            )

        except ValueError:

            continue

        # 50-100 arası sayıları puan adayı olarak değerlendir
        if 50 <= puan <= 100:

            yakin_baslik = text[
                max(
                    0,
                    text.find(sayi) - 80
                ):
                text.find(sayi) + 80
            ]

            if (
                "kpss" in yakin_baslik
                and puan > KPSS_PUANI
            ):

                return False

    # --------------------------------------------------------
    # BAŞVURU KAPANMIŞ MI?
    # --------------------------------------------------------

    kapanmis_ifadeler = [

        "basvurular sona ermistir",

        "basvuru sona ermistir",

        "basvuru suresi dolmustur",

        "son basvuru tarihi gecmistir",

        "basvuruya kapalidir"
    ]

    for ifade in kapanmis_ifadeler:

        if ifade in text:

            return False

    return True


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

    if len(aciklama) > 1800:

        aciklama = (
            aciklama[:1800]
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
    # RSS ADRESİ
    # --------------------------------------------------------

    rss_url = rss_adresini_bul()

    print(
        "RSS:",
        rss_url
    )

    # --------------------------------------------------------
    # RSS'İ İNDİR
    # --------------------------------------------------------

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
    # İLANLARI OKU
    # --------------------------------------------------------

    ilanlar = rss_oku(
        response.content
    )

    print(
        "Toplam ilan:",
        len(ilanlar)
    )

    # --------------------------------------------------------
    # DAHA ÖNCE GÖNDERİLENLER
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
    # İLANLARI KONTROL ET
    # --------------------------------------------------------

    for ilan in ilanlar:

        # ID yoksa hash üret
        if not ilan["id"]:

            ham_veri = (

                ilan["title"]
                + ilan["link"]
                + ilan["description"]
            )

            ilan["id"] = hashlib.sha256(
                ham_veri.encode(
                    "utf-8"
                )
            ).hexdigest()

        # Daha önce gönderilmiş
        if ilan["id"] in gonderilenler:

            continue

        # Uygun değil
        if not ilan_uygun_mu(
            ilan
        ):

            continue

        uygun_sayisi += 1

        print("")
        print(
            "UYGUN İLAN:"
        )

        print(
            ilan["title"]
        )

        # ----------------------------------------------------
        # TELEGRAM
        # ----------------------------------------------------

        try:

            mesaj = telegram_mesaji(
                ilan
            )

            telegram_gonder(
                mesaj
            )

            print(
                "Telegram mesajı gönderildi."
            )

            yeni_gonderilenler.add(
                ilan["id"]
            )

            telegram_sayisi += 1

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
    

print("")
print("===== TÜM İLANLAR =====")

for i, ilan in enumerate(ilanlar, 1):

    print("")
    print(f"--- İLAN {i} ---")
    print("BAŞLIK:", ilan["title"])
    print("AÇIKLAMA:", ilan["description"][:1000])
    print("LINK:", ilan["link"])
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
# PROGRAMI BAŞLAT
# ============================================================

if __name__ == "__main__":

    main()
