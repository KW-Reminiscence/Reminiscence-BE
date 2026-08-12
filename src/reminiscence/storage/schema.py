"""Shared version and directory policy for application JSON documents."""

from __future__ import annotations

from pathlib import Path

CURRENT_SCHEMA_VERSION = 1
DATA_DIRECTORY_MODE = 0o750


def ensure_data_directory(path: Path) -> None:
    """Create one data directory with the appliance's restrictive mode."""

    path.mkdir(parents=True, exist_ok=True, mode=DATA_DIRECTORY_MODE)
    path.chmod(DATA_DIRECTORY_MODE)
