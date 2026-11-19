import os
import re
import json
import html
import hashlib
import logging
import requests
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Tuple, Set
from bs4 import BeautifulSoup
from iskur import iskur_ilanlarini_getir

# Loglama Yapılandırması
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s"
)

USER_PROFILE = {
    "kpss": 80.86227,
    "yas": 29
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}

# Takip Edilecek 20 Resmi ve Haber/İlan Kaynağı
SOURCES: List[Dict[str, str]] = [
    {"name": "Resmi Gazete", "url": "https://www.resmigazete.gov.tr"},
    {"name": "Kariyer Kapısı (CBİKO)", "url": "https://isealimkariyerkapisi.cbiko.gov.tr"},
    {"name": "SBB Kamu İlan", "url": "https://kamuilan.sbb.gov.tr"},
    {"name": "İŞKUR E-Şube", "url": "https://esube.iskur.gov.tr"},
    {"name": "ÖSYM AİS", "url": "https://ais.osym.gov.tr"},
    {"name": "ÖSYM", "url": "https://www.osym.gov.tr"},
    {"name": "Adalet Bakanlığı PGM", "url": "https://pgm.adalet.gov.tr"},
    {"name": "Sağlık Bakanlığı YHGM", "url": "https://yhgm.saglik.gov.tr"},
    {"name": "MEB Personel", "url": "https://personel.meb.gov.tr"},
    {"name": "İçişleri Bakanlığı Personel", "url": "https://www.icisleri.gov.tr/personel"},
    {"name": "Polis Akademisi", "url": "https://www.pa.edu.tr"},
    {"name": "MSB Personel Temin", "url": "https://personeltemin.msb.gov.tr"},
    {"name": "Jandarma PTM", "url": "https://vatandas.jandarma.gov.tr/PTM"},
    {"name": "YÖK İlan", "url": "https://ilan.yok.gov.tr"},
    {"name": "Türkiye Belediyeler Birliği", "url": "https://www.tbb.gov.tr"},
    {"name": "Memurlar.net İlan", "url": "https://ilan.memurlar.net"},
    {"name": "KamuPersoneli.net", "url": "https://www.kamupersoneli.net"},
    {"name": "İşinOlsa", "url": "https://www.isinolsa.com"},
    {"name": "KamuAjans", "url": "https://www.kamuajans.com"},
    {"name": "MyMemur", "url": "https://www.mymemur.com.tr"},
]

def tr_lower(metin: str) -> str:
    """Türkçe karakter desteği sağlanan küçük harfe dönüştürme fonksiyonu."""
    if not metin:
        return ""
    donusum = {"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"}
    for eski, yeni in donusum.items():
        metin = metin.replace(eski, yeni)
    return metin.lower()

def generate_id(metin: str) -> str:
    """Benzersiz ilan kimliği oluşturur."""
    return hashlib.md5(metin.encode('utf-8')).hexdigest()

def load_sent_ids() -> Set[str]:
    """Daha önce bildirilen ilan kimliklerini yükler."""
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
    """Bildirilen ilan kimliklerini kaydeder."""
    try:
        with open("sent_ids.json", "w", encoding="utf-8") as f:
            json.dump(list(sent_ids), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"sent_ids.json kaydetme hatası: {e}")

