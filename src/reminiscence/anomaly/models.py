"""Provider-neutral inputs and outputs for personal anomaly evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AnomalyStatus(StrEnum):
    """Current individual state."""

    NORMAL = "NORMAL"
    ANOMALOUS = "ANOMALOUS"


class AnomalyMode(StrEnum):
    """Rule or model used for the latest domain evaluation."""

    COLD_START = "COLD_START"
    ISOLATION_FOREST = "ISOLATION_FOREST"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class RoutineMetric:
    """Minimal routine execution fields consumed by anomaly detection."""

    routine_id: str
    scheduled_at: datetime
    state: str
    confirmation_delay_seconds: int | None


@dataclass(frozen=True, slots=True)
class ConversationMetric:
    """Completed session summary consumed by conversation detection."""

    session_id: str
    started_at: datetime
    user_turn_count: int
    total_utterance_chars: int
    average_utterance_chars: float | None
    average_turn_duration_seconds: float | None
    no_response_count: int


@dataclass(frozen=True, slots=True)
class DomainEvaluation:
    """One detector's current state and human-readable basis."""

    status: AnomalyStatus
    mode: AnomalyMode
    sample_count: int
    score: float | None
    reasons: tuple[str, ...]
    feature_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PersonalEvaluation:
    """Combined state while preserving separate domain models."""

    evaluated_at: datetime
    status: AnomalyStatus
    routine: DomainEvaluation
    conversation: DomainEvaluation
