"""Pre-migration backup and exact JSON directory restoration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reminiscence.storage import legacy_snapshot as legacy_snapshot_module
from reminiscence.storage.legacy_snapshot import (
    create_legacy_snapshot,
    restore_legacy_snapshot,
    verify_legacy_snapshot,
)
from reminiscence.storage.migration import migrate_data_directory
from reminiscence.storage.snapshot import JsonSnapshotError


def _write(path: Path, value: object) -> bytes:
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    path.write_bytes(data)
    return data


def test_legacy_snapshot_restores_exact_json_membership_after_migration(
    tmp_path: Path,
) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    configuration = _write(
        data_directory / "configuration.json",
        {"photos": [], "conversation": {"suggestion_time": "14:00"}, "routines": []},
    )
    activity = _write(
        data_directory / "activity_metrics.json",
        {"routine_executions": [], "conversation_sessions": []},
    )
    (data_directory / ".instance.lock").write_text("not-json", encoding="utf-8")

    snapshot = create_legacy_snapshot(
        data_directory,
        tmp_path / "backups",
        snapshot_id="legacy-before-v1",
    )
    migrate_data_directory(data_directory, apply=True)
    assert len(tuple(data_directory.glob("*.json"))) > 2

    restore_legacy_snapshot(snapshot, data_directory)

    assert {path.name for path in data_directory.glob("*.json")} == {
        "configuration.json",
        "activity_metrics.json",
    }
    assert (data_directory / "configuration.json").read_bytes() == configuration
    assert (data_directory / "activity_metrics.json").read_bytes() == activity
    assert (data_directory / ".instance.lock").read_text(encoding="utf-8") == "not-json"


def test_legacy_snapshot_rejects_non_object_and_symlink_json(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    _write(data_directory / "array.json", [])
    with pytest.raises(JsonSnapshotError, match="root must be an object"):
        create_legacy_snapshot(
            data_directory,
            tmp_path / "backups",
            snapshot_id="invalid-root",
        )

    (data_directory / "array.json").unlink()
    target = data_directory / "target.txt"
    target.write_text("{}", encoding="utf-8")
    (data_directory / "linked.json").symlink_to(target)
    with pytest.raises(JsonSnapshotError, match="regular file"):
        create_legacy_snapshot(
            data_directory,
            tmp_path / "backups",
            snapshot_id="invalid-link",
        )


def test_legacy_snapshot_detects_checksum_and_unmanifested_file(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    _write(data_directory / "configuration.json", {"routines": []})
    snapshot = create_legacy_snapshot(
        data_directory,
        tmp_path / "backups",
        snapshot_id="tamper",
    )

    (snapshot / "configuration.json").write_text("{}", encoding="utf-8")
    with pytest.raises(JsonSnapshotError, match="checksum mismatch"):
        verify_legacy_snapshot(snapshot)

    snapshot = create_legacy_snapshot(
        data_directory,
        tmp_path / "backups",
        snapshot_id="extra",
    )
    _write(snapshot / "unexpected.json", {})
    with pytest.raises(JsonSnapshotError, match="unmanifested"):
        verify_legacy_snapshot(snapshot)


def test_legacy_restore_rolls_back_exact_current_state_after_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    _write(data_directory / "configuration.json", {"before": True})
    _write(data_directory / "activity_metrics.json", {"before": True})
    snapshot = create_legacy_snapshot(
        data_directory,
        tmp_path / "backups",
        snapshot_id="rollback",
    )
    _write(data_directory / "configuration.json", {"current": 1})
    _write(data_directory / "activity_metrics.json", {"current": 2})
    _write(data_directory / "new.json", {"current": 3})
    current = {
        path.name: path.read_bytes() for path in data_directory.glob("*.json")
    }
    real_write = legacy_snapshot_module.atomic_write_bytes
    calls = 0

    def fail_second_write(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise JsonSnapshotError("injected failure")
        real_write(path, data)

    monkeypatch.setattr(
        legacy_snapshot_module,
        "atomic_write_bytes",
        fail_second_write,
    )

    with pytest.raises(JsonSnapshotError, match="original data restored"):
        restore_legacy_snapshot(snapshot, data_directory)

    assert {
        path.name: path.read_bytes() for path in data_directory.glob("*.json")
    } == current
