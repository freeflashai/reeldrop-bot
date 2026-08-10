"""Permitted YouTube video handler; no access-control or DRM bypass."""
from . import detect_platform, download_video

def can_handle(url): return detect_platform(url) == "youtube"
def download(url, quality_limit, temp_dir, user_id): return download_video(url, "youtube", quality_limit, temp_dir, user_id)
