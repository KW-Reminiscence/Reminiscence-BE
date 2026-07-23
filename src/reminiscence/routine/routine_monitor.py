"""
routine_monitor.py
-------------------
루틴 이탈 감지의 핵심 로직 (상태머신).

이번 리뷰 반영 사항:
    - scheduled_datetime을 만들 때 now의 timezone을 그대로 유지 (naive/aware 비교 TypeError 방지)
    - check() 호출 시 날짜가 바뀐 걸 감지하면 자동으로 하루치 상태를 리셋
      (자정을 넘겨서까지 프로세스가 계속 돌아도 어제 데이터가 오늘 지표에 안 섞이도록)
    - confirm()이 check()보다 먼저 호출돼도 scheduled_datetime을 그 자리에서 채워 넣음
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum, auto
from typing import Callable, Optional

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
    last_reminder_at: Optional[datetime] = None
    scheduled_datetime: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    response_answer: Optional[bool] = None


class RoutineMonitor:
    def __init__(
        self,
        on_reminder: Optional[Callable[[Routine, datetime, int], None]] = None,
        on_deviation: Optional[Callable[[dict], None]] = None,
    ):
        self._trackers: dict[str, _RoutineTracker] = {}
        self.on_reminder = on_reminder
        self.on_deviation = on_deviation
        self._current_date: Optional[date] = None

    def register(self, routine: Routine) -> None:
        self._trackers[routine.name] = _RoutineTracker(routine=routine)

    def reset_for_new_day(self, today: date) -> None:
        """
        하루가 바뀔 때 모든 루틴 상태를 새로 시작.
        check()/confirm()가 날짜 변경을 감지하면 자동으로 호출하므로, 보통 직접 부를 필요는 없음.
        """
        for tracker in self._trackers.values():
            tracker.state = RoutineState.PENDING
            tracker.reminder_count = 0
            tracker.last_reminder_at = None
            tracker.scheduled_datetime = None
            tracker.confirmed_at = None
            tracker.response_answer = None
        self._current_date = today

    def _sync_current_date(self, today: date) -> None:
        """
        check()와 confirm() 양쪽 진입점에서 공통으로 호출해, 어느 쪽이 먼저 불려도
        날짜 변경을 놓치지 않도록 함.
        """
        if self._current_date is None:
            self._current_date = today
        elif today != self._current_date:
            self.reset_for_new_day(today)

    def confirm(self, routine_name: str, now: datetime, answer: bool = True) -> bool:
        self._sync_current_date(now.date())

        tracker = self._trackers.get(routine_name)
        if tracker is None:
            return False
        if tracker.state in (RoutineState.CONFIRMED, RoutineState.DEVIATED):
            return False

        # check()보다 confirm()이 먼저 호출된 경우를 대비해 예정 시각을 여기서도 채워줌
        if tracker.scheduled_datetime is None:
            tracker.scheduled_datetime = self._today_datetime(tracker.routine.scheduled_time, now)

        tracker.state = RoutineState.CONFIRMED
        tracker.confirmed_at = now
        tracker.response_answer = answer
        return True

    def check(self, now: datetime) -> None:
        self._sync_current_date(now.date())

        for tracker in self._trackers.values():
            if tracker.state in (RoutineState.CONFIRMED, RoutineState.DEVIATED):
                continue

            if tracker.scheduled_datetime is None:
                tracker.scheduled_datetime = self._today_datetime(tracker.routine.scheduled_time, now)

            grace_deadline = tracker.scheduled_datetime + timedelta(minutes=tracker.routine.grace_minutes)
            if now < grace_deadline:
                continue

            if tracker.state == RoutineState.PENDING:
                tracker.state = RoutineState.REMINDING

            should_remind = (
                tracker.last_reminder_at is None
                or now >= tracker.last_reminder_at + timedelta(minutes=tracker.routine.reminder_interval_minutes)
            )

            if should_remind and tracker.reminder_count < tracker.routine.max_reminders:
                tracker.reminder_count += 1
                tracker.last_reminder_at = now
                if self.on_reminder:
                    self.on_reminder(tracker.routine, now, tracker.reminder_count)
                continue

            # 마지막(max_reminders번째) 재알림을 보낸 뒤에도 한 번의 재알림 주기를 더 기다렸다가
            # 그래도 응답이 없으면 이탈로 확정한다 (마지막 재알림에 응답할 기회를 보장하기 위함).
            if tracker.reminder_count >= tracker.routine.max_reminders and should_remind:
                tracker.state = RoutineState.DEVIATED
                if self.on_deviation:
                    self.on_deviation(self._build_deviation_payload(tracker, now))

    def status_of(self, routine_name: str) -> Optional[RoutineState]:
        tracker = self._trackers.get(routine_name)
        return tracker.state if tracker else None

    def daily_trackers(self):
        """오늘(자동 리셋된 이후) 하루치 트래커 전체를 반환"""
        return list(self._trackers.values())

    @staticmethod
    def _today_datetime(t, now: datetime) -> datetime:
        # now가 timezone-aware면 그대로 이어받아야, 이후 비교에서 TypeError가 안 남
        return datetime.combine(now.date(), t, tzinfo=now.tzinfo)

    @staticmethod
    def _build_deviation_payload(tracker: _RoutineTracker, now: datetime) -> dict:
        return {
            "type": "deviation",
            "routine": tracker.routine.name,
            "category": tracker.routine.category.value,
            "status": "미확인",
            "scheduled_time": tracker.routine.scheduled_time.strftime("%H:%M"),
            "detected_at": now.isoformat(timespec="seconds"),
            "reminder_count": tracker.reminder_count,
        }
