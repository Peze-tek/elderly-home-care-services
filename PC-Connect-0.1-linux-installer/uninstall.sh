#!/usr/bin/env bash
set -euo pipefail
rm -rf "$HOME/.local/share/pc-connect"
rm -f "$HOME/.local/bin/pc-connect"
rm -f "$HOME/.local/share/applications/pc-connect.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/pc-connect.svg"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi
echo "PC Connect has been removed."
