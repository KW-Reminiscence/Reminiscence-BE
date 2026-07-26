"""Deterministic transition rules for scheduled routine executions."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from reminiscence.routine.models import (
    RoutineDefinition,
    RoutineEvent,
    RoutineEventType,
    RoutineExecution,
    RoutineState,
)


class RoutineStateError(ValueError):
    """Raised when an operation is incompatible with the execution state."""


class RoutineConfirmationExpiredError(RoutineStateError):
    """Raised when confirmation arrives after the response window."""


def _require_aware(timestamp: datetime, field_name: str) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def response_deadline(
    definition: RoutineDefinition,
    execution: RoutineExecution,
) -> datetime:
    """Return the exclusive confirmation deadline for an execution."""

    return (
        execution.scheduled_at
        + definition.grace_period
        + definition.reminder_interval * definition.max_reminders
    )


def start_execution(
    definition: RoutineDefinition,
    scheduled_at: datetime,
) -> tuple[RoutineExecution, RoutineEvent]:
    """Start REMINDING exactly at the scheduled time and emit the first prompt."""

    _require_aware(scheduled_at, "scheduled_at")
    execution_id = f"{definition.routine_id}:{scheduled_at.date().isoformat()}"
    execution = RoutineExecution(
        execution_id=execution_id,
        routine_id=definition.routine_id,
        scheduled_at=scheduled_at,
        state=RoutineState.REMINDING,
        reminder_count=0,
        last_prompted_at=scheduled_at,
    )
    event = RoutineEvent(
        event_type=RoutineEventType.INITIAL_REMINDER,
        execution_id=execution_id,
        occurred_at=scheduled_at,
        reminder_number=0,
    )
    return execution, event


def advance_execution(
    definition: RoutineDefinition,
    execution: RoutineExecution,
    now: datetime,
) -> tuple[RoutineExecution, RoutineEvent | None]:
    """Advance one execution to the state implied by the current time."""

    _require_aware(now, "now")
    if execution.routine_id != definition.routine_id:
        raise ValueError("execution and definition routine_id must match")
    if execution.state is not RoutineState.REMINDING:
        return execution, None
    if now < execution.scheduled_at:
        raise ValueError("now must not be earlier than scheduled_at")

    deadline = response_deadline(definition, execution)
    if now >= deadline:
        closed = replace(
            execution,
            state=RoutineState.NOT_ANSWERED,
            closed_at=deadline,
        )
        return closed, RoutineEvent(
            event_type=RoutineEventType.NOT_ANSWERED,
            execution_id=execution.execution_id,
            occurred_at=deadline,
        )

    first_reminder_at = execution.scheduled_at + definition.grace_period
    if now < first_reminder_at or definition.max_reminders == 0:
        return execution, None

    elapsed = now - first_reminder_at
    due_count = min(
        definition.max_reminders,
        1 + elapsed // definition.reminder_interval,
    )
    if due_count <= execution.reminder_count:
        return execution, None

    prompted_at = first_reminder_at + definition.reminder_interval * (due_count - 1)
    reminded = replace(
        execution,
        reminder_count=due_count,
        last_prompted_at=prompted_at,
    )
    return reminded, RoutineEvent(
        event_type=RoutineEventType.RE_REMINDER,
        execution_id=execution.execution_id,
        occurred_at=prompted_at,
        reminder_number=due_count,
    )


def confirm_execution(
    definition: RoutineDefinition,
    execution: RoutineExecution,
    confirmed_at: datetime,
) -> tuple[RoutineExecution, RoutineEvent]:
    """Confirm an active execution while its response window is open."""

    _require_aware(confirmed_at, "confirmed_at")
    if execution.routine_id != definition.routine_id:
        raise ValueError("execution and definition routine_id must match")
    if execution.state is not RoutineState.REMINDING:
        raise RoutineStateError(f"cannot confirm execution in {execution.state} state")
    if confirmed_at < execution.scheduled_at:
        raise RoutineStateError("cannot confirm before scheduled_at")
    if confirmed_at >= response_deadline(definition, execution):
        raise RoutineConfirmationExpiredError("confirmation window has expired")

    delay_seconds = int((confirmed_at - execution.scheduled_at).total_seconds())
    confirmed = replace(
        execution,
        state=RoutineState.CONFIRMED,
        confirmed_at=confirmed_at,
        confirmation_delay_seconds=delay_seconds,
        closed_at=confirmed_at,
    )
    return confirmed, RoutineEvent(
        event_type=RoutineEventType.CONFIRMED,
        execution_id=execution.execution_id,
        occurred_at=confirmed_at,
    )
