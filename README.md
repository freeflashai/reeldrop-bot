# ReelDrop Bot

ReelDrop is a completely free, unlimited Instagram downloader Telegram bot. It accepts supported public Instagram links, sends the video in Telegram, records the outcome in SQLite, and removes request files.

## Supported Instagram Content

- Public Reels (`/reel/`, `/reels/`)
- Public video posts (`/p/`, `/tv/`)
- Public, unexpired Stories (`/stories/<username>/<id>`)
- Public, currently accessible Live URLs (`/<username>/live`)

Only parsed HTTP/HTTPS URLs on `instagram.com` are accepted. The bot rejects other platforms, malformed URLs, local hosts, unsafe schemes, unsupported Instagram paths, and lookalike domains.

## Free Access

All supported Instagram content is free, downloads are unlimited, and every user receives the best available quality up to 1080p. `/upgrade` only confirms that the bot is free; it never opens a payment invoice. The bot never upscales video.

## Audio Extraction and Quality Selection

- Pasting a supported Instagram link displays buttons for `360p`, `480p`, `720p`, `1080p`, and `MP3 Audio`; processing begins after a selection.
- `/audio <Instagram link>` extracts 192 kbps MP3 audio using FFmpeg and sends it directly in Telegram.
- `/quality 360`, `/quality 480`, `/quality 720`, or `/quality 1080` saves the user's preferred maximum video resolution.
- `/quality` without a value shows the current setting.
- If the selected resolution is unavailable, ReelDrop sends the best available lower/source quality and never upscales.

## Public Content Limitations

ReelDrop does not bypass Instagram login, private accounts, expired Stories, inaccessible Live sessions, DRM, or other access controls. No cookies or credentials are accepted or harvested. Story and Live support depends on public accessibility and yt-dlp extractor support at request time.

## Setup and Environment Variables

Install Python 3.11+, copy `.env.example` to `.env`, set `TELEGRAM_BOT_TOKEN`, install dependencies with `pip install -r requirements.txt`, then run `python bot.py`.

Required/important variables:

- `TELEGRAM_BOT_TOKEN`
- `ADMIN_TELEGRAM_ID` for `/admin`
- `FREE_DAILY_LIMIT=0`, `PRO_DAILY_SOFT_LIMIT=0` are legacy compatibility settings; download-count limits are disabled
- `MAX_CONCURRENT_DOWNLOADS=3`
- `MAX_TELEGRAM_FILE_SIZE_MB=49`, `TEMP_FILE_MAX_AGE_HOURS=24`
- `WEBHOOK_BASE_URL`, `WEBHOOK_SECRET_TOKEN`, and `PORT` for webhook deployments

Never commit `.env`.

## FFmpeg

FFmpeg is required when yt-dlp merges video and audio. On Windows run `winget install Gyan.FFmpeg`; on Debian/Ubuntu run `sudo apt-get update && sudo apt-get install -y ffmpeg`. Verify with `ffmpeg -version`. An executable available on `PATH` works on Windows, Render, Oracle Cloud, and Linux VPS hosts.

## Admin Analytics

`/admin` shows successful totals, today's successes, registered users, and Instagram successful downloads. Failed attempts are stored but excluded. `/mystats` shows the free unlimited plan and Instagram download count.

## Render Deployment

The included Dockerfile installs FFmpeg. Create a private repository, deploy it as a Docker web service, set `TELEGRAM_BOT_TOKEN` and `ADMIN_TELEGRAM_ID`, and use a persistent disk for `reeldrop.db` if analytics must survive restarts. `RENDER_EXTERNAL_URL` automatically enables webhook mode.

## Oracle Cloud / Linux VPS Deployment

Install Python, FFmpeg, and the requirements; copy the project and `.env`; then run `python bot.py` under systemd or another supervisor. Without `WEBHOOK_BASE_URL`, polling is used. Give the service account write access to the project database and `temp/`.

## Database and Temporary Files

Startup safely adds missing download analytics fields and the user's `video_quality` preference without deleting records. Each job uses `temp/<user_id>/<request_uuid>/`. Video and extracted MP3 files are removed after success or any failure, and stale files are cleaned at startup.

## Testing

Run `python -m unittest discover -s tests -v`. Network downloads are intentionally not part of unit tests; validate representative public/authorized links manually because extractor and source availability change.

## Troubleshooting

- Update extractors: `python -m pip install -U yt-dlp`.
- Confirm FFmpeg is on `PATH` if merging fails.
- Private/login-required/restricted links are intentionally rejected.
- Telegram file-size limits are configurable, but the Bot API ultimately controls upload acceptance.
- On ephemeral hosts, attach persistent storage for SQLite analytics.

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
│   └── instagram.py
├── tests/test_core.py
├── requirements.txt
├── Dockerfile
├── render.yaml
├── .env.example
└── temp/.gitkeep
```
