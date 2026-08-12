"""Explicit JSON schema migration behavior."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from reminiscence.storage import migration
from reminiscence.storage import snapshot as snapshot_module
from reminiscence.storage.migration import (
    CURRENT_SCHEMA_VERSION,
    JsonMigrationError,
    migrate_data_directory,
    validate_data_directory,
)
from reminiscence.storage.snapshot import JsonSnapshotError


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


def test_apply_corrects_existing_data_directory_mode(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir(mode=0o755)
    data_directory.chmod(0o755)

    migrate_data_directory(data_directory, apply=True)

    assert stat.S_IMODE(data_directory.stat().st_mode) == 0o750


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


def test_apply_rolls_back_every_document_after_midway_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration_path = tmp_path / "configuration.json"
    original = json.dumps(_legacy_configuration()).encode("utf-8")
    configuration_path.write_bytes(original)
    real_write = migration.atomic_write_bytes
    calls = 0

    def fail_second_write(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise JsonSnapshotError("simulated disk failure")
        real_write(path, data)

    monkeypatch.setattr(migration, "atomic_write_bytes", fail_second_write)

    with pytest.raises(JsonMigrationError, match="original data restored"):
        migrate_data_directory(tmp_path, apply=True)

    assert configuration_path.read_bytes() == original
    assert not (tmp_path / "activity_metrics.json").exists()


def test_apply_rolls_back_document_replaced_before_directory_fsync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration_path = tmp_path / "configuration.json"
    original = json.dumps(_legacy_configuration()).encode("utf-8")
    configuration_path.write_bytes(original)
    real_fsync_directory = snapshot_module._fsync_directory
    calls = 0

    def fail_first_directory_fsync(path: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated directory fsync failure")
        real_fsync_directory(path)

    monkeypatch.setattr(
        snapshot_module,
        "_fsync_directory",
        fail_first_directory_fsync,
    )

    with pytest.raises(JsonMigrationError, match="original data restored"):
        migrate_data_directory(tmp_path, apply=True)

    assert configuration_path.read_bytes() == original
    assert not (tmp_path / "activity_metrics.json").exists()


def test_strict_validation_requires_migration_and_known_shapes(tmp_path: Path) -> None:
    migrate_data_directory(tmp_path, apply=True)
    validate_data_directory(tmp_path)
    auth_path = tmp_path / "auth_sessions.json"
    auth_path.write_text(
        json.dumps({"schema_version": 1, "sessions": {}}),
        encoding="utf-8",
    )

    with pytest.raises(JsonMigrationError, match="sessions must be an array"):
        validate_data_directory(tmp_path)


@pytest.mark.parametrize(
    "filename",
    [
        "configuration.json",
        "activity_metrics.json",
        "auth_sessions.json",
        "auth_attempts.json",
    ],
)
def test_current_schema_does_not_fill_missing_required_fields(
    tmp_path: Path,
    filename: str,
) -> None:
    migrate_data_directory(tmp_path, apply=True)
    path = tmp_path / filename
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

    with pytest.raises(JsonMigrationError, match="missing fields"):
        validate_data_directory(tmp_path)

    with pytest.raises(JsonMigrationError, match="missing fields"):
        migrate_data_directory(tmp_path, apply=True)
    assert json.loads(path.read_text(encoding="utf-8")) == {"schema_version": 1}


@pytest.mark.parametrize(
    ("filename", "invalid_root", "message"),
    [
        (
            "configuration.json",
            {
                "schema_version": 1,
                "routines": [None],
                "photos": [],
                "conversation": {},
            },
            "each routine must be an object",
        ),
        (
            "activity_metrics.json",
            {
                "schema_version": 1,
                "routine_executions": [None],
                "conversation_sessions": [],
            },
            "each routine execution must be an object",
        ),
        (
            "notification_state.json",
            {
                "schema_version": 1,
                "anomaly_notification_attempted": False,
                "updated_at": "2026-08-13T12:00:00",
            },
            "timezone-aware",
        ),
    ],
)
def test_strict_validation_rejects_invalid_nested_domain_values(
    tmp_path: Path,
    filename: str,
    invalid_root: dict[str, object],
    message: str,
) -> None:
    migrate_data_directory(tmp_path, apply=True)
    (tmp_path / filename).write_text(json.dumps(invalid_root), encoding="utf-8")

    with pytest.raises(JsonMigrationError, match=message):
        validate_data_directory(tmp_path)


@pytest.mark.parametrize(
    ("section", "observation", "message"),
    [
        (
            "routine_observations",
            {"target_date": "2026-08-12", "values": [2, 0, 0, 0, 1, 0]},
            "ratios",
        ),
        (
            "routine_observations",
            {"target_date": "2026-08-12", "values": [0, 0, -1, 0, 1, 0]},
            "delays",
        ),
        (
            "routine_observations",
            {"target_date": "2026-08-12", "values": [0, 0, 0, 0, 1, 1.5]},
            "integer",
        ),
        (
            "conversation_quality_observations",
            {
                "session_id": "session-1",
                "completed_at": "2026-08-12T12:00:00+09:00",
                "values": [-1, 0, 0, 0, 0],
            },
            "negative",
        ),
        (
            "conversation_quality_observations",
            {
                "session_id": "session-1",
                "completed_at": "2026-08-12T12:00:00+09:00",
                "values": [1.5, 0, 0, 0, 0],
            },
            "integers",
        ),
    ],
)
def test_strict_validation_rejects_semantically_invalid_observations(
    tmp_path: Path,
    section: str,
    observation: dict[str, object],
    message: str,
) -> None:
    migrate_data_directory(tmp_path, apply=True)
    path = tmp_path / "activity_metrics.json"
    root = json.loads(path.read_text(encoding="utf-8"))
    root[section] = [observation]
    path.write_text(json.dumps(root), encoding="utf-8")

    with pytest.raises(JsonMigrationError, match=message):
        validate_data_directory(tmp_path)


@pytest.mark.parametrize(
    ("baseline_root", "message"),
    [
        (
            {"routine_vectors": [[2, 0, 0, 0, 1, 0]] * 28},
            "ratios",
        ),
        (
            {"routine_vectors": [[0, 0, -1, 0, 1, 0]] * 28},
            "delays",
        ),
        (
            {"routine_vectors": [[0, 0, 0, 0, 1, 1.5]] * 28},
            "streak",
        ),
        (
            {"conversation_quality_vectors": [[-1, 0, 0, 0, 0]] * 20},
            "negative",
        ),
        (
            {"conversation_quality_vectors": [[1.5, 0, 0, 0, 0]] * 20},
            "integers",
        ),
        (
            {"participation_weekly_turn_mean": 20},
            "model settings",
        ),
    ],
)
def test_strict_validation_rejects_semantically_invalid_baselines(
    tmp_path: Path,
    baseline_root: dict[str, object],
    message: str,
) -> None:
    migrate_data_directory(tmp_path, apply=True)
    path = tmp_path / "anomaly_baseline.json"
    path.write_text(
        json.dumps({"schema_version": 1, **baseline_root}),
        encoding="utf-8",
    )

    with pytest.raises(JsonMigrationError, match=message):
        validate_data_directory(tmp_path)


def test_strict_validation_rejects_multiple_tablet_sessions(tmp_path: Path) -> None:
    migrate_data_directory(tmp_path, apply=True)
    path = tmp_path / "auth_sessions.json"
    session = {
        "token_hash": "a" * 64,
        "credential_fingerprint": "b" * 64,
        "role": "TABLET",
        "created_at": "2026-08-13T12:00:00+09:00",
        "expires_at": "2026-09-13T12:00:00+09:00",
    }
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sessions": [session, {**session, "token_hash": "c" * 64}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(JsonMigrationError, match="one Tablet"):
        validate_data_directory(tmp_path)
