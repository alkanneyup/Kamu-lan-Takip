import os
import re
import json
import html
import hashlib
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
from datetime import datetime


# ============================================================
# KAMU İLAN TAKİP - NİHAİ SÜRÜM
# ============================================================

BASE_URL = "https://kariyerkapisi.gov.tr"

KPSS_PUANI = 76.29
ADAY_CINSIYET = "erkek"
ADAY_OGRENIM = "onlisans"
ADAY_BOLUM = "adalet"

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

GONDERILEN_DOSYA = "sent_ids.json"

USER_AGENT = "Kamu-Ilan-Takip/2.0"


# ============================================================
# HTTP
# ============================================================

def get_url(url):
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=30
    )
    response.raise_for_status()
    return response


# ============================================================
# TÜRKÇE NORMALİZASYON
# ============================================================

def normalize(text):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    table = str.maketrans({
        "İ": "i",
        "I": "i",
        "ı": "i",
        "Ğ": "g",
        "ğ": "g",
        "Ü": "u",
        "ü": "u",
        "Ş": "s",
        "ş": "s",
        "Ö": "o",
        "ö": "o",
        "Ç": "c",
        "ç": "c",
    })

    return text.translate(table).lower().strip()


# ============================================================
# RSS ADRESİ
# ============================================================

def rss_adresini_bul():

    sayfa = get_url(
        BASE_URL + "/RSS/RssLinkiAl"
    )

    scriptler = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        sayfa.text,
        re.I
    )

    infrastructure = None

    for script in scriptler:
        if "Infrastructure" in script:
            infrastructure = urljoin(
                BASE_URL,
                script
            )
            break

    if not infrastructure:
        infrastructure = (
            BASE_URL
            + "/js/Infrastructure.enxa2bxk74.js"
        )

    print("Infrastructure:", infrastructure)

    js = get_url(infrastructure).text

    match = re.search(
        r'kvkkbaseurl\s*[:=]\s*["\']([^"\']+)',
        js,
        re.I
    )

    if match:
        base = match.group(1)
        if not base.endswith("/"):
            base += "/"
        return base + "RSS"

    return BASE_URL + "/RSS"


# ============================================================
# RSS PARSE
# ============================================================

def parse_rss(content):

    if isinstance(content, bytes):
        content = content.decode(
            "utf-8-sig",
            errors="replace"
        )for ilan in ilanlar[:3]:
    print("BASLIK:", ilan["title"])
    print("LINK:", ilan["link"])
    print("-" * 60)
    else:
        content = content.lstrip("\ufeff")

    root = ET.fromstring(content)

    ilanlar = []

    for item in root.findall(".//item"):

        alanlar = {}

        for child in item:
            tag = child.tag.split("}")[-1]
            value = "".join(
                child.itertext()
            )
            alanlar[tag] = value.strip()

        title = alanlar.get("title", "")
        link = alanlar.get("link", "")
        description = alanlar.get("description", "")
        guid = alanlar.get("guid", "")

        raw = " ".join(
            str(v)
            for v in alanlar.values()
        )

        ilan_id = (
            guid
            or link
            or hashlib.sha256(
                raw.encode("utf-8")
            ).hexdigest()
        )

        ilanlar.append({
            "title": html.unescape(title).strip(),
            "link": link.strip(),
            "description": html.unescape(
                description
            ).strip(),
            "raw": html.unescape(raw),
            "id": ilan_id.strip()
        })

    return ilanlar


# ============================================================
# GÖNDERİLENLER
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
        ) as f:
            return set(json.load(f))
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
# PUAN TESPİTİ
# ============================================================

def kpss_bilgisi(text):

    t = normalize(text)

    kpss = "kpss" in t

    if not kpss:
        return {
            "var": False,
            "puan": None,
            "puan_turu": None
        }

    puan = None

    kaliplar = [
        r"kpss.{0,120}?en az\s+(\d{2}(?:[.,]\d+)?)",
        r"kpss.{0,120}?(\d{2}(?:[.,]\d+)?)\s*puan",
        r"(\d{2}(?:[.,]\d+)?)\s*puan.{0,80}?kpss",
    ]

    for pattern in kaliplar:

        match = re.search(
            pattern,
            t,
            re.I
        )

        if match:

            try:
                value = float(
                    match.group(1)
                    .replace(",", ".")
                )

                if 40 <= value <= 100:
                    puan = value
                    break

            except ValueError:
                pass

    tur = None

    match = re.search(
        r"kpss.{0,80}?\b(p[0-9]{1,3})\b",
        t,
        re.I
    )

    if match:
        tur = match.group(1).upper()

    return {
        "var": True,
        "puan": puan,
        "puan_turu": tur
    }


