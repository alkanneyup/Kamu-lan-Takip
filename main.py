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
YAS = 29

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

GONDERILEN_DOSYA = "sent_ids.json"

USER_AGENT = "Kamu-Ilan-Takip/3.0"

REQUEST_TIMEOUT = 30


# ============================================================
# HTTP
# ============================================================

def get_url(url):

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response


# ============================================================
# NORMALİZASYON
# ============================================================

def normalize(text):

    if not text:
        return ""

    text = html.unescape(str(text))

    text = text.lower()

    karakterler = {
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
    }

    for eski, yeni in karakterler.items():
        text = text.replace(eski, yeni)

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# ============================================================
# RSS ADRESİNİ BUL
# ============================================================

def rss_adresini_bul():

    print("")
    print("=== RSS ADRESİ BULMA ===")

    sayfa_url = (
        BASE_URL
        + "/RSS/RssLinkiAl"
    )

    print(
        "[HTTP]",
        sayfa_url
    )

    response = get_url(
        sayfa_url
    )

    print(
        "[HTTP]",
        response.status_code,
        "|",
        len(response.content),
        "byte"
    )

    sayfa = response.text

    scriptler = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        sayfa,
        re.IGNORECASE,
    )

    print(
        "[RSS] Script sayısı:",
        len(scriptler)
    )

    infrastructure_url = None

    for script in scriptler:

        if "Infrastructure" in script:

            infrastructure_url = urljoin(
                BASE_URL,
                script,
            )

            break

    if not infrastructure_url:

        infrastructure_url = (
            BASE_URL
            + "/js/Infrastructure.enxa2bxk74.js"
        )

    print(
        "[RSS] Infrastructure:",
        infrastructure_url
    )

    js_response = get_url(
        infrastructure_url
    )

    js = js_response.text

    # kvkkbaseurl
    eslesme = re.search(
        r'kvkkbaseurl\s*[:=]\s*["\']([^"\']+)',
        js,
        re.IGNORECASE,
    )

    if eslesme:

        rss_base = eslesme.group(1)

    else:

        rss_base = BASE_URL + "/"

    if not rss_base.endswith("/"):
        rss_base += "/"

    rss_url = (
        rss_base
        + "RSS"
    )

    print(
        "[RSS] Son RSS adresi:",
        rss_url
    )

    return rss_url


# ============================================================
# RSS OKUMA
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

        content = str(content).lstrip(
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
            "",
        )

        link = item.findtext(
            "link",
            "",
        )

        description = item.findtext(
            "description",
            "",
        )

        guid = item.findtext(
            "guid",
            "",
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
            ).strip(),
        }

        ilanlar.append(
            ilan
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
            namespace,
        )

        for entry in entries:

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
                ).strip(),
            }

            ilanlar.append(
                ilan
            )

    print(
        "[RSS] Toplam ilan:",
        len(ilanlar)
    )

    return ilanlar


# ============================================================
# GÖNDERİLEN İLANLAR
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
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

        if isinstance(
            data,
            list,
        ):

            return set(
                str(x)
                for x in data
            )

        return set()

    except Exception as exc:

        print(
            "[UYARI] sent_ids.json okunamadı:",
            exc,
        )

        return set()


def gonderilenleri_kaydet(
    gonderilenler
):

    try:

        with open(
            GONDERILEN_DOSYA,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                sorted(
                    gonderilenler
                ),
                file,
                ensure_ascii=False,
                indent=2,
            )

        print(
            "[KAYIT] sent_ids.json güncellendi."
        )

    except Exception as exc:

        print(
            "[HATA] sent_ids.json yazılamadı:",
            exc,
        )


# ============================================================
# YARDIMCI METİN FONKSİYONLARI
# ============================================================

def ilan_metni(ilan):

    return normalize(
        (
            ilan.get(
                "title",
                "",
            )
            + " "
            + ilan.get(
                "description",
                "",
            )
        )
    )


def ilk_sayi(text):

    if not text:
        return None

    eslesme = re.search(
        r"\d{1,3}(?:[.,]\d+)?",
        text,
    )

    if not eslesme:
        return None

    try:

        return float(
            eslesme.group(0).replace(
                ",",
                ".",
            )
        )

    except ValueError:

        return None


# ============================================================
# KPSS ANALİZİ
# ============================================================

