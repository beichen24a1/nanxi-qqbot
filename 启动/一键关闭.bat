@echo off
REM Nanxi QQ bot - stop everything (AstrBot by port, then SnowLuma container).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_all.ps1"
pause
