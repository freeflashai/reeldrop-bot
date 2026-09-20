"""Compatibility facade for platform detection, downloads, and temp cleanup."""

from platforms import (  # noqa: F401
    DownloadResult,
    MediaCollectionResult,
    PrivateOrInaccessibleError,
    ReelDownloadError,
    UnsupportedUrlError,
    VideoUnavailableError,
    cleanup_old_temp_files,
    delete_request_files,
    detect_platform,
    download_audio,
    download_media_collection,
    download_video,
    extract_url,
    get_metadata,
    is_supported_url,
)
from platforms.facebook import is_supported_facebook_url
from platforms.instagram import extract_instagram_url, is_supported_instagram_url
from platforms.snapchat import is_supported_snapchat_url



class UnsupportedInstagramUrlError(UnsupportedUrlError):
    """Backwards-compatible exception name."""


def download_instagram_video(url, temp_root, user_id):
    """Backwards-compatible Instagram-only entry point (720p)."""
    if detect_platform(url) != "instagram" or not is_supported_instagram_url(url):
        raise UnsupportedInstagramUrlError("Unsupported Instagram URL")
    result = download_video(url, "instagram", 720, temp_root, user_id)
    return result.path, result.request_dir
