#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
python3 -m pip install -U pyinstaller
python3 -m PyInstaller --clean --noconfirm packaging/pc-connect.spec
printf 'Build complete: dist/PC Connect\n'
