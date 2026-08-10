# ReelDrop Bot

ReelDrop is a Telegram bot that auto-detects a supported video platform, applies Free/Pro access and quality rules, sends the video in Telegram, records the outcome in SQLite, and removes request files.

## Supported Platforms

- Instagram: public Reels and public video posts (`/reel/`, `/reels/`, `/p/`)
- Facebook: publicly accessible videos and Reels, including `fb.watch`
- Snapchat (Pro): publicly accessible/authorized links where yt-dlp supports them
- YouTube (Pro): only content the user owns, is licensed to download, or is explicitly downloadable/permitted

Hostname detection uses parsed HTTP/HTTPS URLs. It rejects malformed URLs, local hosts, other schemes, and lookalike domains.

## Free vs Pro

| Plan | Platforms | Daily use | Quality |
|---|---|---:|---:|
| Free | Instagram, Facebook | Unlimited | up to 720p |
| Pro | All supported platforms | Unlimited | up to 1080p |

ReelDrop Pro costs 25 Telegram Stars for 30 days. `/upgrade` opens the Stars invoice. The bot never upscales video.

## Public/Authorized Content and YouTube Limitations

ReelDrop does not bypass DRM, logins, private content, age restrictions, geo-blocks, restricted groups, disappearing-content controls, or other access controls. YouTube use is limited to content the user is authorized to download. No cookies or credentials are accepted or harvested.

## Setup and Environment Variables

Install Python 3.11+, copy `.env.example` to `.env`, set `TELEGRAM_BOT_TOKEN`, install dependencies with `pip install -r requirements.txt`, then run `python bot.py`.

Required/important variables:

- `TELEGRAM_BOT_TOKEN`
- `ADMIN_TELEGRAM_ID` for `/admin`, `/makepro USER_ID`, `/removepro USER_ID`
- `PRO_PRICE_STARS=25`, `PRO_DURATION_DAYS=30`
- `FREE_DAILY_LIMIT=0`, `PRO_DAILY_SOFT_LIMIT=0` are legacy compatibility settings; download-count limits are disabled
- `MAX_CONCURRENT_DOWNLOADS=3`
- `MAX_TELEGRAM_FILE_SIZE_MB=49`, `TEMP_FILE_MAX_AGE_HOURS=24`
- `WEBHOOK_BASE_URL`, `WEBHOOK_SECRET_TOKEN`, and `PORT` for webhook deployments

Never commit `.env`.

## FFmpeg

FFmpeg is required when yt-dlp merges video and audio. On Windows run `winget install Gyan.FFmpeg`; on Debian/Ubuntu run `sudo apt-get update && sudo apt-get install -y ffmpeg`. Verify with `ffmpeg -version`. An executable available on `PATH` works on Windows, Render, Oracle Cloud, and Linux VPS hosts.

## Admin Analytics

`/admin` shows successful totals, today's successes, Active Pro/Free users, and per-platform successful downloads. Failed attempts are stored but excluded. `/mystats` shows plan, platform breakdown, and expiry or remaining Free allowance.

## Render Deployment

The included Dockerfile installs FFmpeg. Create a private repository, deploy it as a Docker web service, set `TELEGRAM_BOT_TOKEN` and `ADMIN_TELEGRAM_ID`, and use a persistent disk for `reeldrop.db` if analytics must survive restarts. `RENDER_EXTERNAL_URL` automatically enables webhook mode.

## Oracle Cloud / Linux VPS Deployment

Install Python, FFmpeg, and the requirements; copy the project and `.env`; then run `python bot.py` under systemd or another supervisor. Without `WEBHOOK_BASE_URL`, polling is used. Give the service account write access to the project database and `temp/`.

## Database and Temporary Files

Startup safely adds missing `platform`, `requested_quality`, `plan`, and `pro_until` fields without deleting records. Each job uses `temp/<user_id>/<request_uuid>/`. Its files are removed after success or any failure, and stale files are cleaned at startup.

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
