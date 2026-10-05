#!/usr/bin/env bash
set -euo pipefail

APP_NAME="PC Connect"
APP_ID="pc-connect"
VERSION="4.0.1"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HOME}/.local/share/pc-connect"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
VENV="${INSTALL_DIR}/.venv"

printf '\n%s\n' "Installing ${APP_NAME} ${VERSION}..."

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is required."
    exit 1
fi

# Install the Ubuntu/Debian runtime pieces only when they are missing.
if ! python3 -c 'import tkinter' >/dev/null 2>&1 || ! python3 -m venv --help >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        echo "Installing required Ubuntu/Debian packages..."
        sudo apt-get update
        sudo apt-get install -y python3-venv python3-tk
    else
        echo "Please install python3-venv and python3-tk, then run this installer again."
        exit 1
    fi
fi

mkdir -p "${HOME}/.local/share" "${BIN_DIR}" "${APP_DIR}" "${ICON_DIR}"
rm -rf "${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"

# Copy the application into a stable per-user location so it does not depend on
# the extracted ZIP remaining in Downloads.
cp -a "${ROOT}/." "${INSTALL_DIR}/"

python3 -m venv "${VENV}"
"${VENV}/bin/python" -m pip install --upgrade pip >/dev/null
"${VENV}/bin/python" -m pip install --no-cache-dir "${INSTALL_DIR}" >/dev/null

cat > "${BIN_DIR}/${APP_ID}" <<EOF2
#!/usr/bin/env bash
exec "${VENV}/bin/python" -m pc_connect "\$@"
EOF2
chmod +x "${BIN_DIR}/${APP_ID}"

cp "${INSTALL_DIR}/packaging/icons/pc-connect.svg" "${ICON_DIR}/pc-connect.svg"

cat > "${APP_DIR}/${APP_ID}.desktop" <<EOF2
[Desktop Entry]
Type=Application
Name=PC Connect
Comment=Private local-network communication and file sharing
Exec=${BIN_DIR}/${APP_ID}
Icon=pc-connect
Terminal=false
Categories=Network;Utility;
StartupNotify=true
EOF2

# Make the launcher available immediately in this terminal and future shells.
case ":${PATH}:" in
    *":${BIN_DIR}:"*) ;;
    *) echo "NOTE: ${BIN_DIR} is not currently in PATH." ;;
esac

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APP_DIR}" >/dev/null 2>&1 || true
fi

printf '\nInstallation complete.\n'
printf 'Launch from the terminal with: %s\n' "${BIN_DIR}/${APP_ID}"
printf 'Or open PC Connect from your Applications menu.\n'
