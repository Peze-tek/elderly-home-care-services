#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
./scripts/build_macos.sh
hdiutil create -volname "PC Connect" -srcfolder "dist/PC Connect.app" -ov -format UDZO -o "dist/PC-Connect.dmg"
printf 'DMG created: dist/PC-Connect.dmg\n'
