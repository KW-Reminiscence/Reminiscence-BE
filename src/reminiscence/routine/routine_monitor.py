"""
routine_monitor.py
-------------------
루틴 이탈 감지의 핵심 로직 (상태머신은 기존과 동일).

이번 버전에서 바뀐 점:
    confirm()이 이제 "응답했는지"뿐 아니라 "응답 내용(했다/안 했다)"까지 받습니다.
    예: 식사 여부를 물었을 때 "네 먹었어요"면 answer=True, "아직요"면 answer=False.

    반복 미응답 횟수는 reminder_count를 그대로 씁니다.
    (재알림이 발생했다는 것 자체가 "그 시점까지 응답이 없었다"는 뜻이므로)
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum, auto

from .routine import Routine


class RoutineState(Enum):
    PENDING = auto()
    REMINDING = auto()
    CONFIRMED = auto()
    DEVIATED = auto()


@dataclass
class _RoutineTracker:
    routine: Routine
    state: RoutineState = RoutineState.PENDING
    reminder_count: int = 0
    last_reminder_at: datetime | None = None
    scheduled_datetime: datetime | None = None
    confirmed_at: datetime | None = None
    response_answer: bool | None = None  # 응답 내용: 했다(True) / 안 했다(False)


class RoutineMonitor:
    def __init__(
        self,
        on_reminder: Callable[[Routine, datetime, int], None] | None = None,
        on_deviation: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._trackers: dict[str, _RoutineTracker] = {}
        self.on_reminder = on_reminder
        self.on_deviation = on_deviation

    def register(self, routine: Routine) -> None:
        self._trackers[routine.name] = _RoutineTracker(routine=routine)

    def confirm(self, routine_name: str, now: datetime, answer: bool = True) -> bool:
        """
        루틴 응답 처리.
        answer=True  → "했어요" (식사함/약 먹음/기상함)
        answer=False → "아직요" (안 함) — 그래도 "응답은 했다"는 사실 자체는 중요하므로
        CONFIRMED로 처리

        실제로는 LLM이 사용자 발화("네 먹었어요" 등)를 해석한 뒤 이 메서드를 호출.
        """
        tracker = self._trackers.get(routine_name)
        if tracker is None:
            return False
        if tracker.state in (RoutineState.CONFIRMED, RoutineState.DEVIATED):
            return False

        tracker.state = RoutineState.CONFIRMED
        tracker.confirmed_at = now
        tracker.response_answer = answer
        return True

    def check(self, now: datetime) -> None:
        for tracker in self._trackers.values():
            if tracker.state in (RoutineState.CONFIRMED, RoutineState.DEVIATED):
                continue

            if tracker.scheduled_datetime is None:
                tracker.scheduled_datetime = self._today_datetime(
                    tracker.routine.scheduled_time, now
                )

            grace_deadline = tracker.scheduled_datetime + timedelta(
                minutes=tracker.routine.grace_minutes
            )
            if now < grace_deadline:
                continue

            if tracker.state == RoutineState.PENDING:
                tracker.state = RoutineState.REMINDING

            should_remind = (
                tracker.last_reminder_at is None
                or now
                >= tracker.last_reminder_at
                + timedelta(minutes=tracker.routine.reminder_interval_minutes)
            )

            if should_remind and tracker.reminder_count < tracker.routine.max_reminders:
                tracker.reminder_count += 1
                tracker.last_reminder_at = now
                if self.on_reminder:
                    self.on_reminder(tracker.routine, now, tracker.reminder_count)
                continue

            if tracker.reminder_count >= tracker.routine.max_reminders and should_remind:
                tracker.state = RoutineState.DEVIATED
                if self.on_deviation:
                    self.on_deviation(self._build_deviation_payload(tracker, now))

    def status_of(self, routine_name: str) -> RoutineState | None:
        tracker = self._trackers.get(routine_name)
        return tracker.state if tracker else None

    def daily_trackers(self) -> list[_RoutineTracker]:
        """지표 계산 모듈이 오늘 하루치 트래커 전체를 읽어가기 위한 접근자"""
        return list(self._trackers.values())

    @staticmethod
    def _today_datetime(t: time, now: datetime) -> datetime:
        return datetime.combine(now.date(), t)

    @staticmethod
    def _build_deviation_payload(tracker: _RoutineTracker, now: datetime) -> dict[str, object]:
        return {
            "type": "deviation",
            "routine": tracker.routine.name,
            "category": tracker.routine.category.value,
            "status": "미확인",
            "scheduled_time": tracker.routine.scheduled_time.strftime("%H:%M"),
            "detected_at": now.isoformat(timespec="seconds"),
            "reminder_count": tracker.reminder_count,
        }
