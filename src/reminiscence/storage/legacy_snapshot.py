"""Checksummed pre-migration snapshots for legacy JSON directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from reminiscence.storage.snapshot import (
    JsonSnapshotError,
    _fsync_directory,
    atomic_write_bytes,
    exclusive_snapshot_lock,
    remove_file_durably,
)

LEGACY_SNAPSHOT_SCHEMA_VERSION = 1
LEGACY_SNAPSHOT_KIND = "legacy-json-directory"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_identifier(identifier: str) -> None:
    if (
        not identifier
        or identifier in {".", ".."}
        or Path(identifier).name != identifier
    ):
        raise JsonSnapshotError("snapshot_id must be one path-safe segment")


def _validate_json_object(path: Path, data: bytes) -> None:
    try:
        value: object = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JsonSnapshotError(f"invalid legacy JSON document: {path}") from exc
    if not isinstance(value, dict):
        raise JsonSnapshotError(f"legacy JSON root must be an object: {path}")


def _read_legacy_documents(data_directory: Path) -> dict[str, bytes]:
    documents: dict[str, bytes] = {}
    try:
        paths = sorted(data_directory.glob("*.json"))
    except OSError as exc:
        raise JsonSnapshotError(
            f"failed to list legacy JSON directory: {data_directory}"
        ) from exc
    if not paths:
        raise JsonSnapshotError("legacy data directory contains no JSON documents")
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise JsonSnapshotError(f"legacy JSON path must be a regular file: {path}")
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise JsonSnapshotError(f"failed to read legacy JSON document: {path}") from exc
        _validate_json_object(path, data)
        documents[path.name] = data
    return documents


def create_legacy_snapshot(
    data_directory: Path,
    backup_directory: Path,
    *,
    snapshot_id: str,
) -> Path:
    """Preserve every legacy JSON file and exact membership before migration."""

    _validate_identifier(snapshot_id)
    backup_directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    destination = backup_directory / snapshot_id
    if destination.exists():
        raise JsonSnapshotError(f"snapshot already exists: {destination}")
    staging = Path(
        tempfile.mkdtemp(
            dir=backup_directory,
            prefix=f".{snapshot_id}.",
            suffix=".tmp",
        )
    )
    os.chmod(staging, 0o700)
    try:
        with exclusive_snapshot_lock(data_directory):
            documents = _read_legacy_documents(data_directory)
        files: list[dict[str, Any]] = []
        for filename, data in documents.items():
            output_path = staging / filename
            output_path.write_bytes(data)
            output_path.chmod(0o600)
            files.append(
                {"name": filename, "size": len(data), "sha256": _sha256(data)}
            )
        manifest = {
            "schema_version": LEGACY_SNAPSHOT_SCHEMA_VERSION,
            "kind": LEGACY_SNAPSHOT_KIND,
            "files": files,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_path.chmod(0o600)
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
        raise JsonSnapshotError(
            f"failed to create legacy snapshot: {destination}"
        ) from exc


def verify_legacy_snapshot(snapshot_directory: Path) -> dict[str, bytes]:
    """Verify exact membership, JSON object roots, sizes and hashes."""

    manifest_path = snapshot_directory / "manifest.json"
    try:
        manifest: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JsonSnapshotError(
            f"invalid legacy snapshot manifest: {manifest_path}"
        ) from exc
    if not isinstance(manifest, dict):
        raise JsonSnapshotError("legacy snapshot manifest root must be an object")
    if (
        manifest.get("schema_version") != LEGACY_SNAPSHOT_SCHEMA_VERSION
        or manifest.get("kind") != LEGACY_SNAPSHOT_KIND
    ):
        raise JsonSnapshotError("unsupported legacy snapshot manifest")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise JsonSnapshotError("legacy snapshot files must be a non-empty array")
    documents: dict[str, bytes] = {}
    for item in files:
        if not isinstance(item, dict):
            raise JsonSnapshotError("legacy snapshot file entry must be an object")
        name = item.get("name")
        size = item.get("size")
        digest = item.get("sha256")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not name.endswith(".json")
            or name in documents
        ):
            raise JsonSnapshotError(f"unsafe or duplicate legacy snapshot file: {name!r}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise JsonSnapshotError(f"invalid legacy snapshot size: {name}")
        if not isinstance(digest, str) or len(digest) != 64:
            raise JsonSnapshotError(f"invalid legacy snapshot hash: {name}")
        path = snapshot_directory / name
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise JsonSnapshotError(f"missing legacy snapshot file: {path}") from exc
        if len(data) != size or _sha256(data) != digest:
            raise JsonSnapshotError(f"legacy snapshot checksum mismatch: {path}")
        _validate_json_object(path, data)
        documents[name] = data
    actual_names = {
        path.name
        for path in snapshot_directory.iterdir()
        if path.is_file() and path.name != "manifest.json"
    }
    if actual_names != set(documents):
        raise JsonSnapshotError("legacy snapshot contains unmanifested files")
    return documents


def restore_legacy_snapshot(snapshot_directory: Path, data_directory: Path) -> None:
    """Restore the exact pre-migration JSON membership with rollback on failure."""

    documents = verify_legacy_snapshot(snapshot_directory)
    with exclusive_snapshot_lock(data_directory):
        json_paths = list(data_directory.glob("*.json"))
        unsafe_paths = [
            path for path in json_paths if not path.is_file() or path.is_symlink()
        ]
        if unsafe_paths:
            raise JsonSnapshotError(
                f"current JSON path must be a regular file: {unsafe_paths[0]}"
            )
        current_paths = {
            path.name: path
            for path in json_paths
        }
        touched_names = set(current_paths) | set(documents)
        originals = {
            name: current_paths[name].read_bytes() if name in current_paths else None
            for name in touched_names
        }
        applied: list[str] = []
        try:
            for name in sorted(touched_names):
                applied.append(name)
                path = data_directory / name
                if name in documents:
                    atomic_write_bytes(path, documents[name])
                else:
                    remove_file_durably(path)
        except (OSError, JsonSnapshotError) as exc:
            rollback_errors: list[str] = []
            for name in reversed(applied):
                try:
                    original = originals[name]
                    path = data_directory / name
                    if original is None:
                        remove_file_durably(path)
                    else:
                        atomic_write_bytes(path, original)
                except (OSError, JsonSnapshotError) as rollback_exc:
                    rollback_errors.append(f"{name}: {rollback_exc}")
            if rollback_errors:
                raise JsonSnapshotError(
                    "legacy restore failed and rollback was incomplete: "
                    + "; ".join(rollback_errors)
                ) from exc
            raise JsonSnapshotError(
                "legacy restore failed; original data restored"
            ) from exc


def main(argv: Sequence[str] | None = None) -> int:
    """Create, verify or restore one pre-migration legacy snapshot."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--data-dir", type=Path, required=True)
    create.add_argument("--backup-dir", type=Path, required=True)
    create.add_argument("--snapshot-id", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("snapshot", type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("snapshot", type=Path)
    restore.add_argument("--data-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "create":
        print(
            create_legacy_snapshot(
                arguments.data_dir,
                arguments.backup_dir,
                snapshot_id=arguments.snapshot_id,
            )
        )
    elif arguments.command == "verify":
        verify_legacy_snapshot(arguments.snapshot)
        print(f"verified: {arguments.snapshot}")
    else:
        restore_legacy_snapshot(arguments.snapshot, arguments.data_dir)
        print(f"restored: {arguments.snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
