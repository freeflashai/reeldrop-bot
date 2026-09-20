"""FastAPI web service for 1-Click media downloads and Telegram webhook."""

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from telegram import Update

import config
from database import Database
from downloader import (
    delete_request_files,
    download_audio,
    download_video,
    get_metadata,
    is_supported_url,
)

logger = logging.getLogger(__name__)

telegram_app = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app
    from bot import build_bot_app

    logger.info("Starting ReelDrop API & Bot...")
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    Database(config.DATABASE_PATH).initialize()

    if config.TELEGRAM_BOT_TOKEN:
        telegram_app = build_bot_app()
        await telegram_app.initialize()
        await telegram_app.start()
        if config.WEBHOOK_BASE_URL:
            webhook_url = f"{config.WEBHOOK_BASE_URL}/telegram-webhook"
            logger.info("Setting Telegram webhook to: %s", webhook_url)
            await telegram_app.bot.set_webhook(
                url=webhook_url,
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=False,
            )
        else:
            logger.info("WEBHOOK_BASE_URL not set; API running in standalone mode")

    yield

    if telegram_app:
        logger.info("Shutting down Telegram Bot...")
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(title="ReelDrop 1-Click Downloader API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "ReelDrop 1-Click Downloader API",
        "bot": "@instareeldownloaderr_bot",
        "web": config.WEB_DOWNLOADER_URL,
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/info")
async def video_info(url: str = Query(..., description="Supported video URL (Instagram, Facebook, Snapchat)")):
    """Fetch video preview metadata."""
    is_valid, platform = is_supported_url(url)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Unsupported platform URL")
    try:
        data = await asyncio.to_thread(get_metadata, url, platform)
        return {
            "platform": platform,
            "title": data.get("title") or "Video",
            "qualities": ["1080", "720", "480", "360", "mp3"],
        }
    except Exception as e:
        logger.exception("Metadata fetch failed for %s", url)
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/download")
async def download_media(
    url: str = Query(..., description="Supported video URL (Instagram, Facebook, Snapchat)"),
    f: str = Query("720", description="Quality format: 1080, 720, 480, 360, mp3"),
    background_tasks: BackgroundTasks = None,
):
    """
    1-Click direct file download endpoint.
    Returns FileResponse with Content-Disposition: attachment so browser downloads directly.
    """
    is_valid, platform = is_supported_url(url)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Unsupported platform URL")
    req_user_id = int(str(uuid4().int)[:8])

    try:
        if f.lower() == "mp3":
            result = await asyncio.to_thread(download_audio, url, platform, config.TEMP_DIR, req_user_id)
            media_type = "audio/mpeg"
            ext = "mp3"
        else:
            try:
                quality = int(f)
            except ValueError:
                quality = 720
            result = await asyncio.to_thread(download_video, url, platform, quality, config.TEMP_DIR, req_user_id)
            media_type = "video/mp4"
            ext = "mp4"

        if background_tasks:
            background_tasks.add_task(delete_request_files, result.request_dir)

        safe_title = re.sub(r'[^\w\s.-]', '', result.title or f"{platform}_media").strip() or f"{platform}_media"
        filename = f"{safe_title}.{ext}"

        return FileResponse(
            path=result.path,
            media_type=media_type,
            filename=filename,
        )
    except Exception as e:
        logger.exception("Download failed for %s (format: %s)", url, f)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram webhook updates."""
    if not telegram_app:
        logger.warning("Telegram app not initialized when update arrived")
        return Response(status_code=503)

    try:
        data = await request.json()
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        logger.exception("Error processing Telegram update: %s", e)
        return Response(status_code=500)
