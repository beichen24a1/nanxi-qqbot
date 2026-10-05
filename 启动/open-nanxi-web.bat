@echo off
REM Open Nanxi's DSH web UI (reads the one-time token from its console log).
REM ASCII only: cmd reads this file as GBK, non-ASCII here becomes mojibake.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0open-nanxi-web.ps1" %*