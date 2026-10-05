@echo off
REM Apply Nanxi notify webhooks into AUTO-MAS user configs (with backup).
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"D:\dsh\QQbot\venv312\Scripts\python.exe" "%~dp0apply_mas_webhook.py" --apply
pause
