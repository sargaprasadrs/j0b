@echo off
REM ============================================================
REM  j0b DAILY AUTO-DRAFT - double-click to run everything.
REM
REM  What this does, in order:
REM    1. finds Python
REM    2. installs missing dependencies (pip install -r requirements.txt)
REM    3. one-time Gmail API authorization (browser opens, click Allow once)
REM    4. runs the whole pipeline:
REM         fetch fresh jobs -> score vs your profile -> dedupe
REM         (never same person/company twice) -> resolve recipient emails
REM         -> opencode writes a personalized subject+body from your resume
REM         -> saves each as a GMAIL DRAFT with your resume attached
REM    5. shows a summary and keeps the window open.
REM
REM  DRAFTS ONLY. Nothing is ever sent - you review and hit Send yourself.
REM  Every run is logged to data\auto_send.log.
REM ============================================================
setlocal EnableExtensions
title j0b - daily auto-draft
cd /d "%~dp0"

echo ============================================
echo  j0b daily auto-draft
echo  (creates Gmail drafts only - never sends)
echo ============================================
echo.

REM ---- 1. find a Python interpreter ----
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY (
    where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
    echo [j0b] ERROR: Python not found. Install it from https://www.python.org/downloads/
    pause
    exit /b 1
)
%PY% -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo [j0b] ERROR: Python is not working correctly.
    pause
    exit /b 1
)

REM ---- 2. dependencies (installs once, only if missing) ----
%PY% -c "import googleapiclient, google_auth_oauthlib" >nul 2>&1
if errorlevel 1 (
    echo [j0b] installing dependencies - one time, takes a minute or two...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [j0b] ERROR: dependency install failed - run:  %PY% -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

REM ---- 3. Gmail API one-time setup ----
if not exist "%~dp0client_secret.json" (
    echo [j0b] ERROR: client_secret.json is missing.
    echo [j0b] Get it from Google Cloud - see gmail_drafts.py for the 4 steps -
    echo [j0b] save it in this folder, then run this file again.
    pause
    exit /b 1
)
if not exist "%~dp0token.json" (
    echo [j0b] first run - authorizing Gmail, a browser will open - click Allow once...
    %PY% "%~dp0gmail_setup.py"
    if errorlevel 1 (
        echo [j0b] ERROR: Gmail authorization failed - see the message above.
        pause
        exit /b 1
    )
)

REM ---- optional warnings (not blocking) ----
if not exist "%~dp0autoapply\data\resume.pdf" (
    echo [j0b] NOTE: no resume at autoapply\data\resume.pdf - drafts will have no attachment.
)
where opencode >nul 2>&1 || (
    echo [j0b] NOTE: opencode not found - emails will use the built-in template.
)

REM ---- 4. run the pipeline ----
echo.
echo [j0b] starting at %date% %time%
%PY% "%~dp0auto_send.py" %*
set "RC=%ERRORLEVEL%"

REM ---- 5. summary ----
echo.
echo ============================================
if "%RC%"=="0" (
    echo  DONE - check your Gmail  Drafts  folder.
) else (
    echo  FINISHED with exit code %RC% - see the log above.
)
echo  Log: %~dp0data\auto_send.log
echo ============================================
echo.
pause
exit /b %RC%
