"""Consistent checksummed snapshots for versioned JSON application data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any

from reminiscence.storage.documents import (
    DOCUMENT_SPECS_BY_FILENAME,
    JsonDocumentValidationError,
)
from reminiscence.storage.schema import CURRENT_SCHEMA_VERSION, ensure_data_directory

SNAPSHOT_SCHEMA_VERSION = 1
BACKUP_FILENAMES = (
    "configuration.json",
    "activity_metrics.json",
    "anomaly_baseline.json",
    "personal_state.json",
    "notification_state.json",
)


class JsonSnapshotError(RuntimeError):
    """Raised when a snapshot cannot be created or safely restored."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_document(path: Path, data: bytes) -> None:
    try:
        value: object = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JsonSnapshotError(f"invalid JSON document: {path}") from exc
    if not isinstance(value, dict):
        raise JsonSnapshotError(f"JSON root must be an object: {path}")
    version = value.get("schema_version")
    if version != CURRENT_SCHEMA_VERSION or isinstance(version, bool):
        raise JsonSnapshotError(
            f"unsupported schema_version in {path}: {version!r}"
        )
    spec = DOCUMENT_SPECS_BY_FILENAME.get(path.name)
    if spec is None:
        raise JsonSnapshotError(f"unknown JSON document: {path.name}")
    try:
        spec.validate(value)
    except (JsonDocumentValidationError, RuntimeError, ValueError) as exc:
        raise JsonSnapshotError(f"invalid JSON document {path}: {exc}") from exc


