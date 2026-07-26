"""Edge-case coverage for routine state transitions."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from reminiscence.routine import (
    RoutineCategory,
    RoutineConfirmationExpiredError,
    RoutineDefinition,
    RoutineEventType,
    RoutineState,
    RoutineStateError,
    advance_execution,
    confirm_execution,
    start_execution,
)

SEOUL = ZoneInfo("Asia/Seoul")


def definition(*, max_reminders: int = 3) -> RoutineDefinition:
    return RoutineDefinition(
        routine_id="morning-medication",
        name="아침 약",
        category=RoutineCategory.MEDICATION,
        weekdays=frozenset(range(7)),
        scheduled_time=time(9, 0),
        grace_period=timedelta(minutes=10),
        reminder_interval=timedelta(minutes=10),
        max_reminders=max_reminders,
    )


def scheduled_at() -> datetime:
    return datetime(2026, 7, 27, 9, 0, tzinfo=SEOUL)


def test_start_emits_initial_reminder_at_scheduled_time() -> None:
    execution, event = start_execution(definition(), scheduled_at())

    assert execution.state is RoutineState.REMINDING
    assert execution.reminder_count == 0
    assert execution.execution_id == "morning-medication:2026-07-27"
    assert event.event_type is RoutineEventType.INITIAL_REMINDER
    assert event.occurred_at == scheduled_at()


def test_no_re_reminder_is_emitted_before_grace_period_ends() -> None:
    routine = definition()
    execution, _ = start_execution(routine, scheduled_at())

    unchanged, event = advance_execution(
        routine,
        execution,
        scheduled_at() + timedelta(minutes=9, seconds=59),
    )

    assert unchanged == execution
    assert event is None


def test_re_reminder_is_emitted_on_exact_boundary() -> None:
    routine = definition()
    execution, _ = start_execution(routine, scheduled_at())

    reminded, event = advance_execution(
        routine,
        execution,
        scheduled_at() + timedelta(minutes=10),
    )

    assert reminded.state is RoutineState.REMINDING
    assert reminded.reminder_count == 1
    assert event is not None
    assert event.event_type is RoutineEventType.RE_REMINDER
    assert event.reminder_number == 1


def test_repeated_tick_at_same_time_is_idempotent() -> None:
    routine = definition()
    execution, _ = start_execution(routine, scheduled_at())
    reminded, _ = advance_execution(
        routine,
        execution,
        scheduled_at() + timedelta(minutes=10),
    )

    unchanged, event = advance_execution(
        routine,
        reminded,
        scheduled_at() + timedelta(minutes=10),
    )

    assert unchanged == reminded
    assert event is None


def test_late_tick_collapses_missed_reminders_to_latest_due_number() -> None:
    routine = definition()
    execution, _ = start_execution(routine, scheduled_at())

    reminded, event = advance_execution(
        routine,
        execution,
        scheduled_at() + timedelta(minutes=25),
    )

    assert reminded.reminder_count == 2
    assert reminded.last_prompted_at == scheduled_at() + timedelta(minutes=20)
    assert event is not None
    assert event.reminder_number == 2


def test_execution_becomes_not_answered_at_exact_deadline() -> None:
    routine = definition()
    execution, _ = start_execution(routine, scheduled_at())

    closed, event = advance_execution(
        routine,
        execution,
        scheduled_at() + timedelta(minutes=40),
    )

    assert closed.state is RoutineState.NOT_ANSWERED
    assert closed.closed_at == scheduled_at() + timedelta(minutes=40)
    assert event is not None
    assert event.event_type is RoutineEventType.NOT_ANSWERED


def test_confirmation_records_delay_and_stops_future_transitions() -> None:
    routine = definition()
    execution, _ = start_execution(routine, scheduled_at())

    confirmed, event = confirm_execution(
        routine,
        execution,
        scheduled_at() + timedelta(minutes=7, seconds=5),
    )
    unchanged, later_event = advance_execution(
        routine,
        confirmed,
        scheduled_at() + timedelta(hours=1),
    )

    assert confirmed.state is RoutineState.CONFIRMED
    assert confirmed.confirmation_delay_seconds == 425
    assert event.event_type is RoutineEventType.CONFIRMED
    assert unchanged == confirmed
    assert later_event is None


@pytest.mark.parametrize(
    ("confirmation_time", "error_type"),
    [
        (scheduled_at() - timedelta(seconds=1), RoutineStateError),
        (scheduled_at() + timedelta(minutes=40), RoutineConfirmationExpiredError),
        (scheduled_at() + timedelta(hours=1), RoutineConfirmationExpiredError),
    ],
)
def test_confirmation_outside_window_is_rejected(
    confirmation_time: datetime,
    error_type: type[Exception],
) -> None:
    routine = definition()
    execution, _ = start_execution(routine, scheduled_at())

    with pytest.raises(error_type):
        confirm_execution(routine, execution, confirmation_time)


def test_zero_re_reminders_closes_after_grace_period() -> None:
    routine = definition(max_reminders=0)
    execution, _ = start_execution(routine, scheduled_at())

    before, before_event = advance_execution(
        routine,
        execution,
        scheduled_at() + timedelta(minutes=9, seconds=59),
    )
    closed, closed_event = advance_execution(
        routine,
        before,
        scheduled_at() + timedelta(minutes=10),
    )

    assert before_event is None
    assert closed.state is RoutineState.NOT_ANSWERED
    assert closed_event is not None


def test_definition_rejects_invalid_schedule_values() -> None:
    with pytest.raises(ValueError, match="weekdays"):
        RoutineDefinition(
            routine_id="invalid",
            name="잘못된 루틴",
            category=RoutineCategory.MEAL,
            weekdays=frozenset({7}),
            scheduled_time=time(9, 0),
            grace_period=timedelta(minutes=10),
            reminder_interval=timedelta(minutes=10),
            max_reminders=1,
        )


def test_state_machine_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        start_execution(definition(), datetime(2026, 7, 27, 9, 0))
