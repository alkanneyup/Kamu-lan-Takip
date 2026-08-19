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

def ilan_detay_getir(url):
    """Kariyer Kapısı detay API'sine doğrudan istek atarak metni çeker."""
    try:
        # Link içerisindeki GUID id değerini ayıkla
        match = re.search(r'i=([a-f0-9\-]+)', url)
        if match:
            guid = match.group(1)
            # Kariyer Kapısı arka plan API adresi
            api_url = f"https://kariyerkapisi.gov.tr/RSS/IlanDetayGetir?id={guid}"
            res = requests.get(api_url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                try:
                    data = res.json()
                    metin = data.get('Metin', '') or data.get('Açıklama', '') or str(data)
                    if metin:
                        clean_text = re.sub(r'<[^>]+>', ' ', metin)
                        return " ".join(html.unescape(clean_text).split())
                except Exception:
                    pass
        
        # API yanıt vermezse standart HTML fallback
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
    baslik_lower = baslik.lower()
    metin_lower = (baslik + " " + detay_metni).lower()
    
    # 1. Başlık Düzeyinde Kesin Uyumsuz Pozisyonlar (Adalet Önlisans Dışı)
    uyumsuz_anahtarlar = [
        "bilişim", "mühendis", "yüksek lisans", "konsolosluk", "doktor", 
        "hemşire", "yurtdışı", "staj", "yazılım", "mimar", "uzman", 
        "öğretim üyesi", "akademik", "biyolog", "eczacı", "psikolog", 
        "tekniker", "teknisyen", "pilot", "kaptan", "görevde yükselme"
    ]
    
    if any(k in baslik_lower for k in uyumsuz_anahtarlar):
        return "🔴 BAŞVURAMAZSIN", "Pozisyon unvanı Önlisans/Adalet profiline uygun değil."

    # 2. Başlık Düzeyinde Doğrudan Uyumlu Pozisyonlar
    uyumlu_basliklar = ["büro personeli", "infaz koruma", "zabıt katibi", "mübaşir", "adalet", "koruma ve güvenlik"]
    
    # 3. Metin Yetersizliği Kontrolü
    if len(detay_metni) < 150:
        if any(k in baslik_lower for k in uyumlu_basliklar):
            return "🟢 BAŞVURABİLİRSİN", "İlan başlığı profilinizle doğrudan uyumlu."
        return "🟡 KONTROL GEREKİYOR", "İlan detay metni çekilemedi, başlık genel."

    # 4. Detay Metni İncelemesi
    if "lisans mezunu" in metin_lower and "önlisans" not in metin_lower:
        return "🔴 BAŞVURAMAZSIN", "İlan yalnızca lisans mezuniyeti şartı arıyor."

    if any(k in metin_lower for k in ["adalet", "önlisans", "büro personeli"]):
        return "🟢 BAŞVURABİLİRSİN", "Profilinizle uyumlu şartlar tespit edildi."

    return "🟡 KONTROL GEREKİYOR", "Özel şartların manuel incelenmesi önerilir."

def main():
    print("============================================================")
    print("KAMU İLAN TAKİP - GÜNCELLENMİŞ SÜRÜM")
    print("============================================================")
    
    # 1. Kariyer Kapısı RSS
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

    # 2. İŞKUR İlanları Entegrasyonu
    try:
        iskur_ilanlari = iskur_ilanlarini_getir()
        if iskur_ilanlari:
            ilanlar.extend(iskur_ilanlari)
            print(f"[İŞKUR] {len(iskur_ilanlari)} adet ilan eklendi.")
    except Exception as e:
        print(f"[HATA] İŞKUR verileri alınamadı: {e}")

    print(f"\n=== Toplam Taranacak İlan: {len(ilanlar)} ===")
    
    basvuru_sayilari = {"🟢 BAŞVURABİLİRSİN": 0, "🟡 KONTROL GEREKİYOR": 0, "🔴 BAŞVURAMAZSIN": 0}

    for idx, ilan in enumerate(ilanlar, 1):
        baslik = ilan.get('title', '')
        link = ilan.get('link', '')
        
        detay = ilan_detay_getir(link) if link else ""
        durum, aciklama = ilan_analiz_et(baslik, detay)
        
        basvuru_sayilari[durum] += 1
        print(f"\n[{idx}/{len(ilanlar)}] {baslik}")
        print(f"DURUM: {durum} ({aciklama})")

    print("\n============================================================")
    print("TARAMA TAMAMLANDI")
    print("============================================================")
    print(f"🟢 Başvurabilir: {basvuru_sayilari['🟢 BAŞVURABİLİRSİN']}")
    print(f"🟡 Kontrol gerekiyor: {basvuru_sayilari['🟡 KONTROL GEREKİYOR']}")
    print(f"🔴 Başvuramaz: {basvuru_sayilari['🔴 BAŞVURAMAZSIN']}")

if __name__ == "__main__":
    main()
    
