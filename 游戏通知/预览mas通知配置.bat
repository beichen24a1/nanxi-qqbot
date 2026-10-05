@echo off
REM Preview only: show what would be written into AUTO-MAS config (no changes).
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"D:\dsh\QQbot\venv312\Scripts\python.exe" "%~dp0apply_mas_webhook.py"
pause
