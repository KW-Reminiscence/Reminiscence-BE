"""Create the poster handoff archive and its SHA-256 manifest."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT.parent
ARCHIVE = OUTPUT_DIR / "Reminiscence_포스터_handoff_최종.zip"
MANIFEST = ROOT / "MANIFEST.sha256"
ARCHIVE_ROOT = "Reminiscence_포스터_handoff_최종"


def package_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path != MANIFEST
        and "__pycache__" not in path.parts
        and path.name != ".DS_Store"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(files: list[Path]) -> None:
    lines = [f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}" for path in files]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_archive(files: list[Path]) -> None:
    temporary = ARCHIVE.with_suffix(".zip.tmp")
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in [*files, MANIFEST]:
            destination = f"{ARCHIVE_ROOT}/{path.relative_to(ROOT).as_posix()}"
            archive.write(path, destination)
    os.replace(temporary, ARCHIVE)


def main() -> None:
    files = package_files()
    write_manifest(files)
    write_archive(files)
    print(ARCHIVE)


if __name__ == "__main__":
    main()
