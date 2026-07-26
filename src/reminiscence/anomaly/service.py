"""Application service for evaluating and persisting personal state."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from reminiscence.anomaly.detector import PersonalAnomalyDetector
from reminiscence.anomaly.models import AnomalyStatus, PersonalEvaluation
from reminiscence.anomaly.storage import ActivityMetricReader, PersonalStateStore


@dataclass(frozen=True, slots=True)
class AnomalyEvaluationOutcome:
    """Current evaluation and whether it newly entered ANOMALOUS."""

    evaluation: PersonalEvaluation
    became_anomalous: bool


DEFAULT_ANOMALY_CONFIRMATION_COUNT = 3


class AnomalyService:
    """Evaluate activity data and store the latest state."""

    def __init__(
        self,
        reader: ActivityMetricReader,
        state_store: PersonalStateStore,
        detector: PersonalAnomalyDetector | None = None,
        *,
        confirmation_count: int = DEFAULT_ANOMALY_CONFIRMATION_COUNT,
    ) -> None:
        if confirmation_count <= 0:
            raise ValueError("confirmation_count must be positive")
        self._reader = reader
        self._state_store = state_store
        self._detector = detector or PersonalAnomalyDetector()
        self._confirmation_count = confirmation_count

    def evaluate(self, evaluated_at: datetime) -> AnomalyEvaluationOutcome:
        """Evaluate current metrics and detect a transition into anomaly."""

        previous = self._state_store.load()
        routine_metrics, conversation_metrics = self._reader.read(evaluated_at)
        candidate = self._detector.evaluate(
            routine_metrics,
            conversation_metrics,
            evaluated_at,
        )
        if candidate.status is AnomalyStatus.ANOMALOUS:
            previous_count = (
                self._confirmation_count
                if previous is not None
                and previous.status is AnomalyStatus.ANOMALOUS
                else (
                    previous.consecutive_anomalous_evaluations
                    if previous is not None
                    else 0
                )
            )
            consecutive_count = min(
                previous_count + 1,
                self._confirmation_count,
            )
        else:
            consecutive_count = 0
        confirmed_status = (
            AnomalyStatus.ANOMALOUS
            if consecutive_count >= self._confirmation_count
            else AnomalyStatus.NORMAL
        )
        evaluation = replace(
            candidate,
            status=confirmed_status,
            consecutive_anomalous_evaluations=consecutive_count,
        )
        became_anomalous = (
            evaluation.status is AnomalyStatus.ANOMALOUS
            and (
                previous is None
                or previous.status is not AnomalyStatus.ANOMALOUS
            )
        )
        self._state_store.save(evaluation)
        return AnomalyEvaluationOutcome(
            evaluation=evaluation,
            became_anomalous=became_anomalous,
        )

    def current_state(self) -> PersonalEvaluation | None:
        """Return the last persisted state."""

        return self._state_store.load()
