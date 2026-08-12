"""Authentication value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AuthRole(StrEnum):
    """Supported single-appliance browser roles."""

    GUARDIAN = "GUARDIAN"
    TABLET = "TABLET"


@dataclass(frozen=True, slots=True)
class AuthSession:
    """Validated server-side session identity."""

    role: AuthRole
    created_at: datetime
    expires_at: datetime

