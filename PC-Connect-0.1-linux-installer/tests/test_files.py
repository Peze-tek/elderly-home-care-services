from pathlib import Path
from pc_connect.utils.files import safe_name, unique_path, safe_extract_zip
import zipfile


def test_safe_name():
    assert safe_name("../../hello.txt") == "hello.txt"
    assert safe_name(r"C:\\temp\\hello.txt") == "hello.txt"


def test_unique_path(tmp_path):
    first = unique_path(tmp_path, "file.txt")
    first.write_text("x")
    second = unique_path(tmp_path, "file.txt")
    assert second.name == "file (1).txt"


def test_safe_extract_rejects_traversal(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../../evil.txt", "bad")
    try:
        safe_extract_zip(archive, tmp_path / "out")
    except ValueError:
        return
    raise AssertionError("unsafe archive was accepted")