# ============================================================
# CİNSİYET
# ============================================================

def cinsiyet_bilgisi(text):

    t = normalize(text)

    erkek = bool(
        re.search(
            r"\berkek\b",
            t
        )
    )

    kadin = bool(
        re.search(
            r"\b(kadin|kadın)\b",
            t
        )
    )

    if erkek and not kadin:
        return "erkek"

    if kadin and not erkek:
        return "kadin"

    if erkek and kadin:
        return "kadin/erkek"

    return "belirtilmemis"


# ============================================================
# YAŞ
# ============================================================

def yas_bilgisi(text):

    t = normalize(text)

    alt = None
    ust = None

    patterns = [
        r"(\d{2})\s*yasini doldurmus",
        r"(\d{2})\s*yasindan buyuk",
        r"(\d{2})\s*yasindan kucuk",
        r"(\d{2})\s*yasini doldurmamis",
        r"(\d{2})\s*yasini asmamis",
        r"(\d{2})\s*yasindan gun almamis",
    ]

    for pattern in patterns:

        for match in re.finditer(
            pattern,
            t
        ):

            sayi = int(
                match.group(1)
            )

            cevre = t[
                max(
                    0,
                    match.start() - 50
                ):
                match.end() + 50
            ]

            if any(x in cevre for x in [
                "doldurmus",
                "buyuk"
            ]):
                alt = max(
                    alt or 0,
                    sayi
                )

            if any(x in cevre for x in [
                "kucuk",
                "doldurmamis",
                "asmamis",
                "gun almamis"
            ]):
                ust = min(
                    ust or 999,
                    sayi
                )

    return alt, ust


# ============================================================
# EĞİTİM
# ============================================================

def egitim_bilgisi(text):

    t = normalize(text)

    lisans = bool(
        re.search(
            r"\blisans\b",
            t
        )
    )

    onlisans = bool(
        re.search(
            r"\b(onlisans|on lisans)\b",
            t
        )
    )

    lise = bool(
        re.search(
            r"\b(lise|ortaogretim)\b",
            t
        )
    )

    adalet = bool(
        re.search(
            r"\badalet\b",
            t
        )
    )

    genel_onlisans = bool(
        re.search(
            r"(herhangi bir|herhangi).{0,50}"
            r"onlisans",
            t
        )
    )

    return {
        "lisans": lisans,
        "onlisans": onlisans,
        "lise": lise,
        "adalet": adalet,
        "genel_onlisans": genel_onlisans
    }


# ============================================================
# BAŞVURU TARİHİ
# ============================================================

def basvuru_tarihi_gecmis_mi(text):

    t = normalize(text)

    bugun = datetime.now().date()

    tarihler = re.findall(
        r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b",
        t
    )

    parsed = []

    for gun, ay, yil in tarihler:

        try:

            tarih = datetime(
                int(yil),
                int(ay),
                int(gun)
            ).date()

            parsed.append(tarih)

        except ValueError:
            continue

    if not parsed:
        return False, None

    # İlandaki en ileri tarih genellikle son başvuru tarihidir.
    son_tarih = max(parsed)

    return (
        son_tarih < bugun,
        son_tarih
    )


# ============================================================
# İLAN ANALİZİ
# ============================================================

