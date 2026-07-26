"""Persistence and restart behavior for the routine scheduler."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from reminiscence.routine import RoutineEventType, RoutineState, RoutineStateError
from reminiscence.routine.scheduler import RoutineNotFoundError, RoutineScheduler
from reminiscence.routine.storage import JsonRoutineStore, RoutineStorageError

SEOUL = ZoneInfo("Asia/Seoul")


def write_configuration(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "photos": [{"path": "family.jpg"}],
                "routines": [
                    {
                        "id": "morning-medication",
                        "name": "아침 약",
                        "category": "MEDICATION",
                        "weekdays": list(range(7)),
                        "scheduled_time": "09:00",
                        "grace_minutes": 10,
                        "reminder_interval_minutes": 10,
                        "max_reminders": 3,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def build_scheduler(tmp_path: Path) -> tuple[RoutineScheduler, Path]:
    configuration_path = tmp_path / "configuration.json"
    activity_path = tmp_path / "activity_metrics.json"
    write_configuration(configuration_path)
    return (
        RoutineScheduler(
            JsonRoutineStore(configuration_path, activity_path),
            SEOUL,
        ),
        activity_path,
    )


def at(hour: int, minute: int, second: int = 0, *, day: int = 27) -> datetime:
    return datetime(2026, 7, day, hour, minute, second, tzinfo=SEOUL)


def test_tick_starts_once_at_exact_schedule(tmp_path: Path) -> None:
    scheduler, _ = build_scheduler(tmp_path)

    before = scheduler.tick(at(8, 59, 59))
    first = scheduler.tick(at(9, 0))
    duplicate = scheduler.tick(at(9, 0))

    assert before == ()
    assert len(first) == 1
    assert first[0].event_type is RoutineEventType.INITIAL_REMINDER
    assert duplicate == ()
    assert len(scheduler.list_executions()) == 1


def test_restart_continues_from_persisted_reminder_count(tmp_path: Path) -> None:
    scheduler, activity_path = build_scheduler(tmp_path)
    scheduler.tick(at(9, 0))
    scheduler.tick(at(9, 10))

    restarted = RoutineScheduler(
        JsonRoutineStore(tmp_path / "configuration.json", activity_path),
        SEOUL,
    )
    event = restarted.tick(at(9, 20))

    assert len(event) == 1
    assert event[0].reminder_number == 2
    assert restarted.list_executions()[0].reminder_count == 2


def test_late_startup_does_not_emit_stale_initial_prompt(tmp_path: Path) -> None:
    scheduler, _ = build_scheduler(tmp_path)

    events = scheduler.tick(at(9, 25))

    assert len(events) == 1
    assert events[0].event_type is RoutineEventType.RE_REMINDER
    assert events[0].reminder_number == 2


def test_startup_after_deadline_persists_not_answered_directly(tmp_path: Path) -> None:
    scheduler, _ = build_scheduler(tmp_path)

    events = scheduler.tick(at(10, 0))
    execution = scheduler.list_executions()[0]

    assert len(events) == 1
    assert events[0].event_type is RoutineEventType.NOT_ANSWERED
    assert execution.state is RoutineState.NOT_ANSWERED
    assert execution.closed_at == at(9, 40)


def test_confirmation_is_persisted_and_later_tick_is_silent(tmp_path: Path) -> None:
    scheduler, _ = build_scheduler(tmp_path)
    scheduler.tick(at(9, 0))

    confirmed = scheduler.confirm(
        "morning-medication:2026-07-27",
        at(9, 7, 5),
    )
    later = scheduler.tick(at(10, 0))

    assert confirmed.state is RoutineState.CONFIRMED
    assert confirmed.confirmation_delay_seconds == 425
    assert later == ()


def test_confirmation_at_deadline_persists_not_answered_and_is_rejected(
    tmp_path: Path,
) -> None:
    scheduler, _ = build_scheduler(tmp_path)
    scheduler.tick(at(9, 0))

    with pytest.raises(RoutineStateError, match="NOT_ANSWERED"):
        scheduler.confirm("morning-medication:2026-07-27", at(9, 40))

    assert scheduler.list_executions()[0].state is RoutineState.NOT_ANSWERED


def test_each_date_gets_a_distinct_execution(tmp_path: Path) -> None:
    scheduler, _ = build_scheduler(tmp_path)

    scheduler.tick(at(10, 0, day=27))
    scheduler.tick(at(9, 0, day=28))

    identifiers = {
        execution.execution_id for execution in scheduler.list_executions()
    }
    assert identifiers == {
        "morning-medication:2026-07-27",
        "morning-medication:2026-07-28",
    }


def test_save_preserves_unrelated_activity_sections(tmp_path: Path) -> None:
    scheduler, activity_path = build_scheduler(tmp_path)
    activity_path.write_text(
        json.dumps({"conversation_sessions": [{"session_id": "existing"}]}),
        encoding="utf-8",
    )

    scheduler.tick(at(9, 0))
    persisted = json.loads(activity_path.read_text(encoding="utf-8"))

    assert persisted["conversation_sessions"] == [{"session_id": "existing"}]
    assert len(persisted["routine_executions"]) == 1
    assert list(tmp_path.glob("*.tmp")) == []


def test_removed_definition_does_not_corrupt_existing_history(tmp_path: Path) -> None:
    scheduler, activity_path = build_scheduler(tmp_path)
    scheduler.tick(at(9, 0))
    (tmp_path / "configuration.json").write_text(
        json.dumps({"routines": []}),
        encoding="utf-8",
    )

    restarted = RoutineScheduler(
        JsonRoutineStore(tmp_path / "configuration.json", activity_path),
        SEOUL,
    )

    assert restarted.tick(at(10, 0)) == ()
    assert len(restarted.list_executions()) == 1


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        "[]",
        '{"routines": {}}',
        '{"routines": [{"id": "missing-fields"}]}',
    ],
)
def test_invalid_configuration_is_rejected(tmp_path: Path, content: str) -> None:
    configuration_path = tmp_path / "configuration.json"
    configuration_path.write_text(content, encoding="utf-8")
    store = JsonRoutineStore(configuration_path, tmp_path / "activity_metrics.json")

    with pytest.raises(RoutineStorageError):
        store.load_definitions()


def test_unknown_execution_is_rejected(tmp_path: Path) -> None:
    scheduler, _ = build_scheduler(tmp_path)

    with pytest.raises(RoutineNotFoundError):
        scheduler.confirm("missing", at(9, 5))


def test_naive_scheduler_time_is_rejected(tmp_path: Path) -> None:
    scheduler, _ = build_scheduler(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        scheduler.tick(datetime(2026, 7, 27, 9, 0))


def test_weekday_filter_prevents_execution_creation(tmp_path: Path) -> None:
    configuration_path = tmp_path / "configuration.json"
    activity_path = tmp_path / "activity_metrics.json"
    write_configuration(configuration_path)
    root = json.loads(configuration_path.read_text(encoding="utf-8"))
    root["routines"][0]["weekdays"] = [1]
    configuration_path.write_text(json.dumps(root), encoding="utf-8")
    scheduler = RoutineScheduler(
        JsonRoutineStore(configuration_path, activity_path),
        SEOUL,
    )

    assert at(9, 0).weekday() == 0
    assert scheduler.tick(at(9, 0)) == ()


def test_utc_tick_is_converted_to_server_timezone(tmp_path: Path) -> None:
    scheduler, _ = build_scheduler(tmp_path)

    events = scheduler.tick(at(9, 0).astimezone(ZoneInfo("UTC")))

    assert len(events) == 1
    assert events[0].event_type is RoutineEventType.INITIAL_REMINDER


def test_activity_file_records_timezone_offsets(tmp_path: Path) -> None:
    scheduler, activity_path = build_scheduler(tmp_path)

    scheduler.tick(at(9, 0) + timedelta(seconds=1))
    persisted = activity_path.read_text(encoding="utf-8")

    assert "+09:00" in persisted
