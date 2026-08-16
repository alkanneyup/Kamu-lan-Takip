import os
import re
import json
import html
import hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin, urlencode

BASE = "https://kariyerkapisi.gov.tr"
USER_AGENT = "Kamu-Ilan-Takip/1.0"

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

KPSS_SCORE = 76.29

SENT_FILE = "sent_ids.json"


def get(url, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["User-Agent"] = USER_AGENT

    response = requests.get(
        url,
        headers=headers,
        timeout=30,
        **kwargs
    )

    response.raise_for_status()
    return response


def discover_base_url():
    """
    Kariyer Kapısı'nın kendi Infrastructure JS dosyasından
    RSS/API taban adreslerini bulmaya çalışır.
    """

    page = get(BASE + "/RSS/RssLinkiAl").text

    scripts = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        page,
        re.I
    )

    infrastructure = None

    for script in scripts:
        if "Infrastructure" in script:
            infrastructure = urljoin(BASE, script)
            break

    if not infrastructure:
        infrastructure = BASE + "/js/Infrastructure.enxa2bxk74.js"

    js = get(infrastructure).text

    kvkk_match = re.search(
        r'kvkkbaseurl\s*[:=]\s*["\']([^"\']+)',
        js,
        re.I
    )

    api_match = re.search(
        r'apiURL\s*[:=]\s*["\']([^"\']+)',
        js,
        re.I
    )

    kvkk_base = kvkk_match.group(1) if kvkk_match else BASE + "/"

    api_base = api_match.group(1) if api_match else BASE

    return kvkk_base, api_base


def build_rss_url():
    """
    Filtresiz RSS.
    Daha sonra kurum/il/ilan türü filtreleri ekleyebiliriz.
    """

    kvkk_base, _ = discover_base_url()

    if not kvkk_base.endswith("/"):
        kvkk_base += "/"

    return kvkk_base + "RSS"


def parse_rss(content):
    """
    RSS/Atom formatlarını mümkün olduğunca toleranslı şekilde okur.
    """

    content = content.lstrip("\ufeff")

    root = ET.fromstring(content)

    items = []

    # RSS
    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        description = item.findtext("description", "")
        guid = item.findtext("guid", "")

        items.append({
            "title": html.unescape(title or "").strip(),
            "link": (link or "").strip(),
            "description": html.unescape(description or "").strip(),
            "id": (guid or link or title or "").strip()
        })

    # Atom
    if not items:
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for entry in root.findall(".//atom:entry", ns):
            title = entry.findtext("atom:title", "", ns)

            link_element = entry.find("atom:link", ns)
            link = ""

            if link_element is not None:
                link = link_element.attrib.get("href", "")

            summary = entry.findtext("atom:summary", "", ns)
            entry_id = entry.findtext("atom:id", "", ns)

            items.append({
                "title": html.unescape(title or "").strip(),
                "link": link.strip(),
                "description": html.unescape(summary or "").strip(),
                "id": (entry_id or link or title or "").strip()
            })

    return items


def load_sent():
    if not os.path.exists(SENT_FILE):
        return set()

    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_sent(sent):
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(sent), f, ensure_ascii=False, indent=2)


def normalize(text):
    text = text.lower()

    replacements = {
        "ı": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c"
    }

    for a, b in replacements.items():
        text = text.replace(a, b)

    return text


def is_relevant(item):
    """
    İlk sürümde güvenli tarafta kalmak için
    ilan metnindeki güçlü sinyalleri arıyoruz.
    """

    text = normalize(
        item["title"] + " " + item["description"]
    )

    # Adalet / hukuk / büro alanına yakın güçlü ifadeler
    alan_kelime = [
        "adalet",
        "hukuk",
        "icra",
        "zabit katibi",
        "zabita katibi",
        "katip",
        "yazi isleri",
        "mahkeme",
        "icra mudurlugu",
        "icra mudur"
    ]

    alan_uygun = any(x in text for x in alan_kelime)

    # Önlisans sinyali
    onlisans = any(x in text for x in [
        "onlisans",
        "on lisans",
        "adalet programi",
        "adalet bolumu"
    ])

    # KPSS sinyali
    kpss = "kpss" in text

    # Çok düşük olmayan taban puanlar için güvenli kontrol.
    # İlanın açıkça 76.29'dan yüksek bir taban puan istediği
    # görülüyorsa eliyoruz.
    score_patterns = [
        r'(?:taban|en az|min(?:imum)?)\D{0,30}(\d{2}(?:[.,]\d+)?)',
        r'(\d{2}(?:[.,]\d+)?)\s*puan(?:indan|ından)?\s*(?:az|dusuk)'
    ]

    for pattern in score_patterns:
        for match in re.findall(pattern, text):
            try:
                required = float(match.replace(",", "."))

                if required > KPSS_SCORE:
                    return False
            except ValueError:
                pass

    # Başvuru kapanmış ifadeleri
    kapanmis = [
        "basvuru sona ermistir",
        "basvurular sona ermistir",
        "basvuru suresi dolmustur",
        "son basvuru tarihi gecmistir"
    ]

    if any(x in text for x in kapanmis):
        return False

    # Güçlü uygunluk
    return alan_uygun and (onlisans or kpss)


def telegram_send(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": False
        },
        timeout=30
    )

    response.raise_for_status()


def make_message(item):
    return (
        "🔔 YENİ UYGUN KAMU İLANI\n\n"
        f"📌 {item['title']}\n\n"
        f"📝 {item['description'][:1800]}\n\n"
        f"🔗 {item['link']}"
    )


def main():
    print("Kamu İlan Takip başlıyor...")

    rss_url = build_rss_url()

    print("RSS:", rss_url)

    response = get(rss_url)

    print("RSS HTTP:", response.status_code)
    print("RSS uzunluğu:", len(response.text))

    items = parse_rss(response.content)

    print("Toplam ilan:", len(items))

    sent = load_sent()

    new_sent = set(sent)

    uygun = 0
    gonderilen = 0

    for item in items:

        if not item["id"]:
            raw = (
                item["title"] +
                item["link"] +
                item["description"]
            )

            item["id"] = hashlib.sha256(
                raw.encode("utf-8")
            ).hexdigest()

        if item["id"] in sent:
            continue

        if not is_relevant(item):
            continue

        uygun += 1

        try:
            telegram_send(make_message(item))
            print("Telegram gönderildi:", item["title"])

            new_sent.add(item["id"])
            gonderilen += 1

        except Exception as e:
            print("Telegram hatası:", e)

    save_sent(new_sent)

    print("Uygun yeni ilan:", uygun)
    print("Gönderilen:", gonderilen)
    print("Tamamlandı.")


if __name__ == "__main__":
    main()
