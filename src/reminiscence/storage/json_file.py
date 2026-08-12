"""Concurrent and atomic local JSON object storage."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from fcntl import LOCK_EX, LOCK_SH, LOCK_UN, flock
from pathlib import Path
from typing import Any, BinaryIO


class JsonStorageError(RuntimeError):
    """Raised when a JSON object cannot be read or atomically replaced."""


_LOCK_REGISTRY_GUARD = threading.Lock()
_LOCKS_BY_PATH: dict[Path, threading.RLock] = {}


def _shared_lock(path: Path) -> threading.RLock:
    resolved_path = path.resolve()
    with _LOCK_REGISTRY_GUARD:
        return _LOCKS_BY_PATH.setdefault(resolved_path, threading.RLock())


class JsonObjectStore:
    """Read and update one versioned JSON object under thread and file locks."""

    def __init__(
        self,
        path: Path,
        *,
        missing_default: Mapping[str, Any] | None = None,
        schema_version: int | None = None,
        read_only: bool = False,
    ) -> None:
        if schema_version is not None and schema_version < 1:
            raise ValueError("schema_version must be a positive integer")
        self.path = path
        self._missing_default = dict(missing_default or {})
        self._schema_version = schema_version
        self._read_only = read_only
        self._lock = _shared_lock(path)

    @property
    def lock_path(self) -> Path:
        """Return the stable sidecar lock path used across processes."""

        return self.path.with_name(f".{self.path.name}.lock")

    @property
    def snapshot_lock_path(self) -> Path:
        """Return the data-directory lock shared with snapshot operations."""

        return self.path.parent / ".snapshot.lock"

    def read(self) -> dict[str, Any]:
        """Return a detached JSON object."""

        with self._lock:
            if self._read_only:
                return self._read_unlocked()
            with self._snapshot_lock(exclusive=False), self._file_lock(exclusive=False):
                return self._read_unlocked()

    def update(
        self,
        mutator: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        """Mutate and atomically persist an object while holding the path lock."""

        if self._read_only:
            raise JsonStorageError(f"JSON object is read-only: {self.path}")
        with (
            self._lock,
            self._snapshot_lock(exclusive=False),
            self._file_lock(exclusive=True),
        ):
            value = self._read_unlocked()
            mutator(value)
            self._apply_schema_version(value)
            self._write_unlocked(value)
            return deepcopy(value)

    def replace(self, value: Mapping[str, Any]) -> dict[str, Any]:
        """Replace the complete JSON object under an exclusive file lock."""

        if self._read_only:
            raise JsonStorageError(f"JSON object is read-only: {self.path}")
        replacement = deepcopy(dict(value))
        with (
            self._lock,
            self._snapshot_lock(exclusive=False),
            self._file_lock(exclusive=True),
        ):
            self._apply_schema_version(replacement)
            self._write_unlocked(replacement)
            return deepcopy(replacement)

    @contextmanager
    def _file_lock(self, *, exclusive: bool) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock_path.open("a+b") as lock_file:
                self._acquire_file_lock(lock_file, exclusive=exclusive)
                try:
                    yield
                finally:
                    flock(lock_file.fileno(), LOCK_UN)
        except OSError as exc:
            raise JsonStorageError(
                f"failed to lock JSON object at {self.path}"
            ) from exc

    @contextmanager
    def _snapshot_lock(self, *, exclusive: bool) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.snapshot_lock_path.open("a+b") as lock_file:
                self._acquire_file_lock(lock_file, exclusive=exclusive)
                try:
                    yield
                finally:
                    flock(lock_file.fileno(), LOCK_UN)
        except OSError as exc:
            raise JsonStorageError(
                f"failed to lock JSON snapshot directory at {self.path.parent}"
            ) from exc

    @staticmethod
    def _acquire_file_lock(lock_file: BinaryIO, *, exclusive: bool) -> None:
        flock(lock_file.fileno(), LOCK_EX if exclusive else LOCK_SH)

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            default_value = deepcopy(self._missing_default)
            self._apply_schema_version(default_value)
            return default_value
        try:
            value: object = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JsonStorageError(f"failed to read JSON object from {self.path}") from exc
        if not isinstance(value, dict):
            raise JsonStorageError(f"JSON root must be an object: {self.path}")
        self._validate_schema_version(value)
        return value

    def _validate_schema_version(self, value: Mapping[str, Any]) -> None:
        if self._schema_version is None:
            return
        actual = value.get("schema_version")
        if actual != self._schema_version or isinstance(actual, bool):
            raise JsonStorageError(
                "unsupported or missing schema_version for "
                f"{self.path}: expected {self._schema_version}, got {actual!r}"
            )

    def _apply_schema_version(self, value: dict[str, Any]) -> None:
        if self._schema_version is not None:
            value["schema_version"] = self._schema_version

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
            self._fsync_parent_directory()
        except (OSError, TypeError, ValueError) as exc:
            temporary_path.unlink(missing_ok=True)
            raise JsonStorageError(
                f"failed to write JSON object to {self.path}"
            ) from exc

    def _fsync_parent_directory(self) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(self.path.parent, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
