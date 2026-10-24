import tarfile
import zipfile
from pathlib import Path

from config import ARCHIVE_EXTENSIONS


def is_archive(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(ext) for ext in ARCHIVE_EXTENSIONS)


def extract_archive(src: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    name = src.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(src, "r") as z:
            z.extractall(dest)
    else:
        with tarfile.open(src, "r:*") as t:
            t.extractall(dest)