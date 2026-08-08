"""Telegram handlers and application entry point for ReelDrop Bot."""

import asyncio
import logging

from telegram import Update
from telegram.error import BadRequest, NetworkError, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import config
from database import Database
from downloader import (
    PrivateOrInaccessibleError,
    ReelDownloadError,
    UnsupportedInstagramUrlError,
    VideoUnavailableError,
    cleanup_old_temp_files,
    delete_request_files,
    download_instagram_video,
    extract_instagram_url,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
# HTTPX request URLs contain the Telegram bot token, so never log them at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.request").setLevel(logging.WARNING)
database = Database(config.DATABASE_PATH)
download_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_DOWNLOADS)

WELCOME_TEXT = (
    "👋 Welcome to ReelDrop\n\n"
    "Instagram Reel ya public video ka link bhejo.\n\n"
    "Main best available quality up to 720p me video download karke yahin bhej dunga.\n\n"
    "Just paste the link 👇"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user:
        await asyncio.to_thread(database.ensure_user, update.effective_user.id)
    if update.message:
        await update.message.reply_text(WELCOME_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Public Instagram Reel ya video post ka link bhejo.\n\n"
            "Supported links:\n"
            "• instagram.com/reel/...\n"
            "• instagram.com/reels/...\n"
            "• instagram.com/p/...\n\n"
            "Private, deleted, login-required, ya protected videos download nahi hongi."
        )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    total, user_total, failed = await asyncio.to_thread(database.get_stats, update.effective_user.id)
    await update.message.reply_text(
        f"📊 ReelDrop Stats\n\n"
        f"Total successful downloads: {total}\n"
        f"Aapke successful downloads: {user_total}\n"
        f"Failed downloads: {failed}"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    text = update.message.text or ""
    url = extract_instagram_url(text)
    logger.info("Telegram user ID: %s", user_id)

    if not url:
        await update.message.reply_text("❌ Valid Instagram Reel/Post link bhejo.")
        return

    used = await asyncio.to_thread(database.successful_downloads_last_hour, user_id)
    if used >= config.MAX_DOWNLOADS_PER_HOUR:
        await update.message.reply_text("⏳ Aapne hourly limit reach kar li hai. Thodi der baad try karein.")
        return

    status_message = await update.message.reply_text("⏳ Reel process ho rahi hai...")
    request_dir = None
    try:
        async with download_semaphore:
            logger.info("Download started for Telegram user ID: %s", user_id)
            video_path, request_dir = await asyncio.to_thread(
                download_instagram_video, url, config.TEMP_DIR, user_id
            )
            logger.info("Download completed for Telegram user ID: %s", user_id)

        if video_path.stat().st_size > config.MAX_TELEGRAM_FILE_SIZE_BYTES:
            await asyncio.to_thread(database.record_download, user_id, "failed")
            await status_message.edit_text(
                f"⚠️ Video {config.MAX_TELEGRAM_FILE_SIZE_MB} MB se badi hai, isliye Telegram par send nahi ho sakti."
            )
            return

        await status_message.edit_text("📤 Telegram par upload ho raha hai...")
        logger.info("Upload started for Telegram user ID: %s", user_id)
        with video_path.open("rb") as video_file:
            await update.message.reply_video(
                video=video_file,
                caption="✅ Download complete\n🎬 ReelDrop Bot",
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=30,
                pool_timeout=30,
            )
        await asyncio.to_thread(database.record_download, user_id, "success")
        logger.info("Upload completed for Telegram user ID: %s", user_id)
        try:
            await status_message.delete()
        except BadRequest:
            logger.warning("Could not delete status message for user %s", user_id)
    except PrivateOrInaccessibleError:
        logger.exception("Private or inaccessible video for user %s", user_id)
        await asyncio.to_thread(database.record_download, user_id, "failed")
        await status_message.edit_text("🔒 Ye Reel private ya inaccessible lag rahi hai.")
    except VideoUnavailableError:
        logger.exception("Unavailable video for user %s", user_id)
        await asyncio.to_thread(database.record_download, user_id, "failed")
        await status_message.edit_text("❌ Video available nahi hai ya remove ho chuki hai.")
    except UnsupportedInstagramUrlError:
        logger.exception("Unsupported URL for user %s", user_id)
        await status_message.edit_text("❌ Ye supported Instagram Reel/Post link nahi hai.")
    except (NetworkError, TelegramError):
        logger.exception("Telegram upload error for user %s", user_id)
        await asyncio.to_thread(database.record_download, user_id, "failed")
        try:
            await status_message.edit_text("⚠️ Telegram upload fail ho gaya. Thodi der baad dobara try karo.")
        except TelegramError:
            pass
    except ReelDownloadError:
        logger.exception("Download error for user %s", user_id)
        await asyncio.to_thread(database.record_download, user_id, "failed")
        await status_message.edit_text("⚠️ Video download nahi ho payi. Thodi der baad dobara try karo.")
    except Exception:
        logger.exception("Unexpected error for user %s", user_id)
        await asyncio.to_thread(database.record_download, user_id, "failed")
        try:
            await status_message.edit_text("⚠️ Video download nahi ho payi. Thodi der baad dobara try karo.")
        except TelegramError:
            pass
    finally:
        await asyncio.to_thread(delete_request_files, request_dir)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled Telegram update error", exc_info=context.error)


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and add your token.")

    database.initialize()
    cleanup_old_temp_files(config.TEMP_DIR, config.TEMP_FILE_MAX_AGE_HOURS)

    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    logger.info("Bot started")
    if config.WEBHOOK_BASE_URL:
        webhook_path = "telegram-webhook"
        logger.info("Starting in webhook mode")
        application.run_webhook(
            listen="0.0.0.0",
            port=config.PORT,
            url_path=webhook_path,
            webhook_url=f"{config.WEBHOOK_BASE_URL}/{webhook_path}",
            secret_token=config.WEBHOOK_SECRET_TOKEN or None,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Starting in local polling mode")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
