"""Persistable conversation metrics without transcript content."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite


class ConversationSource(StrEnum):
    """How the user entered a conversation session."""

    SCHEDULED = "SCHEDULED"
    VOLUNTARY = "VOLUNTARY"


class ConversationStatus(StrEnum):
    """Lifecycle state for a conversation session."""

    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class ConversationCompletionReason(StrEnum):
    """Why the tablet finalized an active conversation."""

    USER_FINISHED = "USER_FINISHED"
    INACTIVITY_TIMEOUT = "INACTIVITY_TIMEOUT"
    MAX_DURATION = "MAX_DURATION"
    NAVIGATION = "NAVIGATION"


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
    speech_detected: bool | None = None

    def __post_init__(self) -> None:
        if not self.turn_id.strip():
            raise ValueError("turn_id must not be blank")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        if self.utterance_chars < 0:
            raise ValueError("utterance_chars must not be negative")
        if (
            not isfinite(self.turn_duration_seconds)
            or self.turn_duration_seconds < 0
        ):
            raise ValueError("turn_duration_seconds must be finite and non-negative")
        if self.chars_per_second is not None and (
            not isfinite(self.chars_per_second) or self.chars_per_second < 0
        ):
            raise ValueError("chars_per_second must be finite and non-negative")
        if self.speech_detected is not None and not isinstance(
            self.speech_detected,
            bool,
        ):
            raise ValueError("speech_detected must be a boolean or null")
        expected_no_response = (
            self.utterance_chars == 0 or self.speech_detected is False
        )
        if self.no_response != expected_no_response:
            raise ValueError("no_response must match speech and utterance metrics")
        if not isfinite(self.asr_latency_seconds) or self.asr_latency_seconds < 0:
            raise ValueError("asr_latency_seconds must be finite and non-negative")
        if self.asr_attempts <= 0:
            raise ValueError("asr_attempts must be positive")


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
    completion_reason: ConversationCompletionReason | None = None

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be blank")
        if self.photo_id is not None and not self.photo_id.strip():
            raise ValueError("photo_id must not be blank")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("started_at must be timezone-aware")
        if self.status is ConversationStatus.ACTIVE and (
            self.completed_at is not None or self.completion_reason is not None
        ):
            raise ValueError("ACTIVE session must not have completion fields")
        if self.status is ConversationStatus.COMPLETED:
            if self.completed_at is None:
                raise ValueError("COMPLETED session requires completed_at")
            if (
                self.completed_at.tzinfo is None
                or self.completed_at.utcoffset() is None
            ):
                raise ValueError("completed_at must be timezone-aware")
            if self.completed_at < self.started_at:
                raise ValueError("completed_at must not be before started_at")
        for turn in self.turns:
            if turn.recorded_at < self.started_at:
                raise ValueError("turn must not be recorded before session start")
            if self.completed_at is not None and turn.recorded_at > self.completed_at:
                raise ValueError("turn must not be recorded after session completion")

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
