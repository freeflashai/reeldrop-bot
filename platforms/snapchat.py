"""Snapchat URL validation and parsing helpers."""

import re
from urllib.parse import urlparse

SNAPCHAT_HOSTS = {
    "snapchat.com",
    "www.snapchat.com",
    "story.snapchat.com",
}


def is_supported_snapchat_url(url: str) -> bool:
    """Check if a URL points to a public Snapchat Spotlight, story, or clip."""
    try:
        parsed = urlparse(url)
    except (ValueError, UnicodeError):
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in SNAPCHAT_HOSTS:
        return False

    path = parsed.path.rstrip("/")
    return bool(re.fullmatch(
        r"/(?:spotlight|p|t)/[A-Za-z0-9_-]+|"
        r"/add/[A-Za-z0-9._-]+/story/[A-Za-z0-9_-]+|"
        r"/(?:s|o)/[A-Za-z0-9_-]+",
        path,
    ))
