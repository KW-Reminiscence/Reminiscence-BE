"""Parse activity metrics and persist the current personal anomaly state."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

from reminiscence.anomaly.models import (
    AnomalyMode,
    AnomalyStatus,
    ConversationMetric,
    DomainEvaluation,
    PersonalEvaluation,
    RoutineMetric,
)
from reminiscence.storage import JsonObjectStore, JsonStorageError


class AnomalyStorageError(JsonStorageError):
    """Raised when anomaly inputs or current state are malformed."""


KNOWN_ROUTINE_STATES = frozenset({"REMINDING", "CONFIRMED", "NOT_ANSWERED"})
TERMINAL_ROUTINE_STATES = frozenset({"CONFIRMED", "NOT_ANSWERED"})


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AnomalyStorageError(f"{field_name} must be a non-empty string")
    return value


def _required_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise AnomalyStorageError(f"{field_name} must be an integer")
    return value


def _optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _required_int(value, field_name)


def _optional_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AnomalyStorageError(f"{field_name} must be a number")
    number = float(value)
    if not isfinite(number):
        raise AnomalyStorageError(f"{field_name} must be finite")
    return number


def _aware_datetime(value: Any, field_name: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(_required_string(value, field_name))
    except ValueError as exc:
        raise AnomalyStorageError(f"{field_name} must be a valid datetime") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise AnomalyStorageError(f"{field_name} must be timezone-aware")
    return timestamp


def _parse_routine_metric(value: Any) -> RoutineMetric:
    if not isinstance(value, dict):
        raise AnomalyStorageError("each routine execution must be an object")
    try:
        state = _required_string(value["state"], "state")
        if state not in KNOWN_ROUTINE_STATES:
            raise AnomalyStorageError(f"unknown routine state: {state}")
        confirmation_delay_seconds = _optional_int(
            value.get("confirmation_delay_seconds"),
            "confirmation_delay_seconds",
        )
        if confirmation_delay_seconds is not None and confirmation_delay_seconds < 0:
            raise AnomalyStorageError(
                "confirmation_delay_seconds must not be negative"
            )
        if state == "CONFIRMED" and confirmation_delay_seconds is None:
            raise AnomalyStorageError(
                "CONFIRMED routine requires confirmation_delay_seconds"
            )
        if state != "CONFIRMED" and confirmation_delay_seconds is not None:
            raise AnomalyStorageError(
                f"{state} routine must not have confirmation_delay_seconds"
            )
        return RoutineMetric(
            routine_id=_required_string(value["routine_id"], "routine_id"),
            scheduled_at=_aware_datetime(value["scheduled_at"], "scheduled_at"),
            state=state,
            confirmation_delay_seconds=confirmation_delay_seconds,
        )
    except (KeyError, ValueError) as exc:
        raise AnomalyStorageError(f"invalid routine execution: {exc}") from exc


def _parse_conversation_metric(value: Any) -> ConversationMetric | None:
    if not isinstance(value, dict):
        raise AnomalyStorageError("each conversation session must be an object")
    if value.get("status") != "COMPLETED":
        return None
    try:
        summary = value["summary"]
        if not isinstance(summary, dict):
            raise AnomalyStorageError("conversation summary must be an object")
        user_turn_count = _required_int(
            summary["user_turn_count"],
            "user_turn_count",
        )
        total_utterance_chars = _required_int(
            summary["total_utterance_chars"],
            "total_utterance_chars",
        )
        no_response_count = _required_int(
            summary["no_response_count"],
            "no_response_count",
        )
        if min(user_turn_count, total_utterance_chars, no_response_count) < 0:
            raise AnomalyStorageError(
                "conversation summary counts must not be negative"
            )
        return ConversationMetric(
            session_id=_required_string(value["session_id"], "session_id"),
            started_at=_aware_datetime(value["started_at"], "started_at"),
            user_turn_count=user_turn_count,
            total_utterance_chars=total_utterance_chars,
            average_utterance_chars=_optional_number(
                summary.get("average_utterance_chars"),
                "average_utterance_chars",
            ),
            average_turn_duration_seconds=_optional_number(
                summary.get("average_turn_duration_seconds"),
                "average_turn_duration_seconds",
            ),
            no_response_count=no_response_count,
        )
    except (KeyError, ValueError) as exc:
        raise AnomalyStorageError(
            f"invalid conversation session: {exc}"
        ) from exc


class ActivityMetricReader:
    """Read normalized detector inputs from activity_metrics.json."""

    def __init__(self, store: JsonObjectStore) -> None:
        self._store = store

    def read(
        self,
        evaluated_at: datetime,
    ) -> tuple[tuple[RoutineMetric, ...], tuple[ConversationMetric, ...]]:
        """Return metrics no later than the evaluation time."""

        root = self._store.read()
        routines_value = root.get("routine_executions", [])
        conversations_value = root.get("conversation_sessions", [])
        if not isinstance(routines_value, list):
            raise AnomalyStorageError("routine_executions must be an array")
        if not isinstance(conversations_value, list):
            raise AnomalyStorageError("conversation_sessions must be an array")
        routines = tuple(
            metric
            for metric in (
                _parse_routine_metric(value) for value in routines_value
            )
            if metric.state in TERMINAL_ROUTINE_STATES
            and metric.scheduled_at <= evaluated_at
        )
        parsed_conversations = (
            _parse_conversation_metric(value) for value in conversations_value
        )
        conversations = tuple(
            metric
            for metric in parsed_conversations
            if metric is not None and metric.started_at <= evaluated_at
        )
        return routines, conversations


def _serialize_domain(evaluation: DomainEvaluation) -> dict[str, Any]:
    return {
        "status": evaluation.status.value,
        "mode": evaluation.mode.value,
        "sample_count": evaluation.sample_count,
        "score": evaluation.score,
        "reasons": list(evaluation.reasons),
        "feature_names": list(evaluation.feature_names),
    }


def _parse_domain(value: Any) -> DomainEvaluation:
    if not isinstance(value, dict):
        raise AnomalyStorageError("domain state must be an object")
    try:
        reasons = value["reasons"]
        feature_names = value["feature_names"]
        if not isinstance(reasons, list) or not all(
            isinstance(reason, str) for reason in reasons
        ):
            raise AnomalyStorageError("reasons must be an array of strings")
        if not isinstance(feature_names, list) or not all(
            isinstance(feature_name, str) for feature_name in feature_names
        ):
            raise AnomalyStorageError("feature_names must be an array of strings")
        return DomainEvaluation(
            status=AnomalyStatus(
                _required_string(value["status"], "domain status")
            ),
            mode=AnomalyMode(_required_string(value["mode"], "mode")),
            sample_count=_required_int(value["sample_count"], "sample_count"),
            score=_optional_number(value.get("score"), "score"),
            reasons=tuple(reasons),
            feature_names=tuple(feature_names),
        )
    except (KeyError, ValueError) as exc:
        raise AnomalyStorageError(f"invalid domain state: {exc}") from exc


class PersonalStateStore:
    """Persist only the latest explainable personal state."""

    def __init__(self, store: JsonObjectStore) -> None:
        self._store = store

    def load(self) -> PersonalEvaluation | None:
        """Return the current state if it has been evaluated."""

        root = self._store.read()
        if not root or set(root) <= {"schema_version"}:
            return None
        try:
            return PersonalEvaluation(
                evaluated_at=_aware_datetime(root["evaluated_at"], "evaluated_at"),
                status=AnomalyStatus(
                    _required_string(root["status"], "status")
                ),
                routine=_parse_domain(root["routine"]),
                conversation=_parse_domain(root["conversation"]),
                consecutive_anomalous_evaluations=_required_int(
                    root.get("consecutive_anomalous_evaluations", 0),
                    "consecutive_anomalous_evaluations",
                ),
            )
        except (KeyError, ValueError) as exc:
            raise AnomalyStorageError(f"invalid personal state: {exc}") from exc

    def save(self, evaluation: PersonalEvaluation) -> None:
        """Replace the current state and model metadata atomically."""

        def mutate(root: dict[str, Any]) -> None:
            root.clear()
            root.update(
                {
                    "status": evaluation.status.value,
                    "evaluated_at": evaluation.evaluated_at.isoformat(),
                    "consecutive_anomalous_evaluations": (
                        evaluation.consecutive_anomalous_evaluations
                    ),
                    "routine": _serialize_domain(evaluation.routine),
                    "conversation": _serialize_domain(evaluation.conversation),
                    "model_metadata": {
                        "algorithm": "IsolationForest",
                        "random_state": 42,
                        "routine_baseline_days": 28,
                        "conversation_baseline_sessions": 20,
                    },
                }
            )

        self._store.update(mutate)
