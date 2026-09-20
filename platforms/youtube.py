"""YouTube URL validation and parsing helpers."""

import re
from urllib.parse import parse_qs, urlparse

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
}


def is_supported_youtube_url(url: str) -> bool:
    """Check if a URL points to a public YouTube video or Short."""
    try:
        parsed = urlparse(url)
    except (ValueError, UnicodeError):
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in YOUTUBE_HOSTS:
        return False

    if host == "youtu.be":
        path = parsed.path.strip("/")
        return bool(path and re.fullmatch(r"[A-Za-z0-9_-]{6,}", path))

    path = parsed.path.rstrip("/")
    if bool(re.fullmatch(r"/shorts/[A-Za-z0-9_-]+", path)) or bool(re.fullmatch(r"/(?:embed|v)/[A-Za-z0-9_-]+", path)):
        return True

    if path in {"/watch", "/watch/"}:
        qs = parse_qs(parsed.query)
        video_ids = qs.get("v")
        return bool(video_ids and re.fullmatch(r"[A-Za-z0-9_-]{6,}", video_ids[0]))

    return False


def extract_youtube_video_id(url: str) -> str | None:
    """Extract YouTube video identifier from Short, Watch, or youtu.be URL."""
    try:
        parsed = urlparse(url)
    except (ValueError, UnicodeError):
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if host == "youtu.be":
        path = parsed.path.strip("/")
        if path:
            return path.split("/")[0].split("?")[0]
        return None
    if host in YOUTUBE_HOSTS:
        path = parsed.path.rstrip("/")
        for prefix in ("/shorts/", "/embed/", "/v/"):
            if path.startswith(prefix):
                parts = path.split(prefix)[1].split("/")
                return parts[0].split("?")[0] if parts else None
        qs = parse_qs(parsed.query)
        v = qs.get("v")
        if v and v[0]:
            return v[0]
    return None

