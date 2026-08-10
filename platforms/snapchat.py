"""Public/authorized Snapchat video handler; no authentication bypass."""
from . import detect_platform, download_video

def can_handle(url): return detect_platform(url) == "snapchat"
def download(url, quality_limit, temp_dir, user_id): return download_video(url, "snapchat", quality_limit, temp_dir, user_id)
