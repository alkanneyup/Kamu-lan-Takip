import os, re, sys, json, html, hashlib, logging, requests, io, zlib
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
    r = (sess or requests).get(url, headers=None if sess else HEADERS, timeout=(3, 5), allow_redirects=True)
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
        r = requests.get("https://kariyerkapisi.gov.tr/RSS", headers=HEADERS, timeout=(3, 5))
        if r.status_code == 200:
            for it in ET.fromstring(r.content).findall("./channel/item"):
                t = (it.find("title").text or "").strip() if it.find("title") is not None else ""
                l = (it.find("link").text or "").strip() if it.find("link") is not None else ""
                if t and l: tum.append({"title": t, "link": l, "source": "Kariyer Kapısı"})
    except Exception as e: logging.error(f"RSS hatası: {e}")
    try:
        s = requests.Session(); s.headers.update({**HEADERS, "Upgrade-Insecure-Requests": "1"})
        ilk = s.get("https://kamuilan.sbb.gov.tr/", timeout=(4, 6), allow_redirects=True)
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
    if isinstance(obj, str):
        return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", obj)).replace("\\/", "/").split())
    if isinstance(obj, dict): return " ".join(_json_str(v) for v in obj.values())
    if isinstance(obj, list): return " ".join(_json_str(v) for v in obj)
    return ""

def _zlib_metin_cikar(raw_pdf: bytes) -> str:
    parcalar: List[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", raw_pdf, re.DOTALL):
        akis = m.group(1)
        for wbits in (15, -15, 31):
            try:
                txt = zlib.decompress(akis, wbits).decode("latin-1", errors="ignore")
                parantez_ici = re.findall(r"\(([^()\\]{2,200})\)", txt)
                if parantez_ici: parcalar.append(" ".join(parantez_ici))
                duz = " ".join(re.findall(r"[A-Za-z0-9\s\.\,\:\;\-\/\(\)\%]{4,}", txt))
                if duz: parcalar.append(duz)
                break
            except Exception: continue
    if not parcalar:
        ham = re.findall(rb"[A-Za-z0-9\s\.\,\:\;\-\/\(\)\%]{4,}", raw_pdf)
        parcalar.append(" ".join(x.decode("utf-8", errors="ignore") for x in ham))
    return " ".join(" ".join(parcalar).split())[:10000]

def _pdf_metin_oku(pdf_url: str) -> str:
    if not pdf_url: return ""
    try:
        r = requests.get(pdf_url, headers=HEADERS, timeout=(3, 5), allow_redirects=True)
        if r.status_code != 200 or not r.content: return ""
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(r.content))
            metin = " ".join((page.extract_text() or "") for page in reader.pages[:8])
            if len(metin.strip()) > 30: return " ".join(metin.split())[:10000]
        except Exception: pass
        return _zlib_metin_cikar(r.content)
    except Exception: return ""

def _pdf_linkleri_bul(metin_veya_html: str, base_url: str = "") -> List[str]:
    bulunan: List[str] = []
    temiz = metin_veya_html.replace("\\/", "/")
    for raw in re.findall(r"""(?:https?://[^\s"'<>()]+|/?[A-Za-z0-9_./-]+\.(?:pdf|PDF)(?:\?[^\s"'<>()]*)?)""", temiz):
        full = urljoin(base_url, raw.strip()) if base_url else raw.strip()
        if ".pdf" in full.lower() and full.startswith(("http://", "https://")):
            bulunan.append(full)
    return list(dict.fromkeys(bulunan))

def detay_oku(url: str) -> Tuple[str, int]:
    if not url: return "", 0
    parcalar: List[str] = []
    pdf_linkler: List[str] = []
    try:
        if ".pdf" in url.lower(): pdf_linkler.append(url)
        r = requests.get(url, headers=HEADERS, timeout=(2.5, 4), allow_redirects=True)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for el in soup.find_all(["a", "iframe", "embed", "object", "source"]):
                raw_href = (el.get("href") or el.get("src") or el.get("data") or "").strip()
                if raw_href:
                    full_h = urljoin(r.url, raw_href)
                    if ".pdf" in full_h.lower() or "ilan-metni" in full_h.lower():
                        pdf_linkler.append(full_h)
            pdf_linkler.extend(_pdf_linkleri_bul(r.text, r.url))
            tablo_satirlari = [" | ".join(td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])) for tr in soup.find_all("tr")]
            for tag in soup(["script", "style", "nav", "header", "footer"]): tag.decompose()
            parcalar.append(" ".join(soup.get_text(" ", strip=True).split()))
            if tablo_satirlari: parcalar.append(" ; ".join(x for x in tablo_satirlari if x.strip()))
        # Sadece sayfa/HTML içinde gerçekten .pdf linki bulunduysa en fazla 2 PDF indir (hız için)
        benzersiz_pdf = list(dict.fromkeys(pdf_linkler))
        for p_url in benzersiz_pdf[:2]:
            pdf_txt = _pdf_metin_oku(p_url)
            if pdf_txt: parcalar.append(pdf_txt)
        return " ".join(p for p in parcalar if p)[:16000], len(benzersiz_pdf)
    except Exception:
        return " ".join(p for p in parcalar if p)[:16000], len(list(dict.fromkeys(pdf_linkler)))
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

