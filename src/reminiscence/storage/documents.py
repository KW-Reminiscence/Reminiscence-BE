"""Canonical schemas for every versioned application JSON document."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any


class JsonDocumentValidationError(ValueError):
    """Raised when a versioned document does not match its domain schema."""


@dataclass(frozen=True, slots=True)
class DocumentSpec:
    """One known JSON document and its root-level defaults and validator."""

    filename: str
    defaults: dict[str, Any]
    validate: Callable[[dict[str, Any]], None]


def _require_exact_keys(
    root: dict[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    keys = set(root)
    optional_keys = set() if optional is None else optional
    missing = required - keys
    unknown = keys - required - optional_keys - {"schema_version"}
    if missing:
        raise JsonDocumentValidationError(
            "missing fields: " + ", ".join(sorted(missing))
        )
    if unknown:
        raise JsonDocumentValidationError(
            "unknown fields: " + ", ".join(sorted(unknown))
        )


def _require_list(root: dict[str, Any], key: str) -> list[Any]:
    value = root.get(key)
    if not isinstance(value, list):
        raise JsonDocumentValidationError(f"{key} must be an array")
    return value


def _aware_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise JsonDocumentValidationError(f"{field_name} must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise JsonDocumentValidationError(
            f"{field_name} must be a valid datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise JsonDocumentValidationError(f"{field_name} must be timezone-aware")
    return parsed


def _validate_configuration(root: dict[str, Any]) -> None:
    from reminiscence.conversation.photos import parse_photos
    from reminiscence.routine.storage import (
        _parse_definition,
        _validate_non_overlapping_windows,
    )

    _require_exact_keys(
        root,
        required={"routines", "photos", "conversation"},
    )
    routines = tuple(_parse_definition(value) for value in _require_list(root, "routines"))
    identifiers = [routine.routine_id for routine in routines]
    if len(identifiers) != len(set(identifiers)):
        raise JsonDocumentValidationError("routine ids must be unique")
    _validate_non_overlapping_windows(routines)
    parse_photos(_require_list(root, "photos"))

    conversation = root["conversation"]
    if not isinstance(conversation, dict):
        raise JsonDocumentValidationError("conversation must be an object")
    unknown = set(conversation) - {"suggestion_time"}
    if unknown:
        raise JsonDocumentValidationError(
            "unknown conversation fields: " + ", ".join(sorted(unknown))
        )
    suggestion_time = conversation.get("suggestion_time")
    if suggestion_time is not None:
        if not isinstance(suggestion_time, str):
            raise JsonDocumentValidationError(
                "conversation.suggestion_time must be a string"
            )
        try:
            parsed_time = time.fromisoformat(suggestion_time)
        except ValueError as exc:
            raise JsonDocumentValidationError(
                "conversation.suggestion_time must be a valid local time"
            ) from exc
        if parsed_time.tzinfo is not None:
            raise JsonDocumentValidationError(
                "conversation.suggestion_time must not include a timezone"
            )


def _validate_activity(root: dict[str, Any]) -> None:
    from reminiscence.anomaly.storage import (
        _parse_conversation_metric,
        _parse_participation_observation,
        _parse_quality_observation,
        _parse_routine_observation,
    )
    from reminiscence.conversation.storage import _parse_session
    from reminiscence.routine.storage import _parse_execution

    _require_exact_keys(
        root,
        required={"routine_executions", "conversation_sessions"},
        optional={
            "routine_observations",
            "conversation_quality_observations",
            "participation_observations",
            "anomaly_observation_started_on",
        },
    )
    executions = _require_list(root, "routine_executions")
    sessions = _require_list(root, "conversation_sessions")
    parsed_executions = tuple(_parse_execution(value) for value in executions)
    parsed_sessions = tuple(_parse_session(value) for value in sessions)
    execution_ids = [execution.execution_id for execution in parsed_executions]
    session_ids = [session.session_id for session in parsed_sessions]
    if len(execution_ids) != len(set(execution_ids)):
        raise JsonDocumentValidationError("routine execution ids must be unique")
    if len(session_ids) != len(set(session_ids)):
        raise JsonDocumentValidationError("conversation session ids must be unique")
    for value in sessions:
        _parse_conversation_metric(value)
    observation_specs = (
        ("routine_observations", _parse_routine_observation),
        ("conversation_quality_observations", _parse_quality_observation),
        ("participation_observations", _parse_participation_observation),
    )
    for key, parser in observation_specs:
        values = root.get(key, [])
        if not isinstance(values, list):
            raise JsonDocumentValidationError(f"{key} must be an array")
        parsed = tuple(parser(value) for value in values)
        keys = [item.key for item in parsed]
        if len(keys) != len(set(keys)):
            raise JsonDocumentValidationError(f"{key} keys must be unique")
    observation_started_on = root.get("anomaly_observation_started_on")
    if observation_started_on is not None:
        from reminiscence.anomaly.storage import _local_date

        _local_date(observation_started_on, "anomaly_observation_started_on")


def _validate_anomaly_baseline(root: dict[str, Any]) -> None:
    from reminiscence.anomaly.storage import BaselineStore, _number

    _require_exact_keys(
        root,
        required=set(),
        optional={
            "routine_vectors",
            "conversation_quality_vectors",
            "participation_weekly_turn_mean",
            "model",
        },
    )
    routine = BaselineStore._vectors(root.get("routine_vectors"), 6, "routine_vectors")
    quality = BaselineStore._vectors(
        root.get("conversation_quality_vectors"),
        5,
        "conversation_quality_vectors",
    )
    if routine and len(routine) != 28:
        raise JsonDocumentValidationError("routine_vectors must contain 28 rows")
    if quality and len(quality) != 20:
        raise JsonDocumentValidationError(
            "conversation_quality_vectors must contain 20 rows"
        )
    for index, vector in enumerate(routine):
        _validate_routine_baseline_vector(vector, index)
    for index, vector in enumerate(quality):
        _validate_quality_baseline_vector(vector, index)
    participation = root.get("participation_weekly_turn_mean")
    if participation is not None and _number(
        participation,
        "participation_weekly_turn_mean",
    ) < 0:
        raise JsonDocumentValidationError(
            "participation_weekly_turn_mean must not be negative"
        )
    model = root.get("model")
    if (routine or quality or participation is not None) and model is None:
        raise JsonDocumentValidationError(
            "anomaly model settings are required when a baseline exists"
        )
    if model is not None and model != {
        "algorithm": "IsolationForest",
        "random_state": 42,
        "n_estimators": 100,
        "contamination": 0.1,
    }:
        raise JsonDocumentValidationError("anomaly model settings are invalid")


def _validate_routine_baseline_vector(
    vector: tuple[float, ...],
    index: int,
) -> None:
    if any(vector[position] < 0 or vector[position] > 1 for position in (0, 1, 4)):
        raise JsonDocumentValidationError(
            f"routine_vectors[{index}] ratios must be between 0 and 1"
        )
    if vector[2] < 0 or vector[3] < 0:
        raise JsonDocumentValidationError(
            f"routine_vectors[{index}] delays must not be negative"
        )
    if vector[5] < 0 or not vector[5].is_integer():
        raise JsonDocumentValidationError(
            f"routine_vectors[{index}] streak must be a non-negative integer"
        )


def _validate_quality_baseline_vector(
    vector: tuple[float, ...],
    index: int,
) -> None:
    if any(value < 0 for value in vector):
        raise JsonDocumentValidationError(
            f"conversation_quality_vectors[{index}] values must not be negative"
        )
    if any(not vector[position].is_integer() for position in (0, 1, 4)):
        raise JsonDocumentValidationError(
            f"conversation_quality_vectors[{index}] counts must be integers"
        )


def _validate_personal_state(root: dict[str, Any]) -> None:
    from reminiscence.anomaly.models import AnomalyStatus
    from reminiscence.anomaly.storage import _parse_domain

    keys = set(root) - {"schema_version"}
    if not keys:
        return
    _require_exact_keys(
        root,
        required={
            "status",
            "evaluated_at",
            "consecutive_anomalous_evaluations",
            "routine",
            "conversation",
            "model_metadata",
        },
    )
    try:
        AnomalyStatus(root["status"])
    except (TypeError, ValueError) as exc:
        raise JsonDocumentValidationError("invalid personal_state status") from exc
    _aware_datetime(root["evaluated_at"], "evaluated_at")
    consecutive = root["consecutive_anomalous_evaluations"]
    if not isinstance(consecutive, int) or isinstance(consecutive, bool) or consecutive < 0:
        raise JsonDocumentValidationError(
            "consecutive_anomalous_evaluations must be a non-negative integer"
        )
    _parse_domain(root["routine"])
    _parse_domain(root["conversation"])
    metadata = root["model_metadata"]
    if not isinstance(metadata, dict):
        raise JsonDocumentValidationError("model_metadata must be an object")
    legacy_metadata = {
        "algorithm": "IsolationForest",
        "random_state": 42,
        "routine_baseline_days": 28,
        "conversation_baseline_sessions": 20,
    }
    current_metadata = {
        **legacy_metadata,
        "participation_baseline_days": 28,
        "consensus_required_signals": 2,
    }
    if metadata != legacy_metadata and metadata != current_metadata:
        raise JsonDocumentValidationError("model_metadata is invalid")


def _validate_notification_state(root: dict[str, Any]) -> None:
    from reminiscence.notification.state import _parse_state

    _require_exact_keys(
        root,
        required=set(),
        optional={
            "anomaly_notification_attempted",
            "delivery_status",
            "attempt_count",
            "updated_at",
            "next_retry_at",
            "last_error",
        },
    )
    if "anomaly_notification_attempted" in root and any(
        field in root
        for field in (
            "delivery_status",
            "attempt_count",
            "next_retry_at",
            "last_error",
        )
    ):
        raise JsonDocumentValidationError(
            "legacy and current notification state fields must not be mixed"
        )
    _parse_state(root)


def _validate_auth_sessions(root: dict[str, Any]) -> None:
    from reminiscence.auth.storage import _parse_session

    _require_exact_keys(root, required={"sessions"})
    sessions = tuple(_parse_session(value) for value in _require_list(root, "sessions"))
    hashes = [session["token_hash"] for session in sessions]
    if len(hashes) != len(set(hashes)):
        raise JsonDocumentValidationError("auth session token hashes must be unique")
    tablet_sessions = [session for session in sessions if session["role"].value == "TABLET"]
    if len(tablet_sessions) > 1:
        raise JsonDocumentValidationError("at most one Tablet session is allowed")


def _validate_auth_attempts(root: dict[str, Any]) -> None:
    from reminiscence.auth.storage import _parse_attempt

    _require_exact_keys(root, required={"attempts"})
    for value in _require_list(root, "attempts"):
        _parse_attempt(value)


DOCUMENT_SPECS = (
    DocumentSpec(
        "configuration.json",
        {"routines": [], "photos": [], "conversation": {}},
        _validate_configuration,
    ),
    DocumentSpec(
        "activity_metrics.json",
        {"routine_executions": [], "conversation_sessions": []},
        _validate_activity,
    ),
    DocumentSpec("anomaly_baseline.json", {}, _validate_anomaly_baseline),
    DocumentSpec("personal_state.json", {}, _validate_personal_state),
    DocumentSpec("notification_state.json", {}, _validate_notification_state),
    DocumentSpec("auth_sessions.json", {"sessions": []}, _validate_auth_sessions),
    DocumentSpec("auth_attempts.json", {"attempts": []}, _validate_auth_attempts),
)


DOCUMENT_SPECS_BY_FILENAME = {spec.filename: spec for spec in DOCUMENT_SPECS}
