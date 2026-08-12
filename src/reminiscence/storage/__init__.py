"""Local persistence primitives shared by backend domains."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from reminiscence.storage.json_file import JsonObjectStore, JsonStorageError
from reminiscence.storage.migration import CURRENT_SCHEMA_VERSION


def open_versioned_store(
    path: Path,
    *,
    missing_default: Mapping[str, Any] | None = None,
    read_only: bool = False,
) -> JsonObjectStore:
    """Open one application JSON document at the current schema version."""

    return JsonObjectStore(
        path,
        missing_default=missing_default,
        schema_version=CURRENT_SCHEMA_VERSION,
        read_only=read_only,
    )


__all__ = ["JsonObjectStore", "JsonStorageError", "open_versioned_store"]