def ilan_analiz_et(ilan):

    text = normalize(
        ilan["title"]
        + " "
        + ilan["description"]
        + " "
        + ilan["raw"]
    )

    egitim = egitim_bilgisi(text)

    kpss = kpss_bilgisi(text)

    cinsiyet = cinsiyet_bilgisi(text)

    yas_alt, yas_ust = yas_bilgisi(text)

    kapanmis, son_tarih = (
        basvuru_tarihi_gecmis_mi(text)
    )

    nedenler = []

    durum = "BASVURABILIRSIN"

    # --------------------------------------------------------
    # EĞİTİM
    # --------------------------------------------------------

    if egitim["adalet"]:

        if (
            "adalet" in text
            and (
                egitim["onlisans"]
                or "adalet program" in text
                or "adalet bolumu" in text
            )
        ):
            nedenler.append(
                "Adalet mezuniyetiyle ilişkili"
            )

    elif egitim["genel_onlisans"]:

        nedenler.append(
            "Herhangi önlisans mezunu"
        )

    elif egitim["onlisans"]:

        # Belirli bir önlisans bölümü isteniyor olabilir.
        bolum_referansi = any(
            kelime in text
            for kelime in [
                "bilgisayar programciligi",
                "muhasebe",
                "elektrik",
                "elektronik",
                "cocuk gelisimi",
                "tibbi dokumantasyon"
            ]
        )

        if bolum_referansi and "adalet" not in text:

            durum = "MANUEL_INCELEME"

            nedenler.append(
                "Önlisans var ancak bölüm özel şartı bulunuyor"
            )

        else:

            nedenler.append(
                "Önlisans şartı mevcut"
            )

    elif egitim["lisans"]:

        durum = "BASVURAMAZSIN"

        nedenler.append(
            "Lisans mezuniyeti gerekiyor"
        )

    elif egitim["lise"]:

        # Lise mezunu şartı tek başına bizim için
        # başvuru engeli değildir; önlisans sahibi
        # aday daha yüksek eğitim seviyesine sahiptir.
        nedenler.append(
            "Lise/ortaöğretim şartı"
        )

    else:

        durum = "MANUEL_INCELEME"

        nedenler.append(
            "Eğitim seviyesi otomatik belirlenemedi"
        )

    # --------------------------------------------------------
    # KPSS
    # --------------------------------------------------------

    if kpss["var"]:

        if kpss["puan"] is not None:

            if kpss["puan"] > KPSS_PUANI:

                durum = "BASVURAMAZSIN"

                nedenler.append(
                    f"KPSS tabanı {kpss['puan']}; "
                    f"aday puanı {KPSS_PUANI}"
                )

            else:

                nedenler.append(
                    f"KPSS tabanı {kpss['puan']}; "
                    f"aday puanı {KPSS_PUANI} yeterli"
                )

        else:

            durum = (
                "MANUEL_INCELEME"
                if durum == "BASVURABILIRSIN"
                else durum
            )

            nedenler.append(
                "KPSS şartı var ancak taban puan otomatik okunamadı"
            )

    else:

        nedenler.append(
            "KPSS şartı tespit edilmedi"
        )

    # --------------------------------------------------------
    # CİNSİYET
    # --------------------------------------------------------

    if cinsiyet == "erkek":

        nedenler.append(
            "Cinsiyet: Erkek"
        )

    elif cinsiyet == "kadin":

        durum = "BASVURAMAZSIN"

        nedenler.append(
            "Cinsiyet: Kadın"
        )

    elif cinsiyet == "kadin/erkek":

        nedenler.append(
            "Cinsiyet: Kadın/Erkek"
        )

    # --------------------------------------------------------
    # YAŞ
    # --------------------------------------------------------

    # Kullanıcının yaşı mevcut profilde bulunmadığı için
    # yaş şartını otomatik ret sebebi yapmıyoruz.
    if yas_alt or yas_ust:

        durum = (
            "MANUEL_INCELEME"
            if durum == "BASVURABILIRSIN"
            else durum
        )

        aralik = []

        if yas_alt:
            aralik.append(
                f"{yas_alt}+"
            )

        if yas_ust:
            aralik.append(
                f"{yas_ust} yaş altı"
            )

        nedenler.append(
            "Yaş şartı: "
            + " / ".join(aralik)
        )

    # --------------------------------------------------------
    # KAPALI İLAN
    # --------------------------------------------------------

    if kapanmis:

        durum = "BASVURAMAZSIN"

        nedenler.append(
            "Son başvuru tarihi geçmiş"
        )

    return {
        "durum": durum,
        "nedenler": nedenler,
        "kpss": kpss,
        "cinsiyet": cinsiyet,
        "yas_alt": yas_alt,
        "yas_ust": yas_ust,
        "son_tarih": son_tarih,
        "egitim": egitim
    }


# ============================================================
# TELEGRAM
# ============================================================

def telegram_gonder(mesaj):

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
            "disable_web_page_preview": False
        },
        timeout=30
    )

    response.raise_for_status()


# ============================================================
# TELEGRAM MESAJI
# ============================================================

