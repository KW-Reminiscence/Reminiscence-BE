"""Coordinate anomaly evaluation and retryable guardian email delivery."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from reminiscence.anomaly.models import AnomalyStatus
from reminiscence.anomaly.service import AnomalyEvaluationOutcome
from reminiscence.notification.config import NotificationConfig
from reminiscence.notification.email_sender import GuardianEmailSender
from reminiscence.notification.state import NotificationAttemptStore


class NotificationDeliveryStatus(StrEnum):
    """Outcome of the notification portion of evaluation."""

    SENT = "SENT"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class NotificationEvaluationOutcome:
    """Combined anomaly evaluation and delivery decision."""

    anomaly: AnomalyEvaluationOutcome
    notification_status: NotificationDeliveryStatus


class AnomalyEvaluator(Protocol):
    """Subset of AnomalyService used by the notification coordinator."""

    def evaluate(self, evaluated_at: datetime) -> AnomalyEvaluationOutcome:
        """Evaluate the current personal state."""

        ...


class NotificationCoordinator:
    """Deliver one email per anomaly episode with bounded retry timing."""

    def __init__(
        self,
        anomaly_service: AnomalyEvaluator,
        attempt_store: NotificationAttemptStore,
        config_loader: Callable[[], NotificationConfig],
        email_sender: GuardianEmailSender,
        *,
        retry_delay: timedelta = timedelta(minutes=5),
        pending_timeout: timedelta = timedelta(minutes=10),
    ) -> None:
        if retry_delay <= timedelta(0):
            raise ValueError("retry_delay must be positive")
        if pending_timeout <= timedelta(0):
            raise ValueError("pending_timeout must be positive")
        self._anomaly_service = anomaly_service
        self._attempt_store = attempt_store
        self._config_loader = config_loader
        self._email_sender = email_sender
        self._retry_delay = retry_delay
        self._pending_timeout = pending_timeout
        self._coordination_lock = threading.RLock()

    def evaluate_and_notify(
        self,
        evaluated_at: datetime,
    ) -> NotificationEvaluationOutcome:
        """Evaluate and claim at most one SMTP attempt at the current time."""

        with self._coordination_lock:
            return self._evaluate_and_notify_locked(evaluated_at)

    def _evaluate_and_notify_locked(
        self,
        evaluated_at: datetime,
    ) -> NotificationEvaluationOutcome:
        anomaly = self._anomaly_service.evaluate(evaluated_at)
        if anomaly.evaluation.status is AnomalyStatus.NORMAL:
            self._attempt_store.reset(evaluated_at)
            return NotificationEvaluationOutcome(
                anomaly=anomaly,
                notification_status=NotificationDeliveryStatus.SKIPPED,
            )
        config = self._config_loader()
        if not self._attempt_store.claim_attempt(
            evaluated_at,
            pending_timeout=self._pending_timeout,
        ):
            return NotificationEvaluationOutcome(
                anomaly=anomaly,
                notification_status=NotificationDeliveryStatus.SKIPPED,
            )

        try:
            self._email_sender.send(
                config,
                anomaly.evaluation,
            )
        except Exception as exc:
            self._attempt_store.mark_failed(
                evaluated_at,
                retry_delay=self._retry_delay,
                error_code=type(exc).__name__,
            )
            raise
        self._attempt_store.mark_sent(evaluated_at)
        return NotificationEvaluationOutcome(
            anomaly=anomaly,
            notification_status=NotificationDeliveryStatus.SENT,
        )
