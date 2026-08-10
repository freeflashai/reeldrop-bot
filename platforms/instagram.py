"""Instagram URL helpers retained for compatibility."""

import re
from urllib.parse import urlparse


def is_supported_instagram_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").lower() in {"instagram.com", "www.instagram.com"}
        and bool(re.fullmatch(r"/(?:reel|reels|p)/[A-Za-z0-9_-]+/?", parsed.path))
    )


def extract_instagram_url(text: str) -> str | None:
    match = re.search(r"https?://(?:www\.)?instagram\.com/(?:reel|reels|p)/[A-Za-z0-9_-]+/?(?:\?[^\s]*)?", text, re.I)
    return match.group(0).rstrip(".,);]}") if match else None
