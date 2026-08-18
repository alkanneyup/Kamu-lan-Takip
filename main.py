import os
import re
import json
import html
import hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, date
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
USER_AGENT = "Kamu-Ilan-Takip/Final-2.0"
TIMEOUT = 30

session = requests.Session()
session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})

# ============================================================
# YARDIMCILAR
# ============================================================

def normalize(text):
    if not text:
        return ""
    text = html.unescape(str(text)).lower()
    table = str.maketrans({
        "ı": "i", "ğ": "g", "ü": "u",
        "ş": "s", "ö": "o", "ç": "c",
    })
    text = text.translate(table)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def temiz_html(text):
    if not text:
        return ""
    text = html.unescape(str(text))
    text = re.sub(r"(?is)<script.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_url(url):
    print("[HTTP]", url)
    r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    print("[HTTP]", r.status_code, "|", len(r.content), "byte")
    r.raise_for_status()
    return r


# ============================================================
# RSS
# ============================================================

def rss_adresini_bul():
    print("\n=== RSS ADRESİ BULMA ===")
    try:
        r = get_url(BASE_URL + "/RSS/RssLinkiAl")
        scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']',
                             r.text, re.I)
        infrastructure = next(
            (urljoin(BASE_URL, x) for x in scripts if "Infrastructure" in x),
            BASE_URL + "/js/Infrastructure.enxa2bxk74.js"
        )
        print("[RSS] Infrastructure:", infrastructure)

        js = get_url(infrastructure).text
        m = re.search(r'kvkkbaseurl\s*[:=]\s*["\']([^"\']+)',
                      js, re.I)
        base = m.group(1) if m else BASE_URL + "/"
        if not base.endswith("/"):
            base += "/"
        rss = base + "RSS"
        print("[RSS] Son RSS adresi:", rss)
        return rss
    except Exception as e:
        print("[UYARI] RSS adresi otomatik bulunamadı:", e)
        return BASE_URL + "/RSS"


def rss_oku(content):
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="replace")
    root = ET.fromstring(content)
    ilanlar = []

    for item in root.findall(".//item"):
        title = item.findtext("title", "") or ""
        link = item.findtext("link", "") or ""
        desc = item.findtext("description", "") or ""
        guid = item.findtext("guid", "") or ""
        ilanlar.append({
            "title": html.unescape(title).strip(),
            "link": link.strip(),
            "description": html.unescape(desc).strip(),
            "id": (guid or link or title).strip(),
        })

    if not ilanlar:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//a:entry", ns):
            title = entry.findtext("a:title", "", ns) or ""
            summary = entry.findtext("a:summary", "", ns) or ""
            eid = entry.findtext("a:id", "", ns) or ""
            link = ""
            le = entry.find("a:link", ns)
            if le is not None:
                link = le.attrib.get("href", "")
            ilanlar.append({
                "title": html.unescape(title).strip(),
                "link": link.strip(),
                "description": html.unescape(summary).strip(),
                "id": (eid or link or title).strip(),
            })

    print("[RSS] Toplam ilan:", len(ilanlar))
    return ilanlar


# ============================================================
# İLAN DETAYI
# ============================================================

def detay_metni_al(ilan):
    link = ilan.get("link", "").strip()
    if not link.startswith("http"):
        return ""

    try:
        r = get_url(link)
        text = temiz_html(r.text)
        if len(text) > 120000:
            text = text[:120000]
        print("[DETAY] Metin:", len(text), "karakter")
        return text
    except Exception as e:
        print("[DETAY] Okunamadı:", e)
        return ""


# ============================================================
# GÖNDERİLENLER
# ============================================================

