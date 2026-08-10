"""Telegram handlers and application entry point for ReelDrop Bot."""

import asyncio
import logging
from datetime import datetime

from telegram import LabeledPrice, Update
from telegram.error import BadRequest, NetworkError, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, PreCheckoutQueryHandler, filters

import config
from database import Database, PLATFORMS
from downloader import (PrivateOrInaccessibleError, ReelDownloadError, SnapchatUnsupportedError,
                        UnsupportedUrlError, VideoUnavailableError, YouTubeNotPermittedError,
                        cleanup_old_temp_files, delete_request_files, detect_platform, download_video, extract_url)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.request").setLevel(logging.WARNING)
database = Database(config.DATABASE_PATH)
download_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_DOWNLOADS)

WELCOME_TEXT = """👋 Welcome to ReelDrop

One bot. Multiple platforms. ⚡

📸 Instagram
🔵 Facebook
👻 Snapchat
▶️ YouTube*

🔗 Bas supported video link bhejo.
🎬 Best available quality me video directly Telegram par pao.

✅ Free to start
🔒 Simple & privacy-conscious
⚡ Fast processing
📱 Directly on Telegram

*YouTube support is limited to content you own, are licensed to download, or that is explicitly downloadable/permitted.

Just paste the link 👇"""
PRO_ONLY_TEXT = "🔒 Ye platform ReelDrop Pro me available hai.\n\n⚡ ReelDrop Pro\n⭐ 25 Stars / 30 Days\n\nUse /upgrade"
PLATFORM_NAMES = {name: name.title() for name in PLATFORMS}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user:
        await asyncio.to_thread(database.ensure_user, update.effective_user.id)
    if update.message:
        await update.message.reply_text(WELCOME_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("Instagram aur Facebook public links Free hain. Snapchat aur permitted YouTube links Pro hain. Private, DRM, login-required, restricted, ya unauthorized content process nahi hota. Bas HTTP/HTTPS video link paste karein.")


async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_invoice(title="ReelDrop Pro", description=f"Pro access for {config.PRO_DURATION_DAYS} days", payload="reeldrop-pro-30", currency="XTR", prices=[LabeledPrice("ReelDrop Pro", config.PRO_PRICE_STARS)])


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if query:
        await query.answer(ok=query.invoice_payload == "reeldrop-pro-30", error_message="Invalid ReelDrop payment." if query.invoice_payload != "reeldrop-pro-30" else None)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user or not update.message.successful_payment:
        return
    payment = update.message.successful_payment
    if payment.invoice_payload == "reeldrop-pro-30" and payment.currency == "XTR" and payment.total_amount == config.PRO_PRICE_STARS:
        await asyncio.to_thread(database.set_pro, update.effective_user.id, config.PRO_DURATION_DAYS)
        await update.message.reply_text(f"✅ ReelDrop Pro active ho gaya — {config.PRO_DURATION_DAYS} days ke liye.")


def _is_admin(update: Update) -> bool:
    return bool(update.effective_user and config.ADMIN_TELEGRAM_ID and update.effective_user.id == config.ADMIN_TELEGRAM_ID)


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not _is_admin(update):
        return
    total, today, pro, free, breakdown = await asyncio.to_thread(database.admin_stats)
    lines = ["📊 ReelDrop Admin", "", f"Total Successful Downloads: {total}", f"Downloads Today: {today}", f"Active Pro Users: {pro}", f"Free Users: {free}", "", "Platform Breakdown:"]
    lines += [f"{PLATFORM_NAMES[p]}: {breakdown.get(p, 0)}" for p in PLATFORMS]
    await update.message.reply_text("\n".join(lines))


async def _admin_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, remove=False) -> None:
    if not update.message or not _is_admin(update):
        return
    try:
        target = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text(f"Usage: /{'removepro' if remove else 'makepro'} TELEGRAM_USER_ID")
        return
    await asyncio.to_thread(database.remove_pro if remove else database.set_pro, target, *(() if remove else (config.PRO_DURATION_DAYS,)))
    await update.message.reply_text(f"✅ User {target} {'is now Free' if remove else 'is now Pro'}.")


async def makepro(update, context): await _admin_plan(update, context)
async def removepro(update, context): await _admin_plan(update, context, True)


async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    pro = await asyncio.to_thread(database.is_pro, user_id)
    total, breakdown = await asyncio.to_thread(database.user_stats, user_id)
    lines = ["📊 Your ReelDrop Stats", "", f"Plan: {'Pro' if pro else 'Free'}", f"Total Downloads: {total}", ""]
    lines += [f"{PLATFORM_NAMES[p]}: {breakdown.get(p, 0)}" for p in PLATFORMS]
    if pro:
        expiry = await asyncio.to_thread(database.pro_expiry, user_id)
        lines += ["", f"Pro Expiry: {datetime.fromisoformat(expiry).strftime('%d %b %Y')}"]
    else:
        lines += ["", "Download limit: Unlimited"]
    await update.message.reply_text("\n".join(lines))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    user_id = update.effective_user.id
    url = extract_url(update.message.text or "")
    platform = detect_platform(url) if url else "unsupported"
    if platform == "unsupported":
        await update.message.reply_text("❌ Ye platform abhi supported nahi hai.")
        return
    pro = await asyncio.to_thread(database.is_pro, user_id)
    plan, quality = ("pro", 1080) if pro else ("free", 720)
    if platform in {"snapchat", "youtube"} and not pro:
        await update.message.reply_text(PRO_ONLY_TEXT)
        return
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
            await update.message.reply_video(video=video_file, caption=f"✅ Download Complete\n\n🎬 Platform: {PLATFORM_NAMES[platform]}\n⚡ ReelDrop{' Pro' if pro else ''}", supports_streaming=True, read_timeout=120, write_timeout=120, connect_timeout=30, pool_timeout=30)
        await asyncio.to_thread(database.record_download, user_id, "success", platform, quality, plan)
        try: await status.delete()
        except BadRequest: pass
    except PrivateOrInaccessibleError:
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        await status.edit_text("🔒 Ye content private, restricted ya inaccessible lag raha hai.")
    except VideoUnavailableError:
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        await status.edit_text("❌ Video available nahi hai ya remove ho chuki hai.")
    except YouTubeNotPermittedError:
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        await status.edit_text("⚠️ Is YouTube video ko ReelDrop process nahi kar sakta.")
    except SnapchatUnsupportedError:
        await asyncio.to_thread(database.record_download, user_id, "failed", platform, quality, plan)
        await status.edit_text("⚠️ Ye Snapchat link abhi process nahi ho pa raha.")
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
    for command, callback in (("start", start), ("help", help_command), ("stats", mystats), ("mystats", mystats), ("upgrade", upgrade), ("admin", admin), ("makepro", makepro), ("removepro", removepro)):
        app.add_handler(CommandHandler(command, callback))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    if config.WEBHOOK_BASE_URL:
        app.run_webhook(listen="0.0.0.0", port=config.PORT, url_path="telegram-webhook", webhook_url=f"{config.WEBHOOK_BASE_URL}/telegram-webhook", secret_token=config.WEBHOOK_SECRET_TOKEN or None, allowed_updates=Update.ALL_TYPES)
    else:
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__": main()
