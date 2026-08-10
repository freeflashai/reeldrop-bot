"""Public Facebook video handler."""
from . import detect_platform, download_video

def can_handle(url): return detect_platform(url) == "facebook"
def download(url, quality_limit, temp_dir, user_id): return download_video(url, "facebook", quality_limit, temp_dir, user_id)
