"""Regression tests retained from the original RoutineMonitor contribution."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reminiscence.routine import RoutineEventType, RoutineState
from reminiscence.routine.scheduler import RoutineScheduler
from reminiscence.routine.storage import JsonRoutineStore

SEOUL = ZoneInfo("Asia/Seoul")


def build_scheduler(tmp_path: Path) -> RoutineScheduler:
    configuration_path = tmp_path / "configuration.json"
    configuration_path.write_text(
        json.dumps(
            {
                "routines": [
                    {
                        "id": "medication",
                        "name": "테스트 약",
                        "category": "MEDICATION",
                        "weekdays": list(range(7)),
                        "scheduled_time": "08:00",
                        "grace_minutes": 10,
                        "reminder_interval_minutes": 10,
                        "max_reminders": 3,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return RoutineScheduler(
        JsonRoutineStore(
            configuration_path,
            tmp_path / "activity_metrics.json",
        ),
        SEOUL,
    )


def at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=SEOUL)


def test_last_reminder_keeps_one_full_response_interval(tmp_path: Path) -> None:
    scheduler = build_scheduler(tmp_path)

    assert scheduler.tick(at(22, 8, 0))[0].reminder_number == 0
    assert scheduler.tick(at(22, 8, 10))[0].reminder_number == 1
    assert scheduler.tick(at(22, 8, 20))[0].reminder_number == 2
    assert scheduler.tick(at(22, 8, 30))[0].reminder_number == 3
    assert scheduler.list_executions()[0].state is RoutineState.REMINDING

    event = scheduler.tick(at(22, 8, 40))[0]

    assert event.event_type is RoutineEventType.NOT_ANSWERED
    assert scheduler.list_executions()[0].state is RoutineState.NOT_ANSWERED


def test_confirmation_stops_all_later_reminders(tmp_path: Path) -> None:
    scheduler = build_scheduler(tmp_path)
    scheduler.tick(at(22, 8, 10))

    scheduler.confirm("medication:2026-07-22", at(22, 8, 12))

    assert scheduler.tick(at(22, 9, 0)) == ()
    assert scheduler.list_executions()[0].state is RoutineState.CONFIRMED


def test_next_day_creates_history_instead_of_resetting_it(tmp_path: Path) -> None:
    scheduler = build_scheduler(tmp_path)
    scheduler.tick(at(22, 8, 10))
    scheduler.confirm("medication:2026-07-22", at(22, 8, 12))

    scheduler.tick(at(23, 8, 10))

    executions = scheduler.list_executions()
    assert len(executions) == 2
    assert executions[0].state is RoutineState.CONFIRMED
    assert executions[1].state is RoutineState.REMINDING


def test_timezone_offset_is_preserved_in_persisted_history(tmp_path: Path) -> None:
    scheduler = build_scheduler(tmp_path)

    scheduler.tick(at(22, 8, 10))

    execution = scheduler.list_executions()[0]
    assert execution.scheduled_at.utcoffset() == at(22, 8, 0).utcoffset()
