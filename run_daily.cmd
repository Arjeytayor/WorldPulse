@echo off
REM WorldPulse daily run -- invoked by Windows Task Scheduler.
REM
REM Calls .venv\Scripts\python.exe explicitly rather than `python`: the Store
REM Python on PATH is a 0-byte execution alias that does not resolve outside an
REM interactive user session, so a scheduled task using it fails with 0x2.
REM
REM The exit code is propagated so Task Scheduler's "Last Run Result" column
REM shows 0x1 on a failed run instead of a permanent 0x0.

cd /d "%~dp0"

set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

if not exist "logs" mkdir "logs"

echo.>> "logs\scheduled.log"
echo ==================== %DATE% %TIME% ====================>> "logs\scheduled.log"

".venv\Scripts\python.exe" run_once.py >> "logs\scheduled.log" 2>&1
set RC=%ERRORLEVEL%

echo ---- exit code: %RC% ---->> "logs\scheduled.log"
exit /b %RC%
