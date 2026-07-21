"""
routine.py
----------
루틴 하나(식사, 약 복용, 기상 확인 등)를 표현하는 데이터 구조.
"""

from dataclasses import dataclass
from datetime import time
from enum import Enum


class RoutineCategory(Enum):
    MEAL = "식사"
    MEDICATION = "약"


@dataclass
class Routine:
    # 루틴 이름 (예: "아침식사", "점심약", "기상 확인")
    name: str

    # 어떤 카테고리인지 (지표를 카테고리별로 묶어서 계산하는 데 사용)
    category: RoutineCategory

    # 루틴이 시작되는 예정 시각
    scheduled_time: time

    # 예정 시각을 지나도 괜찮다고 봐주는 유예 시간 (분)
    grace_minutes: int = 10

    # 유예 시간이 지나면 몇 분 간격으로 재알림을 보낼지 (요구사항: 10분 단위)
    reminder_interval_minutes: int = 10

    # 재알림을 최대 몇 번까지 시도한 뒤 "이탈"로 최종 확정할지 (요구사항: 3회)
    max_reminders: int = 3
