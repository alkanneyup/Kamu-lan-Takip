import os, re, sys, json, html, hashlib, logging, requests, io
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, date
from urllib.parse import urljoin
from typing import List, Dict, Tuple, Set, Optional, Any
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s", stream=sys.stdout, force=True)

try:
    from iskur import iskur_ilanlarini_getir
except Exception:
    def iskur_ilanlarini_getir() -> List[Dict[str, str]]: return []

USER_PROFILE = {"egitim": "Önlisans", "bolum": "Adalet", "puan_turu": "P93", "kpss": 80.86227, "cinsiyet": "Erkek", "yas": 29, "hemsire_lisans": True}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"}

HARIC = ["kararname", "kanun", "yönetmelik", "genelge", "tebliğ", "mahkeme", "yargıtay", "danıştay", "ihale", "kamulaştırma", "vergi", "görevden alma", "siyasi", "ekonomi haberi", "basın açıklaması", "sınav sonucu", "mülakat sonucu", "yerleştirme sonucu", "nihai liste", "asıl ve yedek", "tebligat", "dilekçe", "ücret tarifesi", "sözlü sınav duyurusu", "giriş sınavı", "yazılı sınav duyurusu", "önceki sayı", "sonraki sayı", "ana sayfa", "mevzuat bilgi sistemi", "abonelik", "künye", "iletişim"]
ALIM = ["personel alım", "memur alım", "sözleşmeli personel", "sürekli işçi", "geçici işçi", "işçi alımı", "kamu personeli", "personel temin", "alım ilanı", "alınacaktır", "alacak"]
UNVANLAR = ["memur", "sözleşmeli personel", "sürekli işçi", "geçici işçi", "büro personeli", "destek personeli", "zabıt katibi", "zabıt kâtibi", "infaz ve koruma memuru", "infaz koruma", "icra memuru", "icra katibi", "vhki", "koruma ve güvenlik", "teknisyen", "tekniker", "mühendis", "şoför", "hizmetli", "hemşire", "öğretim görevlisi", "araştırma görevlisi"]
KURUMLAR = ["bakanlığı", "bakanlık", "üniversitesi", "üniversite", "belediyesi", "belediye", "müdürlüğü", "başkanlığı", "genel müdürlüğü", "kurumu", "valiliği", "kaymakamlığı", "işkur"]

def tr_lower(s: str) -> str:
    return "".join({"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"}.get(c, c) for c in (s or "")).lower()

