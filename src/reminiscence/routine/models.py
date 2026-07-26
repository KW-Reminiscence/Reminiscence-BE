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
class RoutinePolicy:
    """Reminder timing copied into each execution when it starts."""

    grace_period: timedelta
    reminder_interval: timedelta
    max_reminders: int

    def __post_init__(self) -> None:
        if self.grace_period <= timedelta(0):
            raise ValueError("grace_period must be positive")
        if self.reminder_interval <= timedelta(0):
            raise ValueError("reminder_interval must be positive")
        if self.max_reminders < 0:
            raise ValueError("max_reminders must not be negative")


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
    active: bool = True

    def __post_init__(self) -> None:
        if not self.routine_id.strip():
            raise ValueError("routine_id must not be blank")
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if not self.weekdays or any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError("weekdays must contain values from 0 to 6")
        if self.scheduled_time.tzinfo is not None:
            raise ValueError("scheduled_time must not include timezone information")
        if not isinstance(self.active, bool):
            raise ValueError("active must be a boolean")
        _ = self.policy

    @property
    def policy(self) -> RoutinePolicy:
        """Return the definition's current reminder policy."""

        return RoutinePolicy(
            grace_period=self.grace_period,
            reminder_interval=self.reminder_interval,
            max_reminders=self.max_reminders,
        )

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
    policy: RoutinePolicy | None = None
    confirmed_at: datetime | None = None
    confirmation_delay_seconds: int | None = None
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.execution_id.strip():
            raise ValueError("execution_id must not be blank")
        if not self.routine_id.strip():
            raise ValueError("routine_id must not be blank")
        if self.scheduled_at.tzinfo is None or self.scheduled_at.utcoffset() is None:
            raise ValueError("scheduled_at must be timezone-aware")
        if self.last_prompted_at.tzinfo is None or self.last_prompted_at.utcoffset() is None:
            raise ValueError("last_prompted_at must be timezone-aware")
        if self.reminder_count < 0:
            raise ValueError("reminder_count must not be negative")
        if self.last_prompted_at < self.scheduled_at:
            raise ValueError("last_prompted_at must not be before scheduled_at")
        if self.policy is not None and self.reminder_count > self.policy.max_reminders:
            raise ValueError("reminder_count must not exceed max_reminders")
        for field_name, timestamp in (
            ("confirmed_at", self.confirmed_at),
            ("closed_at", self.closed_at),
        ):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.state is RoutineState.REMINDING:
            if (
                self.confirmed_at is not None
                or self.confirmation_delay_seconds is not None
                or self.closed_at is not None
            ):
                raise ValueError("REMINDING execution must not contain closure fields")
        elif self.state is RoutineState.CONFIRMED:
            if (
                self.confirmed_at is None
                or self.confirmation_delay_seconds is None
                or self.closed_at is None
            ):
                raise ValueError("CONFIRMED execution requires confirmation fields")
            if self.confirmed_at < self.scheduled_at:
                raise ValueError("confirmed_at must not be before scheduled_at")
            expected_delay = int(
                (self.confirmed_at - self.scheduled_at).total_seconds()
            )
            if self.confirmation_delay_seconds != expected_delay:
                raise ValueError("confirmation_delay_seconds must match confirmed_at")
            if self.closed_at != self.confirmed_at:
                raise ValueError("CONFIRMED closed_at must equal confirmed_at")
        elif self.state is RoutineState.NOT_ANSWERED:
            if self.confirmed_at is not None or self.confirmation_delay_seconds is not None:
                raise ValueError("NOT_ANSWERED execution must not be confirmed")
            if self.closed_at is None:
                raise ValueError("NOT_ANSWERED execution requires closed_at")
        if self.closed_at is not None:
            if self.closed_at < self.scheduled_at:
                raise ValueError("closed_at must not be before scheduled_at")
            if self.last_prompted_at > self.closed_at:
                raise ValueError("last_prompted_at must not be after closed_at")


@dataclass(frozen=True, slots=True)
class RoutineEvent:
    """A transition event consumed by the tablet-facing service."""

    event_type: RoutineEventType
    execution_id: str
    occurred_at: datetime
    reminder_number: int | None = None

    def __post_init__(self) -> None:
        if not self.execution_id.strip():
            raise ValueError("execution_id must not be blank")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.reminder_number is not None and self.reminder_number < 0:
            raise ValueError("reminder_number must not be negative")
