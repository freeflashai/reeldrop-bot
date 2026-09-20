"""Telegram handlers and application entry point for ReelDrop Bot."""

import asyncio
import hashlib
import html
import logging
import re
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit


from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import config
from database import Database, PLATFORMS
from downloader import (PrivateOrInaccessibleError, ReelDownloadError,
                        UnsupportedUrlError, VideoUnavailableError,
                        cleanup_old_temp_files, delete_request_files, detect_platform, download_audio,
                        download_media_collection, extract_url, get_metadata, is_supported_url)


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.request").setLevel(logging.WARNING)
database = Database(config.DATABASE_PATH)
download_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_DOWNLOADS)

PLATFORM_NAMES = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "snapchat": "Snapchat",
}

WELCOME_TEXT = """👋 Welcome to ReelDrop
 
📸 Instagram · 👥 Facebook · 👻 Snapchat
 
🎬 Instagram Reels, Video posts, Stories & Live
👥 Facebook Reels & Watch videos
👻 Snapchat Spotlight & Stories
 
🎵 /audio <link> — MP3 nikalein
⚙️ /quality 360|480|720|1080
 
📊 Live download progress percentage (%)
💾 50MB+ large files seedhe downloads folder me save hote hain!
 
🔗 Bas supported video link bhejo 👇"""


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


def _format_bytes(bytes_count: int | float | None) -> str:
    if not bytes_count or bytes_count <= 0:
        return "0 B"
    num = float(bytes_count)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024.0:
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024.0
    return f"{num:.1f} TB"


def _safe_filename(title: str | None, default_name: str, ext: str) -> str:
    if not title:
        raw_name = default_name
    else:
        raw_name = re.sub(r'[\\/*?:"<>|]', "", title).strip()
        if not raw_name:
            raw_name = default_name
    raw_name = raw_name[:80].strip()
    if not ext.startswith("."):
        ext = f".{ext}"
    return f"{raw_name}{ext}"


