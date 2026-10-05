import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


class IdentityManager:
    """Creates and stores a per-device TLS identity and TOFU trust pins."""
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.security_dir = self.data_dir / "security"
        self.security_dir.mkdir(parents=True, exist_ok=True)
        self.key_path = self.security_dir / "device.key"
        self.cert_path = self.security_dir / "device.crt"
        self.meta_path = self.security_dir / "identity.json"
        self.trust_path = self.security_dir / "trusted_devices.json"
        self.device_id = self._load_or_create_identity()
        self._ensure_certificate()

    def _load_or_create_identity(self):
        if self.meta_path.exists():
            try:
                data = json.loads(self.meta_path.read_text(encoding="utf-8"))
                if data.get("device_id"):
                    return str(data["device_id"])
            except (OSError, ValueError, TypeError):
                pass
        device_id = str(uuid.uuid4())
        self.meta_path.write_text(json.dumps({"device_id": device_id}, indent=2), encoding="utf-8")
        return device_id

    def _ensure_certificate(self):
        if self.key_path.exists() and self.cert_path.exists():
            return
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, f"PC Connect {self.device_id}"),
        ])
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("pc-connect.local")]), critical=False)
            .sign(key, hashes.SHA256())
        )
        self.key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        self.cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass

    def certificate_der(self):
        cert = x509.load_pem_x509_certificate(self.cert_path.read_bytes())
        return cert.public_bytes(serialization.Encoding.DER)

    def fingerprint(self, cert_der=None):
        return hashlib.sha256(cert_der or self.certificate_der()).hexdigest().upper()

    def short_fingerprint(self, cert_der=None):
        return ":".join(self.fingerprint(cert_der)[i:i+2] for i in range(0, 16, 2))

    def load_trust(self):
        if not self.trust_path.exists():
            return {}
        try:
            data = json.loads(self.trust_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def is_trusted(self, device_id, fingerprint):
        return self.load_trust().get(device_id) == fingerprint

    def trust(self, device_id, fingerprint, name=""):
        trusted = self.load_trust()
        trusted[device_id] = fingerprint
        self.trust_path.write_text(json.dumps(trusted, indent=2), encoding="utf-8")
        try:
            os.chmod(self.trust_path, 0o600)
        except OSError:
            pass

    def forget(self, device_id):
        trusted = self.load_trust()
        trusted.pop(device_id, None)
        self.trust_path.write_text(json.dumps(trusted, indent=2), encoding="utf-8")
