@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.10+ from python.org and add it to PATH.
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)

call .venv\Scripts\activate.bat
pip install -q -r requirements.txt

if not exist ".venv\.playwright_chromium_ok" (
  echo Installing Chromium for Playwright (one-time, may take a minute)...
  python -m playwright install chromium
  type nul > .venv\.playwright_chromium_ok
)

python download.py %*
