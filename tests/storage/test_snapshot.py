"""Checksummed JSON snapshot and restore behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reminiscence.storage import snapshot as snapshot_module
from reminiscence.storage.migration import migrate_data_directory
from reminiscence.storage.snapshot import (
    BACKUP_FILENAMES,
    JsonSnapshotError,
    create_snapshot,
    restore_snapshot,
    verify_snapshot,
)


def _initialized_data_directory(tmp_path: Path) -> Path:
    data_directory = tmp_path / "data"
    migrate_data_directory(data_directory, apply=True)
    return data_directory


def test_snapshot_excludes_auth_state_and_restores_domain_documents(
    tmp_path: Path,
) -> None:
    data_directory = _initialized_data_directory(tmp_path)
    activity_path = data_directory / "activity_metrics.json"
    activity = json.loads(activity_path.read_text(encoding="utf-8"))
    activity["routine_executions"].append({"execution_id": "before"})
    activity_path.write_text(json.dumps(activity), encoding="utf-8")

    snapshot = create_snapshot(
        data_directory,
        tmp_path / "backups",
        snapshot_id="before-change",
    )
    activity["routine_executions"] = [{"execution_id": "after"}]
    activity_path.write_text(json.dumps(activity), encoding="utf-8")

    documents = verify_snapshot(snapshot)
    restore_snapshot(snapshot, data_directory)

    assert set(documents) == set(BACKUP_FILENAMES)
    assert "auth_sessions.json" not in documents
    restored = json.loads(activity_path.read_text(encoding="utf-8"))
    assert restored["routine_executions"] == [{"execution_id": "before"}]


def test_snapshot_rejects_missing_required_document(tmp_path: Path) -> None:
    data_directory = _initialized_data_directory(tmp_path)
    (data_directory / "personal_state.json").unlink()

    with pytest.raises(JsonSnapshotError, match="required JSON document"):
        create_snapshot(data_directory, tmp_path / "backups")


def test_verify_rejects_tampered_document_without_restoring(tmp_path: Path) -> None:
    data_directory = _initialized_data_directory(tmp_path)
    snapshot = create_snapshot(
        data_directory,
        tmp_path / "backups",
        snapshot_id="tampered",
    )
    (snapshot / "activity_metrics.json").write_text("{}", encoding="utf-8")
    target_path = data_directory / "activity_metrics.json"
    original = target_path.read_bytes()

    with pytest.raises(JsonSnapshotError, match="checksum mismatch"):
        restore_snapshot(snapshot, data_directory)

    assert target_path.read_bytes() == original


def test_restore_rolls_back_every_document_after_midway_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_directory = _initialized_data_directory(tmp_path)
    snapshot = create_snapshot(
        data_directory,
        tmp_path / "backups",
        snapshot_id="rollback",
    )
    originals = {
        filename: (data_directory / filename).read_bytes()
        for filename in BACKUP_FILENAMES
    }
    for filename in BACKUP_FILENAMES:
        root = json.loads((data_directory / filename).read_text(encoding="utf-8"))
        root["current_marker"] = filename
        (data_directory / filename).write_text(json.dumps(root), encoding="utf-8")
    before_restore = {
        filename: (data_directory / filename).read_bytes()
        for filename in BACKUP_FILENAMES
    }
    assert before_restore != originals
    real_write = snapshot_module.atomic_write_bytes
    calls = 0

    def fail_second_write(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise JsonSnapshotError("simulated disk failure")
        real_write(path, data)

    monkeypatch.setattr(snapshot_module, "atomic_write_bytes", fail_second_write)

    with pytest.raises(JsonSnapshotError, match="original data restored"):
        restore_snapshot(snapshot, data_directory)

    assert {
        filename: (data_directory / filename).read_bytes()
        for filename in BACKUP_FILENAMES
    } == before_restore


@pytest.mark.parametrize("snapshot_id", ["", ".", "..", "nested/path"])
def test_snapshot_rejects_unsafe_identifier(
    tmp_path: Path,
    snapshot_id: str,
) -> None:
    data_directory = _initialized_data_directory(tmp_path)

    with pytest.raises(JsonSnapshotError, match="snapshot_id"):
        create_snapshot(
            data_directory,
            tmp_path / "backups",
            snapshot_id=snapshot_id,
        )
