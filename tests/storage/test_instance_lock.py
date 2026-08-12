"""Single API process ownership of one JSON directory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reminiscence.storage.instance_lock import InstanceLockError, SingleInstanceLock


def test_second_instance_is_rejected_until_owner_releases(tmp_path: Path) -> None:
    first = SingleInstanceLock(tmp_path)
    second = SingleInstanceLock(tmp_path)

    first.acquire()
    try:
        with pytest.raises(InstanceLockError, match="another process"):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    assert second.acquired is True
    second.release()


def test_lock_writes_non_secret_json_metadata(tmp_path: Path) -> None:
    with SingleInstanceLock(tmp_path) as lock:
        metadata = json.loads(lock.path.read_text(encoding="utf-8"))

        assert isinstance(metadata["pid"], int)
        assert metadata["acquired_at"].endswith("+00:00")
        assert lock.acquired is True

    assert lock.acquired is False


def test_same_object_cannot_be_acquired_twice(tmp_path: Path) -> None:
    lock = SingleInstanceLock(tmp_path)
    lock.acquire()
    try:
        with pytest.raises(InstanceLockError, match="already acquired"):
            lock.acquire()
    finally:
        lock.release()