def kpss_analiz(text):

    sonuc = {
        "var": False,
        "taban": None,
        "puan_turu": None,
        "neden": [],
    }

    if "kpss" not in text:

        sonuc["neden"].append(
            "KPSS şartı tespit edilmedi."
        )

        return sonuc

    sonuc["var"] = True

    # --------------------------------------------------------
    # PUAN TÜRÜ
    # --------------------------------------------------------

    puan_turu = re.search(
        r"\b(p\d{2})\b",
        text,
        re.IGNORECASE,
    )

    if puan_turu:

        sonuc["puan_turu"] = (
            puan_turu.group(1).upper()
        )

    # --------------------------------------------------------
    # KPSS'NİN ÇEVRESİNDEKİ SAYILARI ARA
    # --------------------------------------------------------

    adaylar = []

    for eslesme in re.finditer(
        r".{0,100}kpss.{0,150}",
        text,
        re.IGNORECASE,
    ):

        parca = eslesme.group(0)

        sayilar = re.findall(
            r"\b\d{2}(?:[.,]\d+)?\b",
            parca,
        )

        for sayi in sayilar:

            try:

                puan = float(
                    sayi.replace(
                        ",",
                        ".",
                    )
                )

            except ValueError:

                continue

            if 40 <= puan <= 100:

                adaylar.append(
                    puan
                )

    if adaylar:

        # Genellikle ilandaki ilk anlamlı
        # KPSS taban puanı kullanılır.
        sonuc["taban"] = min(
            adaylar
        )

    if sonuc["taban"] is not None:

        if sonuc["taban"] <= KPSS_PUANI:

            sonuc["neden"].append(
                f"KPSS tabanı {sonuc['taban']}; "
                f"puanınız {KPSS_PUANI}."
            )

        else:

            sonuc["neden"].append(
                f"KPSS tabanı {sonuc['taban']}; "
                f"puanınız {KPSS_PUANI} yetersiz."
            )

    else:

        sonuc["neden"].append(
            "KPSS şartı var ancak taban puan otomatik tespit edilemedi."
        )

    return sonuc


# ============================================================
# ÖĞRENİM ANALİZİ
# ============================================================

def egitim_analiz(text):

    sonuc = {
        "uygun": True,
        "kesin_uygun": False,
        "belirsiz": False,
        "neden": [],
    }

    # --------------------------------------------------------
    # LİSANS / YÜKSEK LİSANS / DOKTORA
    # --------------------------------------------------------

    if (
        "lisans mezunu olmak"
        in text
        or "lisans mezuniyet"
        in text
    ):

        sonuc["uygun"] = False

        sonuc["neden"].append(
            "İlan lisans mezuniyeti istiyor."
        )

        return sonuc

    # --------------------------------------------------------
    # AÇIKÇA HERHANGİ BİR ÖNLİSANS
    # --------------------------------------------------------

    genel_onlisans = [
        "herhangi bir onlisans",
        "herhangi bir on lisans",
        "onlisans mezunu olmak",
        "on lisans mezunu olmak",
        "onlisans programlarindan",
        "on lisans programlarindan",
        "onlisans mezunlarindan",
        "on lisans mezunlarindan",
    ]

    for ifade in genel_onlisans:

        if ifade in text:

            sonuc["kesin_uygun"] = True

            sonuc["neden"].append(
                "Herhangi bir önlisans mezuniyeti kabul ediliyor."
            )

            return sonuc

    # --------------------------------------------------------
    # ADALET
    # --------------------------------------------------------

    adalet_ifadeleri = [
        "adalet onlisans",
        "adalet on lisans",
        "adalet programi",
        "adalet bolumu",
        "adalet mezunu",
    ]

    for ifade in adalet_ifadeleri:

        if ifade in text:

            sonuc["kesin_uygun"] = True

            sonuc["neden"].append(
                "Adalet önlisans mezuniyeti uygun görünüyor."
            )

            return sonuc

    # --------------------------------------------------------
    # SADECE ÖNLİSANS GEÇİYORSA
    # --------------------------------------------------------

    if (
        "onlisans"
        in text
        or "on lisans"
        in text
    ):

        sonuc["belirsiz"] = True

        sonuc["neden"].append(
            "Önlisans şartı bulunuyor; bölüm/nitelik ayrıntısı otomatik olarak kesinleştirilemedi."
        )

        return sonuc

    # --------------------------------------------------------
    # EĞİTİM BİLGİSİ YOK
    # --------------------------------------------------------

    sonuc["belirsiz"] = True

    sonuc["neden"].append(
        "Eğitim şartı otomatik olarak tespit edilemedi."
    )

    return sonuc