def md5_id(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def load_sent_ids() -> Set[str]:
    if os.path.exists("sent_ids.json"):
        try: return set(json.load(open("sent_ids.json", "r", encoding="utf-8")))
        except Exception: return set()
    return set()

def save_sent_ids(ids: Set[str]) -> None:
    with open("sent_ids.json", "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)

def _link_cek(url: str, kaynak: str, sess: Optional[requests.Session] = None) -> List[Dict[str, str]]:
    out, seen = [], set()
    r = (sess or requests).get(url, headers=None if sess else HEADERS, timeout=(4, 7), allow_redirects=True)
    if r.status_code != 200:
        logging.warning(f"[{kaynak}] HTTP {r.status_code}")
        return out
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        href, baslik = (a.get("href") or "").strip(), " ".join(a.get_text(" ", strip=True).split())
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")) or len(baslik) < 10: continue
        full = urljoin(r.url, href)
        if full.rstrip("/") != r.url.rstrip("/") and full not in seen:
            seen.add(full); out.append({"title": baslik, "link": full, "source": kaynak})
    return out

def kaynaklari_topla() -> List[Dict[str, str]]:
    tum: List[Dict[str, str]] = []
    for u, k in [("https://www.resmigazete.gov.tr/", "Resmî Gazete"), ("https://kariyerkapisi.gov.tr/", "Kariyer Kapısı")]:
        try: tum.extend(_link_cek(u, k))
        except Exception as e: logging.error(f"{k} hatası: {e}")
    try:
        r = requests.get("https://kariyerkapisi.gov.tr/RSS", headers=HEADERS, timeout=(4, 7))
        if r.status_code == 200:
            for it in ET.fromstring(r.content).findall("./channel/item"):
                t = (it.find("title").text or "").strip() if it.find("title") is not None else ""
                l = (it.find("link").text or "").strip() if it.find("link") is not None else ""
                if t and l: tum.append({"title": t, "link": l, "source": "Kariyer Kapısı"})
    except Exception as e: logging.error(f"RSS hatası: {e}")
    try:
        s = requests.Session(); s.headers.update({**HEADERS, "Upgrade-Insecure-Requests": "1"})
        ilk = s.get("https://kamuilan.sbb.gov.tr/", timeout=(5, 8), allow_redirects=True)
        if ilk.status_code == 200:
            s.headers.update({"Referer": ilk.url})
            tum.extend(_link_cek(ilk.url, "SBB Kamu İlan", sess=s))
        else: logging.warning(f"[SBB Kamu İlan] HTTP {ilk.status_code}")
        s.close()
    except Exception as e: logging.error(f"SBB hatası: {e}")
    try:
        for k in (iskur_ilanlarini_getir() or []):
            if isinstance(k, dict): k.setdefault("source", "İŞKUR"); tum.append(k)
    except Exception as e: logging.error(f"İŞKUR hatası: {e}")
    return tum

def _json_str(obj: Any) -> str:
    if isinstance(obj, str): return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", obj)).split())
    if isinstance(obj, dict): return " ".join(_json_str(v) for v in obj.values())
    if isinstance(obj, list): return " ".join(_json_str(v) for v in obj)
    return ""

def _pdf_metin_oku(pdf_url: str) -> str:
    if not pdf_url: return ""
    try:
        r = requests.get(pdf_url, headers=HEADERS, timeout=(4, 7), allow_redirects=True)
        if r.status_code != 200 or not r.content: return ""
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(r.content))
            metin = " ".join((page.extract_text() or "") for page in reader.pages[:8])
            if len(metin.strip()) > 30:
                return " ".join(metin.split())[:10000]
        except Exception: pass
        # pypdf yoksa veya metin çıkarılamazsa PDF içindeki okunabilir metin parçalarını ayıkla
        ham = re.findall(rb"[A-Za-zÇĞİÖŞÜçğıöşü0-9\s\.\,\:\;\-\/\(\)\%]{4,}", r.content)
        temiz = " ".join(x.decode("utf-8", errors="ignore") for x in ham)
        return " ".join(temiz.split())[:6000]
    except Exception:
        return ""

def detay_oku(url: str) -> str:
    if not url: return ""
    parcalar: List[str] = []
    pdf_linkler: List[str] = []
    try:
        if ".pdf" in url.lower():
            pdf_linkler.append(url)
        m = re.search(r"i=([a-f0-9-]+)", url, re.IGNORECASE)
        if m and "kariyerkapisi" in url:
            guid = m.group(1)
            for api in [f"https://kariyerkapisi.gov.tr/RSS/IlanDetayGetir?id={guid}", f"https://kariyerkapisi.gov.tr/IlanDetay/Getir?id={guid}"]:
                try:
                    ar = requests.get(api, headers=HEADERS, timeout=(3, 5))
                    if ar.status_code == 200:
                        try:
                            j_str = _json_str(ar.json())
                            parcalar.append(j_str)
                            pdf_linkler.extend(re.findall(r"https?://[^\s\"'<>]+\.pdf", j_str, re.IGNORECASE))
                        except Exception:
                            raw_t = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", ar.text)).split())
                            parcalar.append(raw_t)
                            pdf_linkler.extend(re.findall(r"https?://[^\s\"'<>]+\.pdf", raw_t, re.IGNORECASE))
                except Exception: continue
        r = requests.get(url, headers=HEADERS, timeout=(3, 5), allow_redirects=True)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = urljoin(r.url, (a.get("href") or "").strip())
                if ".pdf" in href.lower() or "ilan-metni" in href.lower():
                    pdf_linkler.append(href)
            pdf_linkler.extend(re.findall(r"https?://[^\s\"'<>]+\.pdf", r.text, re.IGNORECASE))
            tablo_satirlari = [" | ".join(td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])) for tr in soup.find_all("tr")]
            script_metinleri = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", s.string or s.get_text() or "")).split()) for s in soup.find_all("script")]
            for tag in soup(["script", "style", "nav", "header", "footer"]): tag.decompose()
            parcalar.append(" ".join(soup.get_text(" ", strip=True).split()))
            if tablo_satirlari: parcalar.append(" ; ".join(x for x in tablo_satirlari if x.strip()))
            if script_metinleri: parcalar.append(" ".join(x for x in script_metinleri if x.strip())[:4000])
        for p_url in list(dict.fromkeys(pdf_linkler))[:2]:
            pdf_txt = _pdf_metin_oku(p_url)
            if pdf_txt: parcalar.append(pdf_txt)
    except Exception: pass
    return " ".join(p for p in parcalar if p)[:18000]
