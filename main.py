import os
import re
import json
import html
import hashlib
import requests
from iskur import iskur_ilanlarini_getir
import xml.etree.ElementTree as ET
from datetime import date
from urllib.parse import urljoin


# ============================================================
# PROFİL
# ============================================================

BASE_URL = "https://kariyerkapisi.gov.tr"

KPSS_PUANI = 76.29
KPSS_TURU = "P93"

OGRENIM = "onlisans"
BOLUM = "adalet"
CINSIYET = "erkek"
YAS = 29

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

GONDERILEN_DOSYA = "sent_ids.json"

USER_AGENT = "Kamu-Ilan-Takip/Final-3.0"
TIMEOUT = 30
MAX_DETAIL_LENGTH = 120000
MAX_TELEGRAM_DESCRIPTION = 1800


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,*/*;q=0.8"
    ),
})


# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================

def normalize(text):
    """
    Türkçe karakterleri normalize eder.
    Arama ve analiz işlemlerinde kullanılır.
    """

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

    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def temiz_html(text):
    """
    HTML etiketlerini temizleyerek okunabilir metin üretir.
    """

    if not text:
        return ""

    text = html.unescape(str(text))

    text = re.sub(
        r"(?is)<script.*?</script>",
        " ",
        text,
    )

    text = re.sub(
        r"(?is)<style.*?</style>",
        " ",
        text,
    )

    text = re.sub(
        r"(?is)<[^>]+>",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def get_url(url):
    """
    HTTP GET isteği.
    """

    print("[HTTP]", url)

    response = session.get(
        url,
        timeout=TIMEOUT,
        allow_redirects=True,
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
# RSS ADRESİNİ BUL
# ============================================================

def rss_adresini_bul():

    print("")
    print("=== RSS ADRESİ BULMA ===")

    sayfa = BASE_URL + "/RSS/RssLinkiAl"

    try:
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

    except Exception as e:

        print(
            "[UYARI] RSS adresi otomatik bulunamadı:",
            repr(e),
        )

        fallback = BASE_URL + "/RSS"

        print(
            "[RSS] Fallback:",
            fallback,
        )

        return fallback


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

    try:

        root = ET.fromstring(content)

    except ET.ParseError as e:

        print(
            "[HATA] RSS XML çözümlenemedi:",
            repr(e),
        )

        return []

    ilanlar = []

    # --------------------------------------------------------
    # RSS FORMAT
    # --------------------------------------------------------

    for item in root.findall(".//item"):

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
            "title": html.unescape(
                title
            ).strip(),

            "link": link.strip(),

            "description": html.unescape(
                description
            ).strip(),

            "id": (
                guid
                or link
                or title
            ).strip(),
        })

    # --------------------------------------------------------
    # ATOM FORMAT
    # --------------------------------------------------------

    if not ilanlar:

        namespace = {
            "atom": "http://www.w3.org/2005/Atom"
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

                link = link_element.attrib.get(
                    "href",
                    "",
                )

            ilanlar.append({
                "title": html.unescape(
                    title
                ).strip(),

                "link": link.strip(),

                "description": html.unescape(
                    summary
                ).strip(),

                "id": (
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
# İLAN DETAYINI AL
# ============================================================

def detay_metni_al(ilan):

    link = ilan.get(
        "link",
        "",
    ).strip()

    if not link.startswith("http"):

        return ""

    try:

        response = get_url(link)

        text = temiz_html(
            response.text
        )

        if len(text) > MAX_DETAIL_LENGTH:

            text = text[
                :MAX_DETAIL_LENGTH
            ]

        print(
            "[DETAY] Metin:",
            len(text),
            "karakter",
        )

        return text

    except Exception as e:

        print(
            "[DETAY] Okunamadı:",
            repr(e),
        )

        return ""


#============================================================
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

    except Exception as e:

        print(
            "[UYARI] sent_ids okunamadı:",
            repr(e),
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
            "[KAYIT] Gönderilen ilanlar kaydedildi:",
            len(gonderilenler),
        )

    except Exception as e:

        print(
            "[HATA] sent_ids kaydedilemedi:",
            repr(e),
        )


# ============================================================
# İLAN ID
# ============================================================

def ilan_id(ilan):

    mevcut = str(
        ilan.get(
            "id",
            "",
        )
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
        ham.encode("utf-8")
    ).hexdigest()


# ============================================================
# BAŞVURU TARİHİ
# ============================================================

TARIH_PATTERNS = [

    r"son\s+basvuru\s+tarihi\s*[:\-]?\s*"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})",

    r"son\s+basvuru\s*[:\-]?\s*"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})",

    r"basvurular\s+"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})"
    r".{0,150}"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})",

    r"basvuru\s+tarihleri\s*[:\-]?\s*"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})"
    r".{0,150}"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
]


def tarih_parse(text):

    try:

        text = (
            text
            .replace("-", ".")
            .replace("/", ".")
        )

        gun, ay, yil = [
            int(x)
            for x in text.split(".")
        ]

        return date(
            yil,
            ay,
            gun,
        )

    except Exception:

        return None


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
                None,
                "Başvuru süresinin sona erdiğini belirten ifade bulundu.",
            )

    son_tarih = None

    for pattern in TARIH_PATTERNS:

        for match in re.finditer(
            pattern,
            text,
            re.IGNORECASE,
        ):

            for value in match.groups():

                if not value:
                    continue

                aday_tarih = tarih_parse(
                    value
                )

                if not aday_tarih:
                    continue

                if (
                    son_tarih is None
                    or aday_tarih > son_tarih
                ):

                    son_tarih = aday_tarih

    if (
        son_tarih
        and son_tarih < date.today()
    ):

        return (
            False,
            son_tarih,
            (
                "Son başvuru tarihi "
                f"{son_tarih.strftime('%d.%m.%Y')} "
                "geçmiş."
            ),
        )

    if son_tarih:

        return (
            True,
            son_tarih,
            (
                "Son başvuru: "
                f"{son_tarih.strftime('%d.%m.%Y')}."
            ),
        )

    return (
        True,
        None,
        "Son başvuru tarihi otomatik tespit edilemedi.",
    )


# ============================================================
# KPSS
# ============================================================

def kpss_kontrol(text):

    if "kpss" not in text:

        return (
            True,
            None,
            None,
            [
                "KPSS şartı tespit edilmedi."
            ],
        )

    # --------------------------------------------------------
    # PUAN TÜRLERİ
    # --------------------------------------------------------

    turler = re.findall(
        r"\bP\s*([0-9]{1,3})\b",
        text,
        re.IGNORECASE,
    )

    turler = [
        "P" + x
        for x in turler
    ]

    turler = list(
        dict.fromkeys(turler)
    )

    # --------------------------------------------------------
    # P93 DIŞINDA AÇIK BİR PUAN TÜRÜ VARSA
    # --------------------------------------------------------

    if turler and "P93" not in turler:

        return (
            False,
            None,
            turler[0],
            [
                (
                    "İlanda P93 yerine "
                    f"{turler[0]} puan türü açıkça belirtilmiş."
                )
            ],
        )

    # --------------------------------------------------------
    # KPSS TABAN PUANI
    # --------------------------------------------------------

    sayilar = []

    desen = (
        r"(?:kpss(?:p\d{1,3})?|p93)"
        r".{0,250}"
    )

    for match in re.finditer(
        desen,
        text,
        re.IGNORECASE,
    ):

        bolge = match.group(0)

        bulunan = re.findall(
            r"\b(\d{2}(?:[.,]\d+)?)\b",
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

            if 40 <= deger <= 100:

                sayilar.append(
                    deger
                )

    taban = (
        min(sayilar)
        if sayilar
        else None
    )

    # --------------------------------------------------------
    # TABAN BULUNAMADI
    # --------------------------------------------------------

    if taban is None:

        return (
            True,
            None,
            "P93",
            [
                (
                    "KPSS şartı var; ancak "
                    "taban puan metinden güvenilir "
                    "biçimde çıkarılamadı."
                )
            ],
        )

    #--------------------------------------------------------
    # P93 KONTROL
    # --------------------------------------------------------

    if taban > KPSS_PUANI:

        return (
            False,
            taban,
            "P93",
            [
                (
                    f"KPSS tabanı {taban}; "
                    f"aday puanı {KPSS_PUANI}. "
                    "Puan yetersiz."
                )
            ],
        )

    return (
        True,
        taban,
        "P93",
        [
            (
                f"KPSS tabanı {taban}; "
                f"aday puanı {KPSS_PUANI} yeterli."
            )
        ],
    )


# ============================================================
# ÖĞRENİM
# ============================================================

def ogrenim_kontrol(text):

    lisans_zorunlu = [

        "lisans mezunu olmak",

        "lisans mezunlarindan",

        "lisans mezunlarından",

        "en az lisans",

        "lisans mezuniyeti",

        "lisans programlarindan",

        "lisans programlarından",
    ]

    if any(
        ifade in text
        for ifade in lisans_zorunlu
    ):

        return (
            False,
            [
                "Lisans mezuniyeti zorunlu."
            ],
        )

    onlisans_ifadeleri = [

        "onlisans",

        "on lisans",

        "onlisans mezunu",

        "on lisans mezunu",

        "onlisans mezunlarindan",

        "on lisans mezunlarindan",

        "onlisans programi",

        "on lisans programi",

        "onlisans programından",

        "on lisans programından",

        "onlisans mezuniyeti",
    ]

    if any(
        ifade in text
        for ifade in onlisans_ifadeleri
    ):

        return (
            True,
            [
                "Önlisans şartı bulunuyor."
            ],
        )

    return (
        True,
        [
            (
                "Eğitim seviyesi metinde açıkça "
                "tespit edilemedi; ilan dışlanmadı."
            )
        ],
    )


# ============================================================
# BÖLÜM
# ============================================================

def bolum_kontrol(text):

    genel = [

        "herhangi bir bolum",

        "herhangi bir alan",

        "herhangi bir brans",

        "bolum sarti aranmaksizin",

        "alan sarti aranmaksizin",

        "brans sarti aranmaksizin",

        "herhangi bir onlisans",

        "herhangi bir on lisans",

        "onlisans mezunu olmak",

        "on lisans mezunu olmak",
    ]

    if any(
        ifade in text
        for ifade in genel
    ):

        return (
            True,
            [
                (
                    "Belirli bir bölüm şartı yok; "
                    "Adalet mezunu başvurabilir."
                )
            ],
        )

    adalet = [

        "adalet bolumu",

        "adalet programi",

        "adalet mezunu",

        "adalet mezunlarindan",

        "adalet onlisans",

        "adalet on lisans",

        "adalet programından",

        "adalet programindan",
    ]

    if any(
        ifade in text
        for ifade in adalet
    ):

        return (
            True,
            [
                "Adalet bölümü/programı kabul ediliyor."
            ],
        )

    farkli_bolumler = [

        "bilgisayar muhendisligi",

        "bilgisayar mühendisligi",

        "yazilim muhendisligi",

        "elektrik elektronik muhendisligi",

        "makine muhendisligi",

        "insaat muhendisligi",

        "muhendislik fakultesi",

        "bilgisayar programciligi",

        "muhasebe",

        "laborant",

        "anestezi",

        "ilk ve acil yardim",

        "tibbi dokumantasyon",

        "cocuk gelisimi",

        "sosyal hizmet",

        "grafik tasarim",

        "web tasarim",

        "paramedik",

        "ebe",

        "hemsire",
    ]

    bulunan = sorted(
        set(
            ifade
            for ifade in farkli_bolumler
            if ifade in text
        )
    )

    if bulunan:

        return (
            False,
            [
                (
                    "Adalet dışındaki özel "
                    "bölüm/nitelik isteniyor: "
                    + ", ".join(bulunan)
                )
            ],
        )

    return (
        True,
        [
            (
                "Belirli bir bölüm şartı tespit "
                "edilmedi; Adalet mezunu dışlanmadı."
            )
        ],
    )


# ============================================================
# CİNSİYET
# ============================================================

def cinsiyet_kontrol(text):

    if CINSIYET == "erkek":

        kadin_ifadeleri = [

            "sadece kadin",

            "sadece kadın",

            "kadin adaylar",

            "kadın adaylar",

            "kadin aday",

            "kadın aday",

            "kadin olmak",

            "kadın olmak",
        ]

        if any(
            ifade in text
            for ifade in kadin_ifadeleri
        ):

            return (
                False,
                [
                    "İlan yalnızca kadın adaylara açık."
                ],
            )

    elif CINSIYET == "kadin":

        erkek_ifadeleri = [

            "sadece erkek",

            "erkek adaylar",

            "erkek aday",

            "erkek olmak",
        ]

        if any(
            ifade in text
            for ifade in erkek_ifadeleri
        ):

            return (
                False,
                [
                    "İlan yalnızca erkek adaylara açık."
                ],
            )

    return (
        True,
        [
            "Cinsiyet açısından engel tespit edilmedi."
        ],
    )


# ============================================================
# YAŞ
# ============================================================

def yas_kontrol(text):

    # --------------------------------------------------------
    # "30 yaşından gün almamış"
    # --------------------------------------------------------

    match = re.search(
        r"(\d{1,2})\s*yasindan\s*gun\s*almamis",
        text,
    )

    if match:

        limit = int(
            match.group(1)
        )

        if YAS >= limit:

            return (
                False,
                [
                    (
                        f"İlan {limit} yaşından "
                        f"gün almamış olmayı istiyor; "
                        f"aday yaşı {YAS}."
                    )
                ],
            )

        return (
            True,
            [
                (
                    f"Yaş şartı {limit}; "
                    f"aday yaşı {YAS}."
                )
            ],
        )

    # --------------------------------------------------------
    # "30 yaşını doldurmamış"
    # --------------------------------------------------------

    match = re.search(
        r"(\d{1,2})\s*yasini\s*doldurmamis",
        text,
    )

    if match:

        limit = int(
            match.group(1)
        )

        if YAS >= limit:

            return (
                False,
                [
                    (
                        f"İlan {limit} yaşını "
                        f"doldurmamış olmayı istiyor; "
                        f"aday yaşı {YAS}."
                    )
                ],
            )

        return (
            True,
            [
                (
                    f"Yaş sınırı {limit}; "
                    f"aday yaşı {YAS}."
                )
            ],
        )

    # --------------------------------------------------------
    # "35 yaşını geçmemiş"
    # --------------------------------------------------------

    match = re.search(
        r"(\d{1,2})\s*yasini\s*gecmemis",
        text,
    )

    if match:

        limit = int(
            match.group(1)
        )

        if YAS > limit:

            return (
                False,
                [
                    (
                        f"İlan {limit} yaşını "
                        f"geçmemiş olmayı istiyor; "
                        f"aday yaşı {YAS}."
                    )
                ],
            )

        return (
            True,
            [
                (
                    f"Yaş sınırı {limit}; "
                    f"aday yaşı {YAS}."
                )
            ],
        )

    # --------------------------------------------------------
    # "35 yaşından büyük olmamak"
    # --------------------------------------------------------

    match = re.search(
        r"(\d{1,2})\s*yasindan\s*buyuk\s*olmamak",
        text,
    )

    if match:

        limit = int(
            match.group(1)
        )

        if YAS > limit:

            return (
                False,
                [
                    (
                        f"İlan {limit} yaşından "
                        f"büyük olmamayı istiyor; "
                        f"aday yaşı {YAS}."
                    )
                ],
            )

        return (
            True,
            [
                (
                    f"Yaş sınırı {limit}; "
                    f"aday yaşı {YAS}."
                )
            ],
        )

    return (
        True,
        [
            "Yaş açısından engel tespit edilmedi."
        ],
    )


# ============================================================
# İLAN ANALİZİ
# ============================================================

def analiz_et(ilan):

    baslik = normalize(
        ilan.get(
            "title",
            "",
        )
    )

    rss = normalize(
        ilan.get(
            "description",
            "",
        )
    )

    detay = normalize(
        ilan.get(
            "detail_text",
            "",
        )
    )

    text = " ".join(
        x
        for x in [
            baslik,
            rss,
            detay,
        ]
        if x
    )

    neden = []
    red = []

    #--------------------------------------------------------
    # TARİH
    # --------------------------------------------------------

    tarih_ok, son_tarih, tarih_nedeni = (
        tarih_kontrol(text)
    )

    neden.append(
        tarih_nedeni
    )

    if not tarih_ok:

        red.append(
            tarih_nedeni
        )

    # --------------------------------------------------------
    # KPSS
    # --------------------------------------------------------

    k_ok, k_taban, k_tur, k_neden = (
        kpss_kontrol(text)
    )

    neden.extend(
        k_neden
    )

    if not k_ok:

        red.extend(
            k_neden
        )

    # --------------------------------------------------------
    # ÖĞRENİM
    # --------------------------------------------------------

    o_ok, o_neden = (
        ogrenim_kontrol(text)
    )

    neden.extend(
        o_neden
    )

    if not o_ok:

        red.extend(
            o_neden
        )

    # --------------------------------------------------------
    # BÖLÜM
    # --------------------------------------------------------

    b_ok, b_neden = (
        bolum_kontrol(text)
    )

    neden.extend(
        b_neden
    )

    if not b_ok:

        red.extend(
            b_neden
        )

    # --------------------------------------------------------
    # CİNSİYET
    # --------------------------------------------------------

    c_ok, c_neden = (
        cinsiyet_kontrol(text)
    )

    neden.extend(
        c_neden
    )

    if not c_ok:

        red.extend(
            c_neden
        )

    # --------------------------------------------------------
    # YAŞ
    # --------------------------------------------------------

    y_ok, y_neden = (
        yas_kontrol(text)
    )

    neden.extend(
        y_neden
    )

    if not y_ok:

        red.extend(
            y_neden
        )

    # --------------------------------------------------------
    # MANUEL KONTROL
    # --------------------------------------------------------

    kpss_belirsiz = (
        "KPSS şartı var; ancak "
        "taban puan metinden güvenilir "
        "biçimde çıkarılamadı."
        in k_neden
    )

    manuel = (
        k_ok
        and kpss_belirsiz
        and "p93" not in text
        and "puan siralamasi" not in text
        and "puan sıralaması" not in text
    )

    # --------------------------------------------------------
    # SONUÇ
    # --------------------------------------------------------

    if red:

        durum = "🔴 BAŞVURAMAZSIN"

    elif manuel:

        durum = "🟡 KONTROL GEREKİYOR"

    else:

        durum = "🟢 BAŞVURABİLİRSİN"

    return {

        "durum": durum,

        "neden": neden,

        "red": red,

        "kpss": k_ok,

        "taban": k_taban,

        "puan_turu": k_tur,

        "son_tarih": son_tarih,
    }


# ============================================================
# TELEGRAM
# ============================================================

def telegram_gonder(mesaj):

    if (
        not TELEGRAM_TOKEN
        or not TELEGRAM_CHAT_ID
    ):

        raise RuntimeError(
            "Telegram secret bilgileri eksik."
        )

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mesaj,
            "disable_web_page_preview": False,
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


#============================================================
# TELEGRAM MESAJI
# ============================================================

def telegram_mesaji(ilan, analiz):

    title = ilan.get(
        "title",
        "",
    )

    link = ilan.get(
        "link",
        "",
    )

    # Önce detay metnini kullan.
    # RSS açıklaması boşsa detaydan devam et.
    aciklama_kaynagi = (
        ilan.get(
            "detail_text",
            "",
        )
        or ilan.get(
            "description",
            "",
        )
    )

    aciklama = temiz_html(
        aciklama_kaynagi
    )

    if len(aciklama) > MAX_TELEGRAM_DESCRIPTION:

        aciklama = (
            aciklama[
                :MAX_TELEGRAM_DESCRIPTION
            ]
            + "..."
        )

    tarih = analiz.get(
        "son_tarih"
    )

    if tarih:

        tarih_text = tarih.strftime(
            "%d.%m.%Y"
        )

    else:

        tarih_text = (
            "Otomatik tespit edilemedi"
        )

    # --------------------------------------------------------
    # KPSS MESAJI
    # --------------------------------------------------------

    kpss = (
        "Yok / şart tespit edilmedi"
    )

    analiz_nedenleri = " ".join(
        analiz.get(
            "neden",
            [],
        )
    )

    if "KPSS" in analiz_nedenleri:

        taban = analiz.get(
            "taban"
        )

        puan_turu = analiz.get(
            "puan_turu"
        )

        if taban is not None:

            kpss = (
                f"{puan_turu or 'KPSS'} ≥ "
                f"{taban} | "
                f"Aday: {KPSS_PUANI}"
            )

        else:

            kpss = (
                "Var fakat taban otomatik "
                "tespit edilemedi"
            )

    # --------------------------------------------------------
    # ANALİZ NEDENLERİ
    # --------------------------------------------------------

    nedenler = analiz.get(
        "neden",
        [],
    )

    neden = "\n".join(
        "• " + x
        for x in nedenler
    )

    # --------------------------------------------------------
    # MESAJ
    # --------------------------------------------------------

    return (
        "⚖️ KAMU İLAN TAKİP\n\n"

        f"📌 {title}\n\n"

        f"{analiz['durum']}\n\n"

        "🎓 Öğrenim: Önlisans\n"

        "⚖️ Bölüm: Adalet\n"

        "👤 Cinsiyet: Erkek\n"

        f"🧑 Yaş: {YAS}\n"

        f"📊 KPSS: {kpss}\n"

        f"📅 Son başvuru: {tarih_text}\n\n"

        f"🔎 ANALİZ\n{neden}\n\n"

        f"📝 Açıklama\n{aciklama}\n\n"

        f"🔗 {link}"
    )


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    print("=" * 60)
    print("KAMU İLAN TAKİP - NİHAİ SÜRÜM")
    print("=" * 60)

    print(
        f"KPSS: {KPSS_PUANI} ({KPSS_TURU})"
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

    print("=" * 60)

    # --------------------------------------------------------
    # ORTAM
    # --------------------------------------------------------

    print("\n=== ORTAM ===")

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

    if (
        not TELEGRAM_TOKEN
        or not TELEGRAM_CHAT_ID
    ):

        print(
            "[HATA] Telegram secret eksik."
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

        ilanlar = rss_oku(
            response.content
        )

    except Exception as e:

        print(
            "[HATA] RSS:",
            repr(e),
        )

        return

    if not ilanlar:

        print(
            "[HATA] Hiç ilan bulunamadı."
        )

        return

    # --------------------------------------------------------
    # GÖNDERİLENLER
    # --------------------------------------------------------

    sent = (
        gonderilenleri_oku()
    )

    toplam = len(
        ilanlar
    )

    uygun = 0
    manuel = 0
    red = 0
    gonderildi = 0

    # --------------------------------------------------------
    # ANALİZ
    # --------------------------------------------------------

    print("\n" + "=" * 60)
    print("İLAN ANALİZLERİ")
    print("=" * 60)

    for i, ilan in enumerate(
        ilanlar,
        1,
    ):

        print(
            f"\n[{i}/{toplam}] "
            f"{ilan.get('title', '')}"
        )

        # ----------------------------------------------------
        # İLAN DETAYI
        # ----------------------------------------------------

        try:

            detail = (
                detay_metni_al(
                    ilan
                )
            )

        except Exception as e:

            print(
                "[UYARI] Detay alınamadı:",
                repr(e),
            )

            detail = ""

        ilan[
            "detail_text"
        ] = detail

        # ----------------------------------------------------
        # ANALİZ
        # ----------------------------------------------------

        try:

            sonuc = (
                analiz_et(
                    ilan
                )
            )

        except Exception as e:

            print(
                "[HATA] İlan analiz edilemedi:",
                repr(e),
            )

            continue

        print(
            "DURUM:",
            sonuc["durum"],
        )

        # ----------------------------------------------------
        # İSTATİSTİK
        # ----------------------------------------------------

        if sonuc[
            "durum"
        ].startswith("🟢"):

            uygun += 1

        elif sonuc[
            "durum"
        ].startswith("🔴"):

            red += 1

        else:

            manuel += 1

        #----------------------------------------------------
        # İLAN ID
        # ----------------------------------------------------

        iid = ilan_id(
            ilan
        )

        # ----------------------------------------------------
        # DAHA ÖNCE GÖNDERİLDİ Mİ?
        # ----------------------------------------------------

        if iid in sent:

            print(
                "Telegram: "
                "DAHA ÖNCE GÖNDERİLDİ"
            )

            # ÖNEMLİ:
            # continue burada ve doğru girintide.
            continue

        # ----------------------------------------------------
        # SADECE 🟢 VE 🟡 GÖNDER
        # ----------------------------------------------------

        if sonuc[
            "durum"
        ].startswith(
            ("🟢", "🟡")
        ):

            try:

                mesaj = (
                    telegram_mesaji(
                        ilan,
                        sonuc,
                    )
                )

                telegram_gonder(
                    mesaj
                )

                # Telegram gerçekten başarılı
                # olduktan sonra kayıt ediyoruz.
                sent.add(
                    iid
                )

                gonderildi += 1

                print(
                    "Telegram: GÖNDERİLDİ"
                )

            except Exception as e:

                print(
                    "[TELEGRAM HATA]",
                    repr(e),
                )

                # Gönderim başarısızsa
                # sent içerisine eklenmez.

        else:

            print(
                "Telegram: "
                "BAŞVURAMAZSIN - gönderilmedi"
            )

    # --------------------------------------------------------
    # GÖNDERİLENLERİ KAYDET
    # --------------------------------------------------------

    gonderilenleri_kaydet(
        sent
    )

    # --------------------------------------------------------
    # SONUÇ
    # --------------------------------------------------------

    print("\n" + "=" * 60)
    print("TARAMA TAMAMLANDI")
    print("=" * 60)

    print(
        "Toplam ilan:",
        toplam,
    )

    print(
        "🟢 Başvurabilir:",
        uygun,
    )

    print(
        "🟡 Kontrol gerekiyor:",
        manuel,
    )

    print(
        "🔴 Başvuramaz:",
        red,
    )

    print(
        "📨 Telegram'a gönderilen:",
        gonderildi,
    )

    print("=" * 60)


# ============================================================
# PROGRAMI BAŞLAT
# ============================================================

if __name__ == "__main__":

    main()
