"""Application service for evaluating and persisting personal state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from reminiscence.anomaly.detector import PersonalAnomalyDetector
from reminiscence.anomaly.models import AnomalyStatus, PersonalEvaluation
from reminiscence.anomaly.storage import ActivityMetricReader, PersonalStateStore


@dataclass(frozen=True, slots=True)
class AnomalyEvaluationOutcome:
    """Current evaluation and whether it newly entered ANOMALOUS."""

    evaluation: PersonalEvaluation
    became_anomalous: bool


class AnomalyService:
    """Evaluate activity data and store the latest state."""

    def __init__(
        self,
        reader: ActivityMetricReader,
        state_store: PersonalStateStore,
        detector: PersonalAnomalyDetector | None = None,
    ) -> None:
        self._reader = reader
        self._state_store = state_store
        self._detector = detector or PersonalAnomalyDetector()

    def evaluate(self, evaluated_at: datetime) -> AnomalyEvaluationOutcome:
        """Evaluate current metrics and detect a transition into anomaly."""

        previous = self._state_store.load()
        routine_metrics, conversation_metrics = self._reader.read(evaluated_at)
        evaluation = self._detector.evaluate(
            routine_metrics,
            conversation_metrics,
            evaluated_at,
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
