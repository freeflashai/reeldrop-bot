# ReelDrop Web Downloader — Firebase Deployment Guide

A modern, responsive, 1-page media downloader for **ReelDrop**.
Features automatic YouTube link loading from Telegram bot (`?v=VIDEO_ID`), high-resolution thumbnail display, video title & metadata preview, 1-click downloads (1080p, 720p, 360p, MP3), and official Telegram Bot promotion for organic Google visitors.

---

## 🚀 How to Deploy on Firebase Hosting (Free in 2 Minutes)

### Step 1: Open Terminal in `web` folder
In your terminal or PowerShell:
```powershell
cd "d:\one drive\OneDrive\Desktop\instagram reel downloader bot\reeldrop-bot\web"
```

### Step 2: Install Firebase CLI (if not already installed)
```powershell
npm install -g firebase-tools
```

### Step 3: Login to Google / Firebase
```powershell
firebase login
```
*(A browser window will open — simply sign in with your Google account).*

### Step 4: Initialize Firebase Hosting
```powershell
firebase init hosting
```
- Select: **Use an existing project** (or **Create a new project** if you don't have one yet in Firebase Console).
- What do you want to use as your public directory? Enter: `.` (just a single dot, since `index.html` is right here).
- Configure as a single-page app? Enter: `y`.
- Set up automatic builds and deploys with GitHub? Enter: `n`.
- Overwrite index.html? Enter: `n` (Important! Keep our existing index.html).

### Step 5: Deploy!
```powershell
firebase deploy --only hosting
```

Your website will immediately be live at:
`https://<your-project-name>.web.app`

---

## 🔗 Linking with your Telegram Bot

Once deployed, set the base URL in your bot or environment variables:
`https://<your-project-name>.web.app/?v=VIDEO_ID`

When a user in Telegram clicks "Download", it opens your branded website with the video already loaded, and organic Google visitors will see your bot link `@instareeldownloaderr_bot`!
