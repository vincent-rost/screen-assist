#!/usr/bin/env bash
# One-time setup: creates a venv with rumps + pynput.
# Re-run after changing requirements.txt.

set -euo pipefail
cd "$(dirname "$0")"

if ! command -v displayplacer >/dev/null 2>&1; then
  echo "Installing displayplacer…"
  brew install jakehilborn/jakehilborn/displayplacer
fi

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
  echo "Installing python-tk@3.14 (tkinter for Homebrew Python)…"
  brew install python-tk@3.14
fi

if [[ ! -d .venv ]]; then
  echo "Creating venv…"
  python3 -m venv .venv
fi

echo "Installing Python dependencies…"
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt

cat <<EOF

Setup complete.

Run the menu bar app:
  .venv/bin/python screen_switcher.py

Open the settings window:
  .venv/bin/python screen_switcher.py --config

Install launch agent (start at login + run 24/7):
  .venv/bin/python screen_switcher.py --install-agent

Note: pynput needs Input Monitoring permission. The first time the
hotkey listener runs, macOS will prompt — grant it for Python.
EOF
