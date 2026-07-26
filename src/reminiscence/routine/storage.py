"""Thread-safe JSON persistence for routine configuration and activity."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from reminiscence.routine.models import (
    RoutineCategory,
    RoutineDefinition,
    RoutineExecution,
    RoutinePolicy,
    RoutineState,
)
from reminiscence.storage import JsonObjectStore, JsonStorageError


class RoutineStorageError(RuntimeError):
    """Raised when local routine data cannot be read or validated."""


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoutineStorageError(f"{field_name} must be a non-empty string")
    return value


def _required_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RoutineStorageError(f"{field_name} must be an integer")
    return value


def _optional_bool(value: Any, field_name: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise RoutineStorageError(f"{field_name} must be a boolean")
    return value


def _parse_definition(value: Any) -> RoutineDefinition:
    if not isinstance(value, dict):
        raise RoutineStorageError("each routine must be an object")
    try:
        weekdays_value = value["weekdays"]
        if not isinstance(weekdays_value, list):
            raise RoutineStorageError("weekdays must be an array")
        weekdays = frozenset(_required_int(day, "weekdays item") for day in weekdays_value)
        return RoutineDefinition(
            routine_id=_required_string(value["id"], "id"),
            name=_required_string(value["name"], "name"),
            category=RoutineCategory(_required_string(value["category"], "category")),
            weekdays=weekdays,
            scheduled_time=time.fromisoformat(
                _required_string(value["scheduled_time"], "scheduled_time")
            ),
            grace_period=timedelta(
                minutes=_required_int(value["grace_minutes"], "grace_minutes")
            ),
            reminder_interval=timedelta(
                minutes=_required_int(
                    value["reminder_interval_minutes"],
                    "reminder_interval_minutes",
                )
            ),
            max_reminders=_required_int(value["max_reminders"], "max_reminders"),
            active=_optional_bool(value.get("active"), "active", default=True),
        )
    except (KeyError, ValueError) as exc:
        raise RoutineStorageError(f"invalid routine definition: {exc}") from exc


def _serialize_execution(execution: RoutineExecution) -> dict[str, Any]:
    return {
        "execution_id": execution.execution_id,
        "routine_id": execution.routine_id,
        "scheduled_at": execution.scheduled_at.isoformat(),
        "state": execution.state.value,
        "reminder_count": execution.reminder_count,
        "last_prompted_at": execution.last_prompted_at.isoformat(),
        "routine_name": execution.routine_name,
        "category": (
            execution.category.value if execution.category is not None else None
        ),
        "policy": (
            {
                "grace_seconds": int(execution.policy.grace_period.total_seconds()),
                "reminder_interval_seconds": int(
                    execution.policy.reminder_interval.total_seconds()
                ),
                "max_reminders": execution.policy.max_reminders,
            }
            if execution.policy is not None
            else None
        ),
        "confirmed_at": (
            execution.confirmed_at.isoformat() if execution.confirmed_at is not None else None
        ),
        "confirmation_delay_seconds": execution.confirmation_delay_seconds,
        "closed_at": execution.closed_at.isoformat() if execution.closed_at is not None else None,
    }


def _optional_datetime(value: Any, field_name: str) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(_required_string(value, field_name))


def _optional_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    return _required_int(value, field_name)


def _optional_policy(value: Any) -> RoutinePolicy | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RoutineStorageError("policy must be an object or null")
    return RoutinePolicy(
        grace_period=timedelta(
            seconds=_required_int(value["grace_seconds"], "policy.grace_seconds")
        ),
        reminder_interval=timedelta(
            seconds=_required_int(
                value["reminder_interval_seconds"],
                "policy.reminder_interval_seconds",
            )
        ),
        max_reminders=_required_int(
            value["max_reminders"],
            "policy.max_reminders",
        ),
    )


def _optional_category(value: Any) -> RoutineCategory | None:
    if value is None:
        return None
    return RoutineCategory(_required_string(value, "category"))


def _parse_execution(value: Any) -> RoutineExecution:
    if not isinstance(value, dict):
        raise RoutineStorageError("each routine execution must be an object")
    try:
        return RoutineExecution(
            execution_id=_required_string(value["execution_id"], "execution_id"),
            routine_id=_required_string(value["routine_id"], "routine_id"),
            scheduled_at=datetime.fromisoformat(
                _required_string(value["scheduled_at"], "scheduled_at")
            ),
            state=RoutineState(_required_string(value["state"], "state")),
            reminder_count=_required_int(value["reminder_count"], "reminder_count"),
            last_prompted_at=datetime.fromisoformat(
                _required_string(value["last_prompted_at"], "last_prompted_at")
            ),
            routine_name=(
                _required_string(value["routine_name"], "routine_name")
                if value.get("routine_name") is not None
                else None
            ),
            category=_optional_category(value.get("category")),
            policy=_optional_policy(value.get("policy")),
            confirmed_at=_optional_datetime(value.get("confirmed_at"), "confirmed_at"),
            confirmation_delay_seconds=_optional_int(
                value.get("confirmation_delay_seconds"),
                "confirmation_delay_seconds",
            ),
            closed_at=_optional_datetime(value.get("closed_at"), "closed_at"),
        )
    except (KeyError, ValueError) as exc:
        raise RoutineStorageError(f"invalid routine execution: {exc}") from exc


def _validate_non_overlapping_windows(
    definitions: tuple[RoutineDefinition, ...],
) -> None:
    week_seconds = 7 * 24 * 60 * 60
    windows: list[tuple[str, int, float, float]] = []
    for definition in definitions:
        if not definition.active:
            continue
        start_seconds = (
            definition.scheduled_time.hour * 60 * 60
            + definition.scheduled_time.minute * 60
            + definition.scheduled_time.second
            + definition.scheduled_time.microsecond / 1_000_000
        )
        duration_seconds = (
            definition.grace_period
            + definition.reminder_interval * definition.max_reminders
        ).total_seconds()
        for weekday in definition.weekdays:
            start = weekday * 24 * 60 * 60 + start_seconds
            windows.append(
                (
                    definition.routine_id,
                    weekday,
                    start,
                    start + duration_seconds,
                )
            )

    for index, left in enumerate(windows):
        for right in windows[index + 1 :]:
            for shift in (-week_seconds, 0, week_seconds):
                shifted_start = right[2] + shift
                shifted_end = right[3] + shift
                if left[2] < shifted_end and shifted_start < left[3]:
                    raise RoutineStorageError(
                        "routine response windows must not overlap: "
                        f"{left[0]} weekday {left[1]} and "
                        f"{right[0]} weekday {right[1]}"
                    )
        if left[3] - left[2] > week_seconds:
            raise RoutineStorageError(
                f"routine response window must be shorter than one week: {left[0]}"
            )


class JsonRoutineStore:
    """Store routines without overwriting unrelated activity metric sections."""

    def __init__(self, configuration_path: Path, activity_path: Path) -> None:
        self._configuration_store = JsonObjectStore(
            configuration_path,
            missing_default={"routines": []},
        )
        self._activity_store = JsonObjectStore(
            activity_path,
            missing_default={"routine_executions": []},
        )

    def load_definitions(self) -> tuple[RoutineDefinition, ...]:
        """Load and validate configured routines."""

        try:
            root = self._configuration_store.read()
            routines_value = root.get("routines", [])
            if not isinstance(routines_value, list):
                raise RoutineStorageError("routines must be an array")
            definitions = tuple(_parse_definition(value) for value in routines_value)
            identifiers = [definition.routine_id for definition in definitions]
            if len(identifiers) != len(set(identifiers)):
                raise RoutineStorageError("routine ids must be unique")
            _validate_non_overlapping_windows(definitions)
            return definitions
        except JsonStorageError as exc:
            raise RoutineStorageError(str(exc)) from exc


    def list_executions(self) -> tuple[RoutineExecution, ...]:
        """Load all persisted routine executions."""

        try:
            root = self._activity_store.read()
            executions_value = root.get("routine_executions", [])
            if not isinstance(executions_value, list):
                raise RoutineStorageError("routine_executions must be an array")
            return tuple(_parse_execution(value) for value in executions_value)
        except JsonStorageError as exc:
            raise RoutineStorageError(str(exc)) from exc

    def get_execution(self, execution_id: str) -> RoutineExecution | None:
        """Return one execution by its stable identifier."""

        return next(
            (
                execution
                for execution in self.list_executions()
                if execution.execution_id == execution_id
            ),
            None,
        )

    def save_execution(self, execution: RoutineExecution) -> None:
        """Insert or replace one execution with an atomic file replacement."""

        def mutate(root: dict[str, Any]) -> None:
            executions_value = root.get("routine_executions", [])
            if not isinstance(executions_value, list):
                raise RoutineStorageError("routine_executions must be an array")
            executions = [_parse_execution(value) for value in executions_value]
            updated = [
                current
                for current in executions
                if current.execution_id != execution.execution_id
            ]
            updated.append(execution)
            updated.sort(key=lambda current: (current.scheduled_at, current.execution_id))
            root["routine_executions"] = [
                _serialize_execution(current) for current in updated
            ]

        try:
            self._activity_store.update(mutate)
        except JsonStorageError as exc:
            raise RoutineStorageError(str(exc)) from exc
