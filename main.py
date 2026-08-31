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

# Telegram Bot Kütüphaneleri
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

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

# ==============================================================================
# KULLANICI / CHAT_ID KAYIT SİSTEMİ
# ==============================================================================

def save_user_chat_id(chat_id: int) -> None:
    """Bota /start veren kullanıcıların ID'lerini kullanicilar.txt dosyasına kaydeder."""
    chat_id_str = str(chat_id)
    try:
        with open("kullanicilar.txt", "a+", encoding="utf-8") as f:
            f.seek(0)
            existing_ids = f.read().splitlines()
            if chat_id_str not in existing_ids:
                f.write(f"{chat_id_str}\n")
                logging.info(f"Yeni kullanıcı kaydedildi: {chat_id_str}")
    except Exception as e:
        logging.error(f"Kullanıcı ID kaydetme hatası: {e}")

def load_user_chat_ids() -> List[str]:
    """Kayıtlı tüm kullanıcı ID'lerini getirir."""
    if os.path.exists("kullanicilar.txt"):
        try:
            with open("kullanicilar.txt", "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        except Exception as e:
            logging.error(f"kullanicilar.txt okuma hatası: {e}")
            return []
    return []

async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kullanıcı bota /start attığında çalışan komut yakalayıcı."""
    if update.effective_user and update.message:
        chat_id = update.effective_user.id
        first_name = update.effective_user.first_name or "Kullanıcı"
        
        save_user_chat_id(chat_id)
        
        await update.message.reply_text(
            f"Merhaba {first_name}! Kamu İlan Takip Sistemine kayıt oldunuz. "
            "Yeni uygun ilanlar geldikçe buradan bildirim alacaksınız."
        )

# ==============================================================================
# YARDIMCI VE YÖNETİM FONKSİYONLARI
# ==============================================================================

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
    """Kayıtlı TÜM kullanıcılara ilan bildirimini gönderir."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_ids = load_user_chat_ids()

    if not bot_token:
        logging.warning("TELEGRAM_BOT_TOKEN bulunamadı!")
        return
        
    if not chat_ids:
        logging.warning("Bildirim gönderilecek kayıtlı kullanıcı (chat_id) bulunamadı!")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    max_len = 3000
    chunks = [text[i:i+max_len] for i in range(0, len(text), max_len)] if len(text) > max_len else [text]

    for target_chat_id in chat_ids:
        for chunk in chunks:
            payload = {
                "chat_id": target_chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            try:
                response = requests.post(url, json=payload, timeout=10)

                # HTML hatası alırsak linkleri koruyarak düz metne dönüştür
                if response.status_code == 400 and "can't parse entities" in response.text:
                    logging.warning(f"HTML Parse hatası ({target_chat_id}), linkler açık adres olarak gönderiliyor...")
                    
                    # Link etiketlerini 'Başlık (URL)' formatına dönüştürür
                    fallback_text = re.sub(r'<a\s+href=["\']([^"\']+)["\']\s*>(.*?)</a>', r'\2 (\1)', chunk)
                    fallback_text = re.sub(r'<[^>]+>', '', fallback_text)
                    
                    payload_fallback = {
                        "chat_id": target_chat_id,
                        "text": fallback_text,
                        "disable_web_page_preview": True
                    }
                    requests.post(url, json=payload_fallback, timeout=10)
                elif response.status_code != 200:
                    logging.error(f"Telegram API Hatası [{target_chat_id}]: {response.status_code} - {response.text}")
            except Exception as e:
                logging.error(f"Telegram mesajı gönderilirken istisna oluştu ({target_chat_id}): {e}")

# ==============================================================================
# İLAN TARAMA VE ANALİZ FONKSİYONLARI
# ==============================================================================

def sbb_kamu_ilan_getir() -> List[Dict[str, str]]:
    """T.C. Cumhurbaşkanlığı SBB Kamu İlan portalından güncel ilanları çeker."""
    ilanlar: List[Dict[str, str]] = []
    base_url = "https://kamuilan.sbb.gov.tr/"
    try:
        res = requests.get(base_url, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                title = a_tag.get_text(strip=True)

                if title and len(title) > 12 and any(k in title.upper() for k in ["ALACAK", "ALIMI", "PERSONEL", "MEMUR", "SÖZLEŞMELİ"]):
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
    """İlan detay sayfasından BeautifulSoup kullanarak temiz metin çeker."""
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
                        soup = BeautifulSoup(metin, "html.parser")
                        return soup.get_text(separator=' ', strip=True)
                except Exception:
                    pass

        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")

            for element in soup(["script", "style", "header", "footer", "nav"]):
                element.extract()

            text = soup.get_text(separator=' ', strip=True)
            return text
    except Exception as e:
        logging.debug(f"İlan detayı çekilemedi ({url}): {e}")
    return ""

def ilan_analiz_et(baslik: str, detay_metni: str) -> Tuple[str, str]:
    """Adayın profiline göre gelişmiş çok kriterli ilan analizi yapar."""
    baslik_tr = tr_lower(baslik)
    metin_tr = tr_lower(baslik + " " + detay_metni)

    if "lisans mezunu" in metin_tr or "lisans derecesi" in metin_tr:
        if "önlisans" not in metin_tr and "ön lisans" not in metin_tr:
            return "🔴 BAŞVURAMAZSIN", "İlan yalnızca Lisans mezuniyeti şartı arıyor."

    kpss_matches = re.findall(r'kpss\s*(?:p93|p3|p94)?\s*(?:en az|minimum)?\s*([0-9]{2}(?:[\.,][0-9]+)?)', metin_tr)
    for match in kpss_matches:
        try:
            req_score = float(match.replace(',', '.'))
            if 50.0 <= req_score <= 100.0:
                if USER_PROFILE["kpss"] < req_score:
                    return "🔴 BAŞVURAMAZSIN", f"KPSS puanınız ({USER_PROFILE['kpss']}) gerekli taban puanın ({req_score}) altında."
        except ValueError:
            continue

    yas_matches = re.findall(r'([0-9]{2})\s*yaşını\s*(?:doldurmamış|bitirmemiş|aşmamış)', metin_tr)
    for match in yas_matches:
        try:
            max_age = int(match)
            if 18 <= max_age <= 65:
                if USER_PROFILE["yas"] >= max_age:
                    return "🔴 BAŞVURAMAZSIN", f"Yaşınız ({USER_PROFILE['yas']}), ilanın yaş sınırını ({max_age}) aşıyor."
        except ValueError:
            continue

    if "sadece kadın" in metin_tr or "kadın adaylar" in metin_tr:
        if "erkek" not in metin_tr:
            return "🔴 BAŞVURAMAZSIN", "İlan yalnızca kadın adaylar için kontenjan ayırmılmıştır."

    kesin_uyumsuz_unvanlar = [
        "mühendis", "doktor", "hemşire", "biyolog", "eczacı", "psikolog",
        "mimar", "pilot", "kaptan", "öğretim üyesi", "yazılım uzmanı", "bilişim"
    ]
    if any(unvan in baslik_tr for unvan in kesin_uyumsuz_unvanlar):
        return "🔴 BAŞVURAMAZSIN", "İlan unvanı Önlisans/Adalet profili ile uyuşmuyor."

    yuksek_uyumlu_anahtarlar = [
        "adalet", "zabıt katibi", "katip", "mübaşir", "infaz koruma", 
        "büro personeli", "koruma ve güvenlik", "cezaevi", "mahkeme"
    ]
    if any(k in baslik_tr or k in metin_tr for k in yuksek_uyumlu_anahtarlar):
        return "🟢 BAŞVURABİLİRSİN", "Adalet/Önlisans profilinizle doğrudan uyumlu pozisyon."

    if "önlisans" in metin_tr or "ön lisans" in metin_tr:
        return "🟢 BAŞVURABİLİRSİN", "Önlisans mezuniyeti şartı sağlayan genel kontenjan."

    if len(detay_metni) < 50:
        return "🟡 KONTROL GEREKİYOR", "İlan detay metni çekilemedi, başlığı genel kontrol ediniz."

    return "🟡 KONTROL GEREKİYOR", "Özel şartların manuel olarak kontrol edilmesi önerilir."

# ==============================================================================
# ANA ÇALIŞMA DÖNGÜSÜ (MAIN)
# ==============================================================================

def main() -> None:
    logging.info("============================================================")
    logging.info("KAMU İLAN TAKİP VE FİLTRELEME OTOMASYONU BAŞLATILDI")
    logging.info("============================================================")

    sent_ids = load_sent_ids()
    new_sent_ids = set(sent_ids)

    ilanlar: List[Dict[str, str]] = []

    # 1. Kariyer Kapısı RSS Servisinden Veri Çekme
    rss_url = "https://kariyerkapisi.gov.tr/RSS"
    try:
        res = requests.get(rss_url, headers=HEADERS, timeout=12)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            for item in root.findall('./channel/item'):
                title = item.find('title').text if item.find('title') is not None else ''
                link = item.find('link').text if item.find('link') is not None else ''
                if title:
                    ilanlar.append({
                        'title': title.strip(),
                        'link': link.strip(),
                        'source': 'Kariyer Kapısı'
                    })
        else:
            logging.warning(f"Kariyer Kapısı RSS yanıt vermedi. Yanıt Kodu: {res.status_code}")
    except Exception as e:
        logging.error(f"Kariyer Kapısı RSS işleme hatası: {e}")

    # 2. SBB Kamu İlan Portalından Veri Çekme
    try:
        sbb_ilanlari = sbb_kamu_ilan_getir()
        if sbb_ilanlari:
            ilanlar.extend(sbb_ilanlari)
    except Exception as e:
        logging.error(f"SBB Kamu İlan verileri alınırken hata oluştu: {e}")

    # 3. İŞKUR Modülünden Veri Çekme
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

        # Telegram HTML Güvenlik Temizlikleri
        clean_title = html.escape(baslik)
        clean_aciklama = html.escape(aciklama)
        clean_kaynak = html.escape(kaynak)

        if link and link.startswith("http"):
            # URL içerisindeki & işaretlerini Telegram uyumlu hale getir
            safe_link = html.escape(link)
            item_str = f"• [{clean_kaynak}] <a href=\"{safe_link}\"><b>{clean_title}</b></a>\n  📌 <i>{clean_aciklama}</i>"
        else:
            item_str = f"• [{clean_kaynak}] <b>{clean_title}</b>\n  📌 <i>{clean_aciklama}</i>"

        if "🟢" in durum:
            yeni_green.append(item_str)
            new_sent_ids.add(ilan_id)
        elif "🟡" in durum:
            yeni_yellow.append(item_str)
            new_sent_ids.add(ilan_id)

    # Telegram Bildirim Yönetimi
    if yeni_green or yeni_yellow:
        msg = "📢 <b>YENİ KAMU İLANLARI TESPİT EDİLDİ</b>\n\n"

        if yeni_green:
            msg += "🟢 <b>BAŞVURABİLECEĞİNİZ İLANLAR:</b>\n" + "\n\n".join(yeni_green) + "\n\n"
        if yeni_yellow:
            msg += "🟡 <b>KONTROL ETMENİZ GEREKEN İLANLAR:</b>\n" + "\n\n".join(yeni_yellow) + "\n\n"

        send_telegram_message(msg)
        save_sent_ids(new_sent_ids)
        logging.info("Yeni ilanlar Telegram üzerinden kaydedilmiş tüm kullanıcılara bildirildi.")
    else:
        logging.info("Kriterlere uygun yeni bildirilecek ilan bulunamadı.")

def run_bot_listener():
    """Botun kullanıcı kaydı (/start) alabilmesi için sürekli dinlemede kalmasını sağlayan fonksiyon."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logging.error("TELEGRAM_BOT_TOKEN olmadan dinleyici çalıştırılamaz.")
        return

    app = ApplicationBuilder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start_command_handler))
    logging.info("Telegram /start dinleyicisi başlatılıyor...")
    app.run_polling()

if __name__ == "__main__":
    main()
