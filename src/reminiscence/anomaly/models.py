"""Provider-neutral observations and explainable anomaly results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class AnomalyStatus(StrEnum):
    """Current individual state."""

    NORMAL = "NORMAL"
    ANOMALOUS = "ANOMALOUS"


class AnomalyMode(StrEnum):
    """Primary evaluation mode used for a domain."""

    COLD_START = "COLD_START"
    ISOLATION_FOREST = "ISOLATION_FOREST"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class RoutineMetric:
    """Routine execution fields consumed while materializing a completed day."""

    routine_id: str
    scheduled_at: datetime
    state: str
    confirmation_delay_seconds: int | None
    category: str | None = None


@dataclass(frozen=True, slots=True)
class ConversationMetric:
    """Completed session summary consumed by conversation detection."""

    session_id: str
    started_at: datetime
    completed_at: datetime
    user_turn_count: int
    total_utterance_chars: int
    average_utterance_chars: float | None
    average_turn_duration_seconds: float | None
    no_response_count: int


@dataclass(frozen=True, slots=True)
class RoutineObservation:
    """Immutable six-feature summary for one completed local date."""

    target_date: date
    values: tuple[float, float, float, float, float, float]

    @property
    def key(self) -> str:
        return self.target_date.isoformat()


@dataclass(frozen=True, slots=True)
class ConversationQualityObservation:
    """Immutable five-feature summary for one completed session."""

    session_id: str
    completed_at: datetime
    values: tuple[float, float, float, float, float]

    @property
    def key(self) -> str:
        return self.session_id


@dataclass(frozen=True, slots=True)
class ParticipationObservation:
    """Immutable daily seven-day conversation participation total."""

    target_date: date
    recent_7_day_user_turn_count: int

    @property
    def key(self) -> str:
        return self.target_date.isoformat()


@dataclass(frozen=True, slots=True)
class AnomalyObservations:
    """All immutable observations available at one evaluation."""

    routine_days: tuple[RoutineObservation, ...]
    conversation_quality: tuple[ConversationQualityObservation, ...]
    participation_days: tuple[ParticipationObservation, ...]


@dataclass(frozen=True, slots=True)
class BaselineState:
    """Fixed personal baselines reconstructed from JSON values."""

    routine_vectors: tuple[tuple[float, ...], ...] = ()
    conversation_quality_vectors: tuple[tuple[float, ...], ...] = ()
    participation_weekly_turn_mean: float | None = None


@dataclass(frozen=True, slots=True)
class DomainEvaluation:
    """One domain's explainable three-signal consensus."""

    status: AnomalyStatus
    mode: AnomalyMode
    sample_count: int
    score: float | None
    reasons: tuple[str, ...]
    feature_names: tuple[str, ...]
    rule_based_signal: bool = False
    isolation_forest_signal: bool = False
    persistence_signal: bool = False
    observation_key: str | None = None

    @property
    def signal_count(self) -> int:
        """Return the number of active independent policy signals."""

        return sum(
            (
                self.rule_based_signal,
                self.isolation_forest_signal,
                self.persistence_signal,
            )
        )


@dataclass(frozen=True, slots=True)
class PersonalEvaluation:
    """Combined state while preserving separate domain evidence."""

    evaluated_at: datetime
    status: AnomalyStatus
    routine: DomainEvaluation
    conversation: DomainEvaluation
    consecutive_anomalous_evaluations: int = 0

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self.consecutive_anomalous_evaluations < 0:
            raise ValueError(
                "consecutive_anomalous_evaluations must not be negative"
            )
