"""Atomic JSON object storage behavior."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from reminiscence.storage import JsonObjectStore, JsonStorageError


def test_missing_file_returns_detached_default(tmp_path: Path) -> None:
    store = JsonObjectStore(tmp_path / "activity.json", missing_default={"items": []})

    first = store.read()
    first["items"].append("changed")

    assert store.read() == {"items": []}


def test_update_preserves_unrelated_sections(tmp_path: Path) -> None:
    path = tmp_path / "activity.json"
    store = JsonObjectStore(path, missing_default={"routine": []})
    store.update(lambda value: value.update({"routine": ["kept"]}))

    result = store.update(lambda value: value.update({"conversation": ["added"]}))

    assert result == {"routine": ["kept"], "conversation": ["added"]}
    assert list(tmp_path.glob("*.tmp")) == []


def test_two_instances_share_one_path_lock(tmp_path: Path) -> None:
    path = tmp_path / "activity.json"
    first_store = JsonObjectStore(path, missing_default={"count": 0})
    second_store = JsonObjectStore(path, missing_default={"count": 0})
    start = threading.Barrier(3)

    def increment(store: JsonObjectStore) -> None:
        start.wait(timeout=1)
        for _ in range(100):
            def mutate(value: dict[str, Any]) -> None:
                value["count"] += 1

            store.update(mutate)

    first_thread = threading.Thread(target=increment, args=(first_store,))
    second_thread = threading.Thread(target=increment, args=(second_store,))
    first_thread.start()
    second_thread.start()
    start.wait(timeout=1)
    first_thread.join(timeout=3)
    second_thread.join(timeout=3)

    assert first_store.read()["count"] == 200


@pytest.mark.parametrize("content", ["not-json", "[]"])
def test_invalid_json_object_is_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "activity.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(JsonStorageError):
        JsonObjectStore(path).read()


def test_non_serializable_update_does_not_replace_existing_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "activity.json"
    path.write_text('{"safe": true}', encoding="utf-8")
    store = JsonObjectStore(path)

    with pytest.raises(JsonStorageError):
        store.update(lambda value: value.update({"invalid": object()}))

    assert path.read_text(encoding="utf-8") == '{"safe": true}'
