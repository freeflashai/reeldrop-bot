# ReelDrop Bot

ReelDrop is a completely free, unlimited multi-platform downloader Telegram bot. It accepts supported public **Instagram**, **Facebook**, and **Snapchat** links, sends the video or extracted MP3 audio directly in Telegram, records analytics in SQLite, and cleans up request files automatically.

## Supported Platforms & Content

### 📸 Instagram
- Public Reels (`/reel/`, `/reels/`)
- Public video & carousel posts (`/p/`, `/tv/`)
- Public, unexpired Stories (`/stories/<username>/<id>`)
- Public, currently accessible Live URLs (`/<username>/live`)

### 👥 Facebook
- Public Reels (`/reel/<id>`, `/share/r/<id>/`)
- Facebook Watch videos (`/watch/?v=<id>`, `fb.watch/<id>/`)
- Public Page & user video posts (`/videos/<id>`, `/share/v/<id>/`)

### 👻 Snapchat
- Public Spotlight videos (`/spotlight/<id>`)
- Public Stories & Snaps (`story.snapchat.com/s/<id>`, `/add/<user>/story/<id>`, `/p/<id>`, `/t/<id>`)

Only parsed HTTP/HTTPS URLs on authorized platform domains are accepted. The bot rejects other platforms, malformed URLs, local hosts, unsafe schemes, channel/profile/explore pages, and lookalike domains.

## Free Access

All supported content is free, downloads are unlimited, and every user receives the best available quality up to 1080p. `/upgrade` confirms that the bot is free. The bot never upscales video.

## Audio Extraction and Quality Selection

- Pasting a supported link displays format buttons for `360p`, `480p`, `720p`, `1080p`, `🎵 MP3 Audio`, and `📝 Copy Caption`; processing begins after a selection.
- `/audio <link>` extracts 192 kbps MP3 audio using FFmpeg and sends it directly in Telegram.
- `/quality 360`, `/quality 480`, `/quality 720`, or `/quality 1080` saves the user's preferred maximum video resolution.
- `/quality` without a value shows the current setting.
- If the selected resolution is unavailable, ReelDrop sends the best available lower/source quality and never upscales.

## Carousel, Caption, and Cache

- Carousel posts automatically download every media item exposed by the post and send them in order.
- `📝 Copy Caption` fetches the public post caption and sends it as copyable text, split safely when it exceeds Telegram's message limit.
- Successful uploads store Telegram `file_id` values in SQLite by normalized URL, quality, and delivery mode. Repeated requests are served instantly without downloading the source again.
- If Telegram rejects a stale cached `file_id`, ReelDrop automatically downloads and refreshes it.

## Public Content Limitations

ReelDrop does not bypass logins, private accounts, expired Stories, inaccessible Live sessions, DRM, or other access controls. No cookies or credentials are accepted or harvested. Content support depends on public accessibility and yt-dlp extractor support at request time. Telegram Bot API has a 50MB file size limit.

## Setup and Environment Variables

Install Python 3.11+, copy `.env.example` to `.env`, set `TELEGRAM_BOT_TOKEN`, install dependencies with `pip install -r requirements.txt`, then run `python bot.py`.

Required/important variables:

- `TELEGRAM_BOT_TOKEN`
- `ADMIN_TELEGRAM_ID` for `/admin`
- `REQUIRED_CHANNEL_ID=@yourchannel` (or a numeric `-100...` ID) makes channel membership mandatory before downloads
- `REQUIRED_CHANNEL_URL=https://t.me/yourchannel` adds the Join Channel button; for a private channel, use its invite link
- `MAX_CONCURRENT_DOWNLOADS=3`
- `MAX_TELEGRAM_FILE_SIZE_MB=49`, `TEMP_FILE_MAX_AGE_HOURS=24`
- `WEBHOOK_BASE_URL`, `WEBHOOK_SECRET_TOKEN`, and `PORT` for webhook deployments

Never commit `.env`.

For mandatory membership checks, add the bot as an administrator in the required channel. The bot checks membership again on every download entry point, so users who leave the channel lose access.

## FFmpeg

FFmpeg is required when yt-dlp merges video and audio or extracts MP3. On Windows run `winget install Gyan.FFmpeg`; on Debian/Ubuntu run `sudo apt-get update && sudo apt-get install -y ffmpeg`. Verify with `ffmpeg -version`.

## Admin Analytics

`/admin` shows successful totals, today's successes, registered users, and download breakdowns by platform (Instagram, Facebook, Snapchat). `/mystats` shows the user's total and platform breakdown.

## Testing

Run `python -m unittest discover -s tests -v`.

## Project Tree

```text
reeldrop-bot/
├── bot.py
├── config.py
├── database.py
├── downloader.py
├── platforms/
│   ├── __init__.py
│   ├── base.py
│   ├── facebook.py
│   ├── instagram.py
│   ├── snapchat.py
│   └── youtube.py
├── tests/test_core.py
├── requirements.txt
├── Dockerfile
├── render.yaml
├── .env.example
└── temp/.gitkeep
```