def _uygunluk_bak(metin: str, egitim: str, p: Dict[str, Any], detay_kisa_js: bool = False) -> str:
    for grp in re.findall(r"(\d{2})\s*yaşını doldurmamış|en fazla\s*(\d{2})\s*yaş|(\d{2})\s*yaşından gün almamış", metin):
        for v in grp:
            if v.isdigit() and int(p["yas"]) > int(v): return "Uygun Değil"
    if tr_lower(str(p["cinsiyet"])) == "erkek" and re.search(r"\byalnızca kadın\b|\bkadın aday\b", metin): return "Uygun Değil"
    for raw_p in re.findall(r"(?:kpss|p93|p3|p94|taban puan)\D*([5-9][0-9](?:[\.,][0-9]+)?)", metin):
        try:
            taban = float(raw_p.replace(",", "."))
            if 50.0 <= taban <= 100.0 and float(p["kpss"]) < taban: return "Uygun Değil"
        except ValueError: continue
    # Bilişim / mühendislik / uzmanlık / kalkınma ajansı gibi yüksek lisans/özel uzmanlık odaklı ilanları ayrıştır
    if any(x in metin for x in ["bilişim personeli", "çözümleyici", "programcı", "kalkınma ajansı", "uzman personel"]):
        return "Kontrol Gerekli"
    if p.get("hemsire_lisans") and "hemşire" in metin and ("lisans" in metin or "hemşirelik" in metin): return "Uygun"
    if egitim == "Önlisans" or any(x in metin for x in ["önlisans", "ön lisans", "p93", "3001", "adalet", "büro personeli", "zabıt katibi", "zabıt kâtibi", "icra katibi"]):
        return "Uygun"
    # Detay JS arkasında kaldığında (detay_kisa_js=True) başlıkta/metinde açıkça elenmeyen genel alım sinyali varsa Kontrol Gerekli ver
    if detay_kisa_js and any(x in metin for x in ["sözleşmeli personel", "memur alım", "personel alım", "kamu personeli"]):
        return "Kontrol Gerekli"
    return "Uygun Değil" if egitim == "Lisans" and not p.get("hemsire_lisans") else "Kontrol Gerekli"

