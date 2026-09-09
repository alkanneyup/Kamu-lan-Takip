import os
import re
import json
import html
import hashlib
import logging
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
from typing import List, Dict, Tuple, Set
from bs4 import BeautifulSoup
from iskur import iskur_ilanlarini_getir

# Loglama Yapılandırması
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s"
)

# Aday Profil Tanımı
USER_PROFILE = {
    "kpss": 76.29,
    "ogrenim": "onlisans",
    "bolum": "adalet",
    "cinsiyet": "erkek",
    "yas": 29
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}

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

def send_telegram_message(text: str) -> None:
    """Telegram üzerinden güvenli biçimde bildirim gönderir."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        logging.warning("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID bulunamadı!")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    max_len = 3800
    chunks = [text[i:i+max_len] for i in range(0, len(text), max_len)] if len(text) > max_len else [text]

    for chunk in chunks:
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code != 200:
                logging.error(f"Telegram API Hatası: {response.status_code} - {response.text}")
        except Exception as e:
            logging.error(f"Telegram mesajı gönderilirken istisna oluştu: {e}")

def sbb_kamu_ilan_getir() -> List[Dict[str, str]]:
    """T.C. Cumhurbaşkanlığı SBB Kamu İlan portalından ilanları çeker."""
    ilanlar: List[Dict[str, str]] = []
    base_url = "https://kamuilan.sbb.gov.tr/"
    try:
        res = requests.get(base_url, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                title = a_tag.get_text(strip=True)
                if title and len(title) > 10:
                    title_lower = tr_lower(title)
                    anahtar_kelimeler = [
                        "alacak", "alımı", "personel", "memur", "sözleşmeli", 
                        "bakanlığı", "belediyesi", "başkanlığı", "üniversitesi", 
                        "genel müdürlüğü", "icra", "katip", "mübaşir", "adalet", "büro"
                    ]
                    if any(k in title_lower for k in anahtar_kelimeler):
                        full_link = urljoin(base_url, href)
                        ilanlar.append({
                            'title': title,
                            'link': full_link,
                            'source': 'SBB Kamu İlan'
                        })
    except Exception as e:
        logging.error(f"SBB Kamu İlan portalından veri çekilirken hata oluştu: {e}")
    return ilanlar

def ilan_detay_getir(url: str) -> str:
    """İlan detay sayfasından metin çeker."""
    if not url:
        return ""
    try:
        match = re.search(r'i=([a-f0-9-]+)', url, re.IGNORECASE)
        if match:
            guid = match.group(1)
            api_url = f"https://kariyerkapisi.gov.tr/RSS/IlanDetayGetir?id={guid}"
            res = requests.get(api_url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                try:
                    data = res.json()
                    metin = data.get('Metin', '') or data.get('Açıklama', '') or str(data)
                    if metin and len(metin) > 50:
                        clean_text = re.sub(r'<[^>]+>', ' ', metin)
                        return " ".join(html.unescape(clean_text).split())
                except Exception:
                    pass

        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            clean_text = re.sub(r'<script.*?>.*?</script>', '', res.text, flags=re.DOTALL | re.IGNORECASE)
            clean_text = re.sub(r'<style.*?>.*?</style>', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
            clean_text = re.sub(r'<[^>]+>', ' ', clean_text)
            return " ".join(html.unescape(clean_text).split())
    except Exception as e:
        logging.debug(f"İlan detayı çekilemedi ({url}): {e}")
    return ""

def ilan_analiz_et(baslik: str, detay_metni: str) -> Tuple[str, str]:
    """
    Adayın Profiline Özel Analiz Engine:
    - Özel Nitelikler (Adalet & 3001 Herhangi Bir Önlisans)
    - Sert Şartlar (KPSS, Yaş, Cinsiyet)
    """
    baslik_tr = tr_lower(baslik)
    
    # "Mimar Sinan" gibi kurum adı çakışmalarını temizle
    baslik_filtreli = re.sub(r'\bmimar\s+sinan\b', '', baslik_tr)
    
    metin_tr = tr_lower(baslik + " " + detay_metni)

    # 1. KONTROL: Dinamik KPSS Puan Kontrolü (Aday Puanı: 76.29)
    kpss_matches = re.findall(r'(?:kpss|p93|p3|p94|puan)\D*([5-9][0-9](?:[\.,][0-9]+)?)', metin_tr)
    for match in kpss_matches:
        try:
            req_score = float(match.replace(',', '.'))
            if 50.0 <= req_score <= 100.0:
                if USER_PROFILE["kpss"] < req_score:
                    return "🔴 BAŞVURAMAZSIN", f"KPSS puanınız ({USER_PROFILE['kpss']}) ilanın taban puanının ({req_score}) altında."
        except ValueError:
            continue

    # 2. KONTROL: Yaş Sınırı Kontrolü (Aday Yaşı: 29)
    yas_matches = re.findall(r'([0-9]{2})\s*yaşını\s*(?:doldurmamış|bitirmemiş|aşmamış|gün almamış)', metin_tr)
    for match in yas_matches:
        try:
            max_age = int(match)
            if 18 <= max_age <= 65:
                if USER_PROFILE["yas"] >= max_age:
                    return "🔴 BAŞVURAMAZSIN", f"Yaşınız ({USER_PROFILE['yas']}), ilanın yaş sınırını ({max_age}) aşıyor."
        except ValueError:
            continue

    # 3. KONTROL: Cinsiyet Kontrolü
    if ("sadece kadın" in metin_tr or "kadın adaylar" in metin_tr) and "erkek" not in metin_tr:
        return "🔴 BAŞVURAMAZSIN", "İlan yalnızca kadın adaylar için kontenjan ayırmıştır."

    # 4. KONTROL: Başlıkta Belirli Tekil Meslek Kontrolü (Başlıkta genel büro/sözleşmeli geçmiyorsa elenir)
    kesin_uyumsuz_meslekler = [
        "mühendis", "doktor", "hemşire", "biyolog", "eczacı", "psikolog",
        "mimar", "pilot", "kaptan", "öğretim üyesi", "yazılım uzmanı", "öğretmen",
        "veteriner", "tekniker", "teknisyen"
    ]
    if any(re.search(r'\b' + m + r'\b', baslik_filtreli) for m in kesin_uyumsuz_meslekler):
        if not any(k in baslik_tr for k in ["büro", "adalet", "katip", "mübaşir", "güvenlik", "destek", "sözleşmeli", "4/b", "personel"]):
            return "🔴 BAŞVURAMAZSIN", "İlan unvanı Adalet / Önlisans nitelikleriyle uyuşmuyor."

    # 5. ÖZEL NİTELİK & BÖLÜM TARAMASI (Adalet & Herhangi Bir Önlisans / 3001)
    
    # A) Adalet Özel Niteliği
    adalet_anahtarlari = [
        "adalet", "zabıt katibi", "katip", "mübaşir", "icra katibi", "icra müdür", 
        "infaz koruma", "cezaevi", "mahkeme", "adalet bakanlığı"
    ]
    if any(k in metin_tr or k in baslik_tr for k in adalet_anahtarlari):
        return "🟢 BAŞVURABİLİRSİN", "Özel niteliklerde 'Adalet' bölümü veya kadrosu tespit edildi."

    # B) Herhangi Bir Önlisans (3001 Nitelik Kodu) Özel Niteliği
    herhangi_onlisans_anahtarlari = [
        "3001", "herhangi bir önlisans", "herhangi bir ön lisans", 
        "önlisans programlarının birinden", "ön lisans programlarının birinden",
        "herhangi bir meslek yüksekokulu", "tüm önlisans", "alan gözetmeksizin",
        "önlisans mezunu olmak"
    ]
    if any(k in metin_tr for k in herhangi_onlisans_anahtarlari):
        return "🟢 BAŞVURABİLİRSİN", "Özel niteliklerde 'Herhangi bir Önlisans (3001)' şartı tespit edildi."

    # C) Genel Büro / İdari Kadro Şartları
    genel_idari_kadrolar = [
        "büro personeli", "veri hazırlama", "vhki", "bilgisayar işletmeni",
        "koruma ve güvenlik", "destek personeli", "memur"
    ]
    egitim_terimleri = ["önlisans", "ön lisans", "myo", "meslek yüksekokulu", "2 yıllık"]
    
    if any(k in metin_tr or k in baslik_tr for k in genel_idari_kadrolar):
        if any(e in metin_tr for e in egitim_terimleri) or any(g in baslik_tr for g in ["4/b", "sözleşmeli", "personel alımı"]):
            return "🟢 BAŞVURABİLİRSİN", "Özel niteliklerde Önlisans düzeyinde genel kadro (Büro/VHKİ/Destek) tespit edildi."

    # D) Toplu 4/B ve Üniversite / Kamu Alımları
    if any(g in baslik_tr for g in ["4/b", "sözleşmeli personel", "personel alım", "memur alım"]):
        return "🟢 BAŞVURABİLİRSİN", "Toplu 4/B sözleşmeli personel alımı (Önlisans/Büro/3001 kontenjanı içerebilir)."

    return "🟡 KONTROL GEREKİYOR", "Özel niteliklerin detaylı incelenmesi önerilir."

def main() -> None:
    logging.info("============================================================")
    logging.info("KAMU İLAN TAKİP VE FİLTRELEME OTOMASYONU BAŞLATILDI")
    logging.info("============================================================")

    sent_ids = load_sent_ids()
    new_sent_ids = set(sent_ids)
    
    ilanlar: List[Dict[str, str]] = []

    try:
        res = requests.get("https://kariyerkapisi.gov.tr/RSS", headers=HEADERS, timeout=12)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            for item in root.findall('./channel/item'):
                title = item.find('title').text if item.find('title') is not None else ''
                link = item.find('link').text if item.find('link') is not None else ''
                if title:
                    ilanlar.append({'title': title.strip(), 'link': link.strip(), 'source': 'Kariyer Kapısı'})
    except Exception as e:
        logging.error(f"Kariyer Kapısı RSS işleme hatası: {e}")

    try:
        sbb_ilanlari = sbb_kamu_ilan_getir()
        if sbb_ilanlari:
            ilanlar.extend(sbb_ilanlari)
    except Exception as e:
        logging.error(f"SBB Kamu İlan verileri alınırken hata oluştu: {e}")

    try:
        iskur_ilanlari = iskur_ilanlarini_getir()
        if iskur_ilanlari:
            ilanlar.extend(iskur_ilanlari)
    except Exception as e:
        logging.error(f"İŞKUR verileri alınırken hata oluştu: {e}")

    logging.info(f"Toplam Taranacak İlan Sayısı: {len(ilanlar)}")

    yeni_green: List[str] = []
    yeni_yellow: List[str] = []

    for idx, ilan in enumerate(ilanlar, 1):
        baslik = ilan.get('title', '')
        link = ilan.get('link', '')
        kaynak = ilan.get('source', 'Kamu Portalı')

        ilan_id = generate_id(link if link else baslik)
        
        if ilan_id in sent_ids:
            continue

        detay = ilan_detay_getir(link) if link else ""
        durum, aciklama = ilan_analiz_et(baslik, detay)

        logging.info(f"[{idx}/{len(ilanlar)}] ({kaynak}) {baslik} -> {durum}")

        clean_title = html.escape(baslik)
        clean_aciklama = html.escape(aciklama)
        clean_kaynak = html.escape(kaynak)

        if link:
            item_str = f"• [{clean_kaynak}] <a href='{link}'><b>{clean_title}</b></a>\n  📌 <i>{clean_aciklama}</i>"
        else:
            item_str = f"• [{clean_kaynak}] <b>{clean_title}</b>\n  📌 <i>{clean_aciklama}</i>"

        if "🟢" in durum:
            yeni_green.append(item_str)
            new_sent_ids.add(ilan_id)
        elif "🟡" in durum:
            yeni_yellow.append(item_str)
            new_sent_ids.add(ilan_id)

    if yeni_green or yeni_yellow:
        msg = "📢 <b>YENİ KAMU İLANLARI TESPİT EDİLDİ</b>\n\n"
        if yeni_green:
            msg += "🟢 <b>BAŞVURABİLECEĞİNİZ İLANLAR:</b>\n" + "\n\n".join(yeni_green) + "\n\n"
        if yeni_yellow:
            msg += "🟡 <b>KONTROL ETMENİZ GEREKEN İLANLAR:</b>\n" + "\n\n".join(yeni_yellow) + "\n\n"

        send_telegram_message(msg)
        save_sent_ids(new_sent_ids)
        logging.info("Yeni ilanlar Telegram üzerinden bildirildi ve veri durumu güncellendi.")
    else:
        logging.info("Kriterlere uygun yeni bildirilecek ilan bulunamadı.")

if __name__ == "__main__":
    main()
