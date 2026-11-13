import os
import re
import json
import html
import hashlib
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import urljoin
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
                    full_link = urljoin(base_url, href)
                    ilanlar.append({
                        'title': title,
                        'link': full_link,
                        'source': 'SBB Kamu İlan'
                    })
    except Exception as e:
        logging.error(f"SBB Kamu İlan portalından veri çekilirken hata oluştu: {e}")
    return ilanlar

def resmi_gazete_ilanlari_getir() -> List[Dict[str, str]]:
    """Resmi Gazete günlük ilanlarını tarar."""
    ilanlar: List[Dict[str, str]] = []
    base_url = "https://www.resmigazete.gov.tr/"
    try:
        res = requests.get(base_url, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                title = a_tag.get_text(strip=True)
                if title and len(title) > 10:
                    title_lower = tr_lower(title)
                    if any(k in title_lower for k in ["ilan", "personel", "alımı", "memur", "sözleşmeli"]):
                        full_link = urljoin(base_url, href)
                        ilanlar.append({
                            'title': title,
                            'link': full_link,
                            'source': 'Resmi Gazete'
                        })
    except Exception as e:
        logging.error(f"Resmi Gazete verileri çekilirken hata oluştu: {e}")
    return ilanlar

def osym_duyurulari_getir() -> List[Dict[str, str]]:
    """ÖSYM tercih ve yerleştirme duyurularını tarar."""
    ilanlar: List[Dict[str, str]] = []
    base_url = "https://www.osym.gov.tr/"
    try:
        res = requests.get(base_url, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                title = a_tag.get_text(strip=True)
                if title and len(title) > 10:
                    title_lower = tr_lower(title)
                    if any(k in title_lower for k in ["kpss", "yerleştirme", "tercih", "ek tercih", "sağlık bakanlığı"]):
                        full_link = urljoin(base_url, href)
                        ilanlar.append({
                            'title': title,
                            'link': full_link,
                            'source': 'ÖSYM Duyuruları'
                        })
    except Exception as e:
        logging.error(f"ÖSYM duyuruları çekilirken hata oluştu: {e}")
    return ilanlar

def ilan_detay_getir(url: str) -> str:
    """İlan detay sayfasından metin çeker."""
    if not url:
        return ""
    try:
        if "kariyerkapisi.gov.tr" in url:
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

def son_basvuru_tarihi_bul(metin: str) -> str:
    """Metin içerisindeki son başvuru tarihini regex ile yakalar."""
    tarih_kaliplari = re.findall(r'(?:son başvuru|son gün|tarihine kadar)\D*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})', metin, re.IGNORECASE)
    if tarih_kaliplari:
        return f"⏰ Son Başvuru: {tarih_kaliplari[0]}"
    return "⏰ Son Başvuru: Detayda Belirtilmiş"

def ilan_analiz_et(baslik: str, detay_metni: str) -> Tuple[bool, str, str]:
    """Kesin eşleşme sağlayan Whitelist analizi."""
    baslik_tr = tr_lower(baslik)
    metin_tr = tr_lower(baslik + " " + detay_metni)

    if "öSYM" in baslik or "kpss" in baslik_tr and ("tercih" in baslik_tr or "yerleştirme" in baslik_tr):
        return True, "ÖSYM merkezi yerleştirme / tercih duyurusu.", "Merkezi Tercih"

    if "hemşire" in baslik_tr or "hemşire" in metin_tr:
        if "lisans" in metin_tr or "fakülte" in metin_tr or "sağlık bilimleri" in metin_tr:
            deadline = son_basvuru_tarihi_bul(detay_metni)
            return True, f"Lisans Hemşirelik kadrosu tespit edildi. {deadline}", "Hemşirelik (Lisans)"

    adalet_zorunlu_kelimeler = [
        "adalet", "zabıt katibi", "katip", "mübaşir", "icra katibi", 
        "infaz koruma", "3001", "önlisans programlarının", "ön lisans programlarının",
        "adalet meslek yüksekokulu", "adalet programı"
    ]
    
    buro_ve_onlisans = ("büro personeli" in metin_tr or "koruma ve güvenlik" in metin_tr or "destek personeli" in metin_tr) and ("önlisans" in metin_tr or "ön lisans" in metin_tr or "myo" in metin_tr)

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
    logging.info("KAMU İLAN TAKİP (ÖSYM + Resmi Gazete + SBB + İŞKUR + Deadline)")
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
        logging.error(f"Kariyer Kapısı hata: {e}")

    try:
        sbb_ilanlari = sbb_kamu_ilan_getir()
        if sbb_ilanlari:
            ilanlar.extend(sbb_ilanlari)
    except Exception as e:
        logging.error(f"SBB hata: {e}")

    try:
        iskur_ilanlari = iskur_ilanlarini_getir()
        if iskur_ilanlari:
            ilanlar.extend(iskur_ilanlari)
    except Exception as e:
        logging.error(f"İŞKUR hata: {e}")

    try:
        rg_ilanlari = resmi_gazete_ilanlari_getir()
        if rg_ilanlari:
            ilanlar.extend(rg_ilanlari)
    except Exception as e:
        logging.error(f"Resmi Gazete hata: {e}")

    try:
        osym_ilanlari = osym_duyurulari_getir()
        if osym_ilanlari:
            ilanlar.extend(osym_ilanlari)
    except Exception as e:
        logging.error(f"ÖSYM hata: {e}")

    logging.info(f"Toplam Taranacak İlan Sayısı: {len(ilanlar)}")

    yeni_green: List[str] = []

    for idx, ilan in enumerate(ilanlar, 1):
        baslik = ilan.get('title', '')
        link = ilan.get('link', '')
        kaynak = ilan.get('source', 'Kamu Portalı')

        ilan_id = generate_id(link if link else baslik)
        
        if ilan_id in sent_ids:
            continue

        detay = ilan_detay_getir(link) if link else ""
        uygun_mu, aciklama, hedef_profil = ilan_analiz_et(baslik, detay)

        if not uygun_mu:
            continue

        logging.info(f"[{idx}/{len(ilanlar)}] ({kaynak}) [{hedef_profil}] UYGUN İLAN -> {baslik}")

        clean_title = html.escape(baslik)
        clean_aciklama = html.escape(aciklama)
        clean_kaynak = html.escape(kaynak)
        clean_profil = html.escape(hedef_profil)

        if link:
            item_str = f"• [{clean_kaynak}] 🎯 <b>[{clean_profil}]</b>\n  <a href='{link}'><b>{clean_title}</b></a>\n  📌 <i>{clean_aciklama}</i>"
        else:
            item_str = f"• [{clean_kaynak}] 🎯 <b>[{clean_profil}]</b>\n  <b>{clean_title}</b>\n  📌 <i>{clean_aciklama}</i>"

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
