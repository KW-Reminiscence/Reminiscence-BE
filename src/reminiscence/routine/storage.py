"""Thread-safe JSON persistence for routine configuration and activity."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Mapping
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from reminiscence.routine.models import (
    RoutineCategory,
    RoutineDefinition,
    RoutineExecution,
    RoutineState,
)


class RoutineStorageError(RuntimeError):
    """Raised when local routine data cannot be read or validated."""


def _read_object(path: Path, *, missing_default: Mapping[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(missing_default)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RoutineStorageError(f"failed to read JSON object from {path}") from exc
    if not isinstance(value, dict):
        raise RoutineStorageError(f"JSON root must be an object: {path}")
    return value


def _atomic_write_object(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            json.dump(value, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise RoutineStorageError(f"failed to write JSON object to {path}") from exc


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoutineStorageError(f"{field_name} must be a non-empty string")
    return value


def _required_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RoutineStorageError(f"{field_name} must be an integer")
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
            confirmed_at=_optional_datetime(value.get("confirmed_at"), "confirmed_at"),
            confirmation_delay_seconds=_optional_int(
                value.get("confirmation_delay_seconds"),
                "confirmation_delay_seconds",
            ),
            closed_at=_optional_datetime(value.get("closed_at"), "closed_at"),
        )
    except (KeyError, ValueError) as exc:
        raise RoutineStorageError(f"invalid routine execution: {exc}") from exc


class JsonRoutineStore:
    """Store routines without overwriting unrelated activity metric sections."""

    def __init__(self, configuration_path: Path, activity_path: Path) -> None:
        self._configuration_path = configuration_path
        self._activity_path = activity_path
        self._lock = threading.RLock()

    def load_definitions(self) -> tuple[RoutineDefinition, ...]:
        """Load and validate configured routines."""

        with self._lock:
            root = _read_object(self._configuration_path, missing_default={"routines": []})
            routines_value = root.get("routines", [])
            if not isinstance(routines_value, list):
                raise RoutineStorageError("routines must be an array")
            definitions = tuple(_parse_definition(value) for value in routines_value)
            identifiers = [definition.routine_id for definition in definitions]
            if len(identifiers) != len(set(identifiers)):
                raise RoutineStorageError("routine ids must be unique")
            return definitions

    def list_executions(self) -> tuple[RoutineExecution, ...]:
        """Load all persisted routine executions."""

        with self._lock:
            root = _read_object(
                self._activity_path,
                missing_default={"routine_executions": []},
            )
            executions_value = root.get("routine_executions", [])
            if not isinstance(executions_value, list):
                raise RoutineStorageError("routine_executions must be an array")
            return tuple(_parse_execution(value) for value in executions_value)

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

        with self._lock:
            root = _read_object(
                self._activity_path,
                missing_default={"routine_executions": []},
            )
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
            _atomic_write_object(self._activity_path, root)
