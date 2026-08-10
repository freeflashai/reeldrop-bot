"""Telegram handlers and application entry point for ReelDrop Bot."""

import asyncio
import logging

from telegram import Update
from telegram.error import BadRequest, NetworkError, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import config
from database import Database, PLATFORMS
from downloader import (PrivateOrInaccessibleError, ReelDownloadError,
                        UnsupportedUrlError, VideoUnavailableError,
                        cleanup_old_temp_files, delete_request_files, detect_platform, download_audio, download_video, extract_url)
from platforms.instagram import is_supported_instagram_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.request").setLevel(logging.WARNING)
database = Database(config.DATABASE_PATH)
download_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_DOWNLOADS)

WELCOME_TEXT = """👋 Welcome to ReelDrop

📸 Instagram

🎬 Reels & video posts
📖 Public Stories
🔴 Public Live videos

🎵 /audio <link> — MP3 nikalein
⚙️ /quality 360|480|720|1080

🔗 Bas supported video link bhejo.
🎬 Best available quality me video directly Telegram par pao.

✅ Free to start
🔒 Simple & privacy-conscious
⚡ Fast processing
📱 Directly on Telegram

Private, login-required ya restricted content process nahi hota.

Just paste the link 👇"""
PLATFORM_NAMES = {name: name.title() for name in PLATFORMS}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user:
        await asyncio.to_thread(database.ensure_user, update.effective_user.id)
    if update.message:
        await update.message.reply_text(WELCOME_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("Public Instagram Reel, video post, Story ya Live link bhejein. Bot free aur unlimited hai. Private, login-required, expired Story, ended/unavailable Live ya restricted content process nahi hota.")


async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("✅ ReelDrop ab sabke liye bilkul free aur unlimited hai. Bas supported video link bhejein.")


async def quality_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not context.args:
        current = await asyncio.to_thread(database.get_video_quality, update.effective_user.id)
        await update.message.reply_text(f"🎬 Current quality: up to {current}p\n\nSet karein: /quality 360, 480, 720 ya 1080")
        return
    try:
        quality = int(context.args[0].lower().removesuffix("p"))
        await asyncio.to_thread(database.set_video_quality, update.effective_user.id, quality)
    except (ValueError, TypeError):
        await update.message.reply_text("❌ Quality 360, 480, 720 ya 1080 mein se choose karein.")
        return
    await update.message.reply_text(f"✅ Video quality up to {quality}p set ho gayi.")


async def audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    url = extract_url(" ".join(context.args))
    if not url or detect_platform(url) != "instagram" or not is_supported_instagram_url(url):
        await update.message.reply_text("❌ Use: /audio <supported Instagram link>")
        return
    status = await update.message.reply_text("🎵 Audio extract ho rahi hai...")
    request_dir = None
    try:
        async with download_semaphore:
            result = await asyncio.to_thread(download_audio, url, "instagram", config.TEMP_DIR, user_id)
            request_dir = result.request_dir
        if result.path.stat().st_size > config.MAX_TELEGRAM_FILE_SIZE_BYTES:
            raise ReelDownloadError("Telegram file size limit exceeded")
        await status.edit_text("📤 Telegram par upload ho rahi hai...")
        with result.path.open("rb") as audio_file:
            await update.message.reply_audio(audio=audio_file, title=result.title or "Instagram Audio", caption="✅ Audio Download Complete\n\n🎵 ReelDrop", read_timeout=120, write_timeout=120, connect_timeout=30, pool_timeout=30)
        await asyncio.to_thread(database.record_download, user_id, "success", "instagram", None, "free")
        try: await status.delete()
        except BadRequest: pass
    except PrivateOrInaccessibleError:
        await asyncio.to_thread(database.record_download, user_id, "failed", "instagram", None, "free")
        await status.edit_text("🔒 Ye content private, restricted ya inaccessible lag raha hai.")
    except VideoUnavailableError:
        await asyncio.to_thread(database.record_download, user_id, "failed", "instagram", None, "free")
        await status.edit_text("❌ Video available nahi hai ya remove ho chuki hai.")
    except (NetworkError, TelegramError, ReelDownloadError, UnsupportedUrlError):
        logger.exception("Audio processing failed for user %s", user_id)
        await asyncio.to_thread(database.record_download, user_id, "failed", "instagram", None, "free")
        try: await status.edit_text("⚠️ Audio extract nahi ho payi. Thodi der baad dobara try karein.")
        except TelegramError: pass
    finally:
        await asyncio.to_thread(delete_request_files, request_dir)


def _is_admin(update: Update) -> bool:
    return bool(update.effective_user and config.ADMIN_TELEGRAM_ID and update.effective_user.id == config.ADMIN_TELEGRAM_ID)


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not _is_admin(update):
        return
    total, today, pro, free, breakdown = await asyncio.to_thread(database.admin_stats)
    lines = ["📊 ReelDrop Admin", "", f"Total Successful Downloads: {total}", f"Downloads Today: {today}", f"Registered Users: {pro + free}", "Plan: Free (Unlimited)", "", "Platform Breakdown:"]
    lines += [f"Instagram: {breakdown.get('instagram', 0)}"]
    await update.message.reply_text("\n".join(lines))


async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    total, breakdown = await asyncio.to_thread(database.user_stats, user_id)
    quality = await asyncio.to_thread(database.get_video_quality, user_id)
    lines = ["📊 Your ReelDrop Stats", "", "Plan: Free (Unlimited)", f"Total Downloads: {total}", ""]
    lines += [f"Instagram: {breakdown.get('instagram', 0)}"]
    lines += ["", "Download limit: Unlimited", f"Video quality: Up to {quality}p"]
    await update.message.reply_text("\n".join(lines))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    url = extract_url(update.message.text or "")
    platform = detect_platform(url) if url else "unsupported"
    if platform != "instagram" or not is_supported_instagram_url(url):
        await update.message.reply_text("❌ Sirf supported Instagram Reel, Post, Story ya Live link bhejein.")
        return
    plan = "free"
    quality = await asyncio.to_thread(database.get_video_quality, user_id)
    status = await update.message.reply_text(f"🔍 Platform detected: {PLATFORM_NAMES[platform]}\n\n⏳ Video process ho rahi hai...")
    request_dir = None
    try:
        async with download_semaphore:
            result = await asyncio.to_thread(download_video, url, platform, quality, config.TEMP_DIR, user_id)
            request_dir = result.request_dir
        if result.path.stat().st_size > config.MAX_TELEGRAM_FILE_SIZE_BYTES:
            raise ReelDownloadError("Telegram file size limit exceeded")
        await status.edit_text("📤 Telegram par upload ho raha hai...")
        with result.path.open("rb") as video_file:
            await update.message.reply_video(video=video_file, caption=f"✅ Download Complete\n\n🎬 Platform: {PLATFORM_NAMES[platform]}\n⚡ ReelDrop", supports_streaming=True, read_timeout=120, write_timeout=120, connect_timeout=30, pool_timeout=30)
        await asyncio.to_thread(database.record_download, user_id, "success", platform, quality, plan)
        try: await status.delete()
        except BadRequest: pass
    except PrivateOrInaccessibleError:
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        await status.edit_text("🔒 Ye content private, restricted ya inaccessible lag raha hai.")
    except VideoUnavailableError:
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        await status.edit_text("❌ Video available nahi hai ya remove ho chuki hai.")
    except (NetworkError, TelegramError, ReelDownloadError, UnsupportedUrlError):
        logger.exception("Processing failed for user %s on %s", user_id, platform)
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        try: await status.edit_text("⚠️ Video process nahi ho payi. Thodi der baad dobara try karein.")
        except TelegramError: pass
    except Exception:
        logger.exception("Unexpected processing failure for user %s", user_id)
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        try: await status.edit_text("⚠️ Video process nahi ho payi. Thodi der baad dobara try karein.")
        except TelegramError: pass
    finally:
        await asyncio.to_thread(delete_request_files, request_dir)


async def error_handler(update, context): logger.error("Unhandled Telegram update error", exc_info=context.error)


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    database.initialize()
    cleanup_old_temp_files(config.TEMP_DIR, config.TEMP_FILE_MAX_AGE_HOURS)
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    for command, callback in (("start", start), ("help", help_command), ("stats", mystats), ("mystats", mystats), ("upgrade", upgrade), ("quality", quality_command), ("audio", audio_command), ("admin", admin)):
        app.add_handler(CommandHandler(command, callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    if config.WEBHOOK_BASE_URL:
        app.run_webhook(listen="0.0.0.0", port=config.PORT, url_path="telegram-webhook", webhook_url=f"{config.WEBHOOK_BASE_URL}/telegram-webhook", secret_token=config.WEBHOOK_SECRET_TOKEN or None, allowed_updates=Update.ALL_TYPES)
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__": main()
