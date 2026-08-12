"""Durable guardian notification delivery state for one anomaly episode."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from reminiscence.storage import JsonObjectStore, JsonStorageError


class NotificationStateError(JsonStorageError):
    """Raised when the current delivery state is malformed."""


class NotificationStateStatus(StrEnum):
    """Persisted delivery lifecycle for the current anomaly episode."""

    IDLE = "IDLE"
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class NotificationState:
    """Validated delivery state loaded from JSON."""

    status: NotificationStateStatus
    attempt_count: int
    updated_at: datetime | None
    next_retry_at: datetime | None
    last_error: str | None


def _aware_datetime(value: Any, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NotificationStateError(f"{field_name} must be a string or null")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise NotificationStateError(f"{field_name} must be a valid datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NotificationStateError(f"{field_name} must be timezone-aware")
    return parsed


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _parse_state(root: dict[str, Any]) -> NotificationState:
    if "anomaly_notification_attempted" in root:
        legacy = root["anomaly_notification_attempted"]
        if not isinstance(legacy, bool):
            raise NotificationStateError(
                "anomaly_notification_attempted must be a boolean"
            )
        updated_at = _aware_datetime(root.get("updated_at"), "updated_at")
        return NotificationState(
            status=(
                NotificationStateStatus.SENT
                if legacy
                else NotificationStateStatus.IDLE
            ),
            attempt_count=1 if legacy else 0,
            updated_at=updated_at,
            next_retry_at=None,
            last_error=None,
        )

    current_fields = {
        "delivery_status",
        "attempt_count",
        "updated_at",
        "next_retry_at",
        "last_error",
    }
    present_fields = current_fields.intersection(root)
    if present_fields and present_fields != current_fields:
        missing = ", ".join(sorted(current_fields - present_fields))
        raise NotificationStateError(f"missing notification state fields: {missing}")
    try:
        status = NotificationStateStatus(
            root.get("delivery_status", NotificationStateStatus.IDLE)
        )
    except (TypeError, ValueError) as exc:
        raise NotificationStateError("delivery_status is invalid") from exc
    attempt_count = root.get("attempt_count", 0)
    if (
        not isinstance(attempt_count, int)
        or isinstance(attempt_count, bool)
        or attempt_count < 0
    ):
        raise NotificationStateError("attempt_count must be a non-negative integer")
    updated_at = _aware_datetime(root.get("updated_at"), "updated_at")
    next_retry_at = _aware_datetime(root.get("next_retry_at"), "next_retry_at")
    last_error = root.get("last_error")
    if last_error is not None and (
        not isinstance(last_error, str) or not last_error.strip()
    ):
        raise NotificationStateError("last_error must be a non-empty string or null")
    if status is NotificationStateStatus.IDLE:
        if attempt_count != 0 or next_retry_at is not None or last_error is not None:
            raise NotificationStateError("IDLE delivery state contains attempt data")
    elif status is NotificationStateStatus.PENDING:
        if attempt_count < 1 or updated_at is None:
            raise NotificationStateError("PENDING delivery state requires an attempt")
        if next_retry_at is not None or last_error is not None:
            raise NotificationStateError("PENDING delivery state contains failure data")
    elif status is NotificationStateStatus.SENT:
        if attempt_count < 1 or updated_at is None:
            raise NotificationStateError("SENT delivery state requires an attempt")
        if next_retry_at is not None or last_error is not None:
            raise NotificationStateError("SENT delivery state contains failure data")
    elif status is NotificationStateStatus.FAILED:
        if (
            attempt_count < 1
            or updated_at is None
            or next_retry_at is None
            or last_error is None
        ):
            raise NotificationStateError("FAILED delivery state requires retry data")
        if next_retry_at < updated_at:
            raise NotificationStateError("next_retry_at must not be before updated_at")
    return NotificationState(
        status=status,
        attempt_count=attempt_count,
        updated_at=updated_at,
        next_retry_at=next_retry_at,
        last_error=last_error,
    )


def _write_state(root: dict[str, Any], state: NotificationState) -> None:
    root.pop("anomaly_notification_attempted", None)
    root["delivery_status"] = state.status.value
    root["attempt_count"] = state.attempt_count
    root["updated_at"] = (
        state.updated_at.isoformat() if state.updated_at is not None else None
    )
    root["next_retry_at"] = (
        state.next_retry_at.isoformat() if state.next_retry_at is not None else None
    )
    root["last_error"] = state.last_error


class NotificationAttemptStore:
    """Atomically claim, complete, fail, and retry one anomaly delivery."""

    def __init__(self, store: JsonObjectStore) -> None:
        self._store = store

    def load(self) -> NotificationState:
        """Return the validated current state, including legacy state."""

        return _parse_state(self._store.read())

    def claim_attempt(
        self,
        attempted_at: datetime,
        *,
        pending_timeout: timedelta,
    ) -> bool:
        """Claim an initial, scheduled retry, or stale pending attempt."""

        _require_aware(attempted_at, "attempted_at")
        if pending_timeout <= timedelta(0):
            raise ValueError("pending_timeout must be positive")
        claimed = False

        def mutate(root: dict[str, Any]) -> None:
            nonlocal claimed
            current = _parse_state(root)
            eligible = current.status is NotificationStateStatus.IDLE
            if current.status is NotificationStateStatus.FAILED:
                eligible = (
                    current.next_retry_at is not None
                    and attempted_at >= current.next_retry_at
                )
            elif current.status is NotificationStateStatus.PENDING:
                eligible = (
                    current.updated_at is not None
                    and attempted_at >= current.updated_at + pending_timeout
                )
            if not eligible:
                return
            _write_state(
                root,
                NotificationState(
                    status=NotificationStateStatus.PENDING,
                    attempt_count=current.attempt_count + 1,
                    updated_at=attempted_at,
                    next_retry_at=None,
                    last_error=None,
                ),
            )
            claimed = True

        self._store.update(mutate)
        return claimed

    def mark_sent(self, sent_at: datetime) -> None:
        """Finish the currently pending attempt successfully."""

        _require_aware(sent_at, "sent_at")

        def mutate(root: dict[str, Any]) -> None:
            current = _parse_state(root)
            if current.status is not NotificationStateStatus.PENDING:
                raise NotificationStateError("only a PENDING delivery can be sent")
            _write_state(
                root,
                NotificationState(
                    status=NotificationStateStatus.SENT,
                    attempt_count=current.attempt_count,
                    updated_at=sent_at,
                    next_retry_at=None,
                    last_error=None,
                ),
            )

        self._store.update(mutate)

    def mark_failed(
        self,
        failed_at: datetime,
        *,
        retry_delay: timedelta,
        error_code: str,
    ) -> None:
        """Schedule a retry without persisting provider error details."""

        _require_aware(failed_at, "failed_at")
        if retry_delay <= timedelta(0):
            raise ValueError("retry_delay must be positive")
        if not error_code.strip():
            raise ValueError("error_code must not be blank")

        def mutate(root: dict[str, Any]) -> None:
            current = _parse_state(root)
            if current.status is not NotificationStateStatus.PENDING:
                raise NotificationStateError("only a PENDING delivery can fail")
            _write_state(
                root,
                NotificationState(
                    status=NotificationStateStatus.FAILED,
                    attempt_count=current.attempt_count,
                    updated_at=failed_at,
                    next_retry_at=failed_at + retry_delay,
                    last_error=error_code,
                ),
            )

        self._store.update(mutate)

    def reset(self, reset_at: datetime) -> None:
        """Open a new notification episode after state returns to NORMAL."""

        _require_aware(reset_at, "reset_at")

        def mutate(root: dict[str, Any]) -> None:
            _parse_state(root)
            _write_state(
                root,
                NotificationState(
                    status=NotificationStateStatus.IDLE,
                    attempt_count=0,
                    updated_at=reset_at,
                    next_retry_at=None,
                    last_error=None,
                ),
            )

        self._store.update(mutate)
