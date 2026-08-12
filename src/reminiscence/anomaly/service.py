"""Application service for observation-driven personal anomaly evaluation."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime

from reminiscence.anomaly.detector import PersonalAnomalyDetector
from reminiscence.anomaly.models import AnomalyStatus, PersonalEvaluation
from reminiscence.anomaly.storage import (
    ActivityObservationStore,
    BaselineStore,
    PersonalStateStore,
)


@dataclass(frozen=True, slots=True)
class AnomalyEvaluationOutcome:
    """Current evaluation and whether it newly entered ANOMALOUS."""

    evaluation: PersonalEvaluation
    became_anomalous: bool


class AnomalyService:
    """Materialize new observations, evaluate them and persist current evidence."""

    def __init__(
        self,
        observation_store: ActivityObservationStore,
        baseline_store: BaselineStore,
        state_store: PersonalStateStore,
        detector: PersonalAnomalyDetector | None = None,
    ) -> None:
        self._observation_store = observation_store
        self._baseline_store = baseline_store
        self._state_store = state_store
        self._detector = detector or PersonalAnomalyDetector()
        self._evaluation_lock = threading.RLock()

    def evaluate(self, evaluated_at: datetime) -> AnomalyEvaluationOutcome:
        """Evaluate only immutable date/session observations available by now."""

        with self._evaluation_lock:
            previous = self._state_store.load()
            if previous is not None and evaluated_at < previous.evaluated_at:
                raise ValueError("evaluated_at must not move backwards")
            observations = self._observation_store.materialize(evaluated_at)
            baseline = self._baseline_store.load_or_initialize(observations)
            candidate = self._detector.evaluate(
                observations,
                baseline,
                evaluated_at,
            )
            evaluation = replace(
                candidate,
                consecutive_anomalous_evaluations=(
                    1 if candidate.status is AnomalyStatus.ANOMALOUS else 0
                ),
            )
            became_anomalous = (
                evaluation.status is AnomalyStatus.ANOMALOUS
                and (
                    previous is None
                    or previous.status is not AnomalyStatus.ANOMALOUS
                )
            )
            self._state_store.save(evaluation)
            return AnomalyEvaluationOutcome(evaluation, became_anomalous)

    def current_state(self) -> PersonalEvaluation | None:
        """Return the last persisted state without materializing observations."""

        return self._state_store.load()
