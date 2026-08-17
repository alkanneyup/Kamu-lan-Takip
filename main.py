import os
import re
import json
import html
import hashlib
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin


# ============================================================
# PROFİL
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

USER_AGENT = "Kamu-Ilan-Takip/Final-1.0"
TIMEOUT = 30


# ============================================================
# HTTP
# ============================================================

def get_url(url):
    print("[HTTP]", url)

    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
        timeout=TIMEOUT,
    )

    print(
        "[HTTP]",
        response.status_code,
        "|",
        len(response.content),
        "byte",
    )

    response.raise_for_status()

    return response


# ============================================================
# NORMALİZASYON
# ============================================================

def normalize(text):
    if not text:
        return ""

    text = html.unescape(str(text)).lower()

    table = str.maketrans({
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
    })

    text = text.translate(table)

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

    sayfa = BASE_URL + "/RSS/RssLinkiAl"

    response = get_url(sayfa)

    scriptler = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        response.text,
        re.IGNORECASE,
    )

    print(
        "[RSS] Script sayısı:",
        len(scriptler),
    )

    infrastructure = None

    for script in scriptler:

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

    js_response = get_url(
        infrastructure
    )

    js = js_response.text

    eslesme = re.search(
        r'kvkkbaseurl\s*[:=]\s*["\']([^"\']+)',
        js,
        re.IGNORECASE,
    )

    if eslesme:

        base = eslesme.group(1)

    else:

        base = BASE_URL + "/"

    if not base.endswith("/"):

        base += "/"

    rss_url = base + "RSS"

    print(
        "[RSS] Son RSS adresi:",
        rss_url,
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

        content = str(
            content
        ).lstrip("\ufeff")

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
        ) or ""

        link = item.findtext(
            "link",
            "",
        ) or ""

        description = item.findtext(
            "description",
            "",
        ) or ""

        guid = item.findtext(
            "guid",
            "",
        ) or ""

        ilanlar.append({

            "title":
                html.unescape(
                    title
                ).strip(),

            "link":
                link.strip(),

            "description":
                html.unescape(
                    description
                ).strip(),

            "id":
                (
                    guid
                    or link
                    or title
                ).strip(),

        })

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
            ) or ""

            summary = entry.findtext(
                "atom:summary",
                "",
                namespace,
            ) or ""

            entry_id = entry.findtext(
                "atom:id",
                "",
                namespace,
            ) or ""

            link = ""

            link_element = entry.find(
                "atom:link",
                namespace,
            )

            if link_element is not None:

                link = (
                    link_element
                    .attrib
                    .get(
                        "href",
                        "",
                    )
                )

            ilanlar.append({

                "title":
                    html.unescape(
                        title
                    ).strip(),

                "link":
                    link.strip(),

                "description":
                    html.unescape(
                        summary
                    ).strip(),

                "id":
                    (
                        entry_id
                        or link
                        or title
                    ).strip(),

            })

    print(
        "[RSS] Toplam ilan:",
        len(ilanlar),
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

    except Exception as hata:

        print(
            "[UYARI] sent_ids okunamadı:",
            hata,
        )

    return set()


def gonderilenleri_kaydet(
    gonderilenler
):

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


# ============================================================
# İLAN ID
# ============================================================

def ilan_id(ilan):

    mevcut = ilan.get(
        "id",
        "",
    )

    if mevcut:

        return str(
            mevcut
        )

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
# İLAN METNİ
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


# ============================================================
# BAŞVURU TARİHİ
# ============================================================

def tarih_kontrol(text):

    kapanmis_ifadeler = [

        "basvurular sona ermistir",

        "basvuru sona ermistir",

        "basvuru suresi dolmustur",

        "basvuru suresi sona ermistir",

        "son basvuru tarihi gecmistir",

        "basvuruya kapalidir",

        "basvurular kapanmistir",

        "basvuru kapatilmistir",

    ]

    for ifade in kapanmis_ifadeler:

        if ifade in text:

            return (
                False,
                [
                    "Başvuru süresinin sona erdiğini belirten ifade bulundu."
                ],
            )

    return (
        True,
        [],
    )


# ============================================================
# KPSS
# ============================================================

def kpss_kontrol(text):

    if "kpss" not in text:

        return {
            "var": False,
            "taban": None,
            "puan_turu": None,
            "manuel": False,
            "neden": [
                "KPSS şartı tespit edilmedi."
            ],
        }

    puan_turu = None

    tur_match = re.search(
        r"\bP\s*([0-9]{2})\b",
        text,
        re.IGNORECASE,
    )

    if tur_match:

        puan_turu = (
            "P"
            + tur_match.group(1)
        )

    # KPSS kelimesinden sonraki yaklaşık
    # 250 karakter içinde bulunan 50-100
    # arası sayıları değerlendir.
    sayilar = []

    for match in re.finditer(
        r"kpss",
        text,
    ):

        bolge = text[
            match.start():
            match.start() + 300
        ]

        bulunan = re.findall(
            r"\b\d{2}(?:[.,]\d+)?\b",
            bolge,
        )

        for sayi in bulunan:

            try:

                deger = float(
                    sayi.replace(
                        ",",
                        ".",
                    )
                )

            except ValueError:

                continue

            if 50 <= deger <= 100:

                sayilar.append(
                    deger
                )

    if not sayilar:

        return {
            "var": True,
            "taban": None,
            "puan_turu": puan_turu,
            "manuel": True,
            "neden": [
                "KPSS şartı var ancak taban puan otomatik olarak belirlenemedi."
            ],
        }

    taban = min(
        sayilar
    )

    if taban > KPSS_PUANI:

        return {
            "var": True,
            "taban": taban,
            "puan_turu": puan_turu,
            "manuel": False,
            "neden": [
                (
                    f"KPSS tabanı {taban}; "
                    f"puanınız {KPSS_PUANI}. "
                    "Puan yetersiz."
                )
            ],
        }

    neden = [
        (
            f"KPSS tabanı {taban}; "
            f"puanınız {KPSS_PUANI}. "
            "Puan yeterli."
        )
    ]

    if puan_turu:

        neden.append(
            "Puan türü: "
            + puan_turu
        )

    return {
        "var": True,
        "taban": taban,
        "puan_turu": puan_turu,
        "manuel": False,
        "neden": neden,
    }


# ============================================================
# ÖĞRENİM
# ============================================================

def ogrenim_kontrol(text):

    # Lisans açıkça zorunluysa
    # önlisans mezunu için uygun değildir.

    lisans_zorunlu = [

        "lisans mezunu olmak",

        "lisans mezunlarindan",

        "lisans mezunlarından",

        "en az lisans",

        "lisans mezuniyeti",

    ]

    for ifade in lisans_zorunlu:

        if ifade in text:

            return {
                "ok": False,
                "manuel": False,
                "neden": [
                    "İlan lisans mezuniyeti istiyor."
                ],
            }

    # Herhangi bir önlisans
    # özellikle kabul edilmeli.

    genel_onlisans = [

        "herhangi bir onlisans",

        "herhangi bir on lisans",

        "herhangi bir onlisans programi",

        "herhangi bir on lisans programi",

        "onlisans mezunu olmak",

        "on lisans mezunu olmak",

        "onlisans mezunlarindan",

        "on lisans mezunlarindan",

        "onlisans mezuniyeti",

        "on lisans mezuniyeti",

        "onlisans mezunu",

        "on lisans mezunu",

    ]

    for ifade in genel_onlisans:

        if ifade in text:

            return {
                "ok": True,
                "manuel": False,
                "neden": [
                    "Herhangi bir önlisans mezuniyeti kabul ediliyor."
                ],
            }

    # Adalet açıkça isteniyorsa

    adalet = [

        "adalet bolumu",

        "adalet programi",

        "adalet mezunu",

        "adalet mezunlarindan",

        "adalet onlisans",

        "adalet on lisans",

    ]

    for ifade in adalet:

        if ifade in text:

            return {
                "ok": True,
                "manuel": False,
                "neden": [
                    "Adalet mezuniyeti şartı profilinizle uyumlu."
                ],
            }

    # Önlisans kelimesi geçiyorsa
    # ama detay çözülemiyorsa manuel.

    if (
        "onlisans" in text
        or "on lisans" in text
    ):

        return {
            "ok": True,
            "manuel": True,
            "neden": [
                "Önlisans şartı bulunuyor ancak alt nitelik otomatik çözülemedi."
            ],
        }

    # Eğitim şartı hiç bulunmuyorsa
    # kesin olarak reddetme.
    #
    # Çünkü bazı ilanların RSS açıklaması
    # eksik olabiliyor.

    return {
        "ok": True,
        "manuel": True,
        "neden": [
            "Eğitim şartı RSS metninde kesin çözülemedi; ilan ayrıntısı kontrol edilmeli."
        ],
    }


# ============================================================
# BÖLÜM
# ============================================================

def bolum_kontrol(text):

    # Herhangi bir bölüm / alan
    # kabul ediliyorsa Adalet mezunu uygundur.

    genel = [

        "herhangi bir bolum",

        "herhangi bir bölüm",

        "herhangi bir alan",

        "bolum sarti aranmaksizin",

        "alan sarti aranmaksizin",

        "brans sarti aranmaksizin",

        "herhangi bir onlisans",

        "herhangi bir on lisans",

    ]

    for ifade in genel:

        if ifade in text:

            return {
                "ok": True,
                "manuel": False,
                "neden": [
                    "Belirli bir bölüm şartı bulunmuyor."
                ],
            }

    # Adalet

    adalet = [

        "adalet bolumu",

        "adalet programi",

        "adalet mezunu",

        "adalet mezunlarindan",

        "adalet onlisans",

        "adalet on lisans",

    ]

    for ifade in adalet:

        if ifade in text:

            return {
                "ok": True,
                "manuel": False,
                "neden": [
                    "Adalet mezuniyeti kabul ediliyor."
                ],
            }

    # Bazı belirgin farklı bölümler

    farkli_bolumler = [

        "bilgisayar muhendisligi",

        "bilgisayar programciligi",

        "yazilim muhendisligi",

        "elektrik elektronik muhendisligi",

        "maliye",

        "iktisat",

        "isletme",

        "muhasebe",

        "cocuk gelisimi",

        "sosyal hizmet",

        "laborant",

        "anestezi",

        "ilk ve acil yardim",

        "tibbi dokumantasyon",

        "grafik tasarim",

        "web tasarim",

    ]

    bulunan = []

    for ifade in farkli_bolumler:

        if ifade in text:

            bulunan.append(
                ifade
            )

    if bulunan:

        return {
            "ok": False,
            "manuel": False,
            "neden": [
                (
                    "Adalet dışındaki özel bölüm/nitelik isteniyor: "
                    + ", ".join(
                        sorted(
                            set(
                                bulunan
                            )
                        )
                    )
                )
            ],
        }

    # Hiçbir bölüm ifadesi yoksa
    # otomatik reddetme.
    #
    # Bu bizim için önemli:
    # bölüm şartı olmayan ilanları kaçırmıyoruz.

    return {
        "ok": True,
        "manuel": True,
        "neden": [
            "Belirli bölüm şartı tespit edilmedi; ilan ayrıntısı kontrol edilmeli."
        ],
    }


# ============================================================
# CİNSİYET
# ============================================================

def cinsiyet_kontrol(text):

    if CINSIYET == "erkek":

        kadin = [

            "sadece kadin",

            "sadece kadın",

            "kadin adaylar",

            "kadın adaylar",

            "kadin olmak",

            "kadın olmak",

            "adaylarin kadin",

            "adayların kadın",

        ]

        for ifade in kadin:

            if ifade in text:

                return {
                    "ok": False,
                    "manuel": False,
                    "neden": [
                        "İlan kadın adaylarla sınırlandırılmış."
                    ],
                }

        erkek = [

            "sadece erkek",

            "erkek adaylar",

            "erkek aday",

            "erkek olmak",

        ]

        for ifade in erkek:

            if ifade in text:

                return {
                    "ok": True,
                    "manuel": False,
                    "neden": [
                        "Erkek aday şartı profilinizle uyumlu."
                    ],
                }

    return {
        "ok": True,
        "manuel": False,
        "neden": [
            "Cinsiyet açısından engel tespit edilmedi."
        ],
    }


# ============================================================
# YAŞ
# ============================================================

def yas_kontrol(text):

    # 30 yaşından gün almamış
    # gibi ifadeler için özel kontrol.

    match = re.search(
        r"(\d{2})\s*yasindan\s*gun\s*almamis",
        text,
    )

    if match:

        limit = int(
            match.group(1)
        )

        if YAS >= limit:

            return {
                "ok": False,
                "manuel": False,
                "neden": [
                    (
                        f"İlan {limit} yaşından gün almamış olmayı istiyor; "
                        f"yaşınız {YAS}."
                    )
                ],
            }

        return {
            "ok": True,
            "manuel": False,
            "neden": [
                (
                    f"Yaş şartı {limit}; "
                    f"yaşınız {YAS}."
                )
            ],
        }

    # "35 yaşını doldurmamış"
    match = re.search(
        r"(\d{2})\s*yasini\s*doldurmamis",
        text,
    )

    if match:

        limit = int(
            match.group(1)
        )

        if YAS >= limit:

            return {
                "ok": False,
                "manuel": False,
                "neden": [
                    (
                        f"İlan {limit} yaşını doldurmamış olmayı istiyor; "
                        f"yaşınız {YAS}."
                    )
                ],
            }

        return {
            "ok": True,
            "manuel": False,
            "neden": [
                (
                    f"Yaş sınırı {limit}; "
                    f"yaşınız {YAS}."
                )
            ],
        }

    # "30 yaşından büyük olmamak"
    match = re.search(
        r"(\d{2})\s*yasindan\s*buyuk",
        text,
    )

    if match:

        limit = int(
            match.group(1)
        )

        if YAS <= limit:

            return {
                "ok": True,
                "manuel": False,
                "neden": [
                    (
                        f"Yaş şartı açısından uygunsunuz; "
                        f"yaşınız {YAS}."
                    )
                ],
            }

        return {
            "ok": False,
            "manuel": False,
            "neden": [
                (
                    f"Yaş sınırı {limit}; "
                    f"yaşınız {YAS}."
                )
            ],
        }

    return {
        "ok": True,
        "manuel": False,
        "neden": [
            "Yaş sınırı tespit edilmedi."
        ],
    }


# ============================================================
# ASKERLİK
# ============================================================

def askerlik_kontrol(text):

    if "askerlik" not in text:

        return {
            "ok": True,
            "manuel": False,
            "neden": [],
        }

    ifadeler = [

        "askerligini yapmis olmak",

        "askerliği yapmış olmak",

        "askerlik hizmetini yapmis",

        "askerlik hizmetini yapmış",

        "askerlikle iliskisi bulunmamak",

        "askerlikle ilişkisi bulunmamak",

    ]

    for ifade in ifadeler:

        if normalize(ifade) in text:

            return {
                "ok": True,
                "manuel": True,
                "neden": [
                    "Askerlik şartı bulunuyor; kişisel durum ayrıca kontrol edilmeli."
                ],
            }

    return {
        "ok": True,
        "manuel": True,
        "neden": [
            "İlanda askerlik şartı geçiyor; ayrıntısı manuel kontrol edilmeli."
        ],
    }


# ============================================================
# ANA İLAN ANALİZİ
# ============================================================

def ilan_analiz_et(ilan):

    text = ilan_metni(
        ilan
    )

    neden = []

    # --------------------------------------------------------
    # TARİH
    # --------------------------------------------------------

    tarih_ok, tarih_neden = (
        tarih_kontrol(
            text
        )
    )

    if not tarih_ok:

        return {
            "durum":
                "BASVURAMAZSIN",

            "kpss":
                False,

            "taban":
                None,

            "neden":
                tarih_neden,
        }

    neden.extend(
        tarih_neden
    )

    # --------------------------------------------------------
    # KPSS
    # --------------------------------------------------------

    kpss = kpss_kontrol(
        text
    )

    neden.extend(
        kpss["neden"]
    )

    if (
        kpss["var"]
        and kpss["taban"] is not None
        and kpss["taban"] > KPSS_PUANI
    ):

        return {
            "durum":
                "BASVURAMAZSIN",

            "kpss":
                True,

            "taban":
                kpss["taban"],

            "neden":
                neden,
        }

    # --------------------------------------------------------
    # ÖĞRENİM
    # --------------------------------------------------------

    ogrenim = (
        ogrenim_kontrol(
            text
        )
    )

    neden.extend(
        ogrenim["neden"]
    )

    if not ogrenim["ok"]:

        return {
            "durum":
                "BASVURAMAZSIN",

            "kpss":
                kpss["var"],

            "taban":
                kpss["taban"],

            "neden":
                neden,
        }

    # --------------------------------------------------------
    # BÖLÜM
    # --------------------------------------------------------

    bolum = (
        bolum_kontrol(
            text
        )
    )

    neden.extend(
        bolum["neden"]
    )

    if not bolum["ok"]:

        return {
            "durum":
                "BASVURAMAZSIN",

            "kpss":
                kpss["var"],

            "taban":
                kpss["taban"],

            "neden":
                neden,
        }

    #--------------------------------------------------------
    # CİNSİYET
    # --------------------------------------------------------

    cinsiyet = (
        cinsiyet_kontrol(
            text
        )
    )

    neden.extend(
        cinsiyet["neden"]
    )

    if not cinsiyet["ok"]:

        return {
            "durum":
                "BASVURAMAZSIN",

            "kpss":
                kpss["var"],

            "taban":
                kpss["taban"],

            "neden":
                neden,
        }

    # --------------------------------------------------------
    # YAŞ
    # --------------------------------------------------------

    yas = (
        yas_kontrol(
            text
        )
    )

    neden.extend(
        yas["neden"]
    )

    if not yas["ok"]:

        return {
            "durum":
                "BASVURAMAZSIN",

            "kpss":
                kpss["var"],

            "taban":
                kpss["taban"],

            "neden":
                neden,
        }

    # --------------------------------------------------------
    # ASKERLİK
    # --------------------------------------------------------

    askerlik = (
        askerlik_kontrol(
            text
        )
    )

    neden.extend(
        askerlik["neden"]
    )

    if not askerlik["ok"]:

        return {
            "durum":
                "BASVURAMAZSIN",

            "kpss":
                kpss["var"],

            "taban":
                kpss["taban"],

            "neden":
                neden,
        }

    # --------------------------------------------------------
    # SONUÇ
    # --------------------------------------------------------

    manuel = any([
        kpss["manuel"],
        ogrenim["manuel"],
        bolum["manuel"],
        yas["manuel"],
        askerlik["manuel"],
    ])

    if manuel:

        durum = (
            "MANUEL_INCELEME"
        )

    else:

        durum = "UYGUN"

    return {

        "durum":
            durum,

        "kpss":
            kpss["var"],

        "taban":
            kpss["taban"],

        "neden":
            neden,
    }


# ============================================================
# TELEGRAM
# ============================================================

def telegram_gonder(
    mesaj
):

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

            "chat_id":
                TELEGRAM_CHAT_ID,

            "text":
                mesaj,

            "disable_web_page_preview":
                False,

        },

        timeout=TIMEOUT,
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

    durum = (
        analiz["durum"]
    )

    if durum == "UYGUN":

        baslik = (
            "🟢 BAŞVURABİLİRSİN"
        )

    elif (
        durum
        == "MANUEL_INCELEME"
    ):

        baslik = (
            "🟡 MANUEL KONTROL GEREKLİ"
        )

    else:

        baslik = (
            "🔴 BAŞVURAMAZSIN"
        )

    if analiz["kpss"]:

        if analiz["taban"] is not None:

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
            "Şart tespit edilmedi"
        )

    neden = "\n".join(

        "• " + str(x)

        for x in
        analiz["neden"]

    )

    aciklama = (
        ilan.get(
            "description",
            "",
        )
    )

    if len(aciklama) > 1800:

        aciklama = (
            aciklama[:1800]
            + "..."
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

        + "🎓 Öğrenim: Önlisans\n"

        + "⚖️ Bölüm: Adalet\n"

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
            neden
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
# ANA PROGRAM
# ============================================================

def main():

    print("")
    print("=" * 55)
    print(
        "KAMU İLAN TAKİP BAŞLIYOR"
    )
    print(
        "KPSS:",
        KPSS_PUANI,
    )
    print(
        "Öğrenim:",
        OGRENIM,
    )
    print(
        "Bölüm:",
        BOLUM,
    )
    print(
        "Cinsiyet:",
        CINSIYET,
    )
    print(
        "Yaş:",
        YAS,
    )
    print("=" * 55)

    # --------------------------------------------------------
    # TELEGRAM ENV
    # --------------------------------------------------------

    print("")
    print(
        "=== ORTAM KONTROLÜ ==="
    )

    print(
        "TELEGRAM_TOKEN:",
        (
            "VAR"
            if TELEGRAM_TOKEN
            else "YOK"
        ),
    )

    print(
        "TELEGRAM_CHAT_ID:",
        (
            "VAR"
            if TELEGRAM_CHAT_ID
            else "YOK"
        ),
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

        rss_url = (
            rss_adresini_bul()
        )

        response = get_url(
            rss_url
        )

    except Exception as hata:

        print("")
        print(
            "!!! RSS HATASI !!!"
        )

        print(
            repr(hata)
        )

        return

    # --------------------------------------------------------
    # RSS PARSE
    # --------------------------------------------------------

    try:

        ilanlar = rss_oku(
            response.content
        )

    except Exception as hata:

        print("")
        print(
            "!!! RSS PARSE HATASI !!!"
        )

        print(
            repr(hata)
        )

        return

    if not ilanlar:

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

    uygunsuz_sayisi = 0

    telegram_sayisi = 0

    # --------------------------------------------------------
    # ANALİZ
    # --------------------------------------------------------

    print("")
    print("=" * 55)
    print(
        "İLAN ANALİZLERİ"
    )
    print("=" * 55)

    for index, ilan in enumerate(
        ilanlar,
        start=1,
    ):

        try:

            analiz = (
                ilan_analiz_et(
                    ilan
                )
            )

        except Exception as hata:

            print(
                "[ANALİZ HATASI]",
                ilan.get(
                    "title",
                    "",
                ),
            )

            print(
                repr(hata)
            )

            continue

        durum = (
            analiz["durum"]
        )

        if durum == "UYGUN":

            uygun_sayisi += 1

        elif (
            durum
            == "MANUEL_INCELEME"
        ):

            manuel_sayisi += 1

        else:

            uygunsuz_sayisi += 1

        print("")
        print(
            f"[{index}/{len(ilanlar)}]",
            durum,
        )

        print(
            ilan.get(
                "title",
                "",
            )
        )

        # ----------------------------------------------------
        # SADECE UYGUN + MANUEL
        # ----------------------------------------------------

        if durum not in (
            "UYGUN",
            "MANUEL_INCELEME",
        ):

            continue

        iid = ilan_id(
            ilan
        )

        if iid in gonderilenler:

            print(
                "Telegram: DAHA ÖNCE GÖNDERİLDİ"
            )

            continue

        try:

            mesaj = (
                telegram_mesaji(
                    ilan,
                    analiz,
                )
            )

            telegram_gonder(
                mesaj
            )

            yeni_gonderilenler.add(
                iid
            )

            telegram_sayisi += 1

            print(
                "Telegram: GÖNDERİLDİ"
            )

        except Exception as hata:

            print(
                "Telegram: HATA"
            )

            print(
                repr(hata)
            )

    # --------------------------------------------------------
    # KAYDET
    # --------------------------------------------------------

    try:

        gonderilenleri_kaydet(
            yeni_gonderilenler
        )

    except Exception as hata:

        print(
            "[UYARI] sent_ids kaydedilemedi:",
            repr(hata),
        )

    # --------------------------------------------------------
    # SONUÇ
    # --------------------------------------------------------

    print("")
    print("=" * 55)
    print(
        "TARAMA TAMAMLANDI"
    )
    print("=" * 55)

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
        uygunsuz_sayisi,
    )

    print(
        "📨 Telegram'a gönderilen:",
        telegram_sayisi,
    )

    print("=" * 55)


# ============================================================
# BAŞLAT
# ============================================================

if __name__ == "__main__":

    main()
