"""Explicit schema migration for Reminiscence JSON documents."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reminiscence.storage.json_file import JsonStorageError
from reminiscence.storage.schema import CURRENT_SCHEMA_VERSION
from reminiscence.storage.snapshot import (
    JsonSnapshotError,
    atomic_write_bytes,
    exclusive_snapshot_lock,
)


class JsonMigrationError(JsonStorageError):
    """Raised when a document cannot be migrated without data loss."""


@dataclass(frozen=True, slots=True)
class DocumentSpec:
    """One known JSON document and its root-level structural validation."""

    filename: str
    defaults: dict[str, Any]
    validate: Callable[[dict[str, Any]], None]


def _require_list(root: dict[str, Any], key: str) -> None:
    value = root.get(key)
    if not isinstance(value, list):
        raise JsonMigrationError(f"{key} must be an array")


def _validate_configuration(root: dict[str, Any]) -> None:
    _require_list(root, "routines")
    _require_list(root, "photos")
    conversation = root.get("conversation")
    if not isinstance(conversation, dict):
        raise JsonMigrationError("conversation must be an object")


def _validate_activity(root: dict[str, Any]) -> None:
    _require_list(root, "routine_executions")
    _require_list(root, "conversation_sessions")


def _validate_object(root: dict[str, Any]) -> None:
    if not isinstance(root, dict):
        raise JsonMigrationError("JSON root must be an object")


def _validate_personal_state(root: dict[str, Any]) -> None:
    keys = set(root) - {"schema_version"}
    if not keys:
        return
    required = {"status", "evaluated_at", "routine", "conversation"}
    missing = required - keys
    if missing:
        raise JsonMigrationError(
            "personal_state is missing fields: " + ", ".join(sorted(missing))
        )
    if not isinstance(root["status"], str) or not isinstance(root["evaluated_at"], str):
        raise JsonMigrationError("personal_state status and evaluated_at must be strings")
    if not isinstance(root["routine"], dict) or not isinstance(
        root["conversation"], dict
    ):
        raise JsonMigrationError("personal_state domains must be objects")


def _validate_notification_state(root: dict[str, Any]) -> None:
    attempted = root.get("anomaly_notification_attempted", False)
    if not isinstance(attempted, bool):
        raise JsonMigrationError("anomaly_notification_attempted must be a boolean")
    updated_at = root.get("updated_at")
    if updated_at is not None and not isinstance(updated_at, str):
        raise JsonMigrationError("notification updated_at must be a string or null")


def _validate_auth_sessions(root: dict[str, Any]) -> None:
    _require_list(root, "sessions")


def _validate_auth_attempts(root: dict[str, Any]) -> None:
    _require_list(root, "attempts")


DOCUMENT_SPECS = (
    DocumentSpec(
        "configuration.json",
        {"routines": [], "photos": [], "conversation": {}},
        _validate_configuration,
    ),
    DocumentSpec(
        "activity_metrics.json",
        {"routine_executions": [], "conversation_sessions": []},
        _validate_activity,
    ),
    DocumentSpec("anomaly_baseline.json", {}, _validate_object),
    DocumentSpec("personal_state.json", {}, _validate_personal_state),
    DocumentSpec("notification_state.json", {}, _validate_notification_state),
    DocumentSpec("auth_sessions.json", {"sessions": []}, _validate_auth_sessions),
    DocumentSpec("auth_attempts.json", {"attempts": []}, _validate_auth_attempts),
)


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Outcome for one document migration."""

    path: Path
    changed: bool
    created: bool


