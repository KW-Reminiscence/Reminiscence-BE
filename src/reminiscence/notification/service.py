"""Coordinate anomaly evaluation and one guardian email attempt."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
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
    """Attempt one email for each anomaly episode and never arbitrary text."""

    def __init__(
        self,
        anomaly_service: AnomalyEvaluator,
        attempt_store: NotificationAttemptStore,
        config_loader: Callable[[], NotificationConfig],
        email_sender: GuardianEmailSender,
    ) -> None:
        self._anomaly_service = anomaly_service
        self._attempt_store = attempt_store
        self._config_loader = config_loader
        self._email_sender = email_sender

    def evaluate_and_notify(
        self,
        evaluated_at: datetime,
    ) -> NotificationEvaluationOutcome:
        """Evaluate and perform at most one SMTP attempt per anomaly episode."""

        anomaly = self._anomaly_service.evaluate(evaluated_at)
        if anomaly.evaluation.status is AnomalyStatus.NORMAL:
            self._attempt_store.reset(evaluated_at)
            return NotificationEvaluationOutcome(
                anomaly=anomaly,
                notification_status=NotificationDeliveryStatus.SKIPPED,
            )
        if self._attempt_store.was_attempted():
            return NotificationEvaluationOutcome(
                anomaly=anomaly,
                notification_status=NotificationDeliveryStatus.SKIPPED,
            )

        self._attempt_store.mark_attempted(evaluated_at)
        self._email_sender.send(
            self._config_loader(),
            anomaly.evaluation,
        )
        return NotificationEvaluationOutcome(
            anomaly=anomaly,
            notification_status=NotificationDeliveryStatus.SENT,
        )
