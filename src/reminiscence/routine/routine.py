"""
routine.py
----------
루틴 하나(식사, 약 복용 등)를 표현하는 데이터 구조.
"""

from dataclasses import dataclass
from datetime import time
from enum import Enum


class RoutineCategory(Enum):
    MEAL = "식사"
    MEDICATION = "약"


@dataclass
class Routine:
    name: str
    category: RoutineCategory
    scheduled_time: time
    grace_minutes: int = 10
    reminder_interval_minutes: int = 10
    max_reminders: int = 3

    def __post_init__(self) -> None:
        if self.grace_minutes < 0:
            raise ValueError("grace_minutes는 0 이상이어야 합니다")
        if self.reminder_interval_minutes <= 0:
            raise ValueError(
                "reminder_interval_minutes는 0보다 커야 합니다 "
                "(0이면 재알림이 무한히 발생함)"
            )
        if self.max_reminders < 0:
            raise ValueError("max_reminders는 0 이상이어야 합니다")
