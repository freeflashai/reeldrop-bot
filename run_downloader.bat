@echo off
title ReelDrop Video Downloader
cd /d "%~dp0"
.\venv\Scripts\python download_now.py
pause
