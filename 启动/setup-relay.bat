@echo off
title AstrDsh Relay setup
echo ==========================================
echo    AstrDsh Relay setup
echo ==========================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-relay.ps1"
set RC=%ERRORLEVEL%
echo.
echo ==========================================
echo    Finished. ExitCode = %RC%
if not "%RC%"=="0" echo    !! There were errors above - screenshot them for the agent.
if "%RC%"=="0" echo    OK - now restart DSH and AstrBot as the script says.
echo ==========================================
pause
