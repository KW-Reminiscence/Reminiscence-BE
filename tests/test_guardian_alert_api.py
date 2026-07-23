"""Guardian alert API and Gmail SMTP delivery tests."""

import smtplib
from collections.abc import Generator
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Self

import pytest
from fastapi.testclient import TestClient

from reminiscence.main import app
from reminiscence.notification.api import provide_email_sender, provide_notification_config
from reminiscence.notification.config import (
    CareRecipientConfig,
    GuardianConfig,
    NotificationConfig,
    SmtpConfig,
)
from reminiscence.notification.email_sender import (
    GUARDIAN_ALERT_SUBJECT,
    SMTP_TIMEOUT_SECONDS,
    SmtpGuardianEmailSender,
)


@pytest.fixture
def notification_config() -> NotificationConfig:
    return NotificationConfig(
        api_password="tablet-password",
        care_recipient=CareRecipientConfig(name="홍길동"),
        guardian=GuardianConfig(email="guardian@example.com"),
        smtp=SmtpConfig(
            host="smtp.gmail.com",
            port=587,
            username="student@gmail.com",
            app_password="gmail-app-password",
            from_name="Reminiscence",
        ),
    )


class RecordingEmailSender(SmtpGuardianEmailSender):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send(
        self,
        config: NotificationConfig,
        alert_type: str,
        description: str,
        detected_at: datetime,
    ) -> None:
        self.calls.append(
            {
                "config": config,
                "alert_type": alert_type,
                "description": description,
                "detected_at": detected_at,
            }
        )


@pytest.fixture
def recording_sender() -> RecordingEmailSender:
    return RecordingEmailSender()


@pytest.fixture
def client(
    notification_config: NotificationConfig,
    recording_sender: RecordingEmailSender,
) -> Generator[TestClient]:
    app.dependency_overrides[provide_notification_config] = lambda: notification_config
    app.dependency_overrides[provide_email_sender] = lambda: recording_sender
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _valid_payload() -> dict[str, str]:
    return {
        "alert_type": "루틴 이탈",
        "description": "약 복용 확인에 연속으로 응답하지 않았습니다.",
        "detected_at": "2026-07-24T01:30:00+00:00",
    }


def test_sends_guardian_alert_with_valid_api_key(
    client: TestClient,
    recording_sender: RecordingEmailSender,
) -> None:
    response = client.post(
        "/guardian-alerts",
        headers={"X-API-Key": "tablet-password"},
        json=_valid_payload(),
    )

    assert response.status_code == 200
    assert response.json() == {"status": "sent"}
    assert len(recording_sender.calls) == 1
    assert recording_sender.calls[0]["alert_type"] == "루틴 이탈"


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-password"}])
def test_rejects_missing_or_wrong_api_key(
    client: TestClient,
    recording_sender: RecordingEmailSender,
    headers: dict[str, str],
) -> None:
    response = client.post("/guardian-alerts", headers=headers, json=_valid_payload())

    assert response.status_code == 401
    assert recording_sender.calls == []
    assert "gmail-app-password" not in response.text
    assert "tablet-password" not in response.text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("alert_type", " "),
        ("alert_type", "a" * 51),
        ("description", ""),
        ("description", "a" * 501),
        ("detected_at", "2026-07-24T10:30:00"),
    ],
)
def test_rejects_invalid_alert_payload(
    client: TestClient,
    recording_sender: RecordingEmailSender,
    field: str,
    value: str,
) -> None:
    payload = _valid_payload()
    payload[field] = value

    response = client.post(
        "/guardian-alerts",
        headers={"X-API-Key": "tablet-password"},
        json=payload,
    )

    assert response.status_code == 422
    assert recording_sender.calls == []


def test_returns_service_unavailable_without_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.dependency_overrides.clear()
    monkeypatch.setenv("NOTIFICATION_CONFIG_PATH", str(tmp_path / "missing.json"))

    response = TestClient(app).post(
        "/guardian-alerts",
        headers={"X-API-Key": "any-password"},
        json=_valid_payload(),
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "보호자 알림 설정을 사용할 수 없습니다"}


class FakeSmtp:
    exception: BaseException | None = None
    instance: "FakeSmtp | None" = None

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.ehlo_count = 0
        self.starttls_called = False
        self.login_credentials: tuple[str, str] | None = None
        self.message: EmailMessage | None = None
        type(self).instance = self
        if self.exception and isinstance(self.exception, TimeoutError):
            raise self.exception

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def ehlo(self) -> None:
        self.ehlo_count += 1

    def starttls(self, *, context: object) -> None:
        self.starttls_called = True

    def login(self, username: str, password: str) -> None:
        self.login_credentials = (username, password)
        if self.exception and isinstance(self.exception, smtplib.SMTPAuthenticationError):
            raise self.exception

    def send_message(self, message: EmailMessage) -> None:
        self.message = message
        if self.exception and isinstance(self.exception, smtplib.SMTPRecipientsRefused):
            raise self.exception


def test_smtp_sender_uses_starttls_and_builds_korean_message(
    notification_config: NotificationConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSmtp.exception = None
    FakeSmtp.instance = None
    monkeypatch.setattr("reminiscence.notification.email_sender.smtplib.SMTP", FakeSmtp)

    SmtpGuardianEmailSender().send(
        config=notification_config,
        alert_type="루틴 이탈",
        description="약 복용 확인에 응답하지 않았습니다.",
        detected_at=datetime(2026, 7, 24, 1, 30, tzinfo=UTC),
    )

    smtp = FakeSmtp.instance
    assert smtp is not None
    assert (smtp.host, smtp.port, smtp.timeout) == (
        "smtp.gmail.com",
        587,
        SMTP_TIMEOUT_SECONDS,
    )
    assert smtp.ehlo_count == 2
    assert smtp.starttls_called
    assert smtp.login_credentials == ("student@gmail.com", "gmail-app-password")
    assert smtp.message is not None
    assert smtp.message["To"] == "guardian@example.com"
    assert smtp.message["Subject"] == GUARDIAN_ALERT_SUBJECT
    body = smtp.message.get_content()
    assert "홍길동 학생" in body
    assert "루틴 이탈" in body
    assert "2026-07-24 10:30:00 KST" in body
    assert "의료 진단이나 응급 신고를 대신하지 않으므로" in body
    assert "gmail-app-password" not in body
    assert "tablet-password" not in body


@pytest.mark.parametrize(
    "smtp_exception",
    [
        smtplib.SMTPAuthenticationError(535, b"authentication failed"),
        smtplib.SMTPRecipientsRefused({"guardian@example.com": (550, b"rejected")}),
        TimeoutError("connection timed out"),
    ],
)
def test_returns_bad_gateway_for_smtp_failures(
    notification_config: NotificationConfig,
    monkeypatch: pytest.MonkeyPatch,
    smtp_exception: BaseException,
) -> None:
    FakeSmtp.exception = smtp_exception
    app.dependency_overrides[provide_notification_config] = lambda: notification_config
    app.dependency_overrides.pop(provide_email_sender, None)
    monkeypatch.setattr("reminiscence.notification.email_sender.smtplib.SMTP", FakeSmtp)

    response = TestClient(app).post(
        "/guardian-alerts",
        headers={"X-API-Key": "tablet-password"},
        json=_valid_payload(),
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "보호자 이메일 전송에 실패했습니다"}
    assert "gmail-app-password" not in response.text
    app.dependency_overrides.clear()


def test_guardian_alert_is_included_in_openapi_document() -> None:
    assert "/guardian-alerts" in app.openapi()["paths"]
