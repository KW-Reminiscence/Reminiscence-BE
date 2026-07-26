"""Conversation lifecycle and transcript-to-metrics reduction."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from reminiscence.asr import RecognitionResult
from reminiscence.conversation.models import (
    ConversationSession,
    ConversationSource,
    ConversationStatus,
    ConversationTurnMetric,
)
from reminiscence.conversation.storage import JsonConversationStore


class ConversationNotFoundError(LookupError):
    """Raised when a session identifier is unknown."""


class ConversationStateError(ValueError):
    """Raised when a completed session receives another mutation."""


def _require_aware(timestamp: datetime, field_name: str) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class ConversationService:
    """Persist only metrics after transiently reducing ASR text."""

    def __init__(
        self,
        store: JsonConversationStore,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._id_factory = id_factory or (lambda: uuid4().hex)

    def start_session(
        self,
        source: ConversationSource,
        photo_id: str | None,
        started_at: datetime,
    ) -> ConversationSession:
        """Create an active conversation session."""

        _require_aware(started_at, "started_at")
        if photo_id is not None and not photo_id.strip():
            raise ValueError("photo_id must not be blank")
        session = ConversationSession(
            session_id=self._id_factory(),
            source=source,
            photo_id=photo_id,
            started_at=started_at,
            status=ConversationStatus.ACTIVE,
            turns=(),
        )
        self._store.save_session(session)
        return session

    def record_turn(
        self,
        session_id: str,
        recognition: RecognitionResult,
        turn_duration_seconds: float,
        recorded_at: datetime,
    ) -> ConversationTurnMetric:
        """Reduce a transient transcript to metrics and discard the text."""

        _require_aware(recorded_at, "recorded_at")
        if turn_duration_seconds < 0 or turn_duration_seconds > 300:
            raise ValueError("turn_duration_seconds must be between 0 and 300")
        session = self._require_active_session(session_id)
        utterance_chars = len("".join(recognition.transcript.split()))
        no_response = utterance_chars == 0
        metric = ConversationTurnMetric(
            turn_id=self._id_factory(),
            recorded_at=recorded_at,
            utterance_chars=utterance_chars,
            turn_duration_seconds=turn_duration_seconds,
            chars_per_second=(
                round(utterance_chars / turn_duration_seconds, 3)
                if utterance_chars > 0 and turn_duration_seconds > 0
                else None
            ),
            no_response=no_response,
            asr_latency_seconds=recognition.latency_seconds,
            asr_attempts=recognition.attempts,
        )
        updated = replace(session, turns=(*session.turns, metric))
        self._store.save_session(updated)
        return metric

    def complete_session(
        self,
        session_id: str,
        completed_at: datetime,
    ) -> ConversationSession:
        """Finalize one active conversation session."""

        _require_aware(completed_at, "completed_at")
        session = self._require_active_session(session_id)
        if completed_at < session.started_at:
            raise ValueError("completed_at must not be before started_at")
        completed = replace(
            session,
            status=ConversationStatus.COMPLETED,
            completed_at=completed_at,
        )
        self._store.save_session(completed)
        return completed

    def get_session(self, session_id: str) -> ConversationSession:
        """Return one session or raise a domain-specific error."""

        session = self._store.get_session(session_id)
        if session is None:
            raise ConversationNotFoundError(
                f"conversation session not found: {session_id}"
            )
        return session

    def list_sessions(self) -> tuple[ConversationSession, ...]:
        """Return all persisted sessions."""

        return self._store.list_sessions()

    def _require_active_session(self, session_id: str) -> ConversationSession:
        session = self.get_session(session_id)
        if session.status is not ConversationStatus.ACTIVE:
            raise ConversationStateError(
                f"conversation session is {session.status}"
            )
        return session
