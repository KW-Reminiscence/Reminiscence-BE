"""
tests/test_routine_monitor.py

실행: PYTHONPATH=src pytest tests/test_routine_monitor.py -v
"""

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from reminiscence.routine.conversation_metrics import ConversationLog
from reminiscence.routine.daily_metrics import compute_daily_vector, load_history
from reminiscence.routine.routine import Routine, RoutineCategory
from reminiscence.routine.routine_monitor import RoutineMonitor, RoutineState


def _routine(
    name: str = "테스트약",
    scheduled: time = time(8, 0),
    grace: int = 10,
    interval: int = 10,
    max_reminders: int = 3,
) -> Routine:
    return Routine(name, RoutineCategory.MEDICATION, scheduled, grace, interval, max_reminders)


def test_no_reminder_before_grace_period_ends() -> None:
    monitor = RoutineMonitor()
    monitor.register(_routine())
    base = datetime(2026, 7, 22, 8, 5)  # 예정 8:00, 유예 10분 이내
    monitor.check(base)
    assert monitor.status_of("테스트약") == RoutineState.PENDING


def test_deviates_after_max_reminders() -> None:
    reminders: list[int] = []
    monitor = RoutineMonitor(on_reminder=lambda r, now, count: reminders.append(count))
    monitor.register(_routine(max_reminders=3, interval=10, grace=10))

    base = datetime(2026, 7, 22, 8, 0)
    now = base
    # 8:10, 8:20, 8:30 세 번 재알림이 발생하고, 그 다음 재알림 주기인 8:40에도
    # 응답이 없으면 그 시점에 이탈이 확정된다.
    for _ in range(50):
        monitor.check(now)
        now += timedelta(minutes=1)

    assert reminders == [1, 2, 3]
    assert monitor.status_of("테스트약") == RoutineState.DEVIATED


def test_confirm_stops_further_reminders() -> None:
    reminders: list[int] = []
    monitor = RoutineMonitor(on_reminder=lambda r, now, count: reminders.append(count))
    monitor.register(_routine())

    base = datetime(2026, 7, 22, 8, 0)
    monitor.check(base + timedelta(minutes=11))  # 첫 재알림 발생
    assert reminders == [1]

    monitor.confirm("테스트약", base + timedelta(minutes=12))
    assert monitor.status_of("테스트약") == RoutineState.CONFIRMED

    # 확인 이후로는 계속 check()를 호출해도 추가 재알림이 없어야 함
    for extra in range(1, 30):
        monitor.check(base + timedelta(minutes=12 + extra))
    assert reminders == [1]


def test_confirm_before_any_check_still_records_delay() -> None:
    """confirm()이 check()보다 먼저 호출돼도 지연이 계산돼야 함"""
    monitor = RoutineMonitor()
    monitor.register(_routine(scheduled=time(8, 0)))

    confirm_time = datetime(2026, 7, 22, 8, 7)
    monitor.confirm("테스트약", confirm_time)

    trackers = {t.routine.name: t for t in monitor.daily_trackers()}
    tracker = trackers["테스트약"]
    assert tracker.scheduled_datetime is not None
    assert tracker.confirmed_at is not None
    delay = (tracker.confirmed_at - tracker.scheduled_datetime).total_seconds() / 60
    assert delay == pytest.approx(7, abs=0.01)


def test_delay_bucketed_to_10_minutes() -> None:
    monitor = RoutineMonitor()
    monitor.register(_routine(scheduled=time(8, 0)))
    monitor.check(datetime(2026, 7, 22, 8, 0))
    monitor.confirm("테스트약", datetime(2026, 7, 22, 8, 23))  # 23분 지연 -> 20분 버킷

    conv = ConversationLog()
    vector = compute_daily_vector(monitor, conv, target_date=date(2026, 7, 22))
    assert vector["약_평균지연"] == 20


def test_no_response_counted_and_excluded_from_length_average() -> None:
    conv = ConversationLog()
    ts = datetime(2026, 7, 22, 14, 0)
    conv.log_turn(ts, "안녕하세요 반가워요", utterance_duration_sec=2.0)
    conv.log_turn(ts + timedelta(minutes=1), "", utterance_duration_sec=None, no_response=True)

    monitor = RoutineMonitor()
    vector = compute_daily_vector(monitor, conv, target_date=date(2026, 7, 22))

    assert vector["대화_무응답횟수"] == 1
    assert vector["대화_평균발화길이"] > 0  # 무응답 턴은 평균에서 제외됨


def test_conversation_turns_filtered_by_target_date() -> None:
    """자정을 넘긴 어제 대화가 오늘 지표에 섞이면 안 됨"""
    conv = ConversationLog()
    conv.log_turn(datetime(2026, 7, 21, 23, 50), "어제 대화", utterance_duration_sec=1.0)
    conv.log_turn(datetime(2026, 7, 22, 0, 10), "오늘 대화", utterance_duration_sec=1.0)

    today_turns = conv.daily_turns(date(2026, 7, 22))
    assert len(today_turns) == 1
    assert today_turns[0].utterance_text == "오늘 대화"


def test_routine_state_resets_on_new_day() -> None:
    """자정을 넘겨서도 계속 실행되면, 날짜가 바뀐 순간 어제 상태가 리셋돼야 함"""
    monitor = RoutineMonitor()
    monitor.register(_routine(scheduled=time(8, 0)))

    day1 = datetime(2026, 7, 22, 8, 0)
    monitor.check(day1)
    monitor.confirm("테스트약", day1 + timedelta(minutes=5))
    assert monitor.status_of("테스트약") == RoutineState.CONFIRMED

    day2 = datetime(2026, 7, 23, 7, 0)
    monitor.check(day2)  # 날짜가 바뀌었으므로 자동 리셋되어야 함
    assert monitor.status_of("테스트약") == RoutineState.PENDING


def test_reset_still_happens_when_confirm_is_called_before_first_check() -> None:
    """check()가 한 번도 안 불린 상태에서 confirm()이 먼저 불려도,
    이후 다음 날 check()가 처음 호출될 때 정상적으로 리셋돼야 함"""
    monitor = RoutineMonitor()
    monitor.register(_routine(scheduled=time(8, 0)))

    day1_late = datetime(2026, 7, 22, 23, 59)
    monitor.confirm("테스트약", day1_late)  # check()가 한 번도 안 불린 상태에서 먼저 호출
    assert monitor.status_of("테스트약") == RoutineState.CONFIRMED

    day2 = datetime(2026, 7, 23, 0, 5)
    monitor.check(day2)
    assert monitor.status_of("테스트약") == RoutineState.PENDING


def test_routine_rejects_zero_reminder_interval() -> None:
    with pytest.raises(ValueError):
        _routine(interval=0)


def test_load_history_rejects_non_positive_days(tmp_path: Path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text('{"date": "2026-07-01"}\n{"date": "2026-07-02"}\n', encoding="utf-8")

    with pytest.raises(ValueError):
        load_history(days=0, path=path)

    with pytest.raises(ValueError):
        load_history(days=-3, path=path)

    # 정상 값은 여전히 잘 동작해야 함
    assert len(load_history(days=1, path=path)) == 1
