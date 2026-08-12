"""Deterministic serialization for the checked-in API contract."""

from __future__ import annotations

import json
from typing import Any


def render_openapi(document: dict[str, Any]) -> str:
    """Serialize an OpenAPI document with stable ordering and formatting."""

    return json.dumps(
        document,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
