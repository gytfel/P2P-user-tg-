@echo off
rem Double-click to run: installs everything into this folder and opens the menu.
setlocal
cd /d "%~dp0"
title Telegram username parser

rem Temporary files go next to the parser, not to drive C: (avoids "No space left on device").
if not exist ".tmp" mkdir ".tmp"
set "TEMP=%~dp0.tmp"
set "TMP=%~dp0.tmp"

if exist ".venv\Scripts\python.exe" goto deps

set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
    python --version >nul 2>nul && set "PY=python"
)
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(sys.version_info < (3, 10))" || goto oldpython

echo Creating Python environment in .venv ...
%PY% -m venv .venv || goto fail

:deps
".venv\Scripts\python.exe" -c "import httpx, telethon, dotenv, python_socks" >nul 2>nul && goto run
echo Installing libraries - only the first time, 1-2 minutes ...
".venv\Scripts\python.exe" -m pip install --no-cache-dir --disable-pip-version-check -r requirements.txt || goto fail

:run
".venv\Scripts\python.exe" -m tgparser
if errorlevel 1 pause
exit /b

:nopython
echo.
echo Python not found.
echo Install Python 3.10 or newer from https://www.python.org/downloads/
echo IMPORTANT: tick "Add python.exe to PATH" in the installer, then run start.bat again.
start "" https://www.python.org/downloads/
pause
exit /b 1

:oldpython
echo.
echo Python is too old: version 3.10 or newer is needed - https://www.python.org/downloads/
pause
exit /b 1

:fail
echo.
echo Something went wrong - see the messages above and send a screenshot of this window.
pause
exit /b 1
