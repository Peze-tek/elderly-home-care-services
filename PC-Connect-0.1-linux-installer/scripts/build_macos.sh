#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
python3 -m pip install -U pyinstaller
python3 -m PyInstaller --clean --noconfirm --windowed --name "PC Connect" src/pc_connect/main.py
printf 'Build complete: dist/PC Connect.app\n'