def send_telegram_messages(green_items: List[str]) -> bool:
    """Telegram mesajlarını tüm Chat ID'lere HTML etiketlerini bölmeden akıllı paketler halinde gönderir."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    raw_chat_ids = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not raw_chat_ids:
        logging.error("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID bulunamadı!")
        return False

    chat_ids = [cid.strip() for cid in raw_chat_ids.split(",") if cid.strip()]
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    messages: List[str] = []
    current_msg = "📢 <b>YENİ UYGUN KAMU İLANLARI TESPİT EDİLDİ</b>\n\n"

    if green_items:
        current_msg += "🟢 <b>SİZE UYGUN İLANLAR:</b>\n"
        for item in green_items:
            if len(current_msg) + len(item) + 4 > 3500:
                messages.append(current_msg)
                current_msg = "🟢 <b>SİZE UYGUN İLANLAR (Devam):</b>\n"
            current_msg += item + "\n\n"

    if current_msg.strip():
        messages.append(current_msg)

    all_success = True
    for chat_id in chat_ids:
        for msg in messages:
            payload = {
                "chat_id": chat_id,
                "text": msg.strip(),
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            try:
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code != 200:
                    logging.error(f"Telegram API Hatası ({chat_id}): {response.status_code} - {response.text}")
                    all_success = False
            except Exception as e:
                logging.error(f"Telegram mesajı gönderilirken istisna oluştu ({chat_id}): {e}")
                all_success = False

    return all_success

def kaynak_ilanlari_getir(kaynak_adi: str, base_url: str) -> List[Dict[str, str]]:
    """Verilen URL'deki bağlantıları tarayarak potansiyel ilan/duyuru kayıtlarını döndürür."""
    ilanlar: List[Dict[str, str]] = []
    seen_links: Set[str] = set()

    on_filtre_kelimeler = [
        "ilan", "personel", "alımı", "alacak", "memur", "sözleşmeli",
        "kpss", "tercih", "yerleştirme", "katip", "mübaşir", "infaz",
        "koruma", "güvenlik", "büro", "hemşire", "önlisans", "3001", "duyuru"
    ]

    try:
        res = requests.get(base_url, headers=HEADERS, timeout=10, allow_redirects=True)
        if res.status_code != 200:
            logging.warning(f"[{kaynak_adi}] HTTP {res.status_code} yanıtı döndü.")
            return ilanlar

        soup = BeautifulSoup(res.text, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = (a_tag.get("href") or "").strip()
            title = " ".join(a_tag.get_text(" ", strip=True).split())

            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            if not title or len(title) < 12 or len(title) > 260:
                continue

            title_tr = tr_lower(title)
            if any(k in title_tr for k in on_filtre_kelimeler):
                full_link = urljoin(res.url, href)
                parsed = urlparse(full_link)
                if parsed.scheme not in ("http", "https"):
                    continue
                if full_link in seen_links:
                    continue
                seen_links.add(full_link)

                ilanlar.append({
                    "title": title,
                    "link": full_link,
                    "source": kaynak_adi
                })
    except Exception as e:
        logging.error(f"[{kaynak_adi}] veri çekilirken hata oluştu ({base_url}): {e}")

    return ilanlar

def ilan_detay_getir(url: str) -> str:
    """İlan detay sayfasından temizlenmiş metin çeker."""
    if not url:
        return ""
    try:
        if "kariyerkapisi" in url:
            match = re.search(r'i=([a-f0-9-]+)', url, re.IGNORECASE)
            if match:
                guid = match.group(1)
                api_url = f"https://kariyerkapisi.gov.tr/RSS/IlanDetayGetir?id={guid}"
                res = requests.get(api_url, headers=HEADERS, timeout=8)
                if res.status_code == 200:
                    try:
                        data = res.json()
                        metin = data.get("Metin", "") or data.get("Açıklama", "") or str(data)
                        if metin and len(metin) > 50:
                            clean_text = re.sub(r'<[^>]+>', ' ', metin)
                            return " ".join(html.unescape(clean_text).split())
                    except Exception:
                        pass

        res = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
        if res.status_code == 200:
            clean_text = re.sub(r'<script.*?>.*?</script>', '', res.text, flags=re.DOTALL | re.IGNORECASE)
            clean_text = re.sub(r'<style.*?>.*?</style>', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
            clean_text = re.sub(r'<[^>]+>', ' ', clean_text)
            return " ".join(html.unescape(clean_text).split())[:15000]
    except Exception as e:
        logging.debug(f"İlan detayı çekilemedi ({url}): {e}")
    return ""

def son_basvuru_tarihi_bul(metin: str) -> str:
    """Metin içerisindeki son başvuru tarihini regex ile yakalar."""
    tarih_kaliplari = re.findall(
        r'(?:son başvuru|son gün|tarihine kadar)\D*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})',
        metin,
        re.IGNORECASE
    )
    if tarih_kaliplari:
        return f"⏰ Son Başvuru: {tarih_kaliplari[0]}"
    return "⏰ Son Başvuru: Detayda Belirtilmiş"

def ilan_analiz_et(baslik: str, detay_metni: str) -> Tuple[bool, str, str]:
    """Kesin eşleşme sağlayan Whitelist analizi yapar."""
    baslik_tr = tr_lower(baslik)
    metin_tr = tr_lower(baslik + " " + detay_metni)

    # ÖSYM / KPSS Yerleştirme veya Tercih Duyuruları
    if ("ösym" in baslik_tr or "kpss" in baslik_tr) and ("tercih" in baslik_tr or "yerleştirme" in baslik_tr):
        deadline = son_basvuru_tarihi_bul(detay_metni)
        return True, f"ÖSYM merkezi yerleştirme / tercih duyurusu. {deadline}", "Merkezi Tercih"

    # Lisans Hemşirelik Kontrolü
    if "hemşire" in baslik_tr or "hemşire" in metin_tr:
        if any(k in metin_tr for k in ["lisans", "fakülte", "sağlık bilimleri", "hemşirelik"]):
            deadline = son_basvuru_tarihi_bul(detay_metni)
            return True, f"Lisans Hemşirelik kadrosu tespit edildi. {deadline}", "Hemşirelik (Lisans)"

    # Adalet / Önlisans / 3001 / İlgili Kadro Kontrolü
    adalet_zorunlu_kelimeler = [
        "adalet", "zabıt katibi", "katip", "mübaşir", "icra katibi",
        "infaz koruma", "3001", "önlisans programlarının", "ön lisans programlarının",
        "adalet meslek yüksekokulu", "adalet programı"
    ]

    buro_ve_onlisans = (
        any(b in metin_tr for b in ["büro personeli", "koruma ve güvenlik", "destek personeli"])
        and any(e in metin_tr for e in ["önlisans", "ön lisans", "myo"])
    )

    if any(k in metin_tr for k in adalet_zorunlu_kelimeler) or buro_ve_onlisans:
        kpss_matches = re.findall(r'(?:kpss|p93|p3|p94|puan)\D*([5-9][0-9](?:[\.,][0-9]+)?)', metin_tr)
        for match in kpss_matches:
            try:
                req_score = float(match.replace(',', '.'))
                if 50.0 <= req_score <= 100.0:
                    if USER_PROFILE["kpss"] < req_score:
                        return False, "", ""
            except ValueError:
                continue
        deadline = son_basvuru_tarihi_bul(detay_metni)
        return True, f"Adalet / Önlisans şartları sağlandı. {deadline}", "Adalet (Önlisans)"

    return False, "", ""

def main() -> None:
    logging.info("============================================================")
    logging.info("KAMU İLAN TAKİP (20 Kaynak + İŞKUR + Deadline + Whitelist)")
    logging.info("============================================================")

    sent_ids = load_sent_ids()
    new_sent_ids = set(sent_ids)
    ilanlar: List[Dict[str, str]] = []

    # 1. Tanımlı 20 Kaynağın Tümü
    for src in SOURCES:
        kaynak_adi = src["name"]
        kaynak_url = src["url"]
        try:
            bulunanlar = kaynak_ilanlari_getir(kaynak_adi, kaynak_url)
            logging.info(f"[{kaynak_adi}] -> {len(bulunanlar)} aday bağlantı bulundu.")
            ilanlar.extend(bulunanlar)
        except Exception as e:
            logging.error(f"[{kaynak_adi}] genel tarama hatası: {e}")

    # 2. İŞKUR Modülü
    try:
        iskur_ilanlari = iskur_ilanlarini_getir()
        if iskur_ilanlari:
            logging.info(f"[İŞKUR Modülü] -> {len(iskur_ilanlari)} kayıt eklendi.")
            ilanlar.extend(iskur_ilanlari)
    except Exception as e:
        logging.error(f"İŞKUR modülü hata: {e}")

    # Aynı URL'den gelen tekrarları ayıkla
    tekil_ilanlar: List[Dict[str, str]] = []
    gorulen_idler: Set[str] = set()
    for ilan in ilanlar:
        uid = generate_id(ilan.get("link") or ilan.get("title", ""))
        if uid not in gorulen_idler:
            gorulen_idler.add(uid)
            tekil_ilanlar.append(ilan)

    logging.info(f"Toplam Taranacak Tekil İlan Sayısı: {len(tekil_ilanlar)}")

    yeni_green: List[str] = []

    for idx, ilan in enumerate(tekil_ilanlar, 1):
        baslik = ilan.get("title", "")
        link = ilan.get("link", "")
        kaynak = ilan.get("source", "Kamu Portalı")

        ilan_id = generate_id(link if link else baslik)
        if ilan_id in sent_ids:
            continue

        detay = ilan_detay_getir(link) if link else ""
        uygun_mu, aciklama, hedef_profil = ilan_analiz_et(baslik, detay)

        if not uygun_mu:
            continue

        logging.info(f"[{idx}/{len(tekil_ilanlar)}] ({kaynak}) [{hedef_profil}] UYGUN İLAN -> {baslik}")

        clean_title = html.escape(baslik)
        clean_aciklama = html.escape(aciklama)
        clean_kaynak = html.escape(kaynak)
        clean_profil = html.escape(hedef_profil)

        if link:
            item_str = (
                f"• [{clean_kaynak}] 🎯 <b>[{clean_profil}]</b>\n"
                f"  <a href='{html.escape(link, quote=True)}'><b>{clean_title}</b></a>\n"
                f"  📌 <i>{clean_aciklama}</i>"
            )
        else:
            item_str = (
                f"• [{clean_kaynak}] 🎯 <b>[{clean_profil}]</b>\n"
                f"  <b>{clean_title}</b>\n"
                f"  📌 <i>{clean_aciklama}</i>"
            )

        yeni_green.append(item_str)
        new_sent_ids.add(ilan_id)

    if yeni_green:
        sent_success = send_telegram_messages(yeni_green)
        if sent_success:
            save_sent_ids(new_sent_ids)
            logging.info("Uygun ilanlar Telegram üzerinden bildirildi.")
        else:
            logging.error("Telegram bildirimi sırasında hata oluştu.")
    else:
        logging.info("Kriterlerinize tam uyan yeni bir ilan bulunamadı.")

if __name__ == "__main__":
    main()
