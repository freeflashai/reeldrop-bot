"""Facebook URL validation and parsing helpers."""

import re
from urllib.parse import parse_qs, urlparse

FACEBOOK_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "web.facebook.com",
    "fb.watch",
}


def is_supported_facebook_url(url: str) -> bool:
    """Check if a URL points to a public Facebook video, reel, or watch post."""
    try:
        parsed = urlparse(url)
    except (ValueError, UnicodeError):
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in FACEBOOK_HOSTS:
        return False

    if host == "fb.watch":
        path = parsed.path.strip("/")
        return bool(path and re.fullmatch(r"[A-Za-z0-9_-]+", path))

    path = parsed.path.rstrip("/")
    if bool(re.fullmatch(r"/reel/[0-9A-Za-z_-]+", path)):
        return True
    if bool(re.fullmatch(r"/share/[rv]/[0-9A-Za-z_-]+", path)):
        return True
    if bool(re.search(r"/videos/[0-9]+", path)):
        return True

    if path in {"/watch", "/watch/"}:
        qs = parse_qs(parsed.query)
        v = qs.get("v")
        return bool(v and re.fullmatch(r"[0-9A-Za-z_-]+", v[0]))

    return False
