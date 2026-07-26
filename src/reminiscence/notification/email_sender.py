"""Send explainable anomaly alerts through STARTTLS SMTP."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Protocol
from zoneinfo import ZoneInfo

from reminiscence.anomaly.models import PersonalEvaluation
from reminiscence.notification.config import NotificationConfig

SMTP_TIMEOUT_SECONDS = 5.0
SEOUL_TIME_ZONE = ZoneInfo("Asia/Seoul")
GUARDIAN_ALERT_SUBJECT = "[Reminiscence] 생활 패턴 확인이 필요합니다"


class GuardianEmailError(RuntimeError):
    """Raised when a guardian email cannot be delivered."""


class GuardianEmailSender(Protocol):
    """Notification boundary used by the anomaly coordinator."""

    def send(
        self,
        config: NotificationConfig,
        evaluation: PersonalEvaluation,
    ) -> None:
        """Send one current anomaly episode alert."""

        ...


class SmtpGuardianEmailSender:
    """Deliver one alert using SMTP STARTTLS."""

    def send(
        self,
        config: NotificationConfig,
        evaluation: PersonalEvaluation,
    ) -> None:
        """Build and send an explainable non-medical alert."""

        message = build_guardian_alert_message(config, evaluation)
        try:
            with smtplib.SMTP(
                config.smtp.host,
                config.smtp.port,
                timeout=SMTP_TIMEOUT_SECONDS,
            ) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                smtp.login(config.smtp.username, config.smtp.app_password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise GuardianEmailError(
                "guardian email delivery failed"
            ) from exc


def build_guardian_alert_message(
    config: NotificationConfig,
    evaluation: PersonalEvaluation,
) -> EmailMessage:
    """Build Korean email content from stored detector reasons."""

    detected_at = evaluation.evaluated_at.astimezone(SEOUL_TIME_ZONE)
    reasons = (
        *evaluation.routine.reasons,
        *evaluation.conversation.reasons,
    )
    reason_lines = (
        [f"- {reason}" for reason in reasons]
        if reasons
        else ["- 개인 기준선에서 생활 패턴 변화가 감지됨"]
    )
    message = EmailMessage()
    message["Subject"] = GUARDIAN_ALERT_SUBJECT
    message["From"] = formataddr(
        (config.smtp.from_name, config.smtp.username)
    )
    message["To"] = config.guardian.email
    message.set_content(
        "\n".join(
            [
                "보호자님,",
                "",
                (
                    f"{config.care_recipient.name} 님의 최근 생활 패턴에서 "
                    "확인이 필요한 변화가 감지되었습니다."
                ),
                f"감지 시각: {detected_at:%Y-%m-%d %H:%M:%S KST}",
                "",
                "확인 근거:",
                *reason_lines,
                "",
                "이 메일은 개인별 활동 기록의 자동 평가 결과입니다.",
                (
                    "의료 진단이나 응급 신고를 대신하지 않으며, "
                    "필요한 경우 직접 상태를 확인해 주세요."
                ),
            ]
        )
    )
    return message