def _bilgi_cikar(baslik: str, detay: str, bugun: date) -> Dict[str, Any]:
    metin = tr_lower(f"{baslik} {detay}")
    kurum = "Belirtilmemiş"
    for src in (baslik, detay):
        m = re.search(r"([A-ZÇĞİÖŞÜ][a-zçğıöşüA-ZÇĞİÖŞÜ0-9\s\-]{2,55}?(?:Bakanlığı|Üniversitesi|Belediyesi|Genel Müdürlüğü|Başkanlığı|Müdürlüğü|Kurumu))", src)
        if m: kurum = " ".join(m.group(1).split()); break
    pozisyon = next((u.title() for u in UNVANLAR if u in metin), "Belirtilmemiş")
    km = re.search(r"(?:kontenjan|alınacak|kadro|adedi)\D{0,25}?(\d{1,4})\s*(?:kişi|personel|memur|işçi|adet|\|)", metin)
    kontenjan = f"{km.group(1)} kişi" if km else "Belirtilmemiş"
    egitim = "Önlisans" if any(x in metin for x in ["önlisans", "ön lisans", "myo", "meslek yüksekokulu"]) else ("Lisans" if any(x in metin for x in ["lisans", "hemşirelik"]) else ("Ortaöğretim" if any(x in metin for x in ["ortaöğretim", "lise"]) else "Belirtilmemiş"))
    kpss = next((t.upper() for t in ("p93", "p3", "p94", "kpss") if t in metin), "Belirtilmemiş")
    bm = re.findall(r"(?:başvuru başlangıç|başvurular\D{0,25}?tarihinde)\D*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})", detay, re.IGNORECASE)
    sm = re.findall(r"(?:son başvuru|son gün|başvuru bitiş|tarihine kadar)\D*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})", detay, re.IGNORECASE)
    son_str, son_dt = "Belirtilmemiş", None
    if sm:
        raw = sm[0].strip().replace("/", ".").replace("-", "."); son_str = raw
        for fmt in ("%d.%m.%Y", "%d.%m.%y"):
            try: son_dt = datetime.strptime(raw, fmt).date(); son_str = son_dt.strftime("%d.%m.%Y"); break
            except ValueError: continue
    return {"kurum": kurum, "pozisyon": pozisyon, "kontenjan": kontenjan, "egitim": egitim, "kpss": kpss, "bas": bm[0] if bm else "Belirtilmemiş", "son": son_str, "son_dt": son_dt}

