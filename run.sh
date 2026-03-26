#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 &>/dev/null; then
  echo "python3 not found. Install Python 3.10+ from python.org or Homebrew."
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

pip install -q -r requirements.txt

if [[ ! -f .venv/.playwright_chromium_ok ]]; then
  echo "Installing Chromium for Playwright (one-time, may take a minute)..."
  python -m playwright install chromium
  touch .venv/.playwright_chromium_ok
fi

exec python download.py "$@"
