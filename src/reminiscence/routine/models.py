"""Immutable value objects for the routine domain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum


class RoutineCategory(StrEnum):
    """Supported routine categories in the MVP."""

    MEAL = "MEAL"
    MEDICATION = "MEDICATION"


class RoutineState(StrEnum):
    """Lifecycle states for one scheduled routine occurrence."""

    REMINDING = "REMINDING"
    CONFIRMED = "CONFIRMED"
    NOT_ANSWERED = "NOT_ANSWERED"


class RoutineEventType(StrEnum):
    """Observable events emitted by the state machine."""

    INITIAL_REMINDER = "INITIAL_REMINDER"
    RE_REMINDER = "RE_REMINDER"
    CONFIRMED = "CONFIRMED"
    NOT_ANSWERED = "NOT_ANSWERED"


@dataclass(frozen=True, slots=True)
class RoutineDefinition:
    """Recurring schedule and reminder policy for one routine."""

    routine_id: str
    name: str
    category: RoutineCategory
    weekdays: frozenset[int]
    scheduled_time: time
    grace_period: timedelta
    reminder_interval: timedelta
    max_reminders: int

    def __post_init__(self) -> None:
        if not self.routine_id.strip():
            raise ValueError("routine_id must not be blank")
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if not self.weekdays or any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError("weekdays must contain values from 0 to 6")
        if self.scheduled_time.tzinfo is not None:
            raise ValueError("scheduled_time must not include timezone information")
        if self.grace_period <= timedelta(0):
            raise ValueError("grace_period must be positive")
        if self.reminder_interval <= timedelta(0):
            raise ValueError("reminder_interval must be positive")
        if self.max_reminders < 0:
            raise ValueError("max_reminders must not be negative")

    def is_scheduled_on(self, target_date: date) -> bool:
        """Return whether this routine is active on the given local date."""

        return target_date.weekday() in self.weekdays

    def scheduled_datetime(self, target_date: date, timezone: tzinfo) -> datetime:
        """Combine the local schedule with an explicit server timezone."""

        return datetime.combine(target_date, self.scheduled_time, tzinfo=timezone)


@dataclass(frozen=True, slots=True)
class RoutineExecution:
    """Persistable state for one scheduled routine occurrence."""

    execution_id: str
    routine_id: str
    scheduled_at: datetime
    state: RoutineState
    reminder_count: int
    last_prompted_at: datetime
    confirmed_at: datetime | None = None
    confirmation_delay_seconds: int | None = None
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.scheduled_at.tzinfo is None or self.scheduled_at.utcoffset() is None:
            raise ValueError("scheduled_at must be timezone-aware")
        if self.last_prompted_at.tzinfo is None or self.last_prompted_at.utcoffset() is None:
            raise ValueError("last_prompted_at must be timezone-aware")
        if self.reminder_count < 0:
            raise ValueError("reminder_count must not be negative")


@dataclass(frozen=True, slots=True)
class RoutineEvent:
    """A transition event consumed by the tablet-facing service."""

    event_type: RoutineEventType
    execution_id: str
    occurred_at: datetime
    reminder_number: int | None = None