def _uygunluk_bak(metin: str, egitim: str, p: Dict[str, Any]) -> str:
    for grp in re.findall(r"(\d{2})\s*yaşını doldurmamış|en fazla\s*(\d{2})\s*yaş|(\d{2})\s*yaşından gün almamış", metin):
        for v in grp:
            if v.isdigit() and int(p["yas"]) > int(v): return "Uygun Değil"
    if tr_lower(str(p["cinsiyet"])) == "erkek" and re.search(r"\byalnızca kadın\b|\bkadın aday\b", metin): return "Uygun Değil"
    for raw_p in re.findall(r"(?:kpss|p93|p3|p94|taban puan)\D*([5-9][0-9](?:[\.,][0-9]+)?)", metin):
        try:
            taban = float(raw_p.replace(",", "."))
            if 50.0 <= taban <= 100.0 and float(p["kpss"]) < taban: return "Uygun Değil"
        except ValueError: continue
    if p.get("hemsire_lisans") and "hemşire" in metin and ("lisans" in metin or "hemşirelik" in metin): return "Uygun"
    if egitim == "Önlisans" or any(x in metin for x in ["önlisans", "ön lisans", "p93", "3001", "adalet", "büro personeli", "zabıt katibi", "zabıt kâtibi", "icra katibi"]): return "Uygun"
    return "Uygun Değil" if egitim == "Lisans" and not p.get("hemsire_lisans") else "Kontrol Gerekli"

