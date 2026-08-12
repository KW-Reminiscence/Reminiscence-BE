"""Confirmed v1.4 anomaly policy boundary tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from reminiscence.anomaly import (
    AnomalyMode,
    AnomalyObservations,
    AnomalyStatus,
    BaselineState,
    ConversationQualityObservation,
    ParticipationObservation,
    PersonalAnomalyDetector,
    RoutineObservation,
)

SEOUL = ZoneInfo("Asia/Seoul")
START_DATE = date(2026, 1, 1)
START = datetime(2026, 1, 1, 18, 0, tzinfo=SEOUL)
NORMAL_ROUTINE = (0.0, 0.0, 300.0, 300.0, 1.0, 0.0)
ANOMALOUS_ROUTINE = (1.0, 1.0, 0.0, 0.0, 0.0, 4.0)
MODEL_ONLY_ROUTINE = (1.0, 1.0, 0.0, 0.0, 0.0, 2.0)
NORMAL_QUALITY = (5.0, 100.0, 20.0, 8.0, 0.0)
ANOMALOUS_QUALITY = (0.0, 0.0, 0.0, 0.0, 5.0)


def routine(index: int, values: tuple[float, ...] = NORMAL_ROUTINE) -> RoutineObservation:
    return RoutineObservation(START_DATE + timedelta(days=index), values)  # type: ignore[arg-type]


def quality(
    index: int,
    values: tuple[float, ...] = NORMAL_QUALITY,
) -> ConversationQualityObservation:
    return ConversationQualityObservation(
        f"session-{index}",
        START + timedelta(days=index),
        values,  # type: ignore[arg-type]
    )


def participation(index: int, turns: int) -> ParticipationObservation:
    return ParticipationObservation(START_DATE + timedelta(days=index), turns)


def observations(
    *,
    routines: tuple[RoutineObservation, ...] = (),
    quality_sessions: tuple[ConversationQualityObservation, ...] = (),
    participation_days: tuple[ParticipationObservation, ...] = (),
) -> AnomalyObservations:
    return AnomalyObservations(routines, quality_sessions, participation_days)


def test_cold_start_combines_three_miss_rule_with_persistence_signal() -> None:
    result = PersonalAnomalyDetector().evaluate_routines(
        (routine(0), routine(1), routine(2, ANOMALOUS_ROUTINE)),
        BaselineState(),
    )

    assert result.status is AnomalyStatus.ANOMALOUS
    assert result.mode is AnomalyMode.COLD_START
    assert result.rule_based_signal is True
    assert result.isolation_forest_signal is False
    assert result.persistence_signal is True
    assert result.signal_count == 2


def test_routine_model_activates_on_29th_completed_day_without_early_finalization() -> None:
    baseline_vectors = tuple(NORMAL_ROUTINE for _ in range(28))
    detector = PersonalAnomalyDetector()
    day_29 = tuple(routine(index) for index in range(28)) + (
        routine(28, MODEL_ONLY_ROUTINE),
    )
    day_30 = day_29 + (routine(29, MODEL_ONLY_ROUTINE),)

    first = detector.evaluate_routines(day_29, BaselineState(baseline_vectors))
    second = detector.evaluate_routines(day_30, BaselineState(baseline_vectors))

    assert first.mode is AnomalyMode.ISOLATION_FOREST
    assert first.isolation_forest_signal is True
    assert first.persistence_signal is False
    assert first.status is AnomalyStatus.NORMAL
    assert second.isolation_forest_signal is True
    assert second.persistence_signal is True
    assert second.status is AnomalyStatus.ANOMALOUS


def test_conversation_quality_requires_20_baseline_and_two_of_recent_three() -> None:
    baseline_vectors = tuple(NORMAL_QUALITY for _ in range(20))
    baseline = BaselineState(conversation_quality_vectors=baseline_vectors)
    detector = PersonalAnomalyDetector()
    first_candidate = tuple(quality(index) for index in range(20)) + (
        quality(20, ANOMALOUS_QUALITY),
    )
    second_candidate = first_candidate + (quality(21, ANOMALOUS_QUALITY),)

    first = detector.evaluate_conversations(
        observations(quality_sessions=first_candidate),
        baseline,
    )
    second = detector.evaluate_conversations(
        observations(quality_sessions=second_candidate),
        baseline,
    )

    assert first.isolation_forest_signal is True
    assert first.persistence_signal is False
    assert first.status is AnomalyStatus.NORMAL
    assert second.isolation_forest_signal is True
    assert second.persistence_signal is True
    assert second.status is AnomalyStatus.ANOMALOUS
    assert "최근 3개" in second.reasons[-1]


def test_participation_exactly_fifty_percent_and_ten_turn_decrease() -> None:
    baseline = BaselineState(participation_weekly_turn_mean=20.0)
    initial = tuple(participation(index, 20) for index in range(28))
    first = PersonalAnomalyDetector().evaluate_conversations(
        observations(participation_days=(*initial, participation(28, 10))),
        baseline,
    )
    second = PersonalAnomalyDetector().evaluate_conversations(
        observations(
            participation_days=(
                *initial,
                participation(28, 10),
                participation(29, 10),
            )
        ),
        baseline,
    )

    assert first.rule_based_signal is True
    assert first.persistence_signal is False
    assert first.status is AnomalyStatus.NORMAL
    assert second.rule_based_signal is True
    assert second.persistence_signal is True
    assert second.status is AnomalyStatus.ANOMALOUS


def test_participation_zero_sessions_is_observed_as_zero() -> None:
    baseline = BaselineState(participation_weekly_turn_mean=20.0)
    days = tuple(participation(index, 20) for index in range(28)) + (
        participation(28, 0),
        participation(29, 0),
    )

    result = PersonalAnomalyDetector().evaluate_conversations(
        observations(participation_days=days),
        baseline,
    )

    assert result.rule_based_signal is True
    assert result.persistence_signal is True
    assert result.status is AnomalyStatus.ANOMALOUS


def test_models_remain_separate_in_combined_state() -> None:
    baseline = BaselineState(
        routine_vectors=tuple(NORMAL_ROUTINE for _ in range(28)),
        conversation_quality_vectors=tuple(NORMAL_QUALITY for _ in range(20)),
    )
    result = PersonalAnomalyDetector().evaluate(
        observations(
            routines=tuple(routine(index) for index in range(30)),
            quality_sessions=(
                *(quality(index) for index in range(20)),
                quality(20, ANOMALOUS_QUALITY),
                quality(21, ANOMALOUS_QUALITY),
            ),
        ),
        baseline,
        START + timedelta(days=31),
    )

    assert result.routine.status is AnomalyStatus.NORMAL
    assert result.conversation.status is AnomalyStatus.ANOMALOUS
    assert result.status is AnomalyStatus.ANOMALOUS


def test_evaluation_is_deterministic() -> None:
    sessions = tuple(quality(index) for index in range(20)) + (
        quality(20, ANOMALOUS_QUALITY),
    )
    baseline = BaselineState(
        conversation_quality_vectors=tuple(NORMAL_QUALITY for _ in range(20))
    )
    detector = PersonalAnomalyDetector()

    assert detector.evaluate_conversations(
        observations(quality_sessions=sessions), baseline
    ) == detector.evaluate_conversations(observations(quality_sessions=sessions), baseline)