def telegram_mesaji(ilan, analiz):

    durum = analiz["durum"]

    if durum == "BASVURABILIRSIN":
        emoji = "🟢"
        baslik = "BAŞVURABİLİRSİN"

    elif durum == "BASVURAMAZSIN":
        emoji = "🔴"
        baslik = "BAŞVURAMAZSIN"

    else:
        emoji = "🟡"
        baslik = "MANUEL İNCELEME GEREKLİ"

    kpss = analiz["kpss"]

    if kpss["var"]:

        if kpss["puan"] is not None:
            kpss_text = (
                f"Var — taban: {kpss['puan']}"
            )
        else:
            kpss_text = (
                "Var — puan otomatik belirlenemedi"
            )

        if kpss["puan_turu"]:
            kpss_text += (
                f" ({kpss['puan_turu']})"
            )

    else:

        kpss_text = "Şart tespit edilmedi"

    cinsiyet = analiz["cinsiyet"]

    if cinsiyet == "erkek":
        cinsiyet_text = "Erkek"
    elif cinsiyet == "kadin":
        cinsiyet_text = "Kadın"
    elif cinsiyet == "kadin/erkek":
        cinsiyet_text = "Kadın/Erkek"
    else:
        cinsiyet_text = "Belirtilmemiş"

    nedenler = "\n".join(
        "• " + n
        for n in analiz["nedenler"]
    )

    mesaj = (
        f"{emoji} {baslik}\n\n"
        f"📌 {ilan['title']}\n\n"
        f"🎓 Öğrenim: Önlisans / Adalet\n"
        f"📊 KPSS: {kpss_text}\n"
        f"🧮 Aday KPSS: {KPSS_PUANI}\n"
        f"👤 Cinsiyet: {cinsiyet_text}\n"
    )

    if analiz["yas_alt"] or analiz["yas_ust"]:

        mesaj += (
            f"🎂 Yaş şartı: "
            f"{analiz['yas_alt'] or '-'} / "
            f"{analiz['yas_ust'] or '-'}\n"
        )

    mesaj += (
        "\n🔎 Değerlendirme:\n"
        + nedenler
        + "\n\n"
        + f"🔗 {ilan['link']}"
    )

    return mesaj


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    print("")
    print("=" * 50)
    print("KAMU İLAN TAKİP BAŞLIYOR")
    print("KPSS puanı:", KPSS_PUANI)
    print("Öğrenim:", ADAY_OGRENIM)
    print("Bölüm:", ADAY_BOLUM)
    print("Cinsiyet:", ADAY_CINSIYET)
    print("=" * 50)

    rss_url = rss_adresini_bul()

    print("RSS:", rss_url)

    response = get_url(rss_url)

    print(
        "RSS HTTP:",
        response.status_code
    )

    print(
        "RSS uzunluğu:",
        len(response.content)
    )

    ilanlar = parse_rss(
        response.content
    )

    print(
        "Toplam ilan:",
        len(ilanlar)
    )

    gonderilenler = (
        gonderilenleri_oku()
    )

    yeni_gonderilenler = set(
        gonderilenler
    )

    uygun = 0
    manuel = 0
    gonderilen = 0

    print("")
    print("=" * 50)
    print("İLAN ANALİZLERİ")
    print("=" * 50)

    for ilan in ilanlar:

        analiz = ilan_analiz_et(
            ilan
        )

        print("")
        print(
            analiz["durum"],
            "|",
            ilan["title"]
        )

        # ----------------------------------------------------
        # SADECE UYGUN VE MANUEL İNCELEME İLANLARI
        # TELEGRAM'A GÖNDER
        # ----------------------------------------------------

        if analiz["durum"] == "BASVURABILIRSIN":

            uygun += 1

        elif analiz["durum"] == "MANUEL_INCELEME":

            manuel += 1

        else:

            continue

        if ilan["id"] in gonderilenler:
            continue

        try:

            mesaj = telegram_mesaji(
                ilan,
                analiz
            )

            telegram_gonder(
                mesaj
            )

            yeni_gonderilenler.add(
                ilan["id"]
            )

            gonderilen += 1

            print(
                "Telegram: GÖNDERİLDİ"
            )

        except Exception as hata:

            print(
                "Telegram HATASI:",
                hata
            )

    gonderilenleri_kaydet(
        yeni_gonderilenler
    )

    print("")
    print("=" * 50)
    print("TARAMA TAMAMLANDI")
    print("=" * 50)

    print(
        "Toplam ilan:",
        len(ilanlar)
    )

    print(
        "🟢 Başvurabilirsin:",
        uygun
    )

    print(
        "🟡 Manuel inceleme:",
        manuel
    )

    print(
        "📨 Telegram'a gönderilen:",
        gonderilen
    )

    print("=" * 50)


if __name__ == "__main__":
    main()
