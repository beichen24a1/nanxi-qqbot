@echo off
REM Wuthering Waves daily done -> Nanxi notify
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"D:\dsh\QQbot\venv312\Scripts\python.exe" "%~dp0nanxi_notify.py" wutheringwaves %*
pause