def _read_legacy(path: Path, defaults: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return json.loads(json.dumps(defaults)), True
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JsonMigrationError(f"failed to read JSON object from {path}") from exc
    if not isinstance(value, dict):
        raise JsonMigrationError(f"JSON root must be an object: {path}")
    return value, False


def plan_document_migration(data_directory: Path, spec: DocumentSpec) -> MigrationResult:
    """Validate one legacy document and report whether schema metadata is needed."""

    path = data_directory / spec.filename
    root, created = _read_legacy(path, spec.defaults)
    existing_version = root.get("schema_version")
    if existing_version not in {None, CURRENT_SCHEMA_VERSION} or isinstance(
        existing_version, bool
    ):
        raise JsonMigrationError(
            f"unsupported schema_version for {path}: {existing_version!r}"
        )
    merged = {**spec.defaults, **root}
    spec.validate(merged)
    return MigrationResult(
        path=path,
        changed=created or existing_version is None,
        created=created,
    )


def _prepared_document(data_directory: Path, spec: DocumentSpec) -> tuple[MigrationResult, bytes]:
    path = data_directory / spec.filename
    root, created = _read_legacy(path, spec.defaults)
    existing_version = root.get("schema_version")
    if existing_version not in {None, CURRENT_SCHEMA_VERSION} or isinstance(
        existing_version, bool
    ):
        raise JsonMigrationError(
            f"unsupported schema_version for {path}: {existing_version!r}"
        )
    merged = {**spec.defaults, **root, "schema_version": CURRENT_SCHEMA_VERSION}
    spec.validate(merged)
    return (
        MigrationResult(
            path=path,
            changed=created or existing_version is None,
            created=created,
        ),
        (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _rollback_documents(
    data_directory: Path,
    originals: dict[str, bytes | None],
    applied: list[str],
) -> list[str]:
    errors: list[str] = []
    for filename in reversed(applied):
        path = data_directory / filename
        original = originals[filename]
        try:
            if original is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, original)
        except (OSError, JsonSnapshotError) as exc:
            errors.append(f"{filename}: {exc}")
    return errors


def migrate_data_directory(
    data_directory: Path,
    *,
    apply: bool,
) -> tuple[MigrationResult, ...]:
    """Plan or apply all known JSON document migrations."""

    if not apply:
        return tuple(
            plan_document_migration(data_directory, spec) for spec in DOCUMENT_SPECS
        )
    with exclusive_snapshot_lock(data_directory):
        prepared = tuple(
            _prepared_document(data_directory, spec) for spec in DOCUMENT_SPECS
        )
        originals = {
            spec.filename: (
                (data_directory / spec.filename).read_bytes()
                if (data_directory / spec.filename).exists()
                else None
            )
            for spec in DOCUMENT_SPECS
        }
        applied: list[str] = []
        try:
            for spec, (result, data) in zip(DOCUMENT_SPECS, prepared, strict=True):
                if result.changed:
                    atomic_write_bytes(result.path, data)
                    applied.append(spec.filename)
        except (OSError, JsonSnapshotError) as exc:
            rollback_errors = _rollback_documents(data_directory, originals, applied)
            if rollback_errors:
                raise JsonMigrationError(
                    "migration failed and rollback was incomplete: "
                    + "; ".join(rollback_errors)
                ) from exc
            raise JsonMigrationError("migration failed; original data restored") from exc
        return tuple(result for result, _ in prepared)


def validate_data_directory(data_directory: Path) -> None:
    """Strictly validate every required versioned application document."""

    with exclusive_snapshot_lock(data_directory):
        for spec in DOCUMENT_SPECS:
            result, _ = _prepared_document(data_directory, spec)
            if result.created or result.changed:
                raise JsonMigrationError(
                    f"document requires explicit migration: {result.path}"
                )


def main(argv: Sequence[str] | None = None) -> int:
    """Run an explicit dry-run or applied migration."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write migrations; without this flag only validate and report",
    )
    arguments = parser.parse_args(argv)
    results = migrate_data_directory(arguments.data_dir, apply=arguments.apply)
    action = "migrated" if arguments.apply else "would migrate"
    for result in results:
        if result.changed:
            print(f"{action}: {result.path}")
        else:
            print(f"current: {result.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