def _get_unique_filepath(dest_dir: Path, filename: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / filename
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    counter = 1
    while True:
        candidate = dest_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


class TelegramProgressTracker:
    """Thread-safe progress reporter that updates a Telegram status message."""

    def __init__(self, message, header: str = "⏳ Processing..."):
        self.message = message
        self.header = header
        self.last_update_time = 0.0
        self.last_text = ""
        self.loop = asyncio.get_running_loop()

    def hook(self, d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            now = time.time()
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0

            percent = (downloaded / total * 100) if total > 0 else 0
            percent_clamped = min(100.0, max(0.0, percent))

            # Rate limit Telegram edits: at most once every 2 seconds, unless at 100%
            if now - self.last_update_time < 2.0 and percent_clamped < 99.5:
                return

            self.last_update_time = now
            speed = d.get("speed")
            eta = d.get("eta")
            speed_str = f"{_format_bytes(speed)}/s" if speed else "N/A"
            eta_str = f"{int(eta)}s" if eta is not None else "..."
            dl_str = _format_bytes(downloaded)

            if total > 0:
                blocks = int(percent_clamped // 10)
                bar = "█" * blocks + "░" * (10 - blocks)
                total_str = _format_bytes(total)
                text = (
                    f"{self.header}\n\n"
                    f"📥 <b>Downloading: {percent_clamped:.0f}%</b>\n"
                    f"<code>[{bar}]</code>\n"
                    f"⚡ <b>Speed:</b> {speed_str} · ⏱ <b>ETA:</b> {eta_str}\n"
                    f"📦 <b>Size:</b> {dl_str} / {total_str}"
                )
            else:
                text = (
                    f"{self.header}\n\n"
                    f"📥 <b>Downloading...</b>\n"
                    f"⚡ <b>Speed:</b> {speed_str}\n"
                    f"📦 <b>Downloaded:</b> {dl_str}"
                )

            try:
                asyncio.run_coroutine_threadsafe(self._safe_edit(text), self.loop)
            except Exception:
                pass

        elif status == "finished":
            now = time.time()
            if now - self.last_update_time >= 1.5:
                self.last_update_time = now
                text = f"{self.header}\n\n📥 <b>Download 100% complete!</b>\n⚙️ Media process ho rahi hai..."
                try:
                    asyncio.run_coroutine_threadsafe(self._safe_edit(text), self.loop)
                except Exception:
                    pass

    async def _safe_edit(self, text: str) -> None:
        if text == self.last_text:
            return
        self.last_text = text
        try:
            await self.message.edit_text(text, parse_mode="HTML")
        except (BadRequest, TelegramError):
            pass



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user:
        await asyncio.to_thread(database.ensure_user, update.effective_user.id)
    if update.message:
        await update.message.reply_text(WELCOME_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Supported platforms: Instagram, Facebook, Snapchat.\n\n"
            "• Instagram: Reels, video posts, Stories, Live\n"
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
        await message.reply_text("❌ Use: /audio <supported link (Instagram, Facebook, Snapchat)>")
        return
    is_valid, platform = is_supported_url(url)
    if not is_valid:
        await message.reply_text("❌ Use: /audio <supported link (Instagram, Facebook, Snapchat)>")
        return
    platform_name = PLATFORM_NAMES.get(platform, platform.title())
    cache_key = _cache_key(url, "audio:mp3:192")

    cached = await asyncio.to_thread(database.get_cached_media, cache_key)
    if cached and await _send_cached(message, cached, f"✅ Audio Download Complete\n\n🎵 {platform_name} Audio · instant cache"):
        await asyncio.to_thread(database.record_download, user_id, "success", platform, None, "free")
        return
    status = await message.reply_text(f"🎵 <b>{platform_name}</b> audio extract ho rahi hai...", parse_mode="HTML")
    progress = TelegramProgressTracker(status, f"🎵 <b>{platform_name} Audio</b>")
    request_dir = None
    try:
        async with download_semaphore:
            result = await asyncio.to_thread(download_audio, url, platform, config.TEMP_DIR, user_id, progress.hook)
            request_dir = result.request_dir
        if result.path.stat().st_size > config.MAX_TELEGRAM_FILE_SIZE_BYTES:
            size_mb = round(result.path.stat().st_size / (1024 * 1024), 1)
            safe_name = _safe_filename(result.title, f"{platform}_audio", result.path.suffix)
            dest_path = _get_unique_filepath(config.DOWNLOADS_DIR, safe_name)
            shutil.copy2(result.path, dest_path)
            title_esc = html.escape(result.title or f"{platform_name} Audio")
            path_str = html.escape(str(dest_path.resolve()))
            await status.edit_text(
                f"💾 <b>Large Audio Saved Directly on Laptop!</b>\n\n"
                f"🎵 <b>Title:</b> {title_esc}\n"
                f"📦 <b>Size:</b> {size_mb} MB\n"
                f"📁 <b>Saved Location:</b>\n<code>{path_str}</code>\n\n"
                f"⚠️ <i>Audio file 50MB se badi hai, isliye Telegram par bhejne ki jagah direct aapke laptop ke downloads folder me save kar di gayi hai!</i>",
                parse_mode="HTML",
            )
            await asyncio.to_thread(database.record_download, user_id, "success", platform, None, "free")
            return
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
        await message.reply_text("❌ Sirf supported Instagram, Facebook ya Snapchat link bhejein.")
        return
    platform_name = PLATFORM_NAMES.get(platform, platform.title())
    if not context.user_data.pop("choice_confirmed", False):

        context.user_data["pending_url"] = url
        context.user_data["pending_platform"] = platform
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("360p", callback_data="media:360"), InlineKeyboardButton("480p", callback_data="media:480")],
            [InlineKeyboardButton("720p", callback_data="media:720"), InlineKeyboardButton("1080p (Full HD)", callback_data="media:1080")],
            [InlineKeyboardButton("💾 Save to Laptop (Full HD / No 50MB Limit)", callback_data="media:laptop")],
            [InlineKeyboardButton("🎵 MP3 Audio", callback_data="media:audio")],
            [InlineKeyboardButton("📝 Copy Caption", callback_data="media:caption")],
        ])
        await message.reply_text(f"🎬 {platform_name} detected! Format choose karein:", reply_markup=keyboard)
        return
    save_to_laptop = context.user_data.pop("save_to_laptop", False)
    plan = "free"
    quality = context.user_data.pop("selected_quality", None)
    if not quality and not save_to_laptop:
        quality = await asyncio.to_thread(database.get_video_quality, user_id)
    if quality:
        await asyncio.to_thread(database.set_video_quality, user_id, quality)

    cache_key = _cache_key(url, f"video:{quality or 'laptop'}")
    if not save_to_laptop:
        cached = await asyncio.to_thread(database.get_cached_media, cache_key)
        cached_caption = f"✅ Download Complete\n\n🎬 {platform_name} · up to {quality}p\n⚡ ReelDrop · instant cache"
        if cached and await _send_cached(message, cached, cached_caption):
            await asyncio.to_thread(database.record_download, user_id, "success", platform, quality, plan)
            return

    quality_display = f"{quality}p tak" if quality else "Best Quality (No 50MB Limit)"
    status = await message.reply_text(
        f"🔍 <b>{platform_name}</b> detected · {quality_display}\n\n⏳ Video process ho rahi hai...",
        parse_mode="HTML",
    )
    progress = TelegramProgressTracker(status, f"🎬 <b>{platform_name}</b> ({quality_display})")
    request_dir = None
    try:
        async with download_semaphore:
            result = await asyncio.to_thread(
                download_media_collection, url, platform, quality, config.TEMP_DIR, user_id, progress.hook
            )
            request_dir = result.request_dir

        has_oversized = any(p.stat().st_size > config.MAX_TELEGRAM_FILE_SIZE_BYTES for p in result.paths)
        if save_to_laptop or has_oversized:
            saved_details = []
            for index, path in enumerate(result.paths):
                size_mb = round(path.stat().st_size / (1024 * 1024), 1)
                default_name = f"{platform}_item_{index + 1}" if len(result.paths) > 1 else f"{platform}_video"
                safe_name = _safe_filename(result.title, default_name, path.suffix)
                dest_path = _get_unique_filepath(config.DOWNLOADS_DIR, safe_name)
                shutil.copy2(path, dest_path)
                saved_details.append((dest_path, size_mb))

            total_size_mb = round(sum(size for _, size in saved_details), 1)
            paths_formatted = "\n".join(f"<code>{html.escape(str(p.resolve()))}</code>" for p, _ in saved_details)
            title_esc = html.escape(result.title or f"{platform_name} Video")

            if save_to_laptop:
                reason = "⚡ <i>Direct laptop save select kiya gaya tha (Full HD / No 50MB Limit).</i>"
            else:
                reason = "⚠️ <i>Video size Telegram limit (50MB) se badi hone ke karan direct aapke laptop ke downloads folder mein save kar di gayi hai!</i>"

            saved_msg = (
                f"💾 <b>File Saved Directly on Laptop!</b>\n\n"
                f"🎬 <b>Title:</b> {title_esc}\n"
                f"📦 <b>Total Size:</b> {total_size_mb} MB\n"
                f"📁 <b>Saved Location:</b>\n{paths_formatted}\n\n"
                f"{reason}\n\n"
                f"✅ File aapke computer ke <b>downloads</b> folder me safely available hai!"
            )
            await status.edit_text(saved_msg, parse_mode="HTML")
            await asyncio.to_thread(database.record_download, user_id, "success", platform, quality, plan)
            return

        await status.edit_text("📤 Telegram par upload ho raha hai...")
        uploaded = []
        total_items = len(result.paths)
        for index, path in enumerate(result.paths):
            size_mb = round(path.stat().st_size / (1024 * 1024), 1)
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
    labels = {
        "audio": "MP3 Audio",
        "caption": "Caption",
        "laptop": "Save to Laptop (Full HD)",
    }
    await query.edit_message_text(f"✅ {labels.get(choice, choice + 'p')} selected")
    context.user_data["selected_url"] = url
    if choice == "audio":
        await audio_command(update, context)
        return
    if choice == "laptop":
        context.user_data["save_to_laptop"] = True
        context.user_data["selected_quality"] = 1080
        context.user_data["choice_confirmed"] = True
        await handle_message(update, context)
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
    app.add_handler(CallbackQueryHandler(media_choice, pattern=r"^media:(?:360|480|720|1080|laptop|audio|caption)$"))
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
