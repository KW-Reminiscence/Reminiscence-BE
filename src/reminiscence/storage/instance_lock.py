"""Single-process ownership for one appliance JSON data directory."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from fcntl import LOCK_EX, LOCK_NB, LOCK_UN, flock
from pathlib import Path
from typing import BinaryIO


class InstanceLockError(RuntimeError):
    """Raised when another API process owns the JSON data directory."""


class SingleInstanceLock:
    """Hold an exclusive non-blocking lock for one data directory."""

    def __init__(self, data_directory: Path) -> None:
        self.path = data_directory / ".instance.lock"
        self._file: BinaryIO | None = None

    @property
    def acquired(self) -> bool:
        """Return whether this object currently owns the lock."""

        return self._file is not None

    def acquire(self) -> None:
        """Acquire ownership or fail without waiting."""

        if self._file is not None:
            raise InstanceLockError("instance lock is already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock_file = self.path.open("a+b")
            try:
                flock(lock_file.fileno(), LOCK_EX | LOCK_NB)
            except BlockingIOError as exc:
                lock_file.close()
                raise InstanceLockError(
                    f"another process owns data directory: {self.path.parent}"
                ) from exc
            metadata = json.dumps(
                {
                    "pid": os.getpid(),
                    "acquired_at": datetime.now(UTC).isoformat(),
                },
                ensure_ascii=False,
            ).encode("utf-8")
            lock_file.seek(0)
            lock_file.truncate()
            lock_file.write(metadata + b"\n")
            lock_file.flush()
            os.fsync(lock_file.fileno())
            self._file = lock_file
        except InstanceLockError:
            raise
        except OSError as exc:
            raise InstanceLockError(f"failed to acquire instance lock: {self.path}") from exc

    def release(self) -> None:
        """Release ownership; repeated release is harmless."""

        lock_file = self._file
        if lock_file is None:
            return
        self._file = None
        try:
            flock(lock_file.fileno(), LOCK_UN)
        finally:
            lock_file.close()

    def __enter__(self) -> SingleInstanceLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
