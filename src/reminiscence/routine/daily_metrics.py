"""
daily_metrics.py
----------------
식사/약 루틴과 대화 로그를 합쳐서 하루치 지표 벡터를 계산합니다.

이번 리뷰 반영 사항:
    - compute_daily_vector()가 target_date를 받아서 대화 로그를 그 날짜로 한정
      (루틴 쪽은 RoutineMonitor가 날짜 변경 시 자동 리셋하므로 별도 필터링 불필요)
    - load_history(days=0) 같은 호출이 전체 이력을 반환해버리던 버그 수정
      (파이썬에서 -0 == 0 이라 records[-0:]이 빈 리스트가 아니라 전체가 되는 문제)
"""

import json
import statistics
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from .conversation_metrics import ConversationLog, ConversationTurn
from .routine import RoutineCategory
from .routine_monitor import RoutineMonitor, RoutineState, _RoutineTracker

HISTORY_PATH = Path("history.jsonl")

CATEGORIES = [RoutineCategory.MEAL, RoutineCategory.MEDICATION]

DELAY_BUCKET_MIN = 10
type MetricValue = int | float
type DailyVector = dict[str, MetricValue]


def _bucket_delay(delay_minutes: float) -> int:
    return int(delay_minutes // DELAY_BUCKET_MIN) * DELAY_BUCKET_MIN


def _category_stats(
    trackers: Iterable[_RoutineTracker],
    category: RoutineCategory,
) -> DailyVector:
    relevant = [t for t in trackers if t.routine.category == category]
    prefix = category.value

    if not relevant:
        return {f"{prefix}_평균지연": 0, f"{prefix}_미이행률": 0.0, f"{prefix}_반복미응답": 0}

    delay_buckets = []
    not_done_count = 0
    reminder_total = 0

    for t in relevant:
        reminder_total += t.reminder_count

        if t.state == RoutineState.DEVIATED:
            not_done_count += 1
            continue

        if t.state == RoutineState.CONFIRMED:
            if t.confirmed_at and t.scheduled_datetime:
                delay_min = max((t.confirmed_at - t.scheduled_datetime).total_seconds() / 60, 0)
                delay_buckets.append(_bucket_delay(delay_min))
            if t.response_answer is False:
                not_done_count += 1

    return {
        f"{prefix}_평균지연": round(statistics.mean(delay_buckets)) if delay_buckets else 0,
        f"{prefix}_미이행률": round(not_done_count / len(relevant), 2),
        f"{prefix}_반복미응답": reminder_total,
    }


def _conversation_stats(turns: Iterable[ConversationTurn]) -> DailyVector:
    turns = list(turns)
    if not turns:
        return {"대화_평균말속도": 0.0, "대화_무응답횟수": 0, "대화_평균발화길이": 0.0}

    rates = [t.speaking_rate_per_min for t in turns if t.speaking_rate_per_min is not None]
    lengths = [t.utterance_length for t in turns if not t.no_response]
    no_response_count = sum(1 for t in turns if t.no_response)

    return {
        "대화_평균말속도": round(statistics.mean(rates), 1) if rates else 0.0,
        "대화_무응답횟수": no_response_count,
        "대화_평균발화길이": round(statistics.mean(lengths), 1) if lengths else 0.0,
    }


def compute_daily_vector(
    monitor: RoutineMonitor,
    conversation_log: ConversationLog,
    target_date: date,
) -> DailyVector:
    """
    target_date: 이 날짜 기준으로 지표를 계산.
                 루틴 쪽은 RoutineMonitor가 날짜 변경 시 자동으로 리셋되므로 현재 상태를 그대로 씀.
                 대화 쪽은 이 함수에서 명시적으로 target_date로 필터링.
    """
    trackers = monitor.daily_trackers()
    vector: DailyVector = {}
    for category in CATEGORIES:
        vector.update(_category_stats(trackers, category))
    vector.update(_conversation_stats(conversation_log.daily_turns(target_date)))
    return vector


def append_history(today: date, vector: DailyVector, path: Path = HISTORY_PATH) -> None:
    record = {"date": today.isoformat(), **vector}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_history(days: int = 7, path: Path = HISTORY_PATH) -> list[dict[str, object]]:
    if days <= 0:
        raise ValueError(f"days는 1 이상이어야 합니다 (받은 값: {days})")

    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        records: list[dict[str, object]] = [json.loads(line) for line in f if line.strip()]
    return records[-days:]
