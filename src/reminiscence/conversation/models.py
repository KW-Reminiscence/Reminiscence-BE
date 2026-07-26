"""Persistable conversation metrics without transcript content."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ConversationSource(StrEnum):
    """How the user entered a conversation session."""

    SCHEDULED = "SCHEDULED"
    VOLUNTARY = "VOLUNTARY"


class ConversationStatus(StrEnum):
    """Lifecycle state for a conversation session."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class ConversationTurnMetric:
    """One user turn reduced to directly observable metrics."""

    turn_id: str
    recorded_at: datetime
    utterance_chars: int
    turn_duration_seconds: float
    chars_per_second: float | None
    no_response: bool
    asr_latency_seconds: float
    asr_attempts: int


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    """Aggregate metrics for one completed or active session."""

    user_turn_count: int
    total_utterance_chars: int
    average_utterance_chars: float | None
    average_turn_duration_seconds: float | None
    no_response_count: int


@dataclass(frozen=True, slots=True)
class ConversationSession:
    """A conversation session with metrics-only user turns."""

    session_id: str
    source: ConversationSource
    photo_id: str | None
    started_at: datetime
    status: ConversationStatus
    turns: tuple[ConversationTurnMetric, ...]
    completed_at: datetime | None = None

    @property
    def summary(self) -> ConversationSummary:
        """Compute an aggregate while excluding no-response turns from averages."""

        answered = tuple(turn for turn in self.turns if not turn.no_response)
        total_chars = sum(turn.utterance_chars for turn in answered)
        return ConversationSummary(
            user_turn_count=len(answered),
            total_utterance_chars=total_chars,
            average_utterance_chars=(
                round(total_chars / len(answered), 3) if answered else None
            ),
            average_turn_duration_seconds=(
                round(
                    sum(turn.turn_duration_seconds for turn in answered)
                    / len(answered),
                    3,
                )
                if answered
                else None
            ),
            no_response_count=sum(turn.no_response for turn in self.turns),
        )
