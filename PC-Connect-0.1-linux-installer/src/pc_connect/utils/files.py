import os
from pathlib import Path
import tempfile
import zipfile


def ensure_data_directories(*directories):
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)


def safe_name(name, default="file"):
    name = os.path.basename(name.replace("\\", "/")).strip()
    for char in '<>:"|?*':
        name = name.replace(char, "_")
    if name in ("", ".", ".."):
        return default
    return name


def unique_path(directory, filename):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    number = 1
    while True:
        candidate = directory / f"{stem} ({number}){suffix}"
        if not candidate.exists():
            return candidate
        number += 1


def format_size(size):
    size = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def create_folder_zip(folder_path):
    folder_path = Path(folder_path).resolve()
    folder_name = folder_path.name
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    zip_path = Path(temp_file.name)
    temp_file.close()
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for root_dir, dirs, files in os.walk(folder_path):
                for dirname in dirs:
                    full_path = Path(root_dir) / dirname
                    relative_path = full_path.relative_to(folder_path)
                    archive.write(full_path, Path(folder_name) / relative_path)
                for filename in files:
                    full_path = Path(root_dir) / filename
                    relative_path = full_path.relative_to(folder_path)
                    archive.write(full_path, Path(folder_name) / relative_path)
        return zip_path, folder_name
    except Exception:
        zip_path.unlink(missing_ok=True)
        raise


def safe_extract_zip(zip_path, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if target != destination and not str(target).startswith(str(destination) + os.sep):
                raise ValueError("Unsafe folder path detected")
        archive.extractall(destination)
