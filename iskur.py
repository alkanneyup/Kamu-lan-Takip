import re
import html
import requests
from bs4 import BeautifulSoup


# ============================================================
# İŞKUR
# ============================================================

ISKUR_URL = "https://acikisharita.iskur.gov.tr/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/139 Safari/537.36"
    )
}


def temizle(text):
    if not text:
        return ""

    text = html.unescape(str(text))
    text = BeautifulSoup(text, "html.parser").get_text(" ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def iskur_sayfasini_oku():
    """
    İŞKUR Açık İş Haritası ana sayfasını okur.

    Şimdilik yalnızca bağlantının erişilebilirliğini
    ve sayfadaki temel bilgileri kontrol eder.
    """

    print("")
    print("=" * 50)
    print("İŞKUR AÇIK İŞLER KONTROLÜ")
    print("=" * 50)

    try:
        response = requests.get(
            ISKUR_URL,
            headers=HEADERS,
            timeout=30,
        )

        print(
            f"[İŞKUR] HTTP: {response.status_code}"
        )

        response.raise_for_status()

    except Exception as exc:
        print(
            "[İŞKUR HATA]",
            exc,
        )
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    text = temizle(
        soup.get_text(" ")
    )

    print(
        "[İŞKUR] Sayfa okundu."
    )

    # Sayfada toplam açık iş bilgisini yakalamaya çalış.
    match = re.search(
        r"TOPLAM AÇIK İŞ\s*([\d\.\,]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        print(
            "[İŞKUR] Toplam açık iş:",
            match.group(1),
        )
    else:
        print(
            "[İŞKUR] Toplam açık iş sayısı "
            "otomatik okunamadı."
        )

    return []


def iskur_ilanlarini_getir():
    """
    İŞKUR ilanlarını ana programa verecek fonksiyon.

    Veri kaynağının gerçek API/istek yapısı
    doğrulandıktan sonra burada ilanlar üretilecek.
    """

    ilanlar = iskur_sayfasini_oku()

    print(
        "[İŞKUR] Alınan ilan:",
        len(ilanlar),
    )

    return ilanlar


if __name__ == "__main__":
    iskur_ilanlarini_getir()
