def detay_oku(url: str, browser_page=None) -> Tuple[str, int, str]:
    if not url:
        return "", 0, "Bağlantı yok"

    parts: List[str] = []
    pdf_links: List[str] = []
    final_url = url
    api_texts: List[str] = []
    api_count = 0
    err_count = 0

    try:
        resp = SESSION.get(url, timeout=(6, 14), allow_redirects=True)
        final_url = resp.url
        if resp.status_code == 200 and "pdf" not in resp.headers.get("Content-Type", "").lower():
            soup = BeautifulSoup(resp.text, "html.parser")
            for el in soup.find_all(["a", "iframe", "embed", "object", "source"]):
                raw = (el.get("href") or el.get("src") or el.get("data") or "").strip()
                if raw and (".pdf" in raw.lower() or "ilan-metni" in raw.lower()):
                    pdf_links.append(urljoin(final_url, raw))
            for sc in soup.find_all("script"):
                st = sc.string or sc.get_text(" ", strip=True)
                if st and any(k in tr_lower(st) for k in ["personel", "ilan", "basvuru", "başvuru", "kadro"]):
                    parts.append(temizle(st[:30000]))
            for tag in soup(["style", "nav", "header", "footer"]):
                tag.decompose()
            parts.append(temizle(soup.get_text(" ", strip=True)))
            for raw in re.findall(r"""(?:https?://[^\s"'<>]+|/[A-Za-z0-9_./-]+\.pdf(?:\?[^\s"'<>]*)?)""", resp.text, flags=re.I):
                pdf_links.append(urljoin(final_url, raw.rstrip("),;")))

        text = temizle(" ".join(parts))

        if len(text) < 450 and browser_page is not None:
            def on_response(api_resp):
                nonlocal api_count, err_count
                try:
                    st_code = api_resp.status
                    a_url = api_resp.url
                    ctype = api_resp.headers.get("content-type", "").lower()
                    if st_code >= 400:
                        err_count += 1
                        logging.warning("[AĞ HATA] HTTP %s | %s", st_code, a_url[:200])
                        return
                    if any(a_url.lower().split("?")[0].endswith(ext) for ext in (".css", ".js", ".woff2", ".png", ".jpg", ".svg", ".ico")):
                        return
                    if "google-analytics" in a_url or "googletagmanager" in a_url:
                        return
                    if "pdf" in ctype or ".pdf" in a_url.lower():
                        pdf_links.append(a_url)
                        return
                    if any(x in ctype for x in ["json", "text", "html"]):
                        body = api_resp.text()
                        if not body:
                            return
                        for raw in re.findall(r"""(?:https?://[^\s"'<>]+|/[A-Za-z0-9_./-]+\.pdf(?:\?[^\s"'<>]*)?)""", body, flags=re.I):
                            pdf_links.append(urljoin(a_url, raw.rstrip("),;")))
                        if "json" in ctype or body.lstrip().startswith(("{", "[")):
                            try:
                                conv = json_metinine_cevir(json.loads(body))
                                if conv:
                                    api_count += 1
                                    api_texts.append(conv[:30000])
                            except Exception:
                                pass
                        elif any(w in tr_lower(body) for w in ["personel", "başvuru", "basvuru", "ilan", "kadro", "kpss", "önlisans"]):
                            api_count += 1
                            api_texts.append(temizle(body[:30000]))
                except Exception:
                    pass

            browser_page.on("response", on_response)
            try:
                browser_page.goto(url, wait_until="domcontentloaded", timeout=15000)
                try:
                    browser_page.wait_for_function(
                        "document.body && document.body.innerText && document.body.innerText.trim().length > 250",
                        timeout=6000,
                    )
                except Exception:
                    pass
                browser_page.wait_for_timeout(800)

                b_soup = BeautifulSoup(browser_page.content(), "html.parser")
                for el in b_soup.find_all(["a", "iframe", "embed", "object", "source"]):
                    raw = (el.get("href") or el.get("src") or el.get("data") or "").strip()
                    if raw and (".pdf" in raw.lower() or "ilan-metni" in raw.lower()):
                        pdf_links.append(urljoin(browser_page.url, raw))
                for tag in b_soup(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()
                b_text = temizle(b_soup.get_text(" ", strip=True))
                if len(b_text) > len(text):
                    text = b_text
                if api_texts:
                    parts.append(" ".join(api_texts))
                if b_text:
                    parts.append(b_text)
                final_url = browser_page.url
                logging.info("[TEŞHİS] URL=%s | METİN=%s | API=%s | HATA=%s", final_url, len(b_text), api_count, err_count)
            finally:
                try:
                    browser_page.remove_listener("response", on_response)
                except Exception:
                    pass

        unique_pdfs = list(dict.fromkeys(pdf_links))[:4]
        pdf_texts = [p for u in unique_pdfs if (p := pdf_metin_oku(u))]
        combined = temizle(" ".join([text, " ".join(parts), " ".join(pdf_texts)]))
        return combined[:30000], len(unique_pdfs), final_url

    except Exception as exc:
        logging.warning("[DETAY HATASI] %s | %s", url, exc)
        return temizle(" ".join(parts))[:30000], len(list(dict.fromkeys(pdf_links))), final_url
USER_PROFILE = {
    "egitim": "Önlisans",
    "bolum": "Adalet",
    "puan_turu": "P93",
    "kpss": 80.86227,
    "cinsiyet": "Erkek",
    "yas": 30,
}

# Yaş sınırı kontrolünde 30 yaşına girmiş/doldurmuş aday kontrolü:
age_limits = []
for pattern in [
    r"(\d{2})\s*yaşını\s*doldurmamış",
    r"en fazla\s*(\d{2})\s*yaş",
    r"(\d{2})\s*yaşından\s*gün\s*almamış",
]:
    age_limits.extend(int(x) for x in re.findall(pattern, text))
if age_limits and int(profile["yas"]) >= min(age_limits):
    return "Uygun Değil", ["Yaş şartı karşılanmıyor"]

# main() içinde yalnızca 'Uygun' ilanlar Telegram'a gider; eksik/belirsiz kayıtlar kontrol_bekleyen.json'a yazılır:
if status == "Uygun":
    identity = result["kimlik"]
    if identity not in sent_ids and identity not in processed:
        processed.add(identity)
        messages.append(telegram_mesaji(result))
        new_sent.add(identity)
        logging.info("[UYGUN] %s", title)
