"""Internal evaluation endpoint that may send one guardian email."""

from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from reminiscence.anomaly.api import get_anomaly_service
from reminiscence.anomaly.models import AnomalyStatus
from reminiscence.anomaly.storage import AnomalyStorageError
from reminiscence.notification.config import (
    NotificationConfigError,
    load_notification_config,
)
from reminiscence.notification.email_sender import (
    GuardianEmailError,
    SmtpGuardianEmailSender,
)
from reminiscence.notification.service import (
    NotificationCoordinator,
    NotificationDeliveryStatus,
)
from reminiscence.notification.state import (
    NotificationAttemptStore,
    NotificationStateError,
)
from reminiscence.storage import JsonObjectStore, JsonStorageError

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationEvaluationResponse(BaseModel):
    """Result of one evaluation and at-most-once email decision."""

    evaluated_at: datetime
    personal_status: AnomalyStatus
    notification_status: NotificationDeliveryStatus
    reasons: list[str]


def _data_directory() -> Path:
    return Path(os.environ.get("REMINISCENCE_DATA_DIR", "data"))


def _server_timezone() -> ZoneInfo:
    timezone_name = os.environ.get("REMINISCENCE_TIMEZONE", "Asia/Seoul")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"unknown REMINISCENCE_TIMEZONE: {timezone_name}") from exc


@lru_cache(maxsize=1)
def get_notification_coordinator() -> NotificationCoordinator:
    """Build the process-wide notification coordinator."""

    return NotificationCoordinator(
        get_anomaly_service(),
        NotificationAttemptStore(
            JsonObjectStore(
                _data_directory() / "notification_state.json",
                missing_default={"anomaly_notification_attempted": False},
            )
        ),
        load_notification_config,
        SmtpGuardianEmailSender(),
    )


def get_current_time() -> datetime:
    """Return trusted server time."""

    return datetime.now(tz=_server_timezone())


CoordinatorDependency = Annotated[
    NotificationCoordinator,
    Depends(get_notification_coordinator),
]
CurrentTimeDependency = Annotated[datetime, Depends(get_current_time)]


@router.post(
    "/evaluate",
    response_model=NotificationEvaluationResponse,
    summary="Evaluate patterns and notify the guardian once",
)
async def evaluate_and_notify(
    coordinator: CoordinatorDependency,
    now: CurrentTimeDependency,
) -> NotificationEvaluationResponse:
    """Run an internal evaluation without accepting arbitrary email content."""

    try:
        outcome = await run_in_threadpool(
            coordinator.evaluate_and_notify,
            now,
        )
    except NotificationConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="guardian notification is not configured",
        ) from exc
    except GuardianEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="guardian email delivery failed",
        ) from exc
    except (
        AnomalyStorageError,
        NotificationStateError,
        JsonStorageError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    evaluation = outcome.anomaly.evaluation
    return NotificationEvaluationResponse(
        evaluated_at=evaluation.evaluated_at,
        personal_status=evaluation.status,
        notification_status=outcome.notification_status,
        reasons=[
            *evaluation.routine.reasons,
            *evaluation.conversation.reasons,
        ],
    )
