import os
import re
import json
import html
import hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import date
from urllib.parse import urljoin
from iskur import iskur_ilanlarini_getir

# ============================================================
# PROFİL ARAMA KRİTERLERİ
# ============================================================
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

def tr_lower(metin):
    """Türkçe karakterleri doğru şekilde küçük harfe dönüştürür."""
    if not metin:
        return ""
    donusum = {"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"}
    for eski, yeni in donusum.items():
        metin = metin.replace(eski, yeni)
    return metin.lower()

def generate_id(metin):
    """İlan bağlantısına göre benzersiz hash üretir."""
    return hashlib.md5(metin.encode('utf-8')).hexdigest()

def load_sent_ids():
    """Daha önce gönderilmiş ilan ID'lerini okur."""
    if os.path.exists("sent_ids.json"):
        try:
            with open("sent_ids.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_sent_ids(sent_ids):
    """Yeni gönderilen ilan ID'lerini dosyaya kaydeder."""
    try:
        with open("sent_ids.json", "w", encoding="utf-8") as f:
            json.dump(sent_ids, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[HATA] sent_ids.json kaydedilemedi: {e}")

def send_telegram_message(text):
    """Telegram botu üzerinden mesaj gönderir."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("[UYARI] TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID bulunamadı!")
        return
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    if len(text) > 4000:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown", "disable_web_page_preview": True}
            requests.post(url, json=payload)
    else:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True}
        requests.post(url, json=payload)

def ilan_detay_getir(url):
    """Kariyer Kapısı detay sayfasından düz metin çeker."""
    try:
        match = re.search(r'i=([a-f0-9\-]+)', url)
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
    except Exception:
        pass
    return ""

def ilan_analiz_et(baslik, detay_metni):
    """Gelişmiş başlık ve detay analizi."""
    baslik_tr = tr_lower(baslik)
    metin_tr = tr_lower(baslik + " " + detay_metni)
    
    uyumsuz_anahtarlar = [
        "bilişim", "mühendis", "yüksek lisans", "konsolosluk", "doktor", 
        "hemşire", "yurtdışı", "yurt dışı", "staj", "yazılım", "mimar", "uzman", 
        "öğretim üyesi", "akademik", "biyolog", "eczacı", "psikolog", 
        "tekniker", "teknisyen", "pilot", "kaptan", "görevde yükselme", 
        "sekreter", "istatistik", "sistem personeli", "bilgisayar"
    ]
    
    if any(k in baslik_tr for k in uyumsuz_anahtarlar):
        return "🔴 BAŞVURAMAZSIN", "Pozisyon unvanı Önlisans/Adalet profiline uygun değil."

    uyumlu_basliklar = ["büro personeli", "infaz koruma", "zabıt katibi", "mübaşir", "adalet", "koruma ve güvenlik"]
    
    if len(detay_metni) < 150:
        if any(k in baslik_tr for k in uyumlu_basliklar):
            return "🟢 BAŞVURABİLİRSİN", "İlan başlığı profilinizle doğrudan uyumlu."
        return "🟡 KONTROL GEREKİYOR", "İlan detay metni çekilemedi, başlık genel."

    if "lisans mezunu" in metin_tr and "önlisans" not in metin_tr:
        return "🔴 BAŞVURAMAZSIN", "İlan yalnızca lisans mezuniyeti şartı arıyor."

    if any(k in metin_tr for k in ["adalet", "önlisans", "büro personeli"]):
        return "🟢 BAŞVURABİLİRSİN", "Profilinizle uyumlu şartlar tespit edildi."

    return "🟡 KONTROL GEREKİYOR", "Özel şartların manuel incelenmesi önerilir."

def main():
    print("============================================================")
    print("KAMU İLAN TAKİP - OTOMATİK BİLDİRİMLİ SÜRÜM")
    print("============================================================")
    
    sent_ids = load_sent_ids()
    new_sent_ids = list(sent_ids)
    
    rss_url = "https://kariyerkapisi.gov.tr/RSS"
    ilanlar = []
    
    try:
        res = requests.get(rss_url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            for item in root.findall('./channel/item'):
                ilanlar.append({
                    'title': item.find('title').text if item.find('title') is not None else '',
                    'link': item.find('link').text if item.find('link') is not None else '',
                    'source': 'Kariyer Kapısı'
                })
    except Exception as e:
        print(f"[HATA] RSS Okunamadı: {e}")

    try:
        iskur_ilanlari = iskur_ilanlarini_getir()
        if iskur_ilanlari:
            ilanlar.extend(iskur_ilanlari)
    except Exception as e:
        print(f"[HATA] İŞKUR verileri alınamadı: {e}")

    print(f"\n=== Toplam Taranacak İlan: {len(ilanlar)} ===")
    
    yeni_green = []
    yeni_yellow = []

    for idx, ilan in enumerate(ilanlar, 1):
        baslik = ilan.get('title', '')
        link = ilan.get('link', '')
        ilan_id = generate_id(link or baslik)
        
        detay = ilan_detay_getir(link) if link else ""
        durum, aciklama = ilan_analiz_et(baslik, detay)
        
        print(f"\n[{idx}/{len(ilanlar)}] {baslik}")
        print(f"DURUM: {durum} ({aciklama})")
        
        if ilan_id not in sent_ids:
            if "🟢" in durum:
                yeni_green.append(f"🟢 [{baslik}]({link})")
                new_sent_ids.append(ilan_id)
            elif "🟡" in durum:
                yeni_yellow.append(f"🟡 [{baslik}]({link})")
                new_sent_ids.append(ilan_id)

    if yeni_green or yeni_yellow:
        msg = "📢 **YENİ KAMU İLANLARI TESPİT EDİLDİ**\n\n"
        if yeni_green:
            msg += "🟢 **BAŞVURABİLECEĞİNİZ İLANLAR:**\n" + "\n".join(yeni_green) + "\n\n"
        if yeni_yellow:
            msg += "🟡 **KONTROL ETMENİZ GEREKEN İLANLAR:**\n" + "\n".join(yeni_yellow) + "\n\n"
        
        send_telegram_message(msg)
        save_sent_ids(new_sent_ids)
        print("\n[TELEGRAM] Yeni ilanlar bildirildi ve sent_ids.json güncellendi.")
    else:
        print("\n[TELEGRAM] Yeni bildirilecek ilan bulunamadı.")

if __name__ == "__main__":
    main()
    
