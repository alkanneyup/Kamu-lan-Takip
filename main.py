import os
import re
import sys
import json
import html
import hashlib
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, date
from urllib.parse import urljoin
from typing import List, Dict, Tuple, Set, Optional, Any
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    stream=sys.stdout,
    force=True
)

try:
    from iskur import iskur_ilanlarini_getir
except Exception as import_err:
    logging.error(f"iskur.py yüklenirken hata oluştu: {import_err}")

    def iskur_ilanlarini_getir() -> List[Dict[str, str]]:
        return []

USER_PROFILE: Dict[str, Any] = {
    "egitim": "Önlisans",
    "bolum": "Adalet",
    "puan_turu": "P93",
    "kpss": 80.86227,
    "cinsiyet": "Erkek",
    "yas": 29,
    "ikincil_hemsirelik_lisans": True,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

KESIN_ELENECEK_IFADELER = [
    "cumhurbaşkanlığı kararı", "cumhurbaşkanlığı kararnamesi", "kararname",
    "kanun", "kanunu", "yönetmelik", "yönetmeliği", "genelge", "genelgesi",
    "tebliğ", "tebliği", "mahkeme kararı", "yargıtay", "danıştay",
    "ihale ilanı", "ihalesi", "kamulaştırma", "vergi düzenlemesi", "vergi usul",
    "görevden alma", "siyasi", "ekonomi haberi", "basın açıklaması",
    "sınav sonucu", "sınav sonuçları", "mülakat sonucu", "mülakat sonuçları",
    "yerleştirme sonucu", "yerleştirme sonuçları", "nihai liste", "asıl ve yedek",
    "tebligat", "dilekçe", "ücret tarifesi", "kura sonucu",
    "önceki sayı", "sonraki sayı", "ana sayfa", "mevzuat bilgi sistemi",
    "abonelik", "künye", "iletişim"
]

ALIM_SINYALLERI = [
    "personel alım", "personel alımı", "memur alım", "memur alımı",
    "sözleşmeli personel", "sürekli işçi", "geçici işçi", "işçi alımı",
    "kamu personeli", "personel temin", "alım ilanı", "alınacaktır", "alacak"
]

KADRO_UNVANLARI = [
    "memur", "sözleşmeli personel", "sürekli işçi", "geçici işçi",
    "büro personeli", "destek personeli", "zabıt katibi", "zabıt kâtibi",
    "infaz ve koruma memuru", "infaz koruma", "icra memuru", "icra katibi",
    "vhki", "veri hazırlama ve kontrol işletmeni", "koruma ve güvenlik",
    "teknisyen", "tekniker", "mühendis", "şoför", "hizmetli", "hemşire",
    "öğretim görevlisi", "araştırma görevlisi", "profesör", "doçent", "dr. öğretim"
]

AKADEMIK_IFADELER = [
    "öğretim görevlisi", "araştırma görevlisi", "profesör", "doçent",
    "dr. öğretim üyesi", "doktor öğretim üyesi", "akademik personel", "2547"
]

KURUM_IFADELERI = [
    "bakanlığı", "bakanlık", "üniversitesi", "üniversite", "belediyesi",
    "belediye", "müdürlüğü", "başkanlığı", "genel müdürlüğü", "kurumu",
    "valiliği", "kaymakamlığı", "adalet bakanlığı", "sağlık bakanlığı", "işkur"
]


def tr_lower(metin: str) -> str:
    if not metin:
        return ""
    donusum = {"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"}
    for eski, yeni in donusum.items():
        metin = metin.replace(eski, yeni)
    return metin.lower()


def generate_id(metin: str) -> str:
    return hashlib.md5(metin.encode("utf-8")).hexdigest()


def ilan_kimligi_olustur(baslik: str, kurum: str, pozisyon: str, link: str) -> str:
    anahtar = "|".join([
        tr_lower(baslik).strip(),
        tr_lower(kurum).strip(),
        tr_lower(pozisyon).strip(),
        (link or "").strip().lower(),
    ])
    return generate_id(anahtar)


def load_sent_ids() -> Set[str]:
    if os.path.exists("sent_ids.json"):
        try:
            with open("sent_ids.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except Exception as e:
            logging.error(f"sent_ids.json okuma hatası: {e}")
            return set()
    return set()


def save_sent_ids(sent_ids: Set[str]) -> None:
    try:
        with open("sent_ids.json", "w", encoding="utf-8") as f:
            json.dump(sorted(list(sent_ids)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"sent_ids.json kaydetme hatası: {e}")


def _linkleri_topla(url: str, kaynak: str, session: Optional[requests.Session] = None) -> List[Dict[str, str]]:
    sonuc: List[Dict[str, str]] = []
    seen: Set[str] = set()
    client = session if session else requests
    r = client.get(url, headers=None if session else HEADERS, timeout=(4, 7), allow_redirects=True)
    if r.status_code != 200:
        logging.warning(f"[{kaynak}] HTTP {r.status_code}")
        return sonuc
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        baslik = " ".join(a.get_text(" ", strip=True).split())
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")) or len(baslik) < 10:
            continue
        full_url = urljoin(r.url, href)
        if full_url.rstrip("/") == r.url.rstrip("/"):
            continue
        if full_url not in seen:
            seen.add(full_url)
            sonuc.append({"title": baslik, "link": full_url, "source": kaynak})
    return sonuc


def kaynaklari_topla() -> List[Dict[str, str]]:
    tum: List[Dict[str, str]] = []

    try:
        tum.extend(_linkleri_topla("https://www.resmigazete.gov.tr/", "Resmî Gazete"))
    except Exception as e:
        logging.error(f"Resmî Gazete hatası: {e}")

    try:
        sbb = requests.Session()
        sbb.headers.update({
            **HEADERS,
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        })
        ilk = sbb.get("https://kamuilan.sbb.gov.tr/", timeout=(5, 8), allow_redirects=True)
        if ilk.status_code == 200:
            sbb.headers.update({"Referer": ilk.url, "Sec-Fetch-Site": "same-origin"})
            tum.extend(_linkleri_topla(ilk.url, "SBB Kamu İlan", session=sbb))
        else:
            logging.warning(f"[SBB Kamu İlan] HTTP {ilk.status_code}")
        sbb.close()
    except Exception as e:
        logging.error(f"SBB hatası: {e}")

    try:
        r = requests.get("https://kariyerkapisi.gov.tr/RSS", headers=HEADERS, timeout=(4, 7))
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            for item in root.findall("./channel/item"):
                t = (item.find("title").text or "").strip() if item.find("title") is not None else ""
                l = (item.find("link").text or "").strip() if item.find("link") is not None else ""
                if t and l:
                    tum.append({"title": t, "link": l, "source": "Kariyer Kapısı"})
        tum.extend(_linkleri_topla("https://kariyerkapisi.gov.tr/", "Kariyer Kapısı"))
    except Exception as e:
        logging.error(f"Kariyer Kapısı hatası: {e}")

    try:
        iskur_veri = iskur_ilanlarini_getir() or []
        for kayit in iskur_veri:
            if isinstance(kayit, dict):
                kayit.setdefault("source", "İŞKUR")
                tum.append(kayit)
    except Exception as e:
        logging.error(f"İŞKUR hatası: {e}")

    return tum


def _json_metin(obj: Any) -> str:
    if isinstance(obj, str):
        return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", obj)).split())
    if isinstance(obj, dict):
        return " ".join(_json_metin(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(_json_metin(v) for v in obj)
    return ""


def detay_oku(url: str) -> str:
    if not url:
        return ""
    parcalar: List[str] = []
    try:
        m = re.search(r"i=([a-f0-9-]+)", url, re.IGNORECASE)
        if m and "kariyerkapisi" in url:
            guid = m.group(1)
            for api in [
                f"https://kariyerkapisi.gov.tr/RSS/IlanDetayGetir?id={guid}",
                f"https://kariyerkapisi.gov.tr/IlanDetay/Getir?id={guid}",
            ]:
                try:
                    ar = requests.get(api, headers=HEADERS, timeout=(3, 5))
                    if ar.status_code == 200:
                        try:
                            parcalar.append(_json_metin(ar.json()))
                        except Exception:
                            parcalar.append(" ".join(html.unescape(re.sub(r"<[^>]+>", " ", ar.text)).split()))
                except Exception:
                    continue

        r = requests.get(url, headers=HEADERS, timeout=(3, 5), allow_redirects=True)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            parcalar.append(" ".join(soup.get_text(" ", strip=True).split()))
    except Exception:
        pass
    return " ".join(p for p in parcalar if p)[:15000]
def _kurum_cikar(baslik: str, detay: str) -> str:
    for kaynak_metin in (baslik, detay):
        m = re.search(
            r"([A-ZÇĞİÖŞÜ][a-zçğıöşüA-ZÇĞİÖŞÜ0-9\s\-]{2,55}?(?:Bakanlığı|Üniversitesi|Belediyesi|Genel Müdürlüğü|Başkanlığı|Müdürlüğü|Kurumu))",
            kaynak_metin
        )
        if m:
            return " ".join(m.group(1).split())
    return "Belirtilmemiş"


def _pozisyon_cikar(baslik: str, detay: str) -> str:
    birlesik = f"{baslik} {detay}"
    birlesik_tr = tr_lower(birlesik)
    for u in KADRO_UNVANLARI:
        if u in birlesik_tr:
            return u.title()
    return "Belirtilmemiş"


def _kontenjan_cikar(metin_tr: str) -> str:
    m = re.search(r"(?:kontenjan|alınacak|kadro)\D{0,25}?(\d{1,4})\s*(?:kişi|personel|memur|işçi|adet)", metin_tr)
    if m:
        return f"{m.group(1)} kişi"
    return "Belirtilmemiş"


def _egitim_ve_kpss_cikar(metin_tr: str) -> Tuple[str, str]:
    egitim = "Belirtilmemiş"
    if "önlisans" in metin_tr or "ön lisans" in metin_tr or "myo" in metin_tr or "meslek yüksekokulu" in metin_tr:
        egitim = "Önlisans"
    elif "lisans" in metin_tr or "hemşirelik" in metin_tr:
        egitim = "Lisans"
    elif "ortaöğretim" in metin_tr or "lise" in metin_tr:
        egitim = "Ortaöğretim"

    kpss_turu = "Belirtilmemiş"
    for tur in ("p93", "p3", "p94", "kpss"):
        if tur in metin_tr:
            kpss_turu = tur.upper()
            break
    return egitim, kpss_turu


def _tarihleri_cikar(detay: str, bugun: date) -> Tuple[str, str, Optional[date]]:
    baslangic_m = re.findall(
        r"(?:başvuru başlangıç|başvurular\D{0,20}?tarihinde)\D*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})",
        detay,
        re.IGNORECASE
    )
    bitis_m = re.findall(
        r"(?:son başvuru|son gün|başvuru bitiş|tarihine kadar)\D*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})",
        detay,
        re.IGNORECASE
    )
    bas_str = baslangic_m[0] if baslangic_m else "Belirtilmemiş"
    son_str = "Belirtilmemiş"
    son_dt: Optional[date] = None

    if bitis_m:
        raw_son = bitis_m[0].strip().replace("/", ".").replace("-", ".")
        son_str = raw_son
        for fmt in ("%d.%m.%Y", "%d.%m.%y"):
            try:
                son_dt = datetime.strptime(raw_son, fmt).date()
                son_str = son_dt.strftime("%d.%m.%Y")
                break
            except ValueError:
                continue

    return bas_str, son_str, son_dt


def _kategori_belirle(baslik_tr: str, detay_tr: str, son_dt: Optional[date], bugun: date) -> str:
    metin = f"{baslik_tr} {detay_tr}"
    if any(s in metin for s in ["sınav sonucu", "mülakat sonucu", "yerleştirme sonucu", "nihai liste"]):
        return "SONUÇ DUYURUSU"
    if son_dt is not None and son_dt < bugun:
        return "SÜRESİ GEÇMİŞ"
    if any(g in metin for g in ["güncelleme", "düzeltme ilanı", "ek ilan", "başvuru tarihi uzat"]):
        return "İLAN GÜNCELLEMESİ"
    return "YENİ ALIM"


def _profil_uygunlugu_degerlendir(
    metin_tr: str,
    egitim: str,
    profil: Optional[Dict[str, Any]] = None
) -> str:
    p = profil or USER_PROFILE
    kpss_puan = float(p.get("kpss", 80.86227))
    yas = int(p.get("yas", 29))
    cinsiyet_tr = tr_lower(str(p.get("cinsiyet", "")))

    yas_limitleri = re.findall(r"(\d{2})\s*yaşını doldurmamış|en fazla\s*(\d{2})\s*yaş|(\d{2})\s*yaşından gün almamış", metin_tr)
    for grp in yas_limitleri:
        for val in grp:
            if val.isdigit() and yas > int(val):
                return "Uygun Değil"

    if cinsiyet_tr == "erkek" and re.search(r"\byalnızca kadın\b|\bkadın aday\b", metin_tr):
        return "Uygun Değil"
    if cinsiyet_tr == "kadın" and re.search(r"\byalnızca erkek\b|\berkek aday\b", metin_tr):
        return "Uygun Değil"

    puanlar = re.findall(r"(?:kpss|p93|p3|p94|taban puan)\D*([5-9][0-9](?:[\.,][0-9]+)?)", metin_tr)
    for raw_p in puanlar:
        try:
            taban = float(raw_p.replace(",", "."))
            if 50.0 <= taban <= 100.0 and kpss_puan < taban:
                return "Uygun Değil"
        except ValueError:
            continue

    if p.get("ikincil_hemsirelik_lisans") and "hemşire" in metin_tr and ("lisans" in metin_tr or "hemşirelik" in metin_tr):
        return "Uygun"

    onlisans_uyumlu = egitim == "Önlisans" or any(
        e in metin_tr for e in ["önlisans", "ön lisans", "p93", "3001", "adalet", "zabıt katibi", "zabıt kâtibi", "icra katibi"]
    )
    if onlisans_uyumlu:
        return "Uygun"

    if egitim == "Lisans" and not p.get("ikincil_hemsirelik_lisans"):
        return "Uygun Değil"

    return "Kontrol Gerekli"


def ilan_degerlendir(
    baslik: str,
    detay: str,
    kaynak: str = "Kamu Portalı",
    link: str = "",
    bugun: Optional[date] = None,
    profil: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    ref_tarih = bugun or datetime.now().date()
    baslik_tr = tr_lower(baslik)
    detay_tr = tr_lower(detay)
    metin_tr = f"{baslik_tr} {detay_tr}"

    if any(k in metin_tr for k in KESIN_ELENECEK_IFADELER):
        return {"kabul": False, "puan": 0, "sebep": "Hariç tutulan içerik"}

    if len(detay.strip()) < 60:
        return {"kabul": False, "puan": 0, "sebep": "Detay metni yetersiz"}

    baslik_alim = any(a in baslik_tr for a in ALIM_SINYALLERI)
    metin_alim = any(a in metin_tr for a in ALIM_SINYALLERI)
    kurum = _kurum_cikar(baslik, detay)
    pozisyon = _pozisyon_cikar(baslik, detay)
    kontenjan = _kontenjan_cikar(metin_tr)
    egitim, kpss_turu = _egitim_ve_kpss_cikar(metin_tr)
    bas_tarih, son_tarih, son_dt = _tarihleri_cikar(detay, ref_tarih)
    kategori = _kategori_belirle(baslik_tr, detay_tr, son_dt, ref_tarih)

    if kategori == "SÜRESİ GEÇMİŞ":
        return {"kabul": False, "puan": 0, "sebep": "Başvuru süresi geçmiş"}

    if not metin_alim:
        return {"kabul": False, "puan": 0, "sebep": "Gerçek personel alım sinyali yok"}

    # En az eğitim/KPSS veya pozisyon/kontenjan şartı doğrulanmış olmalı
    sart_kaniti_var = (
        egitim != "Belirtilmemiş"
        or kpss_turu != "Belirtilmemiş"
        or kontenjan != "Belirtilmemiş"
        or pozisyon != "Belirtilmemiş"
    )
    if not sart_kaniti_var:
        return {"kabul": False, "puan": 0, "sebep": "Şart/kadro bilgisi doğrulanamadı"}

    puan = 0
    if baslik_alim:
        puan += 30
    if kurum != "Belirtilmemiş" or any(k in metin_tr for k in KURUM_IFADELERI):
        puan += 15
    if pozisyon != "Belirtilmemiş":
        puan += 15
    if kontenjan != "Belirtilmemiş":
        puan += 10
    if kpss_turu != "Belirtilmemiş" or "kpss" in metin_tr:
        puan += 10
    if bas_tarih != "Belirtilmemiş" or son_tarih != "Belirtilmemiş":
        puan += 10
    if link.startswith(("http://", "https://")):
        puan += 10

    akademik_mi = any(ak in metin_tr for ak in AKADEMIK_IFADELER)
    uygunluk = _profil_uygunlugu_degerlendir(metin_tr, egitim, profil)

    kabul = (puan >= 50) and (uygunluk == "Uygun")
    kimlik = ilan_kimligi_olustur(baslik, kurum, pozisyon, link)

    return {
        "kabul": kabul,
        "puan": puan,
        "kategori": "AKADEMİK PERSONEL" if akademik_mi else kategori,
        "kurum": kurum,
        "pozisyon": pozisyon,
        "kontenjan": kontenjan,
        "egitim": egitim,
        "kpss": kpss_turu,
        "basvuru_tarihi": bas_tarih,
        "son_basvuru": son_tarih,
        "uygunluk": uygunluk,
        "link": link or "Belirtilmemiş",
        "kimlik": kimlik,
        "sebep": "ok" if kabul else f"Uygun değil veya yetersiz puan ({uygunluk}, {puan})",
    }


def bildirim_metni_olustur(kayit: Dict[str, Any]) -> str:
    baslik_etiket = "🎓 AKADEMİK PERSONEL İLANI" if kayit.get("kategori") == "AKADEMİK PERSONEL" else "🏛️ YENİ KAMU PERSONEL ALIMI"
    if kayit.get("kategori") == "İLAN GÜNCELLEMESİ":
        baslik_etiket = "🔄 İLAN GÜNCELLEMESİ"

    link = kayit.get("link", "Belirtilmemiş")
    resmi_ilan_satiri = f"<a href='{html.escape(link, quote=True)}'>İlan Bağlantısı</a>" if link.startswith(("http://", "https://")) else "Belirtilmemiş"

    return (
        f"<b>{baslik_etiket}</b>\n\n"
        f"Kurum: {html.escape(str(kayit.get('kurum', 'Belirtilmemiş')))}\n"
        f"Pozisyon: {html.escape(str(kayit.get('pozisyon', 'Belirtilmemiş')))}\n"
        f"Kontenjan: {html.escape(str(kayit.get('kontenjan', 'Belirtilmemiş')))}\n"
        f"Eğitim: {html.escape(str(kayit.get('egitim', 'Belirtilmemiş')))}\n"
        f"KPSS: {html.escape(str(kayit.get('kpss', 'Belirtilmemiş')))}\n"
        f"Başvuru Tarihi: {html.escape(str(kayit.get('basvuru_tarihi', 'Belirtilmemiş')))}\n"
        f"Son Başvuru: {html.escape(str(kayit.get('son_basvuru', 'Belirtilmemiş')))}\n\n"
        f"📌 Kullanıcı Profili: {html.escape(str(kayit.get('uygunluk', 'Uygun')))}\n\n"
        f"🔗 Resmî İlan: {resmi_ilan_satiri}\n"
        f"🔗 Başvuru: {resmi_ilan_satiri}"
    )


def telegram_gonder(items: List[str]) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_ids = [c.strip() for c in (os.getenv("TELEGRAM_CHAT_ID") or "").split(",") if c.strip()]
    if not token or not chat_ids:
        logging.error("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    blok: List[str] = []
    uzunluk = 0

    def _gonder_parca(parca_liste: List[str]) -> bool:
        metin = "\n\n---\n\n".join(parca_liste)
        basarili = True
        for cid in chat_ids:
            r = requests.post(
                url,
                json={
                    "chat_id": cid,
                    "text": metin[:4000],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            if r.status_code != 200:
                logging.error(f"Telegram hatası ({cid}): {r.text}")
                basarili = False
        return basarili

    for item in items:
        if uzunluk + len(item) + 10 > 3800 and blok:
            if not _gonder_parca(blok):
                ok = False
            blok = []
            uzunluk = 0
        blok.append(item)
        uzunluk += len(item) + 10

    if blok and not _gonder_parca(blok):
        ok = False

    return ok


def main() -> None:
    bugun = datetime.now().date()
    logging.info(f"KAMU İLAN TAKİP BAŞLADI ({bugun})")

    sent_ids = load_sent_ids()
    new_ids = set(sent_ids)
    adaylar = kaynaklari_topla()

    tekil: List[Dict[str, str]] = []
    gorulen: Set[str] = set()
    for a in adaylar:
        uid = generate_id(a.get("link") or a.get("title", ""))
        if uid not in gorulen:
            gorulen.add(uid)
            tekil.append(a)

    logging.info(f"İncelenecek tekil bağlantı sayısı: {len(tekil)}")
    gonderilecek_mesajlar: List[str] = []
    gorulen_kimlik_bu_tur: Set[str] = set()

    for ilan in tekil:
        baslik = ilan.get("title", "")
        link = ilan.get("link", "")
        kaynak = ilan.get("source", "Kamu Portalı")

        detay = detay_oku(link) if link else ""
        sonuc = ilan_degerlendir(baslik, detay, kaynak=kaynak, link=link, bugun=bugun)

        if not sonuc["kabul"] or sonuc["kategori"] == "SONUÇ DUYURUSU" or sonuc["uygunluk"] != "Uygun":
            continue

        kimlik = sonuc["kimlik"]
        if kimlik in sent_ids or kimlik in gorulen_kimlik_bu_tur:
            continue

        gorulen_kimlik_bu_tur.add(kimlik)
        logging.info(
            f"[{kaynak}] [{sonuc['kategori']}] [{sonuc['uygunluk']}] (Puan: {sonuc['puan']}) -> {baslik}"
        )
        gonderilecek_mesajlar.append(bildirim_metni_olustur(sonuc))
        new_ids.add(kimlik)

    if gonderilecek_mesajlar:
        if telegram_gonder(gonderilecek_mesajlar):
            save_sent_ids(new_ids)
            logging.info(f"{len(gonderilecek_mesajlar)} uygun ilan Telegram üzerinden bildirildi.")
        else:
            logging.error("Telegram bildirimi sırasında hata oluştu.")
    else:
        logging.info("Profilinize uygun ve şartları doğrulanmış yeni ilan bulunamadı.")


def run_tests() -> None:
    bugun = date(2026, 11, 23)
    test_profil = {
        "egitim": "Önlisans",
        "bolum": "Adalet",
        "puan_turu": "P93",
        "kpss": 76.29,
        "cinsiyet": "Erkek",
        "yas": 29,
        "ikincil_hemsirelik_lisans": False,
    }

    r1 = ilan_degerlendir(
        "Adalet Bakanlığı Sözleşmeli Zabıt Kâtibi Alım İlanı",
        "Kurum: Adalet Bakanlığı. Kontenjan: 50 kişi. Önlisans Adalet bölümü mezunları, KPSS P93 en az 70 puan. Son Başvuru: 15.12.2026.",
        kaynak="Kariyer Kapısı",
        link="https://kariyerkapisi.gov.tr/ilan/1",
        bugun=bugun,
        profil=test_profil,
    )
    assert r1["kabul"] and r1["uygunluk"] == "Uygun"

    r_eksik = ilan_degerlendir(
        "Genel İlan Bağlantısı",
        "Kısa metin",
        kaynak="Kariyer Kapısı",
        link="https://kariyerkapisi.gov.tr/ilan/eksik",
        bugun=bugun,
        profil=test_profil,
    )
    assert not r_eksik["kabul"]

    r_kontrol = ilan_degerlendir(
        "Kurum Sözleşmeli Personel Alımı",
        "Kurum: Örnek Kurum. Lise mezunları için alım yapılacaktır. Son Başvuru: 15.12.2026.",
        kaynak="SBB Kamu İlan",
        link="https://kamuilan.sbb.gov.tr/ilan/lise",
        bugun=bugun,
        profil=test_profil,
    )
    assert not r_kontrol["kabul"]

    print("TÜM TEST SENARYOLARI BAŞARILI.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_tests()
    else:
        main()
