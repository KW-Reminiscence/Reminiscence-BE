"""HTTP API for sending a guardian alert."""

import secrets
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from reminiscence.notification.config import (
    NotificationConfig,
    NotificationConfigError,
    load_notification_config,
)
from reminiscence.notification.email_sender import GuardianEmailError, SmtpGuardianEmailSender

router = APIRouter(prefix="/guardian-alerts", tags=["guardian-alerts"])


class GuardianAlertRequest(BaseModel):
    alert_type: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=500)
    detected_at: datetime

    @field_validator("alert_type", "description")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("공백만 입력할 수 없습니다")
        return value

    @field_validator("detected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("detected_at에는 시간대 정보가 필요합니다")
        return value


class GuardianAlertResponse(BaseModel):
    status: Literal["sent"]


def provide_notification_config() -> NotificationConfig:
    try:
        return load_notification_config()
    except NotificationConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="보호자 알림 설정을 사용할 수 없습니다",
        ) from exc


def provide_email_sender() -> SmtpGuardianEmailSender:
    return SmtpGuardianEmailSender()


@router.post(
    "",
    response_model=GuardianAlertResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "API key authentication failed"},
        status.HTTP_502_BAD_GATEWAY: {"description": "Email delivery failed"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Configuration unavailable"},
    },
)
def send_guardian_alert(
    alert: GuardianAlertRequest,
    config: Annotated[NotificationConfig, Depends(provide_notification_config)],
    email_sender: Annotated[SmtpGuardianEmailSender, Depends(provide_email_sender)],
    api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> GuardianAlertResponse:
    if api_key is None or not secrets.compare_digest(
        api_key.encode("utf-8"),
        config.api_password.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key가 올바르지 않습니다",
        )

    try:
        email_sender.send(
            config=config,
            alert_type=alert.alert_type,
            description=alert.description,
            detected_at=alert.detected_at,
        )
    except GuardianEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="보호자 이메일 전송에 실패했습니다",
        ) from exc

    return GuardianAlertResponse(status="sent")