# ============================================================
# BÖLÜM ANALİZİ
# ============================================================

def bolum_analiz(text):

    sonuc = {
        "uygun": True,
        "belirsiz": False,
        "neden": [],
    }

    # --------------------------------------------------------
    # ADALET AÇIKÇA İSTENİYOR
    # --------------------------------------------------------

    adalet = [
        "adalet bolumu",
        "adalet programi",
        "adalet mezunu",
        "adalet onlisans",
        "adalet on lisans",
    ]

    for ifade in adalet:

        if ifade in text:

            sonuc["neden"].append(
                "İlanda Adalet mezuniyeti kabul ediliyor."
            )

            return sonuc

    # --------------------------------------------------------
    # BÖLÜM SINIRLAMASI YOK
    # --------------------------------------------------------

    genel = [
        "herhangi bir onlisans",
        "herhangi bir on lisans",
        "herhangi bir yuksekogretim",
        "herhangi bir bolum",
        "bolum sarti aranmaksizin",
        "alan sarti aranmaksizin",
        "brans sarti aranmaksizin",
    ]

    for ifade in genel:

        if ifade in text:

            sonuc["neden"].append(
                "Belirli bir bölüm şartı bulunmuyor."
            )

            return sonuc

    # --------------------------------------------------------
    # BAŞKA BİR BÖLÜM İSTENİYOR
    # --------------------------------------------------------

    belirgin_bolumler = [
        "bilgisayar programciligi",
        "bilgisayar muhendisligi",
        "elektrik elektronik",
        "muhasebe",
        "isletme",
        "iktisat",
        "maliye",
        "cocuk gelisimi",
        "sosyal hizmet",
        "laborant",
        "anestezi",
        "ilk ve acil yardim",
        "tibbi dokumantasyon",
    ]

    bulunanlar = []

    for bolum in belirgin_bolumler:

        if bolum in text:

            bulunanlar.append(
                bolum
            )

    if bulunanlar:

        sonuc["uygun"] = False

        sonuc["neden"].append(
            "İlan farklı bir bölüm/nitelik istiyor: "
            + ", ".join(bulunanlar)
        )

        return sonuc

    # --------------------------------------------------------
    # OTOMATİK OLARAK KESİNLEŞTİRİLEMEYEN
    # --------------------------------------------------------

    sonuc["belirsiz"] = True

    sonuc["neden"].append(
        "Bölüm şartı otomatik olarak kesinleştirilemedi."
    )

    return sonuc


# ============================================================
# CİNSİYET
# ============================================================

def cinsiyet_analiz(text):

    neden = []

    erkek_ifadeleri = [
        "erkek olmak",
        "erkek aday",
        "erkek adaylar",
        "sadece erkek",
    ]

    kadin_ifadeleri = [
        "kadin olmak",
        "kadın olmak",
        "kadin aday",
        "kadın adaylar",
        "sadece kadin",
        "sadece kadın",
    ]

    for ifade in kadin_ifadeleri:

        if ifade in text:

            if CINSIYET == "erkek":

                return {
                    "uygun": False,
                    "belirsiz": False,
                    "neden": [
                        "İlan yalnızca kadın aday kabul ediyor."
                    ],
                }

    for ifade in erkek_ifadeleri:

        if ifade in text:

            if CINSIYET == "erkek":

                neden.append(
                    "Erkek aday şartı profilinizle uyumlu."
                )

                return {
                    "uygun": True,
                    "belirsiz": False,
                    "neden": neden,
                }

    return {
        "uygun": True,
        "belirsiz": False,
        "neden": [
            "Cinsiyet açısından engel tespit edilmedi."
        ],
    }


# ============================================================
# YAŞ ANALİZİ
# ============================================================

def yas_analiz(text):

    # 35 yaşını doldurmamış olmak
    eslesmeler = re.findall(
        r"(\d{2})\s*yas(?:ini|ını)?\s*doldurmamis",
        text,
    )

    for sinir in eslesmeler:

        try:
            sinir = int(sinir)

            if YAS >= sinir:

                return {
                    "uygun": False,
                    "belirsiz": False,
                    "neden": [
                        f"Yaş sınırı {sinir}; mevcut yaşınız {YAS}."
                    ],
                }

            return {
                "uygun": True,
                "belirsiz": False,
                "neden": [
                    f"Yaş sınırı {sinir}; mevcut yaşınız {YAS}."
                ],
            }

        except ValueError:
            pass

    # 30 yaşını geçmemiş
    eslesmeler = re.findall(
        r"(\d{2})\s*yasini\s*gecmemis",
        text,
    )

    for sinir in eslesmeler:

        try:

            sinir = int(sinir)

            if YAS > sinir:

                return {
                    "uygun": False,
                    "belirsiz": False,
                    "neden": [
                        f"Yaş sınırı {sinir}; mevcut yaşınız {YAS}."
                    ],
                }

        except ValueError:
            pass

    return {
        "uygun": True,
        "belirsiz": False,
        "neden": [
            "Yaş açısından kesin bir engel tespit edilmedi."
        ],
    }


