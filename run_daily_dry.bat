@echo off
REM ============================================================
REM  j0b dry-run - previews today's send plan, SENDS NOTHING
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

%PY% "%~dp0auto_send.py" --dry-run %*
echo.
echo [j0b] dry-run finished - nothing was sent.
pause
