# PC Connect 4.0

PC Connect is a private, direct local-network communication and file-sharing application.

## Security

- TLS 1.3 for all TCP communication.
- Per-device self-signed identity certificate.
- SHA-256 certificate fingerprint authentication.
- TOFU (trust on first use) device pinning.
- Private keys are stored in `~/.pc-connect/security/` with restrictive permissions where supported.
- Discovery remains UDP broadcast only; no chat or file contents are sent through discovery.

On the first connection to a device, PC Connect displays its security fingerprint and asks you to trust it. Once trusted, a changed certificate is rejected instead of silently accepted.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pc-connect
```
