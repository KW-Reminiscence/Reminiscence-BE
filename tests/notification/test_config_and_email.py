"""Notification secret validation and email content tests."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from reminiscence.anomaly.models import (
    AnomalyMode,
    AnomalyStatus,
    DomainEvaluation,
    PersonalEvaluation,
)
from reminiscence.notification.config import (
    NotificationConfigError,
    load_notification_config,
)
from reminiscence.notification.email_sender import (
    GUARDIAN_ALERT_SUBJECT,
    build_guardian_alert_message,
)

SEOUL = ZoneInfo("Asia/Seoul")


@pytest.fixture
def valid_config() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "care_recipient": {"name": "홍길동"},
        "guardian": {"email": "guardian@example.com"},
        "smtp": {
            "host": "smtp.gmail.com",
            "port": 587,
            "username": "sender@gmail.com",
            "app_password": "gmail-app-password",
            "from_name": "Reminiscence",
        },
    }


def write_config(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False),
        encoding="utf-8",
    )
    path.chmod(0o600)


def evaluation() -> PersonalEvaluation:
    routine = DomainEvaluation(
        status=AnomalyStatus.ANOMALOUS,
        mode=AnomalyMode.COLD_START,
        sample_count=3,
        score=None,
        reasons=("아침 약 루틴 3회 연속 미응답",),
        feature_names=("not_answered_ratio",),
    )
    conversation = DomainEvaluation(
        status=AnomalyStatus.NORMAL,
        mode=AnomalyMode.INSUFFICIENT_DATA,
        sample_count=2,
        score=None,
        reasons=(),
        feature_names=("recent_7_day_user_turn_count",),
    )
    return PersonalEvaluation(
        evaluated_at=datetime(2026, 7, 27, 10, 0, tzinfo=SEOUL),
        status=AnomalyStatus.ANOMALOUS,
        routine=routine,
        conversation=conversation,
    )


def test_loads_valid_notification_secret(
    tmp_path: Path,
    valid_config: dict[str, Any],
) -> None:
    path = tmp_path / "notification.json"
    write_config(path, valid_config)

    config = load_notification_config(path)

    assert config.care_recipient.name == "홍길동"
    assert config.guardian.email == "guardian@example.com"
    assert config.smtp.port == 587
    assert config.smtp.app_password == "gmail-app-password"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not-json", "valid JSON"),
        ("[]", "configuration"),
        ('{"schema_version": 1, "guardian": {}}', "care_recipient"),
    ],
)
def test_rejects_malformed_secret(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    path = tmp_path / "notification.json"
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(NotificationConfigError, match=message):
        load_notification_config(path)


def test_rejects_notification_secret_with_non_private_mode(
    tmp_path: Path,
    valid_config: dict[str, Any],
) -> None:
    path = tmp_path / "notification.json"
    write_config(path, valid_config)
    path.chmod(0o640)

    with pytest.raises(NotificationConfigError, match="0600"):
        load_notification_config(path)


@pytest.mark.parametrize(
    ("field_path", "invalid", "message"),
    [
        (("care_recipient", "name"), "", "care_recipient.name"),
        (("care_recipient", "name"), "name\ninjection", "control"),
        (("guardian", "email"), "invalid", "guardian.email"),
        (("smtp", "port"), 0, "smtp.port"),
        (("smtp", "port"), True, "smtp.port"),
        (("smtp", "username"), "", "smtp.username"),
        (("smtp", "app_password"), "", "smtp.app_password"),
    ],
)
def test_rejects_invalid_secret_fields(
    tmp_path: Path,
    valid_config: dict[str, Any],
    field_path: tuple[str, ...],
    invalid: object,
    message: str,
) -> None:
    target = valid_config
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = invalid
    path = tmp_path / "notification.json"
    write_config(path, valid_config)

    with pytest.raises(NotificationConfigError, match=message):
        load_notification_config(path)


def test_email_contains_explanation_and_non_medical_boundary(
    tmp_path: Path,
    valid_config: dict[str, Any],
) -> None:
    path = tmp_path / "notification.json"
    write_config(path, valid_config)
    config = load_notification_config(path)

    message = build_guardian_alert_message(config, evaluation())
    body = message.get_content()

    assert message["Subject"] == GUARDIAN_ALERT_SUBJECT
    assert message["To"] == "guardian@example.com"
    assert "아침 약 루틴 3회 연속 미응답" in body
    assert "의료 진단이나 응급 신고를 대신하지 않으며" in body
    assert "gmail-app-password" not in message.as_string()
