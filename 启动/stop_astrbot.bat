@echo off
REM Stop only AstrBot (by port 6185/3002), leave other programs alone.
set FOUND=0
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":6185" ^| findstr "LISTENING"') do (
  taskkill /F /PID %%p >nul 2>&1
  set FOUND=1
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3002" ^| findstr "LISTENING"') do (
  taskkill /F /PID %%p >nul 2>&1
  set FOUND=1
)
if "%FOUND%"=="1" (
  echo [OK] AstrBot stopped. Other programs unaffected.
) else (
  echo [..] No running AstrBot found.
)
pause
