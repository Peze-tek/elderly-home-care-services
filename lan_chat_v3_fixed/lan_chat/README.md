# LAN Chat v3

## Files
- `app.py` - Tkinter GUI, discovery, encrypted connections, chat, file/folder transfers.
- `protocol.py` - length-framed TCP protocol. Binary file data is never parsed as text.
- `history.py` - persistent transfer history.

## Start

```bash
python3 app.py
```

Open it on two computers connected to the same LAN/Wi-Fi.

## OpenSSL

The application creates a local TLS certificate on first start. OpenSSL must be installed and available as `openssl` in PATH.

Ubuntu/Debian:

```bash
sudo apt install openssl
```

## Security model

- TLS 1.2+ encrypts the connection.
- Each device gets a persistent device ID and TLS certificate.
- First connection uses trust-on-first-use: the certificate fingerprint is shown before trust.
- Later connections reject a changed certificate for the same device ID.
- Incoming unknown devices require explicit approval.
- Received file names are sanitized.
- Received files are written to temporary `.part` files and renamed only after completion.
- ZIP extraction checks paths and limits file count/expanded size.
- Device discovery expires after a timeout.

The first trust decision is still a TOFU decision: if the network is actively attacked during the very first pairing, the user must verify the displayed fingerprint through another channel to defeat that attack.
