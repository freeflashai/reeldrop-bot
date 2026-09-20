"""Telegram handlers and application entry point for ReelDrop Bot."""

import asyncio
import hashlib
import logging
from urllib.parse import parse_qs, urlsplit, urlunsplit


from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import config
from database import Database, PLATFORMS
from downloader import (PrivateOrInaccessibleError, ReelDownloadError,
                        UnsupportedUrlError, VideoUnavailableError,
                        cleanup_old_temp_files, delete_request_files, detect_platform, download_audio,
                        download_media_collection, extract_url, extract_youtube_video_id, get_metadata, is_supported_url)


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.request").setLevel(logging.WARNING)
database = Database(config.DATABASE_PATH)
download_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_DOWNLOADS)

PLATFORM_NAMES = {
    "instagram": "Instagram",
    "youtube": "YouTube",
    "facebook": "Facebook",
    "snapchat": "Snapchat",
}

WELCOME_TEXT = """👋 Welcome to ReelDrop

📸 Instagram · 🔴 YouTube · 👥 Facebook · 👻 Snapchat

🎬 Instagram Reels, Video posts, Stories & Live
🔴 YouTube Shorts & Videos (360p, 480p, 720p, 1080p & MP3)
👥 Facebook Reels & Watch videos
👻 Snapchat Spotlight & Stories


🎵 /audio <link> — MP3 nikalein
⚙️ /quality 360|480|720|1080

🔗 Bas supported video link bhejo.
🎬 Best available quality me video directly Telegram par pao.

✅ Free to use & Unlimited
🔒 Simple & privacy-conscious
⚡ Fast processing
📱 Directly on Telegram

Private, login-required ya restricted content process nahi hota.

Just paste the link 👇"""


def _has_channel_access(member) -> bool:
    """Return whether a getChatMember result represents a current member."""
    status = getattr(member, "status", "")
    return status in {"creator", "administrator", "member"} or (
        status == "restricted" and bool(getattr(member, "is_member", False))
    )


def _join_keyboard() -> InlineKeyboardMarkup | None:
    if not config.REQUIRED_CHANNEL_URL:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=config.REQUIRED_CHANNEL_URL)]])


