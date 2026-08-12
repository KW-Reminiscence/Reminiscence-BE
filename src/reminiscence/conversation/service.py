"""Conversation lifecycle and transcript-to-metrics reduction."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from math import isfinite
from uuid import uuid4

from reminiscence.asr import RecognitionResult
from reminiscence.conversation.models import (
    ConversationSession,
    ConversationSource,
    ConversationStatus,
    ConversationTurnMetric,
)
from reminiscence.conversation.storage import (
    ConversationStorageConflictError,
    ConversationStorageNotFoundError,
    JsonConversationStore,
)


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
        try:
            self._store.create_session(session)
        except ConversationStorageConflictError as exc:
            raise ConversationStateError(str(exc)) from exc
        return session

    def record_turn(
        self,
        session_id: str,
        recognition: RecognitionResult,
        turn_duration_seconds: float,
        recorded_at: datetime,
        turn_id: str | None = None,
    ) -> ConversationTurnMetric:
        """Reduce a transient transcript to metrics and discard the text."""

        _require_aware(recorded_at, "recorded_at")
        if turn_id is not None and not turn_id.strip():
            raise ValueError("turn_id must not be blank")
        if (
            not isfinite(turn_duration_seconds)
            or turn_duration_seconds < 0
            or turn_duration_seconds > 300
        ):
            raise ValueError("turn_duration_seconds must be between 0 and 300")
        metric: ConversationTurnMetric | None = None

        def append_turn(session: ConversationSession) -> ConversationSession:
            nonlocal metric
            requested_id = turn_id or self._id_factory()
            existing = next(
                (turn for turn in session.turns if turn.turn_id == requested_id),
                None,
            )
            if existing is not None:
                metric = existing
                return session
            self._require_active(session)
            if recorded_at < session.started_at:
                raise ValueError("recorded_at must not be before started_at")
            utterance_chars = len("".join(recognition.transcript.split()))
            no_response = utterance_chars == 0
            metric = ConversationTurnMetric(
                turn_id=requested_id,
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
            return replace(session, turns=(*session.turns, metric))

        try:
            self._store.update_session(session_id, append_turn)
        except ConversationStorageNotFoundError as exc:
            raise ConversationNotFoundError(str(exc)) from exc
        if metric is None:  # pragma: no cover - defensive invariant
            raise RuntimeError("conversation turn update produced no metric")
        return metric

    def get_turn(
        self,
        session_id: str,
        turn_id: str,
    ) -> ConversationTurnMetric | None:
        """Return an already reduced turn without invoking providers."""

        session = self.get_session(session_id)
        return next((turn for turn in session.turns if turn.turn_id == turn_id), None)

    def complete_session(
        self,
        session_id: str,
        completed_at: datetime,
    ) -> ConversationSession:
        """Finalize one active conversation session."""

        _require_aware(completed_at, "completed_at")

        def complete(session: ConversationSession) -> ConversationSession:
            if session.status is ConversationStatus.COMPLETED:
                return session
            if completed_at < session.started_at:
                raise ValueError("completed_at must not be before started_at")
            return replace(
                session,
                status=ConversationStatus.COMPLETED,
                completed_at=completed_at,
            )

        try:
            return self._store.update_session(session_id, complete)
        except ConversationStorageNotFoundError as exc:
            raise ConversationNotFoundError(str(exc)) from exc

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

    def require_active_session(self, session_id: str) -> ConversationSession:
        """Validate a session before sending its audio to an ASR provider."""

        return self._require_active_session(session_id)

    def _require_active_session(self, session_id: str) -> ConversationSession:
        session = self.get_session(session_id)
        self._require_active(session)
        return session

    @staticmethod
    def _require_active(session: ConversationSession) -> None:
        if session.status is not ConversationStatus.ACTIVE:
            raise ConversationStateError(
                f"conversation session is {session.status}"
            )
