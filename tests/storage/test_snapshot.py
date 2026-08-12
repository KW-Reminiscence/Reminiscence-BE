"""Checksummed JSON snapshot and restore behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
