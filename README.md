# ReelDrop Bot

ReelDrop is a beginner-friendly Telegram bot that accepts a public Instagram Reel or public video-post URL, downloads the best available quality up to 720p, sends the MP4 back, and removes the temporary file.

It does not bypass Instagram login, private accounts, DRM, or access controls. A video must be publicly accessible to `yt-dlp`.

## What you need

- Windows 10/11
- Python 3.11 or newer
- A Telegram bot token
- FFmpeg

## STEP 1: Install Python

Download Python from [python.org](https://www.python.org/downloads/). During installation, select **Add Python to PATH**. Open PowerShell and check:

```powershell
python --version
```

## STEP 2: Create a Telegram bot

1. Open Telegram and chat with `@BotFather`.
2. Send `/newbot`.
3. Choose a display name and a username ending in `bot`.

## STEP 3: Get the bot token

BotFather will send a token that looks like `123456789:ABC...`. Treat it like a password and never commit or share it.

## STEP 4: Create `.env`

In PowerShell, enter the project folder and copy the example:

```powershell
cd "C:\Users\LENOVO\Desktop\instagram reel downloader bot\reeldrop-bot"
Copy-Item .env.example .env
notepad .env
```

Replace `your_token_here` with the token from BotFather:

```dotenv
TELEGRAM_BOT_TOKEN=123456789:paste_your_real_token_here
```

Save and close Notepad. `.env` is ignored by Git.

## STEP 5: Install FFmpeg on Windows

The simplest option is Windows Package Manager:

```powershell
winget install Gyan.FFmpeg
```

Close and reopen PowerShell, then verify:

```powershell
ffmpeg -version
```

If `winget` is unavailable, download a Windows build from [ffmpeg.org](https://ffmpeg.org/download.html), extract it, and add its `bin` folder to your Windows `PATH`.

## STEP 6: Create and activate a virtual environment

```powershell
python -m venv venv
venv\Scripts\activate
```

If PowerShell blocks activation, run this once in the current window and try again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
venv\Scripts\activate
```

## STEP 7: Install packages

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## STEP 8: Run the bot

```powershell
python bot.py
```

Keep that PowerShell window open. Stop the bot with `Ctrl+C`.

## Test it

1. Open your bot in Telegram.
2. Send `/start`.
3. Paste a public Instagram Reel URL.
4. Wait for the MP4 reply.

Commands:

- `/start` — welcome and quick instructions
- `/help` — supported links and limitations
- `/stats` — total successes, your successes, and failures

## Configuration

Optional `.env` values:

- `MAX_DOWNLOADS_PER_HOUR=10` — successful downloads allowed per user in the previous hour
- `MAX_CONCURRENT_DOWNLOADS=3` — concurrent yt-dlp jobs
- `MAX_TELEGRAM_FILE_SIZE_MB=49` — conservative upload-size ceiling
- `TEMP_FILE_MAX_AGE_HOURS=24` — startup cleanup age

The SQLite database (`reeldrop.db`) is created automatically. Downloads go into unique folders under `temp/` and are deleted after success or failure.

## Deploy on Render Free

The included `Dockerfile` installs FFmpeg and runs the bot. On a local laptop the bot uses polling. On Render it automatically uses a Telegram webhook through Render's `RENDER_EXTERNAL_URL`.

1. Push this folder to a private GitHub repository. Never upload `.env`.
2. In Render, choose **New Web Service** and connect the repository.
3. Choose the **Free** instance type. Render detects the Dockerfile.
4. Add the secret environment variable `TELEGRAM_BOT_TOKEN` with the BotFather token.
5. Deploy and wait for `Starting in webhook mode` in the logs.

Render Free sleeps after inactivity and its filesystem is temporary. The first message after sleep can be delayed, and `/stats` data can reset after a restart. Downloaded videos are temporary by design.

## Troubleshooting

- **Token missing:** confirm the file is named exactly `.env`, not `.env.txt`.
- **FFmpeg error:** reopen PowerShell and run `ffmpeg -version`.
- **Instagram download fails:** update the extractor with `pip install -U yt-dlp`. Instagram changes frequently, and private/login-required content is intentionally unsupported.
- **File too large:** Telegram bot uploads have size limits. This bot reports the issue and deletes the temporary file.

## Project files

```text
reeldrop-bot/
├── bot.py
├── config.py
├── database.py
├── downloader.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── temp/
    └── .gitkeep
```
