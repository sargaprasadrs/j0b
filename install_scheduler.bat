@echo off
REM ============================================================
REM  Install/remove the daily Windows Task Scheduler job "j0b AutoSend"
REM
REM  Usage:
REM    install_scheduler.bat            -> schedule daily at 09:00
REM    install_scheduler.bat 07:30      -> schedule daily at 07:30
REM    install_scheduler.bat uninstall  -> remove the scheduled task
REM
REM  The task runs auto_send.py directly (it reads client_secret.json +
REM  token.json itself and appends to data\auto_send.log). Drafts only -
REM  nothing is ever sent. It runs when you are logged in; to run even when
REM  logged out you must pass /ru DOMAIN\username /rp password.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY (
    where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
    echo [j0b] Python not found. Install it from https://www.python.org/downloads/
    pause
    exit /b 1
)
for /f "delims=" %%i in ('%PY% -c "import sys;print(sys.executable)"') do set "PYPATH=%%i"
if "%PYPATH%"=="" (
    echo [j0b] Python not found.
    pause
    exit /b 1
)

if /i "%~1"=="uninstall" (
    schtasks /delete /f /tn "j0b AutoSend"
    echo [j0b] scheduled task removed.
    exit /b 0
)

set "STARTTIME=%~1"
if "%STARTTIME%"=="" set "STARTTIME=09:00"

schtasks /create /f /tn "j0b AutoSend" /sc daily /st %STARTTIME% /tr "'%PYPATH%' '%~dp0auto_send.py'"

echo.
echo [j0b] scheduled 'j0b AutoSend' to run daily at %STARTTIME%.
echo [j0b] make sure client_secret.json exists and you ran: python gmail_setup.py
echo [j0b] remove with:  install_scheduler.bat uninstall
echo.
pause