async def _require_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Gate downloads behind membership of the configured Telegram channel."""
    if not config.REQUIRED_CHANNEL_ID or not update.effective_user:
        return True
    try:
        member = await context.bot.get_chat_member(config.REQUIRED_CHANNEL_ID, update.effective_user.id)
        if _has_channel_access(member):
            return True
    except (BadRequest, Forbidden):
        logger.exception(
            "Channel membership check failed. Ensure the bot is an admin in %s",
            config.REQUIRED_CHANNEL_ID,
        )
        await update.effective_message.reply_text(
            "⚠️ Membership verify nahi ho pa rahi. Bot admin se contact karein."
        )
        return False
    await update.effective_message.reply_text(
        "🔒 Video download karne ke liye pehle hamara channel join karein, phir link dobara bhejein.",
        reply_markup=_join_keyboard(),
    )
    return False


def _cache_key(url: str, media_kind: str) -> str:
    parsed = urlsplit(url)
    query = ""
    if parsed.query:
        qs = parse_qs(parsed.query)
        if "v" in qs:
            query = f"v={qs['v'][0]}"
    normalized = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), query, ""))
    return hashlib.sha256(f"{normalized}|{media_kind}".encode()).hexdigest()


async def _send_cached(message, cached: list[dict], caption: str) -> bool:
    try:
        for index, item in enumerate(cached):
            item_caption = caption if index == 0 else None
            if item["file_type"] == "video":
                await message.reply_video(video=item["telegram_file_id"], caption=item_caption, supports_streaming=True)
            elif item["file_type"] == "photo":
                await message.reply_photo(photo=item["telegram_file_id"], caption=item_caption)
            elif item["file_type"] == "audio":
                await message.reply_audio(audio=item["telegram_file_id"], caption=item_caption, title=item.get("title") or "Audio")
            else:
                await message.reply_document(document=item["telegram_file_id"], caption=item_caption)
        return bool(cached)
    except TelegramError:
        logger.warning("Cached Telegram file_id was rejected; refreshing media")
        return False


def _telegram_file_id(sent, file_type: str) -> str:
    if file_type == "video": return sent.video.file_id
    if file_type == "photo": return sent.photo[-1].file_id
    if file_type == "audio": return sent.audio.file_id
    return sent.document.file_id


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user:
        await asyncio.to_thread(database.ensure_user, update.effective_user.id)
    if update.message:
        await update.message.reply_text(WELCOME_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Supported platforms: Instagram, YouTube, Facebook, Snapchat.\n\n"
            "• Instagram: Reels, video posts, Stories, Live\n"
            "• YouTube: Shorts & standard videos\n"
            "• Facebook: Reels, Watch & video posts\n"
            "• Snapchat: Spotlight & Stories\n\n"
            "Bas supported link bhejein. Bot bilkul free aur unlimited hai.\n"
            "Private, login-required ya restricted content process nahi hota."
        )


async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text("✅ ReelDrop sabke liye bilkul free aur unlimited hai. Bas supported video link bhejein.")


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
    message = update.effective_message
    if not message or not update.effective_user:
        return
    if not await _require_channel_membership(update, context):
        return
    user_id = update.effective_user.id
    url = context.user_data.pop("selected_url", None) or extract_url(" ".join(context.args))
    if not url:
        await message.reply_text("❌ Use: /audio <supported link (Instagram, YouTube, Facebook, Snapchat)>")
        return
    is_valid, platform = is_supported_url(url)
    if not is_valid:
        await message.reply_text("❌ Use: /audio <supported link (Instagram, YouTube, Facebook, Snapchat)>")
        return
    platform_name = PLATFORM_NAMES.get(platform, platform.title())
    if platform == "youtube":
        video_id = extract_youtube_video_id(url)
        if not video_id:
            await message.reply_text("❌ YouTube video ID pehchan nahi paya. Kripya valid YouTube video ya Short link bhejein.")
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 ReelDrop Web (1-Click MP3)", url=f"{config.WEB_DOWNLOADER_URL}/?v={video_id}&f=mp3")],
        ])
        await message.reply_html(
            "🎵 <b>YouTube Audio (MP3)</b>\n\n"
            "Hamari official ReelDrop website se 1-Click me MP3 download karein:\n\n"
            f"📋 <b>Video:</b> <code>https://www.youtube.com/watch?v={video_id}</code>\n\n"
            "👇 <b>Niche click karein:</b>",
            reply_markup=keyboard,
        )
        await asyncio.to_thread(database.record_download, user_id, "success", "youtube", None, "free")
        return

    cache_key = _cache_key(url, "audio:mp3:192")

    cached = await asyncio.to_thread(database.get_cached_media, cache_key)
    if cached and await _send_cached(message, cached, f"✅ Audio Download Complete\n\n🎵 {platform_name} Audio · instant cache"):
        await asyncio.to_thread(database.record_download, user_id, "success", platform, None, "free")
        return
    status = await message.reply_text(f"🎵 {platform_name} audio extract ho rahi hai...")
    request_dir = None
    try:
        async with download_semaphore:
            result = await asyncio.to_thread(download_audio, url, platform, config.TEMP_DIR, user_id)
            request_dir = result.request_dir
        if result.path.stat().st_size > config.MAX_TELEGRAM_FILE_SIZE_BYTES:
            size_mb = round(result.path.stat().st_size / (1024 * 1024), 1)
            raise ReelDownloadError(f"Audio file size ({size_mb}MB) Telegram limit (50MB) se badi hai.")
        await status.edit_text("📤 Telegram par upload ho rahi hai...")
        with result.path.open("rb") as audio_file:
            sent = await message.reply_audio(
                audio=audio_file,
                title=result.title or f"{platform_name} Audio",
                caption=f"✅ Audio Download Complete\n\n🎵 {platform_name} Audio · ReelDrop",
                read_timeout=120,
                write_timeout=120,
                connect_timeout=30,
                pool_timeout=30,
            )
        await asyncio.to_thread(database.replace_cached_media, cache_key, [(_telegram_file_id(sent, "audio"), "audio", result.title)])
        await asyncio.to_thread(database.record_download, user_id, "success", platform, None, "free")
        try: await status.delete()
        except BadRequest: pass
    except PrivateOrInaccessibleError:
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, None, "free")
        await status.edit_text("🔒 Ye content private, restricted ya inaccessible lag raha hai.")
    except VideoUnavailableError:
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, None, "free")
        await status.edit_text("❌ Video available nahi hai ya remove ho chuki hai.")
    except ReelDownloadError as error:
        logger.exception("Audio download failed for user %s on %s: %s", user_id, platform, error)
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, None, "free")
        try: await status.edit_text(f"⚠️ {str(error)}")
        except TelegramError: pass
    except (NetworkError, TelegramError):
        logger.exception("Audio upload failed for user %s on %s", user_id, platform)
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, None, "free")
        try: await status.edit_text("⚠️ Audio upload timeout ho gaya. Kripya dobara try karein.")
        except TelegramError: pass
    except Exception as error:
        logger.exception("Unexpected audio failure for user %s on %s", user_id, platform)
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, None, "free")
        try: await status.edit_text(f"⚠️ Audio extract nahi ho payi: {str(error)[:100]}")
        except TelegramError: pass
    finally:
        await asyncio.to_thread(delete_request_files, request_dir)


def _is_admin(update: Update) -> bool:
    return bool(update.effective_user and config.ADMIN_TELEGRAM_ID and update.effective_user.id == config.ADMIN_TELEGRAM_ID)


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not _is_admin(update):
        return
    total, today, pro, free, breakdown = await asyncio.to_thread(database.admin_stats)
    lines = [
        "📊 ReelDrop Admin",
        "",
        f"Total Successful Downloads: {total}",
        f"Downloads Today: {today}",
        f"Registered Users: {pro + free}",
        "Plan: Free (Unlimited)",
        "",
        "Platform Breakdown:",
    ]
    for p in PLATFORMS:
        lines.append(f"{PLATFORM_NAMES.get(p, p.title())}: {breakdown.get(p, 0)}")
    await update.message.reply_text("\n".join(lines))


async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    total, breakdown = await asyncio.to_thread(database.user_stats, user_id)
    quality = await asyncio.to_thread(database.get_video_quality, user_id)
    lines = ["📊 Your ReelDrop Stats", "", "Plan: Free (Unlimited)", f"Total Downloads: {total}", "", "Platform Breakdown:"]
    for p in PLATFORMS:
        lines.append(f"{PLATFORM_NAMES.get(p, p.title())}: {breakdown.get(p, 0)}")
    lines += ["", "Download limit: Unlimited", f"Video quality: Up to {quality}p"]
    await update.message.reply_text("\n".join(lines))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not update.effective_user:
        return
    if not await _require_channel_membership(update, context):
        return
    user_id = update.effective_user.id
    url = context.user_data.pop("selected_url", None) or extract_url(message.text or "")
    if not url:
        return
    is_valid, platform = is_supported_url(url)
    if not is_valid:
        await message.reply_text("❌ Sirf supported Instagram, YouTube, Facebook ya Snapchat link bhejein.")
        return
    platform_name = PLATFORM_NAMES.get(platform, platform.title())
    if platform == "youtube":
        video_id = extract_youtube_video_id(url)
        if not video_id:
            await message.reply_text("❌ YouTube video ID pehchan nahi paya. Kripya valid YouTube video ya Short link bhejein.")
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 ReelDrop Web (1-Click Download)", url=f"{config.WEB_DOWNLOADER_URL}/?v={video_id}")],
        ])
        await message.reply_html(
            "🔴 <b>YouTube Video Ready!</b>\n\n"
            "🎬 Hamari official ReelDrop website se 1-Click me video download karein:\n\n"
            f"📋 <b>Video:</b> <code>https://www.youtube.com/watch?v={video_id}</code>\n\n"
            "👇 <b>Niche diye gaye button par click karein:</b>",
            reply_markup=keyboard,
        )
        await asyncio.to_thread(database.record_download, user_id, "success", "youtube", 1080, "free")
        return

    if not context.user_data.pop("choice_confirmed", False):

        context.user_data["pending_url"] = url
        context.user_data["pending_platform"] = platform
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("360p", callback_data="media:360"), InlineKeyboardButton("480p", callback_data="media:480")],
            [InlineKeyboardButton("720p", callback_data="media:720"), InlineKeyboardButton("1080p", callback_data="media:1080")],
            [InlineKeyboardButton("🎵 MP3 Audio", callback_data="media:audio")],
            [InlineKeyboardButton("📝 Copy Caption", callback_data="media:caption")],
        ])
        await message.reply_text(f"🎬 {platform_name} detected! Format choose karein:", reply_markup=keyboard)
        return
    plan = "free"
    quality = context.user_data.pop("selected_quality", None) or await asyncio.to_thread(database.get_video_quality, user_id)
    await asyncio.to_thread(database.set_video_quality, user_id, quality)
    cache_key = _cache_key(url, f"video:{quality}")
    cached = await asyncio.to_thread(database.get_cached_media, cache_key)
    cached_caption = f"✅ Download Complete\n\n🎬 {platform_name} · up to {quality}p\n⚡ ReelDrop · instant cache"
    if cached and await _send_cached(message, cached, cached_caption):
        await asyncio.to_thread(database.record_download, user_id, "success", platform, quality, plan)
        return
    status = await message.reply_text(f"🔍 {platform_name} detected · {quality}p tak\n\n⏳ Video process ho rahi hai...")
    request_dir = None
    try:
        async with download_semaphore:
            result = await asyncio.to_thread(download_media_collection, url, platform, quality, config.TEMP_DIR, user_id)
            request_dir = result.request_dir
        await status.edit_text("📤 Telegram par upload ho raha hai...")
        uploaded = []
        total_items = len(result.paths)
        for index, path in enumerate(result.paths):
            size_mb = round(path.stat().st_size / (1024 * 1024), 1)
            if path.stat().st_size > config.MAX_TELEGRAM_FILE_SIZE_BYTES:
                raise ReelDownloadError(f"Video size ({size_mb}MB) Telegram limit (50MB) se badi hai. Kripya lower quality (480p ya 360p) choose karein.")
            suffix = path.suffix.lower()
            is_photo = suffix in {".jpg", ".jpeg", ".png", ".webp"}
            file_type = "photo" if is_photo else "video"
            if total_items > 1:
                item_caption = f"✅ Download Complete\n\n🎠 Item {index + 1}/{total_items}\n🎬 {platform_name} · up to {quality}p\n⚡ ReelDrop" if index == 0 else f"🎠 Item {index + 1}/{total_items}"
            else:
                item_caption = f"✅ Download Complete\n\n🎬 {platform_name} · up to {quality}p\n⚡ ReelDrop"
            with path.open("rb") as media_file:
                if file_type == "photo":
                    sent = await message.reply_photo(photo=media_file, caption=item_caption, read_timeout=120, write_timeout=120, connect_timeout=30, pool_timeout=30)
                else:
                    sent = await message.reply_video(video=media_file, caption=item_caption, supports_streaming=True, read_timeout=120, write_timeout=120, connect_timeout=30, pool_timeout=30)
            uploaded.append((_telegram_file_id(sent, file_type), file_type, result.title))
        await asyncio.to_thread(database.replace_cached_media, cache_key, uploaded)
        await asyncio.to_thread(database.record_download, user_id, "success", platform, quality, plan)
        try: await status.delete()
        except BadRequest: pass
    except PrivateOrInaccessibleError:
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        await status.edit_text("🔒 Ye content private, restricted ya inaccessible lag raha hai.")
    except VideoUnavailableError:
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        await status.edit_text("❌ Video available nahi hai ya remove ho chuki hai.")
    except ReelDownloadError as error:
        logger.exception("Download failed for user %s on %s: %s", user_id, platform, error)
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        try: await status.edit_text(f"⚠️ {str(error)}")
        except TelegramError: pass
    except (NetworkError, TelegramError) as error:
        logger.exception("Telegram upload failed for user %s on %s", user_id, platform)
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        try: await status.edit_text("⚠️ Telegram upload timeout ho gaya. Kripya lower quality (480p ya 360p) try karein.")
        except TelegramError: pass
    except Exception as error:
        logger.exception("Unexpected processing failure for user %s on %s", user_id, platform)
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        try: await status.edit_text(f"⚠️ Video process nahi ho payi: {str(error)[:100]}")
        except TelegramError: pass
    finally:
        await asyncio.to_thread(delete_request_files, request_dir)


async def media_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return
    await query.answer()
    if not await _require_channel_membership(update, context):
        return
    url = context.user_data.pop("pending_url", None)
    platform = context.user_data.pop("pending_platform", None) or (detect_platform(url) if url else "unsupported")
    if not url:
        await query.edit_message_text("⌛ Ye selection expire ho gayi. Video link dobara bhejein.")
        return
    choice = (query.data or "").removeprefix("media:")
    labels = {"audio": "MP3 Audio", "caption": "Caption"}
    await query.edit_message_text(f"✅ {labels.get(choice, choice + 'p')} selected")
    context.user_data["selected_url"] = url
    if choice == "audio":
        await audio_command(update, context)
        return
    if choice == "caption":
        context.user_data.pop("selected_url", None)
        try:
            metadata = await asyncio.to_thread(get_metadata, url, platform)
            caption = (metadata.get("caption") or "").strip()
            if not caption:
                await update.effective_message.reply_text("ℹ️ Is post/video mein caption available nahi hai.")
                return
            for start in range(0, len(caption), 4000):
                await update.effective_message.reply_text(caption[start:start + 4000])
        except ReelDownloadError:
            logger.exception("Caption extraction failed for user %s on %s", update.effective_user.id, platform)
            await update.effective_message.reply_text("⚠️ Caption fetch nahi ho paya.")
        return
    try:
        quality = int(choice)
        if quality not in {360, 480, 720, 1080}:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text("❌ Invalid format selection.")
        return
    context.user_data["selected_quality"] = quality
    context.user_data["choice_confirmed"] = True
    await handle_message(update, context)


async def error_handler(update, context): logger.error("Unhandled Telegram update error", exc_info=context.error)


def build_bot_app() -> Application:
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    for command, callback in (
        ("start", start),
        ("help", help_command),
        ("stats", mystats),
        ("mystats", mystats),
        ("upgrade", upgrade),
        ("quality", quality_command),
        ("audio", audio_command),
        ("admin", admin),
    ):
        app.add_handler(CommandHandler(command, callback))
    app.add_handler(CallbackQueryHandler(media_choice, pattern=r"^media:(?:360|480|720|1080|audio|caption)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    database.initialize()
    cleanup_old_temp_files(config.TEMP_DIR, config.TEMP_FILE_MAX_AGE_HOURS)

    if config.WEBHOOK_BASE_URL:
        import uvicorn
        logger.info("Starting combined FastAPI & Telegram Webhook server on port %s", config.PORT)
        uvicorn.run("api:app", host="0.0.0.0", port=config.PORT, log_level="info")
    else:
        logger.info("Starting Telegram bot in polling mode")
        app = build_bot_app()
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
