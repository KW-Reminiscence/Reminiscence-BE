"""Application service that applies routine state transitions to local storage."""

from __future__ import annotations

import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from reminiscence.routine.models import (
    RoutineDefinition,
    RoutineEvent,
    RoutineExecution,
    RoutineState,
)
from reminiscence.routine.state_machine import (
    RoutineStateError,
    advance_execution,
    confirm_execution,
    start_execution,
)
from reminiscence.routine.storage import JsonRoutineStore


class RoutineNotFoundError(LookupError):
    """Raised when a routine definition or execution does not exist."""


class RoutineScheduler:
    """Coordinate deterministic routine transitions and persisted state."""

    def __init__(self, store: JsonRoutineStore, timezone: ZoneInfo) -> None:
        self._store = store
        self._timezone = timezone
        self._lock = threading.RLock()

    def _definitions_by_id(self) -> dict[str, RoutineDefinition]:
        return {
            definition.routine_id: definition
            for definition in self._store.load_definitions()
        }

    def tick(self, now: datetime) -> tuple[RoutineEvent, ...]:
        """Apply every transition due at `now` and return new observable events."""

        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        local_now = now.astimezone(self._timezone)
        with self._lock:
            definitions = self._definitions_by_id()
            executions = {
                execution.execution_id: execution
                for execution in self._store.list_executions()
            }
            events: list[RoutineEvent] = []

            for execution in tuple(executions.values()):
                definition = definitions.get(execution.routine_id)
                if definition is None or execution.state is not RoutineState.REMINDING:
                    continue
                advanced, event = advance_execution(definition, execution, local_now)
                if advanced != execution:
                    self._store.save_execution(advanced)
                    executions[advanced.execution_id] = advanced
                if event is not None:
                    events.append(event)

            for definition in definitions.values():
                if not definition.is_scheduled_on(local_now.date()):
                    continue
                scheduled_at = definition.scheduled_datetime(
                    local_now.date(),
                    self._timezone,
                )
                if local_now < scheduled_at:
                    continue
                execution_id = f"{definition.routine_id}:{local_now.date().isoformat()}"
                if execution_id in executions:
                    continue

                started, initial_event = start_execution(definition, scheduled_at)
                current, current_event = advance_execution(
                    definition,
                    started,
                    local_now,
                )
                self._store.save_execution(current)
                executions[current.execution_id] = current
                if current_event is not None:
                    events.append(current_event)
                else:
                    events.append(initial_event)

            events.sort(key=lambda event: (event.occurred_at, event.execution_id))
            return tuple(events)

    def confirm(self, execution_id: str, confirmed_at: datetime) -> RoutineExecution:
        """Confirm one active execution and persist the result."""

        if confirmed_at.tzinfo is None or confirmed_at.utcoffset() is None:
            raise ValueError("confirmed_at must be timezone-aware")
        local_confirmed_at = confirmed_at.astimezone(self._timezone)
        with self._lock:
            execution = self._store.get_execution(execution_id)
            if execution is None:
                raise RoutineNotFoundError(f"routine execution not found: {execution_id}")
            definition = self._definitions_by_id().get(execution.routine_id)
            if definition is None:
                raise RoutineNotFoundError(
                    f"routine definition not found: {execution.routine_id}"
                )

            advanced, _ = advance_execution(
                definition,
                execution,
                local_confirmed_at,
            )
            if advanced != execution:
                self._store.save_execution(advanced)
            if advanced.state is not RoutineState.REMINDING:
                raise RoutineStateError(
                    f"cannot confirm execution in {advanced.state} state"
                )

            confirmed, _ = confirm_execution(
                definition,
                advanced,
                local_confirmed_at,
            )
            self._store.save_execution(confirmed)
            return confirmed

    def list_executions(self) -> tuple[RoutineExecution, ...]:
        """Return persisted executions for API projection."""

        return self._store.list_executions()

    def list_definitions(self) -> tuple[RoutineDefinition, ...]:
        """Return configured definitions for API projection."""

        return self._store.load_definitions()