def gonderilenleri_oku():
    if not os.path.exists(GONDERILEN_DOSYA):
        return set()
    try:
        with open(GONDERILEN_DOSYA, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(str(x) for x in data) if isinstance(data, list) else set()
    except Exception as e:
        print("[UYARI] sent_ids okunamadı:", e)
        return set()


def gonderilenleri_kaydet(ids):
    with open(GONDERILEN_DOSYA, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


def ilan_id(ilan):
    value = ilan.get("id", "").strip()
    if value:
        return value
    raw = "|".join([
        ilan.get("title", ""),
        ilan.get("link", ""),
        ilan.get("description", ""),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ============================================================
# BAŞVURU TARİHİ
# ============================================================

TARIH_PATTERNS = [
    r"son\s+basvuru\s+tarihi\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
    r"son\s+basvuru\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
    r"basvurular\s+(\d{1,2}[./-]\d{1,2}[./-]\d{4}).{0,100}(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
]


def tarih_parse(s):
    try:
        s = s.replace("-", ".").replace("/", ".")
        d, m, y = [int(x) for x in s.split(".")]
        return date(y, m, d)
    except Exception:
        return None


def tarih_kontrol(text):
    kapali = [
        "basvurular sona ermistir",
        "basvuru sona ermistir",
        "basvuru suresi dolmustur",
        "basvuru suresi sona ermistir",
        "basvuruya kapalidir",
        "basvurular kapanmistir",
        "basvuru kapatilmistir",
    ]
    for x in kapali:
        if x in text:
            return False, None, "İlan metni başvurunun kapandığını belirtiyor."

    son = None
    for pattern in TARIH_PATTERNS:
        for m in re.finditer(pattern, text, re.I):
            vals = m.groups()
            candidates = [tarih_parse(x) for x in vals if x]
            candidates = [x for x in candidates if x]
            if candidates:
                candidate = max(candidates)
                if son is None or candidate > son:
                    son = candidate

    if son and son < date.today():
        return False, son, f"Son başvuru tarihi {son.strftime('%d.%m.%Y')} geçmiş."
    if son:
        return True, son, f"Son başvuru: {son.strftime('%d.%m.%Y')}."
    return True, None, "Son başvuru tarihi otomatik tespit edilemedi."


# ============================================================
# KPSS
# ============================================================

def kpss_kontrol(text):
    if "kpss" not in text:
        return True, None, None, ["KPSS şartı tespit edilmedi."]

    # Önce P93/P94/P3 gibi puan türünü bul.
    turler = re.findall(r"\bP\s*([0-9]{1,3})\b", text, re.I)
    turler = ["P" + x for x in turler]

    # P93 açıkça geçiyorsa onu esas al.
    if turler and "P93" not in turler:
        # P3/P94 gibi başka puan türü açıkça zorunluysa,
        # bunu aday açısından uygun kabul etmiyoruz.
        if any(x in ("P3", "P94", "P95", "P96", "P97", "P99") for x in turler):
            return False, None, turler[0], [
                "İlanda P93 yerine farklı bir KPSS puan türü açıkça belirtilmiş."
            ]

    # "en az 70 KPSS", "KPSSP93 70", "KPSS 70 puan"
    sayilar = []
    for m in re.finditer(r"(?:kpss(?:p\d{1,3})?|p93).{0,180}", text):
        bolge = m.group(0)
        for n in re.findall(r"\b(\d{2}(?:[.,]\d+)?)\b", bolge):
            try:
                v = float(n.replace(",", "."))
                if 40 <= v <= 100:
                    sayilar.append(v)
            except ValueError:
                pass

    # Çoklu sayılarda en düşük sayı çoğunlukla taban puandır.
    # Başka tarih/sayıların yanlış alınmasını azaltmak için yalnızca
    # KPSS bağlamındaki sayıları kullanıyoruz.
    taban = min(sayilar) if sayilar else None

    if taban is None:
        return True, None, "P93", [
            "KPSS şartı var; ancak taban puan metinden güvenilir biçimde çıkarılamadı."
        ]

    if "P93" in turler or not turler:
        if taban > KPSS_PUANI:
            return False, taban, "P93", [
                f"KPSS tabanı {taban}; aday puanı {KPSS_PUANI}."
            ]
        return True, taban, "P93", [
            f"KPSS tabanı {taban}; aday puanı {KPSS_PUANI} yeterli."
        ]

    return False, taban, turler[0], [
        f"KPSS puan türü {turler[0]}; adayın kullanılacak puanı P93."
    ]


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
    if any(x in text for x in lisans_zorunlu):
        return False, ["Lisans mezuniyeti zorunlu."]

    onlisans = [
        "onlisans",
        "on lisans",
        "onlisans mezunu",
        "on lisans mezunu",
        "onlisans mezunlarindan",
        "on lisans mezunlarindan",
        "onlisans programi",
        "on lisans programi",
        "onlisans mezuniyeti",
    ]
    if any(x in text for x in onlisans):
        return True, ["Önlisans şartı bulunuyor."]

    # Eğitim seviyesi hiç geçmiyorsa bunu otomatik red etmiyoruz.
    return True, ["Eğitim seviyesi metinde açıkça tespit edilemedi; dışlanmadı."]


# ============================================================
# BÖLÜM
# ============================================================

def bolum_kontrol(text):
    # Açıkça genel bölüm/alan şartı yoksa Adalet mezununu dışlama.
    genel = [
        "herhangi bir bolum",
        "herhangi bir alan",
        "bolum sarti aranmaksizin",
        "alan sarti aranmaksizin",
        "brans sarti aranmaksizin",
        "herhangi bir onlisans",
        "herhangi bir on lisans",
        "onlisans mezunu olmak",
        "on lisans mezunu olmak",
    ]
    if any(x in text for x in genel):
        return True, ["Belirli bir bölüm şartı yok; Adalet mezunu başvurabilir."]

    adalet = [
        "adalet bolumu",
        "adalet programi",
        "adalet mezunu",
        "adalet mezunlarindan",
        "adalet onlisans",
        "adalet on lisans",
        "adalet programından",
    ]
    if any(x in text for x in adalet):
        return True, ["Adalet bölümü/programı kabul ediliyor."]

    # Adalet ile açıkça bağdaşmayan özel nitelikler.
    farkli = [
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
    bulunan = sorted(set(x for x in farkli if x in text))
    if bulunan:
        return False, [
            "Adalet dışındaki özel bölüm/nitelik isteniyor: "
            + ", ".join(bulunan)
        ]

    # Kritik kural: Bölüm belirtilmiyorsa Adalet mezununu dışlama.
    return True, [
        "Belirli bir bölüm şartı tespit edilmedi; Adalet mezunu dışlanmadı."
    ]


# ============================================================
# CİNSİYET
# ============================================================

def cinsiyet_kontrol(text):
    if CINSIYET == "erkek":
        kadin = [
            "sadece kadin",
            "kadin adaylar",
            "kadin aday",
            "kadın adaylar",
            "kadın aday",
            "kadin olmak",
            "kadın olmak",
        ]
        if any(x in text for x in kadin):
            return False, ["İlan yalnızca kadın adaylara açık."]

    if CINSIYET == "kadin":
        erkek = [
            "sadece erkek",
            "erkek adaylar",
            "erkek aday",
            "erkek olmak",
        ]
        if any(x in text for x in erkek):
            return False, ["İlan yalnızca erkek adaylara açık."]

    return True, ["Cinsiyet açısından engel tespit edilmedi."]


# ============================================================
# YAŞ
# ============================================================

def yas_kontrol(text):
    # 30 yaşından gün almamış / 30 yaşını doldurmamış
    patterns = [
        (r"(\d{1,2})\s*yasindan\s*gun\s*almamis", "gun_almamis"),
        (r"(\d{1,2})\s*yasini\s*doldurmamis", "doldurmamis"),
        (r"(\d{1,2})\s*yasini\s*gecmemis", "gecmemis"),
        (r"(\d{1,2})\s*yasindan\s*buyuk\s*olmamak", "buyuk_olmamak"),
    ]

    for pattern, kind in patterns:
        m = re.search(pattern, text)
        if not m:
            continue

        limit = int(m.group(1))

        if kind == "gun_almamis":
            ok = YAS < limit
        else:
            ok = YAS < limit

        if ok:
            return True, [f"Yaş sınırı {limit}; aday yaşı {YAS}."]
        return False, [f"İlan {limit} yaş sınırı koyuyor; aday yaşı {YAS}."]

    # "35 yaşından büyük olmamak" / "35 yaşını geçmemiş"
    m = re.search(r"(\d{1,2})\s*yasindan\s*buyuk\s*olmamak", text)
    if m:
        limit = int(m.group(1))
        ok = YAS <= limit
        return ok, [f"Yaş sınırı {limit}; aday yaşı {YAS}."]

    return True, ["Yaş açısından engel tespit edilmedi."]


# ============================================================
# ANALİZ
# ============================================================

def analiz_et(ilan):
    baslik = normalize(ilan.get("title", ""))
    rss = normalize(ilan.get("description", ""))
    detay = normalize(ilan.get("detail_text", ""))

    text = " ".join(x for x in [baslik, rss, detay] if x)
    neden = []
    red = []

    tarih_ok, son_tarih, tarih_nedeni = tarih_kontrol(text)
    neden.append(tarih_nedeni)
    if not tarih_ok:
        red.append(tarih_nedeni)

    k_ok, k_taban, k_tur, k_neden = kpss_kontrol(text)
    neden.extend(k_neden)
    if not k_ok:
        red.extend(k_neden)

    o_ok, o_neden = ogrenim_kontrol(text)
    neden.extend(o_neden)
    if not o_ok:
        red.extend(o_neden)

    b_ok, b_neden = bolum_kontrol(text)
    neden.extend(b_neden)
    if not b_ok:
        red.extend(b_neden)

    c_ok, c_neden = cinsiyet_kontrol(text)
    neden.extend(c_neden)
    if not c_ok:
        red.extend(c_neden)

    y_ok, y_neden = yas_kontrol(text)
    neden.extend(y_neden)
    if not y_ok:
        red.extend(y_neden)

    # Gerçekten çözülemeyen tek önemli durum:
    # KPSS şartı var ama puan türü/tabanı belirsiz.
    manuel = (
        k_ok
        and "KPSS şartı var; ancak taban puan metinden güvenilir biçimde çıkarılamadı." in k_neden
        and "P93" not in text
        and "puan siralamasi" not in text
        and "puan sıralaması" not in text
    )

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
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram secret bilgileri eksik.")

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mesaj,
            "disable_web_page_preview": False,
        },
        timeout=TIMEOUT,
    )
    print("[TELEGRAM]", r.status_code)
    if not r.ok:
        print("[TELEGRAM HATA]", r.text)
    r.raise_for_status()


def telegram_mesaji(ilan, analiz):
    title = ilan.get("title", "")
    link = ilan.get("link", "")
    aciklama = temiz_html(ilan.get("description", ""))

    if len(aciklama) > 1200:
        aciklama = aciklama[:1200] + "..."

    tarih = analiz["son_tarih"]
    tarih_text = tarih.strftime("%d.%m.%Y") if tarih else "Otomatik tespit edilemedi"

    kpss = "Yok / şart tespit edilmedi"
    if "KPSS" in " ".join(analiz["neden"]):
        if analiz["taban"] is not None:
            kpss = f"{analiz['puan_turu'] or 'KPSS'} ≥ {analiz['taban']} | Aday: {KPSS_PUANI}"
        else:
            kpss = "Var fakat taban otomatik tespit edilemedi"

    neden = "\n".join("• " + x for x in analiz["neden"])

    return (
        "⚖️ KAMU İLAN TAKİP\n\n"
        f"📌 {title}\n\n"
        f"{analiz['durum']}\n\n"
        f"🎓 Öğrenim: Önlisans\n"
        f"⚖️ Bölüm: Adalet\n"
        f"👤 Cinsiyet: Erkek\n"
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
    print("=" * 55)
    print("KAMU İLAN TAKİP - NİHAİ SÜRÜM")
    print(f"KPSS: {KPSS_PUANI} ({KPSS_TURU})")
    print(f"Öğrenim: {OGRENIM}")
    print(f"Bölüm: {BOLUM}")
    print(f"Cinsiyet: {CINSIYET}")
    print(f"Yaş: {YAS}")
    print("=" * 55)

    print("\n=== ORTAM ===")
    print("TELEGRAM_TOKEN:", "VAR" if TELEGRAM_TOKEN else "YOK")
    print("TELEGRAM_CHAT_ID:", "VAR" if TELEGRAM_CHAT_ID else "YOK")

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[HATA] Telegram secret eksik.")
        return

    try:
        rss_url = rss_adresini_bul()
        response = get_url(rss_url)
        ilanlar = rss_oku(response.content)
    except Exception as e:
        print("[HATA] RSS:", repr(e))
        return

    if not ilanlar:
        print("[HATA] Hiç ilan bulunamadı.")
        return

    sent = gonderilenleri_oku()

    toplam = len(ilanlar)
    uygun = 0
    manuel = 0
    red = 0
    gonderildi = 0

    print("\n" + "=" * 55)
    print("İLAN ANALİZLERİ")
    print("=" * 55)

    for i, ilan in enumerate(ilanlar, 1):
        print(f"\n[{i}/{toplam}] {ilan.get('title', '')}")

        # RSS metni yetersizse ilan detayını da çek.
        detail = detay_metni_al(ilan)
        ilan["detail_text"] = detail

        sonuc = analiz_et(ilan)
        print("DURUM:", sonuc["durum"])

        if sonuc["durum"].startswith("🟢"):
            uygun += 1
        elif sonuc["durum"].startswith("🔴"):
            red += 1
        else:
            manuel += 1

        iid = ilan_id(ilan)

        if iid in sent:
            print("Telegram: DAHA ÖNCE GÖNDERİLDİ")
  continue

        # Yalnızca yeni ve kullanıcı açısından anlamlı ilanları gönder.
        # Kırmızı ilanları Telegram'a spam olarak yollamıyoruz.
        if sonuc["durum"].startswith(("🟢", "🟡")):
            try:
                telegram_gonder(telegram_mesaji(ilan, sonuc))
                sent.add(iid)
                gonderildi += 1
                print("Telegram: GÖNDERİLDİ")
            except Exception as e:
                print("[TELEGRAM HATA]", repr(e))
        else:
            print("Telegram: BAŞVURAMAZSIN - gönderilmedi")

    gonderilenleri_kaydet(sent)

    print("\n" + "=" * 55)
    print("TARAMA TAMAMLANDI")
    print("=" * 55)
    print("Toplam ilan:", toplam)
    print("🟢 Başvurabilir:", uygun)
    print("🟡 Kontrol gerekiyor:", manuel)
    print("🔴 Başvuramaz:", red)
    print("📨 Telegram'a gönderilen:", gonderildi)
    print("=" * 55)


if __name__ == "__main__":
    main()
    
