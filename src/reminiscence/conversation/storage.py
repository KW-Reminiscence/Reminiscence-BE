"""Conversation session persistence in activity_metrics.json."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from math import isfinite
from typing import Any

from reminiscence.conversation.models import (
    ConversationSession,
    ConversationSource,
    ConversationStatus,
    ConversationTurnMetric,
)
from reminiscence.storage import JsonObjectStore, JsonStorageError


class ConversationStorageError(JsonStorageError):
    """Raised when conversation metrics are malformed."""


class ConversationStorageNotFoundError(LookupError):
    """Raised when an atomic session update cannot find its target."""


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConversationStorageError(f"{field_name} must be a non-empty string")
    return value


def _required_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConversationStorageError(f"{field_name} must be an integer")
    return value


def _required_number(value: Any, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConversationStorageError(f"{field_name} must be a number")
    number = float(value)
    if not isfinite(number):
        raise ConversationStorageError(f"{field_name} must be finite")
    return number


def _optional_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    return _required_number(value, field_name)


def _parse_turn(value: Any) -> ConversationTurnMetric:
    if not isinstance(value, dict):
        raise ConversationStorageError("each conversation turn must be an object")
    try:
        no_response = value["no_response"]
        if not isinstance(no_response, bool):
            raise ConversationStorageError("no_response must be a boolean")
        return ConversationTurnMetric(
            turn_id=_required_string(value["turn_id"], "turn_id"),
            recorded_at=datetime.fromisoformat(
                _required_string(value["recorded_at"], "recorded_at")
            ),
            utterance_chars=_required_int(
                value["utterance_chars"],
                "utterance_chars",
            ),
            turn_duration_seconds=_required_number(
                value["turn_duration_seconds"],
                "turn_duration_seconds",
            ),
            chars_per_second=_optional_number(
                value.get("chars_per_second"),
                "chars_per_second",
            ),
            no_response=no_response,
            asr_latency_seconds=_required_number(
                value["asr_latency_seconds"],
                "asr_latency_seconds",
            ),
            asr_attempts=_required_int(value["asr_attempts"], "asr_attempts"),
        )
    except (KeyError, ValueError) as exc:
        raise ConversationStorageError(f"invalid conversation turn: {exc}") from exc


def _parse_session(value: Any) -> ConversationSession:
    if not isinstance(value, dict):
        raise ConversationStorageError("each conversation session must be an object")
    try:
        photo_id_value = value.get("photo_id")
        if photo_id_value is not None and not isinstance(photo_id_value, str):
            raise ConversationStorageError("photo_id must be a string or null")
        turns_value = value["turns"]
        if not isinstance(turns_value, list):
            raise ConversationStorageError("turns must be an array")
        completed_at_value = value.get("completed_at")
        return ConversationSession(
            session_id=_required_string(value["session_id"], "session_id"),
            source=ConversationSource(_required_string(value["source"], "source")),
            photo_id=photo_id_value,
            started_at=datetime.fromisoformat(
                _required_string(value["started_at"], "started_at")
            ),
            status=ConversationStatus(_required_string(value["status"], "status")),
            turns=tuple(_parse_turn(turn) for turn in turns_value),
            completed_at=(
                datetime.fromisoformat(
                    _required_string(completed_at_value, "completed_at")
                )
                if completed_at_value is not None
                else None
            ),
        )
    except (KeyError, ValueError) as exc:
        raise ConversationStorageError(f"invalid conversation session: {exc}") from exc


def _serialize_turn(turn: ConversationTurnMetric) -> dict[str, Any]:
    return {
        "turn_id": turn.turn_id,
        "recorded_at": turn.recorded_at.isoformat(),
        "utterance_chars": turn.utterance_chars,
        "turn_duration_seconds": turn.turn_duration_seconds,
        "chars_per_second": turn.chars_per_second,
        "no_response": turn.no_response,
        "asr_latency_seconds": turn.asr_latency_seconds,
        "asr_attempts": turn.asr_attempts,
    }


def _serialize_session(session: ConversationSession) -> dict[str, Any]:
    summary = session.summary
    return {
        "session_id": session.session_id,
        "source": session.source.value,
        "photo_id": session.photo_id,
        "started_at": session.started_at.isoformat(),
        "status": session.status.value,
        "completed_at": (
            session.completed_at.isoformat()
            if session.completed_at is not None
            else None
        ),
        "turns": [_serialize_turn(turn) for turn in session.turns],
        "summary": {
            "user_turn_count": summary.user_turn_count,
            "total_utterance_chars": summary.total_utterance_chars,
            "average_utterance_chars": summary.average_utterance_chars,
            "average_turn_duration_seconds": (
                summary.average_turn_duration_seconds
            ),
            "no_response_count": summary.no_response_count,
        },
    }


class JsonConversationStore:
    """Persist metrics-only conversation sessions."""

    def __init__(self, json_store: JsonObjectStore) -> None:
        self._json_store = json_store

    def list_sessions(self) -> tuple[ConversationSession, ...]:
        """Load every conversation session."""

        root = self._json_store.read()
        sessions_value = root.get("conversation_sessions", [])
        if not isinstance(sessions_value, list):
            raise ConversationStorageError("conversation_sessions must be an array")
        return tuple(_parse_session(value) for value in sessions_value)

    def get_session(self, session_id: str) -> ConversationSession | None:
        """Find one conversation session."""

        return next(
            (
                session
                for session in self.list_sessions()
                if session.session_id == session_id
            ),
            None,
        )

    def save_session(self, session: ConversationSession) -> None:
        """Insert or replace one session while preserving other metric domains."""

        def mutate(root: dict[str, Any]) -> None:
            sessions_value = root.get("conversation_sessions", [])
            if not isinstance(sessions_value, list):
                raise ConversationStorageError(
                    "conversation_sessions must be an array"
                )
            sessions = [_parse_session(value) for value in sessions_value]
            updated = [
                current
                for current in sessions
                if current.session_id != session.session_id
            ]
            updated.append(session)
            updated.sort(key=lambda current: (current.started_at, current.session_id))
            root["conversation_sessions"] = [
                _serialize_session(current) for current in updated
            ]

        self._json_store.update(mutate)

    def update_session(
        self,
        session_id: str,
        updater: Callable[[ConversationSession], ConversationSession],
    ) -> ConversationSession:
        """Atomically read, update, and replace one session."""

        updated_session: ConversationSession | None = None

        def mutate(root: dict[str, Any]) -> None:
            nonlocal updated_session
            sessions_value = root.get("conversation_sessions", [])
            if not isinstance(sessions_value, list):
                raise ConversationStorageError(
                    "conversation_sessions must be an array"
                )
            sessions = [_parse_session(value) for value in sessions_value]
            current = next(
                (
                    session
                    for session in sessions
                    if session.session_id == session_id
                ),
                None,
            )
            if current is None:
                raise ConversationStorageNotFoundError(
                    f"conversation session not found: {session_id}"
                )
            updated_session = updater(current)
            updated = [
                session
                for session in sessions
                if session.session_id != session_id
            ]
            updated.append(updated_session)
            updated.sort(key=lambda session: (session.started_at, session.session_id))
            root["conversation_sessions"] = [
                _serialize_session(session) for session in updated
            ]

        self._json_store.update(mutate)
        if updated_session is None:  # pragma: no cover - defensive invariant
            raise ConversationStorageError("session update produced no result")
        return updated_session