# --------------------------------------------------------
    # ASKERLİK
    # --------------------------------------------------------

    askerlik = askerlik_analiz(
        text
    )

    neden.extend(
        askerlik["neden"]
    )

    # --------------------------------------------------------
    # BELİRSİZLİK KONTROLÜ
    # --------------------------------------------------------

    belirsiz = (
        egitim["belirsiz"]
        or bolum["belirsiz"]
        or askerlik["belirsiz"]
    )

    if belirsiz:

        return {
            "durum": "MANUEL_INCELEME",
            "kpss": kpss["var"],
            "taban": kpss["taban"],
            "neden": neden,
        }

    # --------------------------------------------------------
    # UYGUN
    # --------------------------------------------------------

    return {
        "durum": "UYGUN",
        "kpss": kpss["var"],
        "taban": kpss["taban"],
        "neden": neden,
    }


# ============================================================
# TELEGRAM
# ============================================================

def telegram_gonder(mesaj):

    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN bulunamadı."
        )

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID bulunamadı."
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
        timeout=REQUEST_TIMEOUT,
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

def telegram_mesaji(
    ilan,
    analiz,
):

    aciklama = ilan.get(
        "description",
        "",
    )

    if len(aciklama) > 2200:

        aciklama = (
            aciklama[:2200]
            + "..."
        )

    durum = analiz.get(
        "durum",
        "MANUEL_INCELEME",
    )

    if durum == "UYGUN":

        baslik = (
            "🟢 BAŞVURABİLİRSİN"
        )

    else:

        baslik = (
            "🟡 MANUEL İNCELEME"
        )

    if analiz.get("kpss"):

        if analiz.get("taban") is not None:

            kpss_text = (
                "Var | Taban: "
                + str(
                    analiz["taban"]
                )
            )

        else:

            kpss_text = (
                "Var | Taban otomatik tespit edilemedi"
            )

    else:

        kpss_text = (
            "KPSS şartı tespit edilmedi"
        )

    nedenler = "\n".join(
        "• " + x
        for x in analiz.get(
            "neden",
            [],
        )
    )

    return (
        "🔔 KAMU İLAN TAKİP\n\n"

        + baslik
        + "\n\n"

        + "📌 "
        + ilan.get(
            "title",
            "",
        )
        + "\n\n"

        + "🎓 Öğrenim: "
        + OGRENIM
        + "\n"

        + "⚖️ Bölüm: "
        + BOLUM
        + "\n"

        + "👤 Cinsiyet: "
        + CINSIYET
        + "\n"

        + "🧑 Yaş: "
        + str(YAS)
        + "\n"

        + "📊 KPSS: "
        + kpss_text
        + "\n\n"

        + "🔎 ANALİZ\n"
        + (
            nedenler
            or
            "Şartlar uygun görünüyor."
        )
        + "\n\n"

        + "📝 AÇIKLAMA\n"
        + aciklama
        + "\n\n"

        + "🔗 "
        + ilan.get(
            "link",
            "",
        )
    )


# ============================================================
# İLAN ID
# ============================================================

