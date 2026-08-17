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

USER_AGENT = "Kamu-Ilan-Takip/2.0"


# ============================================================
# YARDIMCI
# ============================================================

def normalize(text):
    if not text:
        return ""

    text = html.unescape(str(text)).lower()

    ceviri = str.maketrans({
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
    })

    text = text.translate(ceviri)

    return re.sub(r"\s+", " ", text).strip()


def temizle_html(text):
    if not text:
        return ""

    text = html.unescape(text)
    text = re.sub(r"<script.*?</script>", " ", text,
                  flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text,
                  flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return html.unescape(text).strip()


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
        timeout=30,
    )

    response.raise_for_status()

    return response


# ============================================================
# RSS ADRESİ
# ============================================================

def rss_adresini_bul():

    print("Kariyer Kapısı RSS sayfası okunuyor...", flush=True)

    sayfa_url = BASE_URL + "/RSS/RssLinkiAl"

    response = get_url(sayfa_url)

    print(
        "RSS bağlantı sayfası HTTP:",
        response.status_code,
        flush=True
    )

    sayfa = response.text

    scripts = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        sayfa,
        re.I
    )

    infrastructure_url = None

    for src in scripts:
        if "Infrastructure" in src:
            infrastructure_url = urljoin(
                BASE_URL,
                src
            )
            break

    if not infrastructure_url:
        infrastructure_url = (
            BASE_URL
            + "/js/Infrastructure.enxa2bxk74.js"
        )

    print(
        "Infrastructure:",
        infrastructure_url,
        flush=True
    )

    try:
        js_response = get_url(infrastructure_url)
        js = js_response.text

        # kvkkbaseurl değişkenini ara
        patterns = [
            r'kvkkbaseurl\s*=\s*["\']([^"\']+)',
            r'kvkkbaseurl\s*:\s*["\']([^"\']+)',
        ]

        rss_base = None

        for pattern in patterns:
            match = re.search(
                pattern,
                js,
                re.I
            )

            if match:
                rss_base = match.group(1)
                break

        if rss_base:

            if not rss_base.endswith("/"):
                rss_base += "/"

            rss_url = rss_base + "RSS"

        else:
            rss_url = BASE_URL + "/RSS"

    except Exception as exc:

        print(
            "Infrastructure okunamadı:",
            exc,
            flush=True
        )

        rss_url = BASE_URL + "/RSS"

    return rss_url


# ============================================================
# RSS PARSE
# ============================================================

def parse_rss(content):

    print("RSS parse başlıyor...", flush=True)

    if isinstance(content, bytes):

        content = content.decode(
            "utf-8-sig",
            errors="replace"
        )

    else:

        content = str(content).lstrip("\ufeff")

    try:
        root = ET.fromstring(content)

    except ET.ParseError as exc:

        print(
            "RSS XML parse hatası:",
            exc,
            flush=True
        )

        return []

    ilanlar = []

    # --------------------------------------------------------
    # RSS
    # --------------------------------------------------------

    for item in root.findall(".//item"):

        title = item.findtext("title", "")
        link = item.findtext("link", "")
        description = item.findtext("description", "")
        guid = item.findtext("guid", "")

        title = temizle_html(title)
        description = temizle_html(description)

        link = (link or "").strip()
        guid = (guid or "").strip()

        ilan_id = guid or link or title

        if not ilan_id:

            ilan_id = hashlib.sha256(
                (
                    title
                    + link
                    + description
                ).encode("utf-8")
            ).hexdigest()

        ilanlar.append({
            "id": ilan_id,
            "title": title,
            "link": link,
            "description": description,
        })

    # --------------------------------------------------------
    # ATOM
    # --------------------------------------------------------

    if not ilanlar:

        namespace = {
            "atom":
                "http://www.w3.org/2005/Atom"
        }

        for entry in root.findall(
            ".//atom:entry",
            namespace
        ):

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

            title = temizle_html(title)
            summary = temizle_html(summary)

            ilan_id = (
                entry_id
                or link
                or title
            )

            ilanlar.append({
                "id": ilan_id,
                "title": title,
                "link": link,
                "description": summary,
            })

    print(
        "Parse edilen ilan:",
        len(ilanlar),
        flush=True
    )

    return ilanlar


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
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, list):
            return set(data)

        return set()

    except Exception as exc:

        print(
            "sent_ids okunamadı:",
            exc,
            flush=True
        )

        return set()