def ilan_degerlendir(baslik: str, detay: str, kaynak: str = "Kamu", link: str = "", bugun: Optional[date] = None, profil: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ref = bugun or datetime.now().date(); p = profil or USER_PROFILE
    b_tr, d_tr = tr_lower(baslik), tr_lower(detay); metin = f"{b_tr} {d_tr}"
    if any(k in metin for k in HARIC): return {"kabul": False, "sebep": "Hariç tutulan içerik"}
    if len(detay.strip()) < 60: return {"kabul": False, "sebep": "Detay metni yetersiz"}
    if not any(a in metin for a in ALIM): return {"kabul": False, "sebep": "Gerçek personel alım sinyali yok"}
    info = _bilgi_cikar(baslik, detay, ref)
    if info["son_dt"] and info["son_dt"] < ref: return {"kabul": False, "sebep": "Başvuru süresi geçmiş"}
    if not any(info[k] != "Belirtilmemiş" for k in ("egitim", "kpss", "kontenjan", "pozisyon")):
        return {"kabul": False, "sebep": "Şart/kadro bilgisi doğrulanamadı", **info}
    puan = (30 if any(a in b_tr for a in ALIM) else 0) + (15 if info["kurum"] != "Belirtilmemiş" or any(k in metin for k in KURUMLAR) else 0) + (15 if info["pozisyon"] != "Belirtilmemiş" else 0) + (10 if info["kontenjan"] != "Belirtilmemiş" else 0) + (10 if info["kpss"] != "Belirtilmemiş" or "kpss" in metin else 0) + (10 if info["bas"] != "Belirtilmemiş" or info["son"] != "Belirtilmemiş" else 0) + (10 if link.startswith(("http://", "https://")) else 0)
    uygunluk = _uygunluk_bak(metin, info["egitim"], p)
    kabul = puan >= 50 and uygunluk == "Uygun"
    kategori = "AKADEMİK PERSONEL" if any(ak in metin for ak in ["öğretim görevlisi", "araştırma görevlisi", "profesör", "doçent", "2547"]) else ("İLAN GÜNCELLEMESİ" if any(g in metin for g in ["güncelleme", "düzeltme ilanı", "ek ilan"]) else "YENİ ALIM")
    kimlik = md5_id("|".join([b_tr.strip(), tr_lower(info["kurum"]).strip(), tr_lower(info["pozisyon"]).strip(), (link or "").strip().lower()]))
    return {"kabul": kabul, "puan": puan, "kategori": kategori, "uygunluk": uygunluk, "link": link or "Belirtilmemiş", "kimlik": kimlik, "sebep": "ok" if kabul else f"Uygun değil veya düşük puan ({uygunluk}, {puan})", **info}

def telegram_gonder(items: List[str]) -> bool:
    token, cids = os.getenv("TELEGRAM_BOT_TOKEN"), [c.strip() for c in (os.getenv("TELEGRAM_CHAT_ID") or "").split(",") if c.strip()]
    if not token or not cids: logging.error("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik."); return False
    url, ok, blok, uz = f"https://api.telegram.org/bot{token}/sendMessage", True, [], 0
    def _post(parca: List[str]) -> bool:
        s_ok = True
        for cid in cids:
            r = requests.post(url, json={"chat_id": cid, "text": "\n\n---\n\n".join(parca)[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=10)
            if r.status_code != 200: logging.error(f"Telegram hatası ({cid}): {r.text}"); s_ok = False
        return s_ok
    for it in items:
        if uz + len(it) + 10 > 3800 and blok:
            if not _post(blok): ok = False
            blok, uz = [], 0
        blok.append(it); uz += len(it) + 10
    return (_post(blok) and ok) if blok else ok

def main() -> None:
    bugun = datetime.now().date()
    logging.info(f"KAMU İLAN TAKİP BAŞLADI ({bugun})")
    sent_ids = load_sent_ids()
    new_ids = set(sent_ids)
    tekil, gorulen = [], set()
    for a in kaynaklari_topla():
        uid = md5_id(a.get("link") or a.get("title", ""))
        if uid not in gorulen: gorulen.add(uid); tekil.append(a)
    logging.info(f"İncelenecek tekil bağlantı sayısı: {len(tekil)}")
    mesajlar, gorulen_kimlik, sayac = [], set(), Counter()
    for ilan in tekil:
        baslik, link, kaynak = ilan.get("title", ""), ilan.get("link", ""), ilan.get("source", "Kamu")
        sonuc = ilan_degerlendir(baslik, detay_oku(link) if link else "", kaynak=kaynak, link=link, bugun=bugun)
        if not sonuc["kabul"]:
            sebep = sonuc["sebep"]
            sayac[sebep] += 1
            if sebep == "Şart/kadro bilgisi doğrulanamadı" or "Kontrol Gerekli" in sebep:
                logging.info(f"[ADAY LOG] ({kaynak}) {baslik} | Eğitim={sonuc.get('egitim', '-')} | KPSS={sonuc.get('kpss', '-')} | Pozisyon={sonuc.get('pozisyon', '-')} | Sebep={sebep}")
            continue
        if sonuc["kimlik"] in sent_ids or sonuc["kimlik"] in gorulen_kimlik: sayac["Tekrar / kayıtlı"] += 1; continue
        gorulen_kimlik.add(sonuc["kimlik"]); new_ids.add(sonuc["kimlik"])
        logging.info(f"[{kaynak}] [{sonuc['kategori']}] [{sonuc['uygunluk']}] (Puan: {sonuc['puan']}) -> {baslik}")
        lnk = f"<a href='{html.escape(sonuc['link'], quote=True)}'>İlan Bağlantısı</a>" if sonuc["link"].startswith(("http://", "https://")) else "Belirtilmemiş"
        mesajlar.append(f"<b>{'🎓 AKADEMİK PERSONEL İLANI' if sonuc['kategori']=='AKADEMİK PERSONEL' else ('🔄 İLAN GÜNCELLEMESİ' if sonuc['kategori']=='İLAN GÜNCELLEMESİ' else '🏛️ YENİ KAMU PERSONEL ALIMI')}</b>\n\nKurum: {html.escape(sonuc['kurum'])}\nPozisyon: {html.escape(sonuc['pozisyon'])}\nKontenjan: {html.escape(sonuc['kontenjan'])}\nEğitim: {html.escape(sonuc['egitim'])}\nKPSS: {html.escape(sonuc['kpss'])}\nBaşvuru Tarihi: {html.escape(sonuc['bas'])}\nSon Başvuru: {html.escape(sonuc['son'])}\n\n📌 Kullanıcı Profili: {html.escape(sonuc['uygunluk'])}\n\n🔗 Resmî İlan: {lnk}\n🔗 Başvuru: {lnk}")
    if sayac:
        logging.info("Eleme özeti -> " + ", ".join(f"{k}: {v}" for k, v in sayac.most_common()))
    if mesajlar:
        if telegram_gonder(mesajlar): save_sent_ids(new_ids); logging.info(f"{len(mesajlar)} uygun ilan gönderildi.")
    else:
        logging.info("Profilinize uygun ve şartları doğrulanmış yeni ilan bulunamadı.")

if __name__ == "__main__":
    main()
