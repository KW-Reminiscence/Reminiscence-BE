"""Strict loader for plaintext appliance credentials in one secret JSON."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_APPLICATION_SECRETS_PATH = Path("/run/secrets/application-secrets.json")
APPLICATION_SECRETS_SCHEMA_VERSION = 1
MIN_GUARDIAN_PASSWORD_LENGTH = 8
MIN_PAIRING_CODE_LENGTH = 6


class ApplicationSecretsError(ValueError):
    """Raised when the appliance secret cannot be loaded safely."""


@dataclass(frozen=True, slots=True)
class AuthSecrets:
    """Plaintext credentials explicitly required by the appliance design."""

    guardian_password: str
    tablet_pairing_code: str


def get_application_secrets_path() -> Path:
    """Return the configured secret path without reading its contents."""

    value = os.environ.get("REMINISCENCE_SECRETS_PATH")
    return Path(value) if value else DEFAULT_APPLICATION_SECRETS_PATH


def _credential(root: dict[str, Any], key: str, minimum: int) -> str:
    value = root.get(key)
    if not isinstance(value, str) or len(value) < minimum or not value.strip():
        raise ApplicationSecretsError(
            f"{key} must contain at least {minimum} characters"
        )
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise ApplicationSecretsError(
            f"{key} must not contain surrounding whitespace or control characters"
        )
    return value


def load_auth_secrets(path: Path | None = None) -> AuthSecrets:
    """Load credentials without returning unrelated API or SMTP secrets."""

    secret_path = path or get_application_secrets_path()
    try:
        metadata = secret_path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ApplicationSecretsError("application secrets must be a regular file")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise ApplicationSecretsError("application secrets file mode must be 0600")
        value: object = json.loads(secret_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ApplicationSecretsError("application secrets cannot be read") from exc
    except json.JSONDecodeError as exc:
        raise ApplicationSecretsError("application secrets are not valid JSON") from exc
    if not isinstance(value, dict):
        raise ApplicationSecretsError("application secrets root must be an object")
    version = value.get("schema_version")
    if version != APPLICATION_SECRETS_SCHEMA_VERSION or isinstance(version, bool):
        raise ApplicationSecretsError("application secrets schema_version must be 1")
    return AuthSecrets(
        guardian_password=_credential(
            value,
            "guardian_password",
            MIN_GUARDIAN_PASSWORD_LENGTH,
        ),
        tablet_pairing_code=_credential(
            value,
            "tablet_pairing_code",
            MIN_PAIRING_CODE_LENGTH,
        ),
    )
