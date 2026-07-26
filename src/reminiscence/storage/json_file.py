"""Concurrent and atomic local JSON object storage."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, cast


class JsonStorageError(RuntimeError):
    """Raised when a JSON object cannot be read or atomically replaced."""


_LOCK_REGISTRY_GUARD = threading.Lock()
_LOCKS_BY_PATH: dict[Path, threading.RLock] = {}


def _shared_lock(path: Path) -> threading.RLock:
    resolved_path = path.resolve()
    with _LOCK_REGISTRY_GUARD:
        return _LOCKS_BY_PATH.setdefault(resolved_path, threading.RLock())


class JsonObjectStore:
    """Read and update one JSON object under a process-wide path lock."""

    def __init__(
        self,
        path: Path,
        *,
        missing_default: Mapping[str, Any] | None = None,
    ) -> None:
        self.path = path
        self._missing_default = dict(missing_default or {})
        self._lock = _shared_lock(path)

    def read(self) -> dict[str, Any]:
        """Return a detached JSON object."""

        with self._lock:
            return self._read_unlocked()

    def update(
        self,
        mutator: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        """Mutate and atomically persist an object while holding the path lock."""

        with self._lock:
            value = self._read_unlocked()
            mutator(value)
            self._write_unlocked(value)
            return value

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return deepcopy(self._missing_default)
        try:
            value: object = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JsonStorageError(f"failed to read JSON object from {self.path}") from exc
        if not isinstance(value, dict):
            raise JsonStorageError(f"JSON root must be an object: {self.path}")
        return cast(dict[str, Any], value)

    def _write_unlocked(self, value: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
                json.dump(value, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.path)
        except (OSError, TypeError, ValueError) as exc:
            temporary_path.unlink(missing_ok=True)
            raise JsonStorageError(
                f"failed to write JSON object to {self.path}"
            ) from exc
