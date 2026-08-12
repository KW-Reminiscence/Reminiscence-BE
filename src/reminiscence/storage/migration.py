"""Explicit schema migration for Reminiscence JSON documents."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reminiscence.storage.json_file import JsonObjectStore, JsonStorageError

CURRENT_SCHEMA_VERSION = 1


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
    DocumentSpec("personal_state.json", {}, _validate_object),
    DocumentSpec("notification_state.json", {}, _validate_object),
    DocumentSpec("auth_sessions.json", {"sessions": []}, _validate_object),
    DocumentSpec("auth_attempts.json", {"attempts": []}, _validate_object),
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


def migrate_document(data_directory: Path, spec: DocumentSpec) -> MigrationResult:
    """Atomically migrate one validated document to the current schema."""

    result = plan_document_migration(data_directory, spec)
    if not result.changed:
        return result
    root, _ = _read_legacy(result.path, spec.defaults)
    merged = {**spec.defaults, **root}
    spec.validate(merged)
    JsonObjectStore(
        result.path,
        missing_default=spec.defaults,
        schema_version=CURRENT_SCHEMA_VERSION,
    ).replace(merged)
    return result


def migrate_data_directory(
    data_directory: Path,
    *,
    apply: bool,
) -> tuple[MigrationResult, ...]:
    """Plan or apply all known JSON document migrations."""

    results = tuple(
        plan_document_migration(data_directory, spec) for spec in DOCUMENT_SPECS
    )
    if not apply:
        return results
    for spec, result in zip(DOCUMENT_SPECS, results, strict=True):
        if result.changed:
            migrate_document(data_directory, spec)
    return results


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
