"""Explicit JSON schema migration behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reminiscence.storage.migration import (
    CURRENT_SCHEMA_VERSION,
    JsonMigrationError,
    migrate_data_directory,
)


def _legacy_configuration() -> dict[str, object]:
    return {
        "routines": [],
        "photos": [],
        "conversation": {"suggestion_time": "14:00"},
    }


def test_dry_run_does_not_create_or_modify_documents(tmp_path: Path) -> None:
    configuration_path = tmp_path / "configuration.json"
    configuration_path.write_text(
        json.dumps(_legacy_configuration()),
        encoding="utf-8",
    )

    results = migrate_data_directory(tmp_path, apply=False)

    assert all(result.changed for result in results)
    assert "schema_version" not in json.loads(
        configuration_path.read_text(encoding="utf-8")
    )
    assert not (tmp_path / "activity_metrics.json").exists()


def test_apply_versions_existing_and_creates_all_known_documents(
    tmp_path: Path,
) -> None:
    configuration_path = tmp_path / "configuration.json"
    configuration_path.write_text(
        json.dumps(_legacy_configuration()),
        encoding="utf-8",
    )

    first_results = migrate_data_directory(tmp_path, apply=True)
    second_results = migrate_data_directory(tmp_path, apply=True)

    assert all(result.changed for result in first_results)
    assert not any(result.changed for result in second_results)
    for path in tmp_path.glob("*.json"):
        root = json.loads(path.read_text(encoding="utf-8"))
        assert root["schema_version"] == CURRENT_SCHEMA_VERSION
    assert json.loads(configuration_path.read_text(encoding="utf-8"))[
        "conversation"
    ] == {"suggestion_time": "14:00"}


def test_migration_rejects_corrupt_json_without_creating_other_documents(
    tmp_path: Path,
) -> None:
    path = tmp_path / "configuration.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(JsonMigrationError, match="failed to read"):
        migrate_data_directory(tmp_path, apply=True)

    assert path.read_text(encoding="utf-8") == "not-json"
    assert not (tmp_path / "activity_metrics.json").exists()


def test_migration_rejects_future_schema(tmp_path: Path) -> None:
    path = tmp_path / "configuration.json"
    path.write_text(
        json.dumps({**_legacy_configuration(), "schema_version": 99}),
        encoding="utf-8",
    )

    with pytest.raises(JsonMigrationError, match="unsupported schema_version"):
        migrate_data_directory(tmp_path, apply=False)


def test_migration_rejects_invalid_known_sections(tmp_path: Path) -> None:
    path = tmp_path / "activity_metrics.json"
    path.write_text(
        json.dumps({"routine_executions": {}, "conversation_sessions": []}),
        encoding="utf-8",
    )

    with pytest.raises(JsonMigrationError, match="routine_executions"):
        migrate_data_directory(tmp_path, apply=False)
