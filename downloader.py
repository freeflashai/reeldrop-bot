"""Instagram URL validation, yt-dlp download logic, and temporary-file cleanup."""

import logging
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import yt_dlp
from yt_dlp.utils import DownloadError


logger = logging.getLogger(__name__)

INSTAGRAM_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:reel|reels|p)/[A-Za-z0-9_-]+/?(?:\?[^\s]*)?",
    re.IGNORECASE,
)


class ReelDownloadError(Exception):
    """Base error for a download that could not be completed."""


class PrivateOrInaccessibleError(ReelDownloadError):
    pass


class VideoUnavailableError(ReelDownloadError):
    pass


class UnsupportedInstagramUrlError(ReelDownloadError):
    pass


def extract_instagram_url(text: str) -> str | None:
    match = INSTAGRAM_URL_PATTERN.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,);]}")


def is_supported_instagram_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or hostname not in {
        "instagram.com",
        "www.instagram.com",
    }:
        return False
    return bool(re.fullmatch(r"/(?:reel|reels|p)/[A-Za-z0-9_-]+/?", parsed.path))


def download_instagram_video(url: str, temp_root: Path, user_id: int) -> tuple[Path, Path]:
    if not is_supported_instagram_url(url):
        raise UnsupportedInstagramUrlError("Unsupported Instagram URL")

    request_dir = temp_root / f"{user_id}_{uuid4().hex}"
    request_dir.mkdir(parents=True, exist_ok=False)
    output_template = str(request_dir / "video.%(ext)s")
    options = {
        "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "overwrites": True,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            requested = info.get("requested_downloads") or []
            candidates = [Path(item["filepath"]) for item in requested if item.get("filepath")]
            prepared = Path(ydl.prepare_filename(info))
            candidates.extend([prepared.with_suffix(".mp4"), prepared])

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate, request_dir

        files = [path for path in request_dir.iterdir() if path.is_file()]
        if files:
            return max(files, key=lambda path: path.stat().st_size), request_dir
        raise ReelDownloadError("yt-dlp completed without producing a file")
    except DownloadError as error:
        delete_request_files(request_dir)
        message = str(error).lower()
        if any(term in message for term in ("private", "login required", "not authorized", "restricted")):
            raise PrivateOrInaccessibleError(str(error)) from error
        if any(term in message for term in ("not available", "unavailable", "removed", "does not exist")):
            raise VideoUnavailableError(str(error)) from error
        raise ReelDownloadError(str(error)) from error
    except ReelDownloadError:
        delete_request_files(request_dir)
        raise
    except Exception as error:
        delete_request_files(request_dir)
        raise ReelDownloadError(str(error)) from error


def delete_request_files(request_dir: Path | None) -> None:
    if request_dir and request_dir.exists():
        shutil.rmtree(request_dir, ignore_errors=True)
        logger.info("Temporary file deleted: %s", request_dir.name)


def cleanup_old_temp_files(temp_root: Path, max_age_hours: int) -> None:
    temp_root.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - max_age_hours * 3600
    for item in temp_root.iterdir():
        try:
            if item.stat().st_mtime >= cutoff:
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
            logger.info("Old temporary item deleted: %s", item.name)
        except OSError:
            logger.exception("Could not clean temporary item: %s", item)
