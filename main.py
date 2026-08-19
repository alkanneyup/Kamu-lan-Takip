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
    """İlan detay sayfasından düz metni çeker."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return ""
        
        # Script ve stil etiketlerini temizle
        clean_text = re.sub(r'<script.*?>.*?</script>', '', res.text, flags=re.DOTALL | re.IGNORECASE)
        clean_text = re.sub(r'<style.*?>.*?</style>', '', clean_text, flags=re.DOTALL | re.IGNORECASE)
        clean_text = re.sub(r'<[^>]+>', ' ', clean_text)
        clean_text = html.unescape(clean_text)
        return " ".join(clean_text.split())
    except Exception as e:
        print(f"[HATA] Detay çekilemedi ({url}): {e}")
        return ""

def ilan_analiz_et(baslik, detay_metni):
    """Profil ile ilan şartlarını karşılaştırır."""
    baslik_lower = baslik.lower()
    metin_lower = (baslik + " " + detay_metni).lower()
    
    # Adalet Önlisans ile kesinlikle uyuşmayan alanlar
    uyumsuz_basliklar = [
        "bilişim", "mühendis", "yüksek lisans", "konsolosluk", 
        "doktor", "hemşire", "yurtdışı staj", "yazılım", "mimar"
    ]
    
    if any(k in baslik_lower for k in uyumsuz_basliklar):
        return "🔴 BAŞVURAMAZSIN", "Pozisyon önlisans/adalet profili ile uyumsuz."

    # Detay metni yetersiz kaldığında güvenli duruma geç
    if len(detay_metni) < 200:
        return "🟡 KONTROL GEREKİYOR", "İlan metni tam çekilemedi, manuel inceleyin."

    # Öğrenim seviyesi kontrolü
    if "lisans mezunu" in metin_lower and "önlisans" not in metin_lower:
        return "🔴 BAŞVURAMAZSIN", "Yalnızca lisans mezuniyeti isteniyor."

    # Uygun alan eşleşmesi
    uygun_kelimeler = ["adalet", "önlisans", "büro personeli", "infaz koruma", "zabıt katibi", "mübaşir"]
    if any(k in metin_lower for k in uygun_kelimeler):
        return "🟢 BAŞVURABİLİRSİN", "Profilinizle uyumlu alanlar tespit edildi."

    return "🟡 KONTROL GEREKİYOR", "Özel şartların manuel incelenmesi gerekiyor."

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
        
        print(f"\n[{idx}/{len(ilanlar)}] {baslik}")
        
        detay = ilan_detay_getir(link) if link else ""
        durum, aciklama = ilan_analiz_et(baslik, detay)
        
        basvuru_sayilari[durum] += 1
        print(f"DURUM: {durum} ({aciklama})")

    print("\n============================================================")
    print("TARAMA TAMAMLANDI")
    print("============================================================")
    print(f"🟢 Başvurabilir: {basvuru_sayilari['🟢 BAŞVURABİLİRSİN']}")
    print(f"🟡 Kontrol gerekiyor: {basvuru_sayilari['🟡 KONTROL GEREKİYOR']}")
    print(f"🔴 Başvuramaz: {basvuru_sayilari['🔴 BAŞVURAMAZSIN']}")

if __name__ == "__main__":
    main()
    