def ilan_id_uret(ilan):

    mevcut = ilan.get(
        "id",
        "",
    ).strip()

    if mevcut:
        return mevcut

    ham = (
        ilan.get(
            "title",
            "",
        )
        + "|"
        + ilan.get(
            "link",
            "",
        )
        + "|"
        + ilan.get(
            "description",
            "",
        )
    )

    return hashlib.sha256(
        ham.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    print("")
    print("=" * 50)
    print(
        "KAMU İLAN TAKİP BAŞLIYOR"
    )
    print(
        f"KPSS puanı: {KPSS_PUANI}"
    )
    print(
        f"Öğrenim: {OGRENIM}"
    )
    print(
        f"Bölüm: {BOLUM}"
    )
    print(
        f"Cinsiyet: {CINSIYET}"
    )
    print(
        f"Yaş: {YAS}"
    )
    print("=" * 50)

    # --------------------------------------------------------
    # ENV
    # --------------------------------------------------------

    print("")
    print(
        "=== ORTAM KONTROLÜ ==="
    )

    print(
        "TELEGRAM_TOKEN:",
        "VAR"
        if TELEGRAM_TOKEN
        else "YOK",
    )

    print(
        "TELEGRAM_CHAT_ID:",
        "VAR"
        if TELEGRAM_CHAT_ID
        else "YOK",
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
    # RSS ADRESİ
    # --------------------------------------------------------

    try:

        rss_url = rss_adresini_bul()

        response = get_url(
            rss_url
        )

        print(
            "[HTTP]",
            response.status_code,
            "|",
            len(response.content),
            "byte"
        )

    except Exception as exc:

        print("")
        print(
            "!!! RSS HATASI !!!"
        )

        print(
            repr(exc)
        )

        return

    # --------------------------------------------------------
    # RSS PARSE
    # --------------------------------------------------------

    try:

        ilanlar = rss_oku(
            response.content
        )

    except Exception as exc:

        print("")
        print(
            "!!! RSS PARSE HATASI !!!"
        )

        print(
            repr(exc)
        )

        return

    if not ilanlar:

        print("")
        print(
            "[HATA] Hiç ilan okunamadı."
        )

        return

    # --------------------------------------------------------
    # GÖNDERİLENLER
    # --------------------------------------------------------

    gonderilenler = (
        gonderilenleri_oku()
    )

    yeni_gonderilenler = set(
        gonderilenler
    )

    # --------------------------------------------------------
    # SAYACLAR
    # --------------------------------------------------------

    uygun_sayisi = 0
    manuel_sayisi = 0
    basvuramaz_sayisi = 0
    telegram_sayisi = 0

    # --------------------------------------------------------
    # ANALİZ
    # --------------------------------------------------------

    print("")
    print("=" * 50)
    print(
        "İLAN ANALİZLERİ"
    )
    print("=" * 50)

    for sira, ilan in enumerate(
        ilanlar,
        1,
    ):

        print("")
        print(
            f"[{sira}/{len(ilanlar)}] "
            f"{ilan.get('title', '')}"
        )

        try:

            analiz = ilan_analiz_et(
                ilan
            )

        except Exception as exc:

            print(
                "[ANALİZ HATASI]",
                repr(exc),
            )

            continue

        durum = analiz.get(
            "durum",
            "MANUEL_INCELEME",
        )

        print(
            "Durum:",
            durum,
        )

        if durum == "UYGUN":

            uygun_sayisi += 1

        elif durum == "MANUEL_INCELEME":

            manuel_sayisi += 1

        elif durum == "BASVURAMAZSIN":

            basvuramaz_sayisi += 1

        # ----------------------------------------------------
        # SADECE UYGUN / MANUEL
        # ----------------------------------------------------

        if durum not in (
            "UYGUN",
            "MANUEL_INCELEME",
        ):

            continue

        ilan_id = ilan_id_uret(
            ilan
        )

        if ilan_id in gonderilenler:

            print(
                "Telegram: DAHA ÖNCE GÖNDERİLDİ"
            )

            continue

        # ----------------------------------------------------
        # TELEGRAM
        # ----------------------------------------------------

        try:

            mesaj = telegram_mesaji(
                ilan,
                analiz,
            )

            telegram_gonder(
                mesaj
            )

            yeni_gonderilenler.add(
                ilan_id
            )

            telegram_sayisi += 1

            print(
                "Telegram: GÖNDERİLDİ"
            )

        except Exception as exc:

            print(
                "Telegram: GÖNDERİM HATASI"
            )

            print(
                repr(exc)
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
    print("=" * 50)
    print(
        "TARAMA TAMAMLANDI"
    )
    print("=" * 50)

    print(
        "Toplam ilan:",
        len(ilanlar),
    )

    print(
        "🟢 Başvurabilir:",
        uygun_sayisi,
    )

    print(
        "🟡 Manuel inceleme:",
        manuel_sayisi,
    )

    print(
        "🔴 Başvuramaz:",
        basvuramaz_sayisi,
    )

    print(
        "📨 Telegram'a gönderilen:",
        telegram_sayisi,
    )

    print("=" * 50)


# ============================================================
# BAŞLAT
# ============================================================

if __name__ == "__main__":
    main()
