from pathlib import Path

from pc_connect.security.identity import IdentityManager


def test_identity_is_stable(tmp_path: Path):
    first = IdentityManager(tmp_path)
    fp = first.fingerprint()
    device_id = first.device_id
    second = IdentityManager(tmp_path)
    assert second.device_id == device_id
    assert second.fingerprint() == fp


def test_trust_pin(tmp_path: Path):
    identity = IdentityManager(tmp_path)
    identity.trust("device-1", "ABC123")
    assert identity.is_trusted("device-1", "ABC123")
    assert not identity.is_trusted("device-1", "BAD")
