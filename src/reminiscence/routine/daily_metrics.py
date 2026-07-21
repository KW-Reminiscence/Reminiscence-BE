"""
daily_metrics.py
----------------
식사/약 루틴과 대화 로그를 합쳐서 하루치 지표 벡터를 계산합니다.

지연은 10분 단위로 버킷화합니다 (재질문 자체가 10분 간격이므로,
"몇 번째 10분 구간에서 확인됐는지"로 표현하는 게 실제 알림 동작과 맞아떨어짐).
예: confirm이 예정 시각+23분에 일어났다면 → 20분 구간으로 기록.
"""

import json
import statistics
from datetime import date
from pathlib import Path

from routine_monitor import RoutineMonitor, RoutineState
from routine import RoutineCategory
from conversation_metrics import ConversationLog

HISTORY_PATH = Path("history.jsonl")

CATEGORIES = [RoutineCategory.MEAL, RoutineCategory.MEDICATION]

DELAY_BUCKET_MIN = 10


def _bucket_delay(delay_minutes: float) -> int:
    """지연 시간을 10분 단위로 내림 처리 (예: 23분 → 20분)"""
    return int(delay_minutes // DELAY_BUCKET_MIN) * DELAY_BUCKET_MIN


def _category_stats(trackers, category: RoutineCategory) -> dict:
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
                not_done_count += 1  # 응답은 했지만 "깜빡했다/안 먹었다"도 미이행으로 집계

    return {
        f"{prefix}_평균지연": round(statistics.mean(delay_buckets)) if delay_buckets else 0,
        f"{prefix}_미이행률": round(not_done_count / len(relevant), 2),
        f"{prefix}_반복미응답": reminder_total,
    }


def _conversation_stats(turns) -> dict:
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


def compute_daily_vector(monitor: RoutineMonitor, conversation_log: ConversationLog) -> dict:
    trackers = monitor.daily_trackers()
    vector = {}
    for category in CATEGORIES:
        vector.update(_category_stats(trackers, category))
    vector.update(_conversation_stats(conversation_log.daily_turns()))
    return vector


def append_history(today: date, vector: dict, path: Path = HISTORY_PATH) -> None:
    record = {"date": today.isoformat(), **vector}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_history(days: int = 7, path: Path = HISTORY_PATH) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    return records[-days:]
