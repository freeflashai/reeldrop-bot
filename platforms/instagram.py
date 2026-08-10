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
        and bool(re.fullmatch(
            r"/(?:reel|reels|p|tv)/[A-Za-z0-9_-]+/?|/stories/[A-Za-z0-9._-]+/[0-9]+/?|/[A-Za-z0-9._-]+/live/?",
            parsed.path,
        ))
    )


def extract_instagram_url(text: str) -> str | None:
    match = re.search(
        r"https?://(?:www\.)?instagram\.com/(?:"
        r"(?:reel|reels|p|tv)/[A-Za-z0-9_-]+|"
        r"stories/[A-Za-z0-9._-]+/[0-9]+|"
        r"[A-Za-z0-9._-]+/live"
        r")/?(?:\?[^\s]*)?",
        text,
        re.I,
    )
    return match.group(0).rstrip(".,);]}") if match else None
