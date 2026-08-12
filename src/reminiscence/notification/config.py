"""Load the single guardian and SMTP configuration from a local secret."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_NOTIFICATION_CONFIG_PATH = Path("/run/secrets/notification-config.json")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CURRENT_NOTIFICATION_CONFIG_SCHEMA_VERSION = 1


class NotificationConfigError(ValueError):
    """Raised when notification configuration cannot be loaded safely."""


@dataclass(frozen=True, slots=True)
class CareRecipientConfig:
    """One care recipient displayed in guardian mail."""

    name: str


@dataclass(frozen=True, slots=True)
class GuardianConfig:
    """One guardian destination in the MVP."""

    email: str


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    """STARTTLS SMTP credentials."""

    host: str
    port: int
    username: str
    app_password: str
    from_name: str


@dataclass(frozen=True, slots=True)
class NotificationConfig:
    """Validated email configuration."""

    care_recipient: CareRecipientConfig
    guardian: GuardianConfig
    smtp: SmtpConfig


def get_notification_config_path() -> Path:
    """Return the configured secret path without reading it."""

    configured_path = os.environ.get("NOTIFICATION_CONFIG_PATH")
    return Path(configured_path) if configured_path else DEFAULT_NOTIFICATION_CONFIG_PATH


def _require_object(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NotificationConfigError(f"{field_name} must be an object")
    return value


def _require_text(container: dict[str, Any], key: str, parent: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise NotificationConfigError(
            f"{parent}.{key} must be a non-empty string"
        )
    if any(ord(character) < 32 for character in value):
        raise NotificationConfigError(
            f"{parent}.{key} must not contain control characters"
        )
    return value.strip()


def load_notification_config(path: Path | None = None) -> NotificationConfig:
    """Load and validate guardian and SMTP settings."""

    config_path = path or get_notification_config_path()
    try:
        metadata = config_path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise NotificationConfigError(
                "notification configuration must be a regular file"
            )
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise NotificationConfigError(
                "notification configuration file mode must be 0600"
            )
        raw_config: object = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise NotificationConfigError(
            "notification configuration cannot be read"
        ) from exc
    except json.JSONDecodeError as exc:
        raise NotificationConfigError(
            "notification configuration is not valid JSON"
        ) from exc

    root = _require_object(raw_config, "configuration")
    schema_version = root.get("schema_version")
    if (
        schema_version != CURRENT_NOTIFICATION_CONFIG_SCHEMA_VERSION
        or isinstance(schema_version, bool)
    ):
        raise NotificationConfigError("configuration.schema_version must be 1")
    care_recipient = _require_object(
        root.get("care_recipient"),
        "care_recipient",
    )
    guardian = _require_object(root.get("guardian"), "guardian")
    smtp = _require_object(root.get("smtp"), "smtp")
    guardian_email = _require_text(guardian, "email", "guardian")
    if not EMAIL_PATTERN.fullmatch(guardian_email):
        raise NotificationConfigError("guardian.email is not valid")
    smtp_port = smtp.get("port")
    if (
        not isinstance(smtp_port, int)
        or isinstance(smtp_port, bool)
        or not 1 <= smtp_port <= 65535
    ):
        raise NotificationConfigError(
            "smtp.port must be an integer between 1 and 65535"
        )

    return NotificationConfig(
        care_recipient=CareRecipientConfig(
            name=_require_text(care_recipient, "name", "care_recipient")
        ),
        guardian=GuardianConfig(email=guardian_email),
        smtp=SmtpConfig(
            host=_require_text(smtp, "host", "smtp"),
            port=smtp_port,
            username=_require_text(smtp, "username", "smtp"),
            app_password=_require_text(smtp, "app_password", "smtp"),
            from_name=_require_text(smtp, "from_name", "smtp"),
        ),
    )