def gonderilenleri_kaydet(ids):

    with open(
        GONDERILEN_DOSYA,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            sorted(ids),
            file,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# PUAN
# ============================================================

def kpss_puani_bul(text):

    text = normalize(text)

    desenler = [

        r"kpss.{0,80}?(?:en az|asgari|taban|puan).*?(\d{2}(?:[.,]\d+)?)",

        r"(\d{2}(?:[.,]\d+)?)\s*(?:puan|puani|puanı).*?kpss",

        r"kpss[- ]?(?:p|p93|p94|p3).*?(\d{2}(?:[.,]\d+)?)",
    ]

    for desen in desenler:

        eslesmeler = re.findall(
            desen,
            text,
            flags=re.I
        )

        for deger in eslesmeler:

            try:
                puan = float(
                    deger.replace(",", ".")
                )

                if 40 <= puan <= 100:
                    return puan

            except ValueError:
                pass

    return None


# ============================================================
# İLAN ANALİZİ
# ============================================================

def ilan_analiz_et(ilan):

    title = ilan.get("title", "")
    description = ilan.get("description", "")

    text = normalize(
        title
        + " "
        + description
    )

    sonuc = {
        "durum": "MANUEL_INCELEME",
        "nedenler": [],
        "kpss": None,
        "ogrenim": None,
        "cinsiyet": "belirtilmemis",
        "yas": None,
    }

    # --------------------------------------------------------
    # SON BAŞVURU
    # --------------------------------------------------------

    kapanmis = [
        "basvuru sona ermistir",
        "basvurular sona ermistir",
        "basvuru suresi dolmustur",
        "son basvuru tarihi gecmistir",
        "basvuruya kapalidir",
    ]

    for ifade in kapanmis:

        if ifade in text:

            sonuc["durum"] = "BASVURAMAZSIN"

            sonuc["nedenler"].append(
                "Başvuru süresi sona ermiş."
            )

            return sonuc

    # --------------------------------------------------------
    # CİNSİYET
    # --------------------------------------------------------

    erkek_ifadeleri = [
        "erkek",
        "yalnizca erkek",
        "sadece erkek",
        "erkek aday",
    ]

    kadin_ifadeleri = [
        "kadin",
        "yalnizca kadin",
        "sadece kadin",
        "kadin aday",
    ]

    erkek = any(
        x in text
        for x in erkek_ifadeleri
    )

    kadin = any(
        x in text
        for x in kadin_ifadeleri
    )

    if erkek and not kadin:

        sonuc["cinsiyet"] = "erkek"

    elif kadin and not erkek:

        sonuc["cinsiyet"] = "kadin"

        sonuc["nedenler"].append(
            "İlan kadın adaylara yönelik görünüyor."
        )

        sonuc["durum"] = "BASVURAMAZSIN"

        return sonuc

    # --------------------------------------------------------
    # ADALET / HUKUK ALANI
    # --------------------------------------------------------

    adalet_kelime = [
        "adalet",
        "adalet bolumu",
        "adalet programi",
        "adalet mezunu",
        "hukuk",
        "icra",
        "icra mudurlugu",
        "icra mudur yardimcisi",
        "zabit katibi",
        "zabita katibi",
        "katip",
        "yazi isleri",
        "mahkeme",
    ]

    alan_var = any(
        x in text
        for x in adalet_kelime
    )

    # --------------------------------------------------------
    # ÖĞRENİM
    # --------------------------------------------------------

    onlisans_var = (
        "onlisans" in text
        or "on lisans" in text
        or "on-lisans" in text
    )

    adalet_var = (
        "adalet bolumu" in text
        or "adalet programi" in text
        or "adalet mezunu" in text
    )

    lise_var = (
        "lise" in text
        or "ortaogretim" in text
    )

    lisans_var = (
        "lisans" in text
        and "onlisans" not in text
    )

    if onlisans_var:
        sonuc["ogrenim"] = "onlisans"

    elif lisans_var:
        sonuc["ogrenim"] = "lisans"

    elif lise_var:
        sonuc["ogrenim"] = "lise"

    # --------------------------------------------------------
    # ADALET MEZUNU İÇİN UYGUNLUK
    # --------------------------------------------------------

    if adalet_var and onlisans_var:

        sonuc["nedenler"].append(
            "Adalet önlisans mezuniyetiyle uyumlu."
        )

    elif alan_var:

        sonuc["nedenler"].append(
            "İlanda adalet/hukuk alanıyla ilişkili şart bulundu."
        )

    # --------------------------------------------------------
    # KPSS
    # --------------------------------------------------------

    kpss_var = "kpss" in text

    sonuc["kpss"] = kpss_puani_bul(text)

    if kpss_var:

        if sonuc["kpss"] is not None:

            gereken = sonuc["kpss"]

            if gereken > KPSS_PUANI:

                sonuc["durum"] = "BASVURAMAZSIN"

                sonuc["nedenler"].append(
                    f"KPSS taban puanı {gereken}; "
                    f"senin puanın {KPSS_PUANI}."
                )

                return sonuc

            else:

                sonuc["nedenler"].append(
                    f"KPSS şartı var; "
                    f"taban {gereken}, puanın {KPSS_PUANI}."
                )

        else:

            sonuc["nedenler"].append(
                "KPSS şartı bulunuyor; puan ayrıca incelenmeli."
            )

    else:

        sonuc["nedenler"].append(
            "Metinde KPSS şartı tespit edilmedi."
        )

    # --------------------------------------------------------
    # YAŞ
    # --------------------------------------------------------

    yas_deseni = re.search(
        r"(?:35|30|40|45|50)\s*yasin[ai]?\s*doldurmamis",
        text
    )

    if yas_deseni:

        sonuc["yas"] = yas_deseni.group(0)

        sonuc["nedenler"].append(
            "Yaş sınırı ilan metninde mevcut; kontrol gerekli."
        )

    # --------------------------------------------------------
    # BÖLÜM
    # --------------------------------------------------------

    if adalet_var:

        sonuc["nedenler"].append(
            "Adalet bölümü açıkça belirtilmiş."
        )

    # --------------------------------------------------------
    # GENEL SONUÇ
    # --------------------------------------------------------

    if sonuc["durum"] != "BASVURAMAZSIN":

        if alan_var or adalet_var:

            sonuc["durum"] = "BASVURABİLİRSİN"

        else:

            sonuc["durum"] = "MANUEL_INCELEME"

            sonuc["nedenler"].append(
                "İlanın tüm özel şartları otomatik doğrulanamadı."
            )

    return sonuc


# ============================================================
# TELEGRAM
# ============================================================

def telegram_gonder(mesaj):

    if not TELEGRAM_TOKEN:
        print(
            "TELEGRAM_TOKEN bulunamadı.",
            flush=True
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "TELEGRAM_CHAT_ID bulunamadı.",
            flush=True
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
        timeout=30,
    )

    response.raise_for_status()

    return True


# ============================================================
# TELEGRAM MESAJ
# ============================================================

def telegram_mesaji(ilan, analiz):

    durum = analiz["durum"]

    if durum == "BASVURABİLİRSİN":
        emoji = "🟢"

    elif durum == "BASVURAMAZSIN":
        emoji = "🔴"

    else:
        emoji = "🟡"

    nedenler = "\n".join(
        "- " + x
        for x in analiz["nedenler"]
    )

    aciklama = ilan["description"]

    if len(aciklama) > 2500:
        aciklama = aciklama[:2500] + "..."

    mesaj = (
        f"{emoji} {durum}\n\n"
        f"📌 {ilan['title']}\n\n"
        f"🎓 Öğrenim: {OGRENIM}\n"
        f"📚 Bölüm: {BOLUM}\n"
        f"👤 Cinsiyet: {CINSIYET}\n"
        f"📊 KPSS: {KPSS_PUANI}\n\n"
        f"🔎 ANALİZ\n"
        f"{nedenler}\n\n"
        f"📝 İLAN\n"
        f"{aciklama}\n\n"
        f"🔗 {ilan['link']}"
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
    print("Öğrenim:", OGRENIM)
    print("Bölüm:", BOLUM)
    print("Cinsiyet:", CINSIYET)
    print("=" * 50)
    print(flush=True)

    # --------------------------------------------------------
    # RSS
    # --------------------------------------------------------

    rss_url = rss_adresini_bul()

    print(
        "RSS:",
        rss_url,
        flush=True
    )

    response = get_url(rss_url)

    print(
        "RSS HTTP:",
        response.status_code,
        flush=True
    )

    print(
        "RSS uzunluğu:",
        len(response.content),
        flush=True
    )

    # --------------------------------------------------------
    # PARSE
    # --------------------------------------------------------

    ilanlar = parse_rss(
        response.content
    )

    print(
        "Toplam ilan:",
        len(ilanlar),
        flush=True
    )

    print("")
    print("=" * 50)
    print("İLAN ANALİZLERİ")
    print("=" * 50)

    # --------------------------------------------------------
    # GÖNDERİLENLER
    # --------------------------------------------------------

    gonderilenler = gonderilenleri_oku()

    yeni_gonderilenler = set(
        gonderilenler
    )

    basvurabilir = 0
    manuel = 0
    basvuramaz = 0
    telegram_sayisi = 0

    # --------------------------------------------------------
    # HER İLAN
    # --------------------------------------------------------

    for sira, ilan in enumerate(
        ilanlar,
        start=1
    ):

        print(
            f"\n[{sira}/{len(ilanlar)}] "
            f"{ilan['title']}",
            flush=True
        )

        analiz = ilan_analiz_et(
            ilan
        )

        durum = analiz["durum"]

        print(
            "SONUÇ:",
            durum,
            flush=True
        )

        for neden in analiz["nedenler"]:

            print(
                " -",
                neden,
                flush=True
            )

        if durum == "BASVURABİLİRSİN":

            basvurabilir += 1

        elif durum == "MANUEL_INCELEME":

            manuel += 1

        else:

            basvuramaz += 1

        # ----------------------------------------------------
        # TELEGRAM
        # ----------------------------------------------------

        # Sadece başvurulabilir veya manuel inceleme
        # gerektiren ilanları gönder.
        #
        # Daha önce gönderilenleri tekrar gönderme.

        if durum in (
            "BASVURABİLİRSİN",
            "MANUEL_INCELEME"
        ):

            if ilan["id"] not in gonderilenler:

                try:

                    mesaj = telegram_mesaji(
                        ilan,
                        analiz
                    )

                    if telegram_gonder(
                        mesaj
                    ):

                        yeni_gonderilenler.add(
                            ilan["id"]
                        )

                        telegram_sayisi += 1

                        print(
                            "Telegram: GÖNDERİLDİ",
                            flush=True
                        )

                except Exception as exc:

                    print(
                        "Telegram HATASI:",
                        exc,
                        flush=True
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
