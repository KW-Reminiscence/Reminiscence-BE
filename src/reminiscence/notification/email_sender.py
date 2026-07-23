"""Send a single guardian alert through an SMTP account."""

import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from zoneinfo import ZoneInfo

from reminiscence.notification.config import NotificationConfig

SMTP_TIMEOUT_SECONDS = 5.0
SEOUL_TIME_ZONE = ZoneInfo("Asia/Seoul")
GUARDIAN_ALERT_SUBJECT = "[Reminiscence] 보호자 확인이 필요한 상황이 감지되었습니다"


class GuardianEmailError(RuntimeError):
    """Raised when the guardian email could not be delivered."""


class SmtpGuardianEmailSender:
    """Send guardian alerts synchronously using STARTTLS."""

    def send(
        self,
        config: NotificationConfig,
        alert_type: str,
        description: str,
        detected_at: datetime,
    ) -> None:
        message = build_guardian_alert_message(config, alert_type, description, detected_at)

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
            raise GuardianEmailError("보호자 이메일 전송에 실패했습니다") from exc


def build_guardian_alert_message(
    config: NotificationConfig,
    alert_type: str,
    description: str,
    detected_at: datetime,
) -> EmailMessage:
    """Build the Korean guardian alert without exposing credentials."""
    detected_at_kst = detected_at.astimezone(SEOUL_TIME_ZONE)
    formatted_time = detected_at_kst.strftime("%Y-%m-%d %H:%M:%S KST")

    message = EmailMessage()
    message["Subject"] = GUARDIAN_ALERT_SUBJECT
    message["From"] = formataddr((config.smtp.from_name, config.smtp.username))
    message["To"] = config.guardian.email
    message.set_content(
        "\n".join(
            [
                "보호자님,",
                "",
                (
                    f"{config.care_recipient.name} 학생에게 보호자 확인이 필요한 "
                    "상황이 감지되었습니다."
                ),
                "",
                f"감지 유형: {alert_type}",
                f"감지 시각: {formatted_time}",
                f"상세 내용: {description}",
                "",
                "이 메일은 자동 감지 결과를 안내합니다.",
                (
                    "의료 진단이나 응급 신고를 대신하지 않으므로 "
                    "필요한 경우 직접 상태를 확인해 주세요."
                ),
            ]
        )
    )
    return message
