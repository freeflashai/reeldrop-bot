"""Shared multi-platform downloader API."""

import logging
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import yt_dlp
from yt_dlp.utils import DownloadError

logger = logging.getLogger(__name__)

PLATFORM_HOSTS = {
    "instagram": {"instagram.com", "www.instagram.com"},
    "facebook": {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.watch", "www.fb.watch"},
    "snapchat": {"snapchat.com", "www.snapchat.com"},
    "youtube": {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"},
}


class ReelDownloadError(Exception):
    pass


class UnsupportedUrlError(ReelDownloadError):
    pass


class PrivateOrInaccessibleError(ReelDownloadError):
    pass


class VideoUnavailableError(ReelDownloadError):
    pass


class YouTubeNotPermittedError(ReelDownloadError):
    pass


class SnapchatUnsupportedError(ReelDownloadError):
    pass


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    request_dir: Path
    title: str | None = None


def _safe_parsed_url(url: str):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith(".localhost"):
            return None
        return parsed
    except (ValueError, UnicodeError):
        return None


def detect_platform(url: str) -> str:
    parsed = _safe_parsed_url(url)
    if not parsed:
        return "unsupported"
    host = parsed.hostname.lower().rstrip(".")
    for platform, hosts in PLATFORM_HOSTS.items():
        if host in hosts:
            return platform
    return "unsupported"


def extract_url(text: str) -> str | None:
    for candidate in re.findall(r"https?://[^\s<>]+", text, flags=re.IGNORECASE):
        cleaned = candidate.rstrip(".,);]}>'\"")
        if _safe_parsed_url(cleaned):
            return cleaned
    return None


def _classify_error(error: DownloadError, platform: str):
    message = str(error).lower()
    if platform == "youtube" and any(x in message for x in ("sign in", "age-restricted", "copyright", "drm", "members-only")):
        return YouTubeNotPermittedError(str(error))
    if platform == "snapchat" and any(x in message for x in ("unsupported url", "no video formats")):
        return SnapchatUnsupportedError(str(error))
    if "requested format is not available" in message:
        return ReelDownloadError(str(error))
    if any(x in message for x in ("private", "login required", "not authorized", "restricted", "sign in")):
        return PrivateOrInaccessibleError(str(error))
    if any(x in message for x in ("not available", "unavailable", "removed", "does not exist", "404")):
        return VideoUnavailableError(str(error))
    return ReelDownloadError(str(error))


def download_video(url: str, platform: str, quality_limit: int, temp_root: Path, user_id: int) -> DownloadResult:
    if platform not in PLATFORM_HOSTS or detect_platform(url) != platform:
        raise UnsupportedUrlError("Unsupported URL")
    request_dir = temp_root / str(user_id) / uuid4().hex
    request_dir.mkdir(parents=True, exist_ok=False)
    options = {
        # Some direct-video extractors (notably Snapchat) omit height metadata.
        # Prefer the capped formats, then fall back to their original MP4/source.
        "format": f"bestvideo[height<={quality_limit}][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality_limit}][ext=mp4]/best[height<={quality_limit}]/best[ext=mp4]/best",
        "outtmpl": str(request_dir / "video.%(ext)s"),
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
            candidates = [Path(x["filepath"]) for x in (info.get("requested_downloads") or []) if x.get("filepath")]
            prepared = Path(ydl.prepare_filename(info))
            candidates += [prepared.with_suffix(".mp4"), prepared]
        candidates += list(request_dir.glob("*"))
        files = [path for path in candidates if path.is_file()]
        if not files:
            raise ReelDownloadError("Downloader produced no file")
        return DownloadResult(max(files, key=lambda path: path.stat().st_size), request_dir, info.get("title"))
    except DownloadError as error:
        delete_request_files(request_dir)
        raise _classify_error(error, platform) from error
    except ReelDownloadError:
        delete_request_files(request_dir)
        raise
    except Exception as error:
        delete_request_files(request_dir)
        raise ReelDownloadError(str(error)) from error


def delete_request_files(request_dir: Path | None) -> None:
    if request_dir and request_dir.exists():
        shutil.rmtree(request_dir, ignore_errors=True)
        parent = request_dir.parent
        try:
            parent.rmdir()
        except OSError:
            pass


def cleanup_old_temp_files(temp_root: Path, max_age_hours: int) -> None:
    temp_root.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - max_age_hours * 3600
    for item in temp_root.rglob("*"):
        try:
            if item.is_file() and item.stat().st_mtime < cutoff:
                item.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not clean temporary item: %s", item.name)
    for item in sorted((p for p in temp_root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            if not any(item.iterdir()):
                item.rmdir()
        except OSError:
            pass
