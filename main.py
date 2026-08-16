def parse_rss(content):
    """
    RSS/Atom formatlarını mümkün olduğunca toleranslı şekilde okur.
    """

    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="replace")
    else:
        content = content.lstrip("\ufeff")

    root = ET.fromstring(content)
