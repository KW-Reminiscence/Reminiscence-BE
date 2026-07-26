"""Cold-start and Isolation Forest boundary tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from reminiscence.anomaly import (
    AnomalyMode,
    AnomalyStatus,
    ConversationMetric,
    PersonalAnomalyDetector,
    RoutineMetric,
)

SEOUL = ZoneInfo("Asia/Seoul")
START = datetime(2026, 1, 1, 9, 0, tzinfo=SEOUL)


def routine(
    day: int,
    state: str = "CONFIRMED",
    *,
    routine_id: str = "morning-medication",
    delay: int | None = 300,
) -> RoutineMetric:
    return RoutineMetric(
        routine_id=routine_id,
        scheduled_at=START + timedelta(days=day),
        state=state,
        confirmation_delay_seconds=delay if state == "CONFIRMED" else None,
    )


def conversation(
    index: int,
    *,
    turns: int = 5,
    chars: int = 100,
    average_chars: float = 20,
    duration: float = 8,
    no_response: int = 0,
) -> ConversationMetric:
    return ConversationMetric(
        session_id=f"session-{index}",
        started_at=START + timedelta(days=index),
        user_turn_count=turns,
        total_utterance_chars=chars,
        average_utterance_chars=average_chars,
        average_turn_duration_seconds=duration,
        no_response_count=no_response,
    )


def test_cold_start_flags_three_consecutive_misses_for_same_routine() -> None:
    result = PersonalAnomalyDetector().evaluate_routines(
        (
            routine(0, "NOT_ANSWERED"),
            routine(1, "NOT_ANSWERED"),
            routine(2, "NOT_ANSWERED"),
        )
    )

    assert result.status is AnomalyStatus.ANOMALOUS
    assert result.mode is AnomalyMode.COLD_START
    assert result.reasons == ("morning-medication 루틴 3회 연속 미응답",)


def test_confirmation_breaks_consecutive_miss_sequence() -> None:
    result = PersonalAnomalyDetector().evaluate_routines(
        (
            routine(0, "NOT_ANSWERED"),
            routine(1, "NOT_ANSWERED"),
            routine(2, "CONFIRMED"),
            routine(3, "NOT_ANSWERED"),
        )
    )

    assert result.status is AnomalyStatus.NORMAL


def test_different_routines_do_not_combine_misses() -> None:
    result = PersonalAnomalyDetector().evaluate_routines(
        (
            routine(0, "NOT_ANSWERED", routine_id="meal"),
            routine(1, "NOT_ANSWERED", routine_id="medication"),
            routine(2, "NOT_ANSWERED", routine_id="meal"),
        )
    )

    assert result.status is AnomalyStatus.NORMAL


def test_routine_model_activates_after_28_baseline_days() -> None:
    metrics = tuple(routine(day) for day in range(28))

    baseline_only = PersonalAnomalyDetector().evaluate_routines(metrics)
    with_current = PersonalAnomalyDetector().evaluate_routines(
        (*metrics, routine(28, "NOT_ANSWERED"))
    )

    assert baseline_only.mode is AnomalyMode.COLD_START
    assert with_current.mode is AnomalyMode.ISOLATION_FOREST
    assert with_current.status is AnomalyStatus.ANOMALOUS
    assert "루틴 미응답 비율" in with_current.reasons[0]


def test_conversation_model_requires_20_baseline_sessions() -> None:
    metrics = tuple(conversation(index) for index in range(20))

    insufficient = PersonalAnomalyDetector().evaluate_conversations(metrics)
    evaluated = PersonalAnomalyDetector().evaluate_conversations(
        (
            *metrics,
            conversation(
                20,
                turns=0,
                chars=0,
                average_chars=0,
                duration=0,
                no_response=5,
            ),
        )
    )

    assert insufficient.mode is AnomalyMode.INSUFFICIENT_DATA
    assert insufficient.status is AnomalyStatus.NORMAL
    assert evaluated.mode is AnomalyMode.ISOLATION_FOREST
    assert evaluated.status is AnomalyStatus.ANOMALOUS
    assert any("사용자 턴 수" in reason for reason in evaluated.reasons)
    assert any("무응답" in reason for reason in evaluated.reasons)
    assert evaluated.feature_names[0] == "recent_7_day_user_turn_count"


def test_models_remain_separate_in_combined_state() -> None:
    result = PersonalAnomalyDetector().evaluate(
        tuple(routine(day) for day in range(29)),
        (
            *(conversation(index) for index in range(20)),
            conversation(20, turns=0, chars=0, duration=0, no_response=5),
        ),
        START + timedelta(days=30),
    )

    assert result.routine.status is AnomalyStatus.NORMAL
    assert result.conversation.status is AnomalyStatus.ANOMALOUS
    assert result.status is AnomalyStatus.ANOMALOUS


def test_evaluation_is_deterministic() -> None:
    metrics = (
        *(conversation(index) for index in range(20)),
        conversation(20, turns=0, chars=0, duration=0, no_response=5),
    )
    detector = PersonalAnomalyDetector()

    first = detector.evaluate_conversations(metrics)
    second = detector.evaluate_conversations(metrics)

    assert first == second
