"""Tests for local JSON notification configuration."""

import json
from pathlib import Path
from typing import Any

import pytest

from reminiscence.notification.config import (
    DEFAULT_NOTIFICATION_CONFIG_PATH,
    NotificationConfigError,
    get_notification_config_path,
    load_notification_config,
)


@pytest.fixture
def valid_config() -> dict[str, Any]:
    return {
        "api_password": "tablet-password",
        "care_recipient": {"name": "홍길동"},
        "guardian": {"email": "guardian@example.com"},
        "smtp": {
            "host": "smtp.gmail.com",
            "port": 587,
            "username": "student@gmail.com",
            "app_password": "gmail-app-password",
            "from_name": "Reminiscence",
        },
    }


def _write_config(path: Path, config: object) -> None:
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")


def test_loads_valid_notification_config(
    tmp_path: Path,
    valid_config: dict[str, Any],
) -> None:
    config_path = tmp_path / "notification.json"
    _write_config(config_path, valid_config)

    config = load_notification_config(config_path)

    assert config.api_password == "tablet-password"
    assert config.care_recipient.name == "홍길동"
    assert config.guardian.email == "guardian@example.com"
    assert config.smtp.host == "smtp.gmail.com"
    assert config.smtp.port == 587


def test_uses_environment_config_path(
    tmp_path: Path,
    valid_config: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "custom-notification.json"
    _write_config(config_path, valid_config)
    monkeypatch.setenv("NOTIFICATION_CONFIG_PATH", str(config_path))

    assert get_notification_config_path() == config_path
    assert load_notification_config().guardian.email == "guardian@example.com"


def test_uses_secret_path_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTIFICATION_CONFIG_PATH", raising=False)

    assert get_notification_config_path() == DEFAULT_NOTIFICATION_CONFIG_PATH


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        ("{not-json", "올바른 JSON"),
        ("[]", "설정 항목은 객체"),
        ('{"api_password": "password"}', "care_recipient 항목은 객체"),
    ],
)
def test_rejects_malformed_configuration(
    tmp_path: Path,
    content: str,
    expected_message: str,
) -> None:
    config_path = tmp_path / "notification.json"
    config_path.write_text(content, encoding="utf-8")

    with pytest.raises(NotificationConfigError, match=expected_message):
        load_notification_config(config_path)


def test_rejects_missing_configuration_file(tmp_path: Path) -> None:
    with pytest.raises(NotificationConfigError, match="읽을 수 없습니다"):
        load_notification_config(tmp_path / "missing.json")


@pytest.mark.parametrize(
    ("field_path", "invalid_value", "expected_message"),
    [
        (("api_password",), "", "설정.api_password"),
        (("api_password",), "한글-비밀번호", "ASCII 문자"),
        (("api_password",), "line\nbreak", "ASCII 문자"),
        (("care_recipient", "name"), "   ", "care_recipient.name"),
        (("guardian", "email"), "invalid-email", "guardian.email 형식"),
        (("smtp", "host"), None, "smtp.host"),
        (("smtp", "port"), 0, "smtp.port"),
        (("smtp", "port"), 65536, "smtp.port"),
        (("smtp", "port"), True, "smtp.port"),
        (("smtp", "username"), "", "smtp.username"),
        (("smtp", "app_password"), "", "smtp.app_password"),
        (("smtp", "from_name"), "", "smtp.from_name"),
    ],
)
def test_rejects_invalid_fields(
    tmp_path: Path,
    valid_config: dict[str, Any],
    field_path: tuple[str, ...],
    invalid_value: object,
    expected_message: str,
) -> None:
    target: dict[str, Any] = valid_config
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = invalid_value
    config_path = tmp_path / "notification.json"
    _write_config(config_path, valid_config)

    with pytest.raises(NotificationConfigError, match=expected_message):
        load_notification_config(config_path)
