"""Current notification-attempt marker for one anomaly episode."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from reminiscence.storage import JsonObjectStore, JsonStorageError


class NotificationStateError(JsonStorageError):
    """Raised when the current marker is malformed."""


class NotificationAttemptStore:
    """Track one attempt per active anomaly without keeping history."""

    def __init__(self, store: JsonObjectStore) -> None:
        self._store = store

    def was_attempted(self) -> bool:
        """Return whether the current anomaly episode was already attempted."""

        root = self._store.read()
        value = root.get("anomaly_notification_attempted", False)
        if not isinstance(value, bool):
            raise NotificationStateError(
                "anomaly_notification_attempted must be a boolean"
            )
        return value

    def mark_attempted(self, attempted_at: datetime) -> None:
        """Mark before SMTP to guarantee at-most-once delivery attempt."""

        def mutate(root: dict[str, Any]) -> None:
            root["anomaly_notification_attempted"] = True
            root["updated_at"] = attempted_at.isoformat()

        self._store.update(mutate)

    def claim_attempt(self, attempted_at: datetime) -> bool:
        """Atomically claim the current anomaly episode for one sender."""

        claimed = False

        def mutate(root: dict[str, Any]) -> None:
            nonlocal claimed
            value = root.get("anomaly_notification_attempted", False)
            if not isinstance(value, bool):
                raise NotificationStateError(
                    "anomaly_notification_attempted must be a boolean"
                )
            if value:
                return
            root["anomaly_notification_attempted"] = True
            root["updated_at"] = attempted_at.isoformat()
            claimed = True

        self._store.update(mutate)
        return claimed

    def reset(self, reset_at: datetime) -> None:
        """Open a new notification episode after state returns to NORMAL."""

        def mutate(root: dict[str, Any]) -> None:
            root["anomaly_notification_attempted"] = False
            root["updated_at"] = reset_at.isoformat()

        self._store.update(mutate)
