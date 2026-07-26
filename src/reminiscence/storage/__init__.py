"""Local persistence primitives shared by backend domains."""

from reminiscence.storage.json_file import JsonObjectStore, JsonStorageError

__all__ = ["JsonObjectStore", "JsonStorageError"]
