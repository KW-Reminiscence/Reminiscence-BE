"""
demo.py
-------
식사/약/기상 루틴과 대화 세션을 하루치 시뮬레이션하고, 지표 벡터가 제대로 뽑히는지 확인.
"""

from datetime import datetime, time, timedelta

from .conversation_metrics import ConversationLog
from .daily_metrics import append_history, compute_daily_vector, load_history
from .routine import Routine, RoutineCategory
from .routine_monitor import RoutineMonitor


def main() -> None:
    monitor = RoutineMonitor()
    conv_log = ConversationLog()

    monitor.register(Routine("아침식사", RoutineCategory.MEAL, time(8, 0)))
    monitor.register(Routine("아침약", RoutineCategory.MEDICATION, time(8, 30)))
    monitor.register(Routine("점심약", RoutineCategory.MEDICATION, time(12, 0)))

    base = datetime(2026, 7, 22)
    now = base + timedelta(hours=7, minutes=20)
    end = base + timedelta(hours=13)

    while now <= end:
        monitor.check(now)

        if now == base + timedelta(hours=8, minutes=23):
            monitor.confirm("아침식사", now, answer=False)  # 23분 지연 → 20분 버킷, "아직요"
        if now == base + timedelta(hours=8, minutes=35):
            monitor.confirm("아침약", now, answer=True)  # 5분 지연 → 0분 버킷, 복용함
        # 점심약은 끝까지 무응답 → 이탈

        now += timedelta(minutes=1)

    # 대화 세션 3턴 시뮬레이션 (정상 2, 무응답 1)
    conv_log.log_turn(
        base + timedelta(hours=14), "응 그때 설악산 갔었지", utterance_duration_sec=1.8
    )
    conv_log.log_turn(
        base + timedelta(hours=14, minutes=5), "어 그게 누구였더라", utterance_duration_sec=2.4
    )
    conv_log.log_turn(
        base + timedelta(hours=14, minutes=10), "", utterance_duration_sec=None, no_response=True
    )

    vector = compute_daily_vector(monitor, conv_log)

    print("오늘 지표 벡터:")
    for k, v in vector.items():
        print(f"  {k}: {v}")

    append_history(base.date(), vector)
    print(f"\nhistory.jsonl 저장 완료 (누적 {len(load_history(days=30))}건)")


if __name__ == "__main__":
    main()