def ilan_degerlendir(baslik: str, detay: str, kaynak: str = "Kamu", link: str = "", bugun: Optional[date] = None, profil: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ref = bugun or datetime.now().date(); p = profil or USER_PROFILE
    b_tr, d_tr = tr_lower(baslik), tr_lower(detay); metin = f"{b_tr} {d_tr}"
    if any(k in metin for k in HARIC): return {"kabul": False, "sebep": "Hariç tutulan içerik"}
    detay_kisa_js = len(detay.strip()) < 450
    if not any(a in metin for a in ALIM): return {"kabul": False, "sebep": "Gerçek personel alım sinyali yok"}
    info = _bilgi_cikar(baslik, detay, ref)
    if info["son_dt"] and info["son_dt"] < ref: return {"kabul": False, "sebep": "Başvuru süresi geçmiş"}
    # Detay kısa/JS arkasında kalsa bile başlıkta pozisyon veya alım sinyali varsa başlık ipucuyla değerlendir
    baslik_sinyali = (info["pozisyon"] != "Belirtilmemiş") or any(a in b_tr for a in ALIM)
    if not any(info[k] != "Belirtilmemiş" for k in ("egitim", "kpss", "kontenjan", "pozisyon")) and not (detay_kisa_js and baslik_sinyali):
        return {"kabul": False, "sebep": "Şart/kadro bilgisi doğrulanamadı", **info}
    puan = (30 if any(a in b_tr for a in ALIM) else 0) + (15 if info["kurum"] != "Belirtilmemiş" or any(k in metin for k in KURUMLAR) else 0) + (15 if info["pozisyon"] != "Belirtilmemiş" else 0) + (10 if info["kontenjan"] != "Belirtilmemiş" else 0) + (10 if info["kpss"] != "Belirtilmemiş" or "kpss" in metin else 0) + (10 if info["bas"] != "Belirtilmemiş" or info["son"] != "Belirtilmemiş" else 0) + (10 if link.startswith(("http://", "https://")) else 0)
    uygunluk = _uygunluk_bak(metin, info["egitim"], p, detay_kisa_js=detay_kisa_js)
    kabul = puan >= 50 and uygunluk == "Uygun"
    kategori = "AKADEMİK PERSONEL" if any(ak in metin for ak in ["öğretim görevlisi", "araştırma görevlisi", "profesör", "doçent", "2547"]) else ("İLAN GÜNCELLEMESİ" if any(g in metin for g in ["güncelleme", "düzeltme ilanı", "ek ilan"]) else "YENİ ALIM")
    kimlik = md5_id("|".join([b_tr.strip(), tr_lower(info["kurum"]).strip(), tr_lower(info["pozisyon"]).strip(), (link or "").strip().lower()]))
    not_ek = " [Detay/PDF sitede kontrol edilmeli]" if detay_kisa_js else ""
    return {"kabul": kabul, "puan": puan, "kategori": kategori, "uygunluk": uygunluk, "link": link or "Belirtilmemiş", "kimlik": kimlik, "not_ek": not_ek, "sebep": "ok" if kabul else f"Uygun değil veya düşük puan ({uygunluk}, {puan})", **info}

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
        detay, pdf_sayisi = detay_oku(link) if link else ("", 0)
        sonuc = ilan_degerlendir(baslik, detay, kaynak=kaynak, link=link, bugun=bugun)
        if not sonuc["kabul"]:
            sebep = sonuc["sebep"]
            sayac[sebep] += 1
            if sebep == "Şart/kadro bilgisi doğrulanamadı" or "Kontrol Gerekli" in sebep:
                logging.info(f"[ADAY LOG] ({kaynak}) {baslik} | DetayUz={len(detay)} | PDF={pdf_sayisi} | Eğitim={sonuc.get('egitim', '-')} | KPSS={sonuc.get('kpss', '-')} | Pozisyon={sonuc.get('pozisyon', '-')} | Sebep={sebep}")
            continue
        if sonuc["kimlik"] in sent_ids or sonuc["kimlik"] in gorulen_kimlik: sayac["Tekrar / kayıtlı"] += 1; continue
        gorulen_kimlik.add(sonuc["kimlik"]); new_ids.add(sonuc["kimlik"])
        logging.info(f"[{kaynak}] [{sonuc['kategori']}] [{sonuc['uygunluk']}] (Puan: {sonuc['puan']}) -> {baslik}{sonuc.get('not_ek', '')}")
        lnk = f"<a href='{html.escape(sonuc['link'], quote=True)}'>İlan Bağlantısı</a>" if sonuc["link"].startswith(("http://", "https://")) else "Belirtilmemiş"
        mesajlar.append(f"<b>{'🎓 AKADEMİK PERSONEL İLANI' if sonuc['kategori']=='AKADEMİK PERSONEL' else ('🔄 İLAN GÜNCELLEMESİ' if sonuc['kategori']=='İLAN GÜNCELLEMESİ' else '🏛️ YENİ KAMU PERSONEL ALIMI')}</b>\n\nKurum: {html.escape(sonuc['kurum'])}\nPozisyon: {html.escape(sonuc['pozisyon'])}\nKontenjan: {html.escape(sonuc['kontenjan'])}\nEğitim: {html.escape(sonuc['egitim'])}\nKPSS: {html.escape(sonuc['kpss'])}\nBaşvuru Tarihi: {html.escape(sonuc['bas'])}\nSon Başvuru: {html.escape(sonuc['son'])}\n\n📌 Kullanıcı Profili: {html.escape(sonuc['uygunluk'])}{html.escape(sonuc.get('not_ek', ''))}\n\n🔗 Resmî İlan: {lnk}\n🔗 Başvuru: {lnk}")
    if sayac:
        logging.info("Eleme özeti -> " + ", ".join(f"{k}: {v}" for k, v in sayac.most_common()))
    if mesajlar:
        if telegram_gonder(mesajlar): save_sent_ids(new_ids); logging.info(f"{len(mesajlar)} uygun ilan gönderildi.")
    else:
        logging.info("Profilinize uygun ve şartları doğrulanmış yeni ilan bulunamadı.")

if __name__ == "__main__":
    main()
