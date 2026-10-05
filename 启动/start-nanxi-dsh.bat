@echo off
REM Launch Nanxi's isolated DSH instance (port 3081).
REM ASCII only: cmd reads this file as GBK, non-ASCII here becomes mojibake.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-nanxi-dsh.ps1"