@contextmanager
def exclusive_snapshot_lock(data_directory: Path) -> Iterator[None]:
    """Block every cooperating application JSON read and write."""

    ensure_data_directory(data_directory)
    lock_path = data_directory / ".snapshot.lock"
    try:
        with lock_path.open("a+b") as lock_file:
            flock(lock_file.fileno(), LOCK_EX)
            try:
                yield
            finally:
                flock(lock_file.fileno(), LOCK_UN)
    except OSError as exc:
        raise JsonSnapshotError(
            f"failed to lock JSON data directory: {data_directory}"
        ) from exc


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Durably replace one file whose directory-level lock is already held."""

    ensure_data_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise JsonSnapshotError(f"failed to restore JSON document: {path}") from exc


def _read_snapshot_documents(data_directory: Path) -> dict[str, bytes]:
    documents: dict[str, bytes] = {}
    for filename in BACKUP_FILENAMES:
        path = data_directory / filename
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise JsonSnapshotError(f"required JSON document is missing: {path}") from exc
        _validate_document(path, data)
        documents[filename] = data
    return documents


def _default_snapshot_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def create_snapshot(
    data_directory: Path,
    backup_directory: Path,
    *,
    snapshot_id: str | None = None,
) -> Path:
    """Create one atomic snapshot while blocking application JSON writes."""

    identifier = _default_snapshot_id() if snapshot_id is None else snapshot_id
    if not identifier or identifier in {".", ".."} or Path(identifier).name != identifier:
        raise JsonSnapshotError("snapshot_id must be one path-safe segment")
    backup_directory.mkdir(parents=True, exist_ok=True)
    destination = backup_directory / identifier
    if destination.exists():
        raise JsonSnapshotError(f"snapshot already exists: {destination}")
    staging = Path(
        tempfile.mkdtemp(dir=backup_directory, prefix=f".{identifier}.", suffix=".tmp")
    )
    try:
        with exclusive_snapshot_lock(data_directory):
            documents = _read_snapshot_documents(data_directory)
        files: list[dict[str, Any]] = []
        for filename, data in documents.items():
            output_path = staging / filename
            output_path.write_bytes(data)
            files.append(
                {"name": filename, "size": len(data), "sha256": _sha256(data)}
            )
        manifest = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "files": files,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for path in staging.iterdir():
            with path.open("rb") as snapshot_file:
                os.fsync(snapshot_file.fileno())
        _fsync_directory(staging)
        os.replace(staging, destination)
        _fsync_directory(backup_directory)
        return destination
    except (OSError, JsonSnapshotError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, JsonSnapshotError):
            raise
        raise JsonSnapshotError(f"failed to create snapshot: {destination}") from exc


def _load_manifest(snapshot_directory: Path) -> dict[str, Any]:
    path = snapshot_directory / "manifest.json"
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JsonSnapshotError(f"invalid snapshot manifest: {path}") from exc
    if not isinstance(value, dict):
        raise JsonSnapshotError("snapshot manifest root must be an object")
    if value.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise JsonSnapshotError("unsupported snapshot manifest schema_version")
    return value


def verify_snapshot(snapshot_directory: Path) -> dict[str, bytes]:
    """Verify manifest membership, sizes, hashes and JSON schemas."""

    manifest = _load_manifest(snapshot_directory)
    files = manifest.get("files")
    if not isinstance(files, list):
        raise JsonSnapshotError("snapshot manifest files must be an array")
    documents: dict[str, bytes] = {}
    names: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            raise JsonSnapshotError("snapshot file entry must be an object")
        name = item.get("name")
        size = item.get("size")
        digest = item.get("sha256")
        if name not in BACKUP_FILENAMES or name in names:
            raise JsonSnapshotError(f"unexpected or duplicate snapshot file: {name!r}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise JsonSnapshotError(f"invalid snapshot file size: {name}")
        if not isinstance(digest, str) or len(digest) != 64:
            raise JsonSnapshotError(f"invalid snapshot file hash: {name}")
        path = snapshot_directory / name
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise JsonSnapshotError(f"missing snapshot file: {path}") from exc
        if len(data) != size or _sha256(data) != digest:
            raise JsonSnapshotError(f"snapshot checksum mismatch: {path}")
        _validate_document(path, data)
        documents[name] = data
        names.append(name)
    if set(names) != set(BACKUP_FILENAMES):
        raise JsonSnapshotError("snapshot does not contain every required document")
    return documents


def restore_snapshot(snapshot_directory: Path, data_directory: Path) -> None:
    """Verify and atomically restore all backed-up JSON documents."""

    documents = verify_snapshot(snapshot_directory)
    with exclusive_snapshot_lock(data_directory):
        originals: dict[str, bytes | None] = {}
        for filename in documents:
            path = data_directory / filename
            originals[filename] = path.read_bytes() if path.exists() else None
        applied: list[str] = []
        try:
            for filename, data in documents.items():
                applied.append(filename)
                atomic_write_bytes(data_directory / filename, data)
        except (OSError, JsonSnapshotError) as exc:
            rollback_errors: list[str] = []
            for filename in reversed(applied):
                path = data_directory / filename
                original = originals[filename]
                try:
                    if original is None:
                        path.unlink(missing_ok=True)
                    else:
                        atomic_write_bytes(path, original)
                except (OSError, JsonSnapshotError) as rollback_exc:
                    rollback_errors.append(f"{filename}: {rollback_exc}")
            if rollback_errors:
                raise JsonSnapshotError(
                    "snapshot restore failed and rollback was incomplete: "
                    + "; ".join(rollback_errors)
                ) from exc
            raise JsonSnapshotError("snapshot restore failed; original data restored") from exc


def main(argv: Sequence[str] | None = None) -> int:
    """Create, verify or restore a JSON snapshot."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--data-dir", type=Path, required=True)
    create.add_argument("--backup-dir", type=Path, required=True)
    create.add_argument("--snapshot-id")
    verify = subparsers.add_parser("verify")
    verify.add_argument("snapshot", type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("snapshot", type=Path)
    restore.add_argument("--data-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "create":
        print(
            create_snapshot(
                arguments.data_dir,
                arguments.backup_dir,
                snapshot_id=arguments.snapshot_id,
            )
        )
    elif arguments.command == "verify":
        verify_snapshot(arguments.snapshot)
        print(f"verified: {arguments.snapshot}")
    else:
        restore_snapshot(arguments.snapshot, arguments.data_dir)
        print(f"restored: {arguments.snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
