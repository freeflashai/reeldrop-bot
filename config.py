"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_BASE_URL = (
    os.getenv("WEBHOOK_BASE_URL", "").strip()
    or os.getenv("RENDER_EXTERNAL_URL", "").strip()
).rstrip("/")
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
TEMP_DIR = BASE_DIR / "temp"
DATABASE_PATH = BASE_DIR / "reeldrop.db"
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

MAX_DOWNLOADS_PER_HOUR = int(os.getenv("MAX_DOWNLOADS_PER_HOUR", "10"))
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3"))
# Kept as deprecated compatibility settings. Download-count limits are disabled.
FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", "0"))
PRO_DAILY_SOFT_LIMIT = int(os.getenv("PRO_DAILY_SOFT_LIMIT", "0"))
PRO_PRICE_STARS = int(os.getenv("PRO_PRICE_STARS", "25"))
PRO_DURATION_DAYS = int(os.getenv("PRO_DURATION_DAYS", "30"))
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0") or 0)
# Channel username (for example: @mychannel) or numeric chat ID (-100...).
# Leave empty to disable the mandatory channel-membership check.
_required_channel_id = os.getenv("REQUIRED_CHANNEL_ID", "").strip()
REQUIRED_CHANNEL_ID = int(_required_channel_id) if _required_channel_id.lstrip("-").isdigit() else _required_channel_id
REQUIRED_CHANNEL_URL = os.getenv("REQUIRED_CHANNEL_URL", "").strip()
MAX_TELEGRAM_FILE_SIZE_MB = int(os.getenv("MAX_TELEGRAM_FILE_SIZE_MB", "49"))
MAX_TELEGRAM_FILE_SIZE_BYTES = MAX_TELEGRAM_FILE_SIZE_MB * 1024 * 1024
TEMP_FILE_MAX_AGE_HOURS = int(os.getenv("TEMP_FILE_MAX_AGE_HOURS", "24"))
COOKIE_FILE = BASE_DIR / "cookies.txt"
YOUTUBE_COOKIES = os.getenv("YOUTUBE_COOKIES", "").strip()
if YOUTUBE_COOKIES:
    COOKIE_FILE.write_text(YOUTUBE_COOKIES, encoding="utf-8")

YOUTUBE_PROXY = os.getenv("YOUTUBE_PROXY", "").strip()

WEB_DOWNLOADER_URL = os.getenv("WEB_DOWNLOADER_URL", "https://reel-drop-downloder.web.app").strip().rstrip("/")



