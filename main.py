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

USER_PROFILE = {
    "kpss": 80.86227,
    "yas": 29
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}

HABER_VE_KALABALIK_IFADELERI = [
    "haber", "duyuru", "duyurusu", "maaşlar ne kadar", "taban puanlar",
    "bu hafta", "ilan yayımlandı", "şartları açıklandı",
    "kontenjanlar ve başvuru şartları", "bölüm şartı yok",
    "sınav yapılmayacak", "mühendis ve tekniker", "hizmetli, şoför",
    "kura", "mülakat", "sınav sonucu", "sonuçları", "sonucu",
    "tebligat", "takvim", "yerleştirme sonuç", "nihai liste",
    "asıl ve yedek", "komisyon", "dilekçe", "ücret tarifesi", "mevzuat"
]

BASVURU_ILANI_IFADELERI = [
    "alım ilanı", "personel alım", "memur alım", "sözleşmeli alım",
    "alımı", "alacak", "alacaktır", "temini", "başvuru ilanı"
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
            json.dump(list(sent_ids), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"sent_ids.json kaydetme hatası: {e}")

def send_telegram_messages(green_items: List[str]) -> bool:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    raw_chat_ids = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not raw_chat_ids:
        logging.error("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID bulunamadı!")
        return False

    chat_ids = [cid.strip() for cid in raw_chat_ids.split(",") if cid.strip()]
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    messages: List[str] = []
    current_msg = "📢 <b>YENİ VE AKTİF BAŞVURU İLANLARI</b>\n\n"

    if green_items:
        current_msg += "🟢 <b>SİZE UYGUN AKTİF İLANLAR:</b>\n"
        for item in green_items:
            if len(current_msg) + len(item) + 4 > 3500:
                messages.append(current_msg)
                current_msg = "🟢 <b>SİZE UYGUN AKTİF İLANLAR (Devam):</b>\n"
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

def resmi_gazete_getir() -> List[Dict[str, str]]:
    ilanlar: List[Dict[str, str]] = []
    base_url = "https://www.resmigazete.gov.tr/"
    seen: Set[str] = set()
    try:
        res = requests.get(base_url, headers=HEADERS, timeout=(5, 10), allow_redirects=True)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                href = (a_tag.get("href") or "").strip()
                title = " ".join(a_tag.get_text(" ", strip=True).split())
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                if len(title) < 10 or len(title) > 200:
                    continue
                title_tr = tr_lower(title)
                if any(k in title_tr for k in HABER_VE_KALABALIK_IFADELERI):
                    continue
                if any(k in title_tr for k in BASVURU_ILANI_IFADELERI):
                    full_link = urljoin(res.url, href)
                    if full_link not in seen:
                        seen.add(full_link)
                        ilanlar.append({"title": title, "link": full_link, "source": "Resmî Gazete"})
    except Exception as e:
        logging.error(f"Resmî Gazete hatası: {e}")
    return ilanlar

def sbb_kamu_ilan_getir() -> List[Dict[str, str]]:
    ilanlar: List[Dict[str, str]] = []
    base_url = "https://kamuilan.sbb.gov.tr/"
    seen: Set[str] = set()
    try:
        res = requests.get(base_url, headers=HEADERS, timeout=(5, 10), allow_redirects=True)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                href = (a_tag.get("href") or "").strip()
                title = " ".join(a_tag.get_text(" ", strip=True).split())
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                if len(title) < 10 or len(title) > 200:
                    continue
                title_tr = tr_lower(title)
                if any(k in title_tr for k in HABER_VE_KALABALIK_IFADELERI):
                    continue
                if any(k in title_tr for k in BASVURU_ILANI_IFADELERI):
                    full_link = urljoin(res.url, href)
                    if full_link not in seen:
                        seen.add(full_link)
                        ilanlar.append({"title": title, "link": full_link, "source": "SBB Kamu İlan"})
        else:
            logging.warning(f"SBB Kamu İlan HTTP {res.status_code} döndü.")
    except Exception as e:
        logging.error(f"SBB Kamu İlan hatası: {e}")
    return ilanlar

def kariyer_kapisi_getir() -> List[Dict[str, str]]:
    ilanlar: List[Dict[str, str]] = []
    seen: Set[str] = set()

    try:
        res = requests.get("https://kariyerkapisi.gov.tr/RSS", headers=HEADERS, timeout=(5, 10))
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            for item in root.findall("./channel/item"):
                title = (item.find("title").text or "").strip() if item.find("title") is not None else ""
                link = (item.find("link").text or "").strip() if item.find("link") is not None else ""
                title_tr = tr_lower(title)
                if title and link and link not in seen and not any(k in title_tr for k in HABER_VE_KALABALIK_IFADELERI):
                    seen.add(link)
                    ilanlar.append({"title": title, "link": link, "source": "Kariyer Kapısı"})
    except Exception as e:
        logging.error(f"Kariyer Kapısı RSS hatası: {e}")

    try:
        res = requests.get("https://kariyerkapisi.gov.tr/", headers=HEADERS, timeout=(5, 10), allow_redirects=True)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                href = (a_tag.get("href") or "").strip()
                title = " ".join(a_tag.get_text(" ", strip=True).split())
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                if len(title) < 8 or len(title) > 220:
                    continue
                title_tr = tr_lower(title)
                if any(k in title_tr for k in HABER_VE_KALABALIK_IFADELERI):
                    continue
                if any(k in title_tr for k in BASVURU_ILANI_IFADELERI):
                    full_link = urljoin(res.url, href)
                    if full_link not in seen:
                        seen.add(full_link)
                        ilanlar.append({"title": title, "link": full_link, "source": "Kariyer Kapısı"})
    except Exception as e:
        logging.error(f"Kariyer Kapısı web hatası: {e}")

    return ilanlar

def _json_metin_topla(obj: Any) -> str:
    if isinstance(obj, str):
        temiz = re.sub(r"<[^>]+>", " ", obj)
        return " ".join(html.unescape(temiz).split())
    if isinstance(obj, dict):
        parcalar = [_json_metin_topla(v) for v in obj.values()]
        return " ".join(p for p in parcalar if p)
    if isinstance(obj, list):
        parcalar = [_json_metin_topla(v) for v in obj]
        return " ".join(p for p in parcalar if p)
    return ""

def ilan_detay_getir(url: str) -> str:
    if not url:
        return ""
    parcalar: List[str] = []

    try:
        if "kariyerkapisi" in url:
            match = re.search(r"i=([a-f0-9-]+)", url, re.IGNORECASE)
            if match:
                guid = match.group(1)
                for api_url in [
                    f"https://kariyerkapisi.gov.tr/RSS/IlanDetayGetir?id={guid}",
                    f"https://kariyerkapisi.gov.tr/IlanDetay/Getir?id={guid}"
                ]:
                    try:
                        res = requests.get(api_url, headers=HEADERS, timeout=(4, 8))
                        if res.status_code == 200:
                            try:
                                data = res.json()
                                metin = _json_metin_topla(data)
                                if metin:
                                    parcalar.append(metin)
                            except Exception:
                                clean_text = re.sub(r"<[^>]+>", " ", res.text)
                                parcalar.append(" ".join(html.unescape(clean_text).split()))
                    except Exception:
                        continue

        res = requests.get(url, headers=HEADERS, timeout=(4, 8), allow_redirects=True)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            script_metinleri: List[str] = []
            for script in soup.find_all("script"):
                raw_s = script.string or script.get_text() or ""
                if raw_s.strip():
                    temiz_s = re.sub(r"<[^>]+>", " ", raw_s)
                    script_metinleri.append(" ".join(html.unescape(temiz_s).split()))
            for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()
            clean_text = " ".join(soup.get_text(" ", strip=True).split())
            parcalar.append(clean_text)
            if len(clean_text) < 300 and script_metinleri:
                parcalar.append(" ".join(script_metinleri)[:6000])
    except Exception as e:
        logging.debug(f"İlan detayı çekilemedi ({url}): {e}")

    birlesik = " ".join(p for p in parcalar if p).strip()
    return birlesik[:15000]

def tarih_parse_et(tarih_str: str) -> Optional[date]:
    temiz = tarih_str.strip().replace("/", ".").replace("-", ".")
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(temiz, fmt).date()
        except ValueError:
            continue
    return None

def son_basvuru_durumu_analiz(metin: str, bugun: date) -> Tuple[bool, str, bool]:
    tarih_kaliplari = re.findall(
        r"(?:son başvuru|son gün|başvuru bitiş|tarihine kadar)\D*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})",
        metin,
        re.IGNORECASE
    )

    if tarih_kaliplari:
        parsed_tarih = tarih_parse_et(tarih_kaliplari[0])
        if parsed_tarih:
            if parsed_tarih < bugun:
                return False, "", False
            yeni_mi = bugun.strftime("%d.%m.%Y") in metin
            return True, f"⏰ Son Başvuru: {parsed_tarih.strftime('%d.%m.%Y')}", yeni_mi
        return True, f"⏰ Son Başvuru: {tarih_kaliplari[0]}", False

    return True, "⏰ Son Başvuru: Detayda Belirtilmiş", False

def ilan_analiz_et(baslik: str, detay_metni: str, bugun: date) -> Tuple[bool, str, str, bool, str]:
    baslik_tr = tr_lower(baslik)
    detay_tr = tr_lower(detay_metni)
    metin_tr = baslik_tr + " " + detay_tr

    if any(k in baslik_tr for k in HABER_VE_KALABALIK_IFADELERI):
        return False, "", "", False, "haber/duyuru/sonuç kaydı"

    if not any(k in metin_tr for k in BASVURU_ILANI_IFADELERI):
        return False, "", "", False, "başvuru ilanı ifadesi yok"

    aktif_mi, deadline_str, yeni_mi = son_basvuru_durumu_analiz(detay_metni, bugun)
    if not aktif_mi:
        return False, "", "", False, "başvuru süresi geçmiş"

    # 1. Lisans Hemşirelik
    hemsire_baslikta_veya_kadrosunda = (
        "hemşire" in baslik_tr
        or bool(re.search(r"(?:alımı|alacak|alacaktır|kadrosu|unvanlı)\b[^.]{0,80}\bhemşire\b", detay_tr))
    )
    if hemsire_baslikta_veya_kadrosunda and any(k in metin_tr for k in ["lisans", "hemşirelik"]):
        return True, f"Lisans Hemşirelik başvuru ilanı. {deadline_str}", "Hemşirelik (Lisans)", yeni_mi, "ok"

    # 2. Adalet / Önlisans / P93 / 3001 / Büro Personeli
    adalet_zorunlu_kelimeler = [
        "adalet", "zabıt katibi", "katip", "mübaşir", "icra katibi",
        "infaz koruma", "3001", "önlisans programlarının", "ön lisans programlarının",
        "adalet meslek yüksekokulu", "adalet programı"
    ]

    buro_ve_onlisans = (
        any(b in metin_tr for b in ["büro personeli", "büro destek", "koruma ve güvenlik", "destek personeli"])
        and any(e in metin_tr for e in ["önlisans", "ön lisans", "myo", "meslek yüksekokulu", "p93"])
    )

    if any(k in metin_tr for k in adalet_zorunlu_kelimeler) or buro_ve_onlisans:
        kpss_matches = re.findall(r"(?:kpss|p93|p3|p94|puan)\D*([5-9][0-9](?:[\.,][0-9]+)?)", metin_tr)
        for match in kpss_matches:
            try:
                req_score = float(match.replace(",", "."))
                if 50.0 <= req_score <= 100.0:
                    if USER_PROFILE["kpss"] < req_score:
                        return False, "", "", False, f"kpss yetersiz ({req_score})"
            except ValueError:
                continue
        return True, f"Adalet / Önlisans başvuru ilanı. {deadline_str}", "Adalet (Önlisans)", yeni_mi, "ok"

    # 3. Detay tablosu dinamik yükleniyorsa (detay_len < 300) Üniversite / Belediye sözleşmeli/memur alımlarını kaçırmamak için kontrol
    if len(detay_metni.strip()) < 300 and any(kurum in baslik_tr for kurum in ["üniversite", "belediye"]):
        if any(alim in baslik_tr for alim in ["sözleşmeli personel alım", "personel alım", "memur alım", "alım ilanı"]):
            return True, f"Üniversite/Belediye başvuru ilanı (detay tablosu dinamik). {deadline_str}", "Adalet / Önlisans (Kontrol)", yeni_mi, "ok_dinamik"

    return False, "", "", False, f"profil eşleşmedi (detay_len={len(detay_metni)})"

def main() -> None:
    bugun = datetime.now().date()
    logging.info("============================================================")
    logging.info(f"KAMU BAŞVURU İLANLARI TAKİBİ ({bugun})")
    logging.info("============================================================")

    sent_ids = load_sent_ids()
    new_sent_ids = set(sent_ids)
    ilanlar: List[Dict[str, str]] = []

    logging.info("1/4 Resmî Gazete taranıyor...")
    rg_ilanlari = resmi_gazete_getir()
    logging.info(f"[Resmî Gazete] -> {len(rg_ilanlari)} başvuru adayı bulundu.")
    ilanlar.extend(rg_ilanlari)

    logging.info("2/4 SBB Kamu İlan taranıyor...")
    sbb_ilanlari = sbb_kamu_ilan_getir()
    logging.info(f"[SBB Kamu İlan] -> {len(sbb_ilanlari)} başvuru adayı bulundu.")
    ilanlar.extend(sbb_ilanlari)

    logging.info("3/4 Kariyer Kapısı taranıyor...")
    kk_ilanlari = kariyer_kapisi_getir()
    logging.info(f"[Kariyer Kapısı] -> {len(kk_ilanlari)} başvuru adayı bulundu.")
    ilanlar.extend(kk_ilanlari)

    logging.info("4/4 İŞKUR taranıyor...")
    try:
        iskur_ilanlari = iskur_ilanlarini_getir()
        if iskur_ilanlari:
            logging.info(f"[İŞKUR] -> {len(iskur_ilanlari)} başvuru adayı bulundu.")
            ilanlar.extend(iskur_ilanlari)
        else:
            logging.info("[İŞKUR] -> 0 başvuru adayı bulundu.")
    except Exception as e:
        logging.error(f"İŞKUR modülü hata: {e}")

    tekil_ilanlar: List[Dict[str, str]] = []
    gorulen_idler: Set[str] = set()
    for ilan in ilanlar:
        uid = generate_id(ilan.get("link") or ilan.get("title", ""))
        if uid not in gorulen_idler:
            gorulen_idler.add(uid)
            tekil_ilanlar.append(ilan)

    logging.info(f"Toplam Taranacak Tekil Başvuru İlanı: {len(tekil_ilanlar)}")

    yeni_green: List[str] = []

    for idx, ilan in enumerate(tekil_ilanlar, 1):
        baslik = ilan.get("title", "")
        link = ilan.get("link", "")
        kaynak = ilan.get("source", "Kamu Portalı")

        ilan_id = generate_id(link if link else baslik)
        if ilan_id in sent_ids:
            continue

        detay = ilan_detay_getir(link) if link else ""
        uygun_mu, aciklama, hedef_profil, yeni_mi, sebep = ilan_analiz_et(baslik, detay, bugun)

        if not uygun_mu:
            continue

        yeni_etiket = " 🚨 <b>[YENİ ALIM]</b>" if yeni_mi else ""
        logging.info(f"[{idx}/{len(tekil_ilanlar)}] ({kaynak}) [{hedef_profil}] AKTİF BAŞVURU -> {baslik}")

        clean_title = html.escape(baslik)
        clean_aciklama = html.escape(aciklama)
        clean_kaynak = html.escape(kaynak)
        clean_profil = html.escape(hedef_profil)

        if link:
            item_str = (
                f"• [{clean_kaynak}] 🎯 <b>[{clean_profil}]</b>{yeni_etiket}\n"
                f"  <a href='{html.escape(link, quote=True)}'><b>{clean_title}</b></a>\n"
                f"  📌 <i>{clean_aciklama}</i>"
            )
        else:
            item_str = (
                f"• [{clean_kaynak}] 🎯 <b>[{clean_profil}]</b>{yeni_etiket}\n"
                f"  <b>{clean_title}</b>\n"
                f"  📌 <i>{clean_aciklama}</i>"
            )

        yeni_green.append(item_str)
        new_sent_ids.add(ilan_id)

    if yeni_green:
        sent_success = send_telegram_messages(yeni_green)
        if sent_success:
            save_sent_ids(new_sent_ids)
            logging.info("Yeni ve aktif başvuru ilanları Telegram üzerinden bildirildi.")
        else:
            logging.error("Telegram bildirimi sırasında hata oluştu.")
    else:
        logging.info("Kriterlerinize uyan yeni veya aktif başvuru ilanı bulunamadı.")

    logging.info("Tarama tamamlandı.")

if __name__ == "__main__":
    main()
