import os
import re
import json
import html
import hashlib
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin


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


def discover_rss_url():
    """
    Kariyer Kapısı'nın RSS sayfasından
    Infrastructure JavaScript dosyasını bulur.
    """

    page_url = BASE + "/RSS/RssLinkiAl"

    response = get(page_url)
    page = response.text

    scripts = re.findall(
        r'<script[^>]+src=["\']([^"\']+)["\']',
        page,
        re.I
    )

    infrastructure_url = None

    for script in scripts:
        if "Infrastructure" in script:
            infrastructure_url = urljoin(BASE, script)
            break

    if not infrastructure_url:
        raise RuntimeError(
            "Infrastructure JavaScript dosyası bulunamadı."
        )

    print("Infrastructure:", infrastructure_url)

    js = get(infrastructure_url).text

    match = re.search(
        r'kvkkbaseurl\s*[:=]\s*["\']([^"\']+)',
        js,
        re.I
    )

    if match:
        base_url = match.group(1)
    else:
        base_url = BASE + "/"

    if not base_url.endswith("/"):
        base_url += "/"

    rss_url = base_url + "RSS"

    return rss_url


def parse_rss(content):
    """
    RSS/Atom formatlarını okur.
    """

    if isinstance(content, bytes):
        content = content.decode(
            "utf-8-sig",
            errors="replace"
        )
    else:
        content = content.lstrip("\ufeff")

    root = ET.fromstring(content)

    items = []

    # Standart RSS
    for item in root.findall(".//item"):

        title = item.findtext("title", "")
        link = item.findtext("link", "")
        description = item.findtext(
            "description",
            ""
        )
        guid = item.findtext("guid", "")

        items.append({
            "title": html.unescape(
                title or ""
            ).strip(),

            "link": (
                link or ""
            ).strip(),

            "description": html.unescape(
                description or ""
            ).strip(),

            "id": (
                guid or link or title or ""
            ).strip()
        })

    # Atom desteği
    if not items:

        ns = {
            "atom": "http://www.w3.org/2005/Atom"
        }

        for entry in root.findall(
            ".//atom:entry",
            ns
        ):

            title = entry.findtext(
                "atom:title",
                "",
                ns
            )

            summary = entry.findtext(
                "atom:summary",
                "",
                ns
            )

            entry_id = entry.findtext(
                "atom:id",
                "",
                ns
            )

            link = ""

            link_element = entry.find(
                "atom:link",
                ns
            )

            if link_element is not None:
                link = link_element.attrib.get(
                    "href",
                    ""
                )

            items.append({
                "title": html.unescape(
                    title or ""
                ).strip(),

                "link": link.strip(),

                "description": html.unescape(
                    summary or ""
                ).strip(),

                "id": (
                    entry_id
                    or link
                    or title
                    or ""
                ).strip()
            })

    return items


def load_sent():

    if not os.path.exists(SENT_FILE):
        return set()

    try:

        with open(
            SENT_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            return set(
                json.load(file)
            )

    except Exception:

        return set()


def save_sent(sent):

    with open(
        SENT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            sorted(sent),
            file,
            ensure_ascii=False,
            indent=2
        )


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

    for old, new in replacements.items():
        text = text.replace(
            old,
            new
        )

    return text


def is_relevant(item):

    text = normalize(
        item["title"]
        + " "
        + item["description"]
    )

    # Adalet alanıyla ilişkili kelimeler
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

        "icra mudur",

        "adalet bakanligi"
    ]

    alan_uygun = any(
        kelime in text
        for kelime in alan_kelime
    )

    if not alan_uygun:
        return False

    # Önlisans / Adalet eğitimi sinyalleri
    onlisans = any(
        kelime in text
        for kelime in [

            "onlisans",

            "on lisans",

            "adalet programi",

            "adalet bolumu",

            "adalet mezunu"
        ]
    )

    # KPSS sinyali
    kpss = "kpss" in text

    if not onlisans and not kpss:
        return False

    # İlan açıkça 76.29'dan yüksek puan istiyorsa ele
    score_patterns = [

        r"(?:taban|en az|minimum|min)\D{0,30}"
        r"(\d{2}(?:[.,]\d+)?)",

        r"(\d{2}(?:[.,]\d+)?)"
        r"\s*puan"
        r"\s*(?:ve|veya)?"
        r"\s*(?:uzeri|üstüo
