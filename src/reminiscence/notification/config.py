"""Load the single guardian notification configuration from JSON."""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_NOTIFICATION_CONFIG_PATH = Path("/run/secrets/notification-config.json")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NotificationConfigError(ValueError):
    """Raised when notification configuration cannot be loaded safely."""


@dataclass(frozen=True)
class CareRecipientConfig:
    name: str


@dataclass(frozen=True)
class GuardianConfig:
    email: str


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    app_password: str
    from_name: str


@dataclass(frozen=True)
class NotificationConfig:
    api_password: str
    care_recipient: CareRecipientConfig
    guardian: GuardianConfig
    smtp: SmtpConfig


def get_notification_config_path() -> Path:
    """Return the configured secret path without reading the secret itself."""
    configured_path = os.getenv("NOTIFICATION_CONFIG_PATH")
    return Path(configured_path) if configured_path else DEFAULT_NOTIFICATION_CONFIG_PATH


def load_notification_config(path: Path | None = None) -> NotificationConfig:
    """Load and validate notification settings from a local JSON file."""
    config_path = path or get_notification_config_path()
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotificationConfigError("알림 설정 파일을 읽을 수 없습니다") from exc

    try:
        raw_config = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise NotificationConfigError("알림 설정 파일이 올바른 JSON이 아닙니다") from exc

    root = _require_object(raw_config, "설정")
    care_recipient = _require_object(root.get("care_recipient"), "care_recipient")
    guardian = _require_object(root.get("guardian"), "guardian")
    smtp = _require_object(root.get("smtp"), "smtp")

    guardian_email = _require_text(guardian, "email", "guardian")
    if not _EMAIL_PATTERN.fullmatch(guardian_email):
        raise NotificationConfigError("guardian.email 형식이 올바르지 않습니다")

    smtp_port = smtp.get("port")
    if type(smtp_port) is not int or not 1 <= smtp_port <= 65535:
        raise NotificationConfigError("smtp.port는 1부터 65535 사이의 정수여야 합니다")

    return NotificationConfig(
        api_password=_require_text(root, "api_password", "설정"),
        care_recipient=CareRecipientConfig(
            name=_require_text(care_recipient, "name", "care_recipient"),
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


def _require_object(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NotificationConfigError(f"{field_name} 항목은 객체여야 합니다")
    return value


def _require_text(container: dict[str, Any], key: str, parent: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise NotificationConfigError(f"{parent}.{key} 항목은 비어 있지 않은 문자열이어야 합니다")
    return value.strip()
