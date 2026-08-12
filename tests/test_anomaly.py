"""Regression tests retained from the original novelty-score contribution."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from reminiscence.anomaly import (
    AnomalyMode,
    AnomalyObservations,
    AnomalyStatus,
    BaselineState,
    ConversationQualityObservation,
    PersonalAnomalyDetector,
)

SEOUL = ZoneInfo("Asia/Seoul")
START = datetime(2026, 1, 1, 14, 0, tzinfo=SEOUL)
NORMAL = (5.0, 100.0, 20.0, 8.0, 0.0)
CHANGED = (0.0, 0.0, 0.0, 0.0, 10.0)


def quality(index: int, values: tuple[float, ...] = NORMAL) -> ConversationQualityObservation:
    return ConversationQualityObservation(
        f"session-{index}",
        START + timedelta(days=index),
        values,  # type: ignore[arg-type]
    )


def evaluate(
    sessions: tuple[ConversationQualityObservation, ...],
    baseline: BaselineState,
):  # type: ignore[no-untyped-def]
    return PersonalAnomalyDetector().evaluate_conversations(
        AnomalyObservations((), sessions, ()),
        baseline,
    )


def test_insufficient_history_defers_model_decision() -> None:
    result = evaluate(tuple(quality(index) for index in range(20)), BaselineState())

    assert result.mode is AnomalyMode.INSUFFICIENT_DATA
    assert result.status is AnomalyStatus.NORMAL
    assert result.score is None


def test_constant_baseline_flags_candidates_and_requires_persistence() -> None:
    baseline = BaselineState(
        conversation_quality_vectors=tuple(NORMAL for _ in range(20))
    )
    sessions = tuple(quality(index) for index in range(20))

    first = evaluate((*sessions, quality(20, CHANGED)), baseline)
    second = evaluate(
        (*sessions, quality(20, CHANGED), quality(21, CHANGED)),
        baseline,
    )

    assert first.isolation_forest_signal is True
    assert first.status is AnomalyStatus.NORMAL
    assert second.status is AnomalyStatus.ANOMALOUS
    assert second.mode is AnomalyMode.ISOLATION_FOREST


def test_explanation_names_largest_observable_changes() -> None:
    baseline = BaselineState(
        conversation_quality_vectors=tuple(NORMAL for _ in range(20))
    )
    sessions = tuple(quality(index) for index in range(20)) + (
        quality(20, CHANGED),
        quality(21, CHANGED),
    )

    result = evaluate(sessions, baseline)

    assert any("사용자 턴 수" in reason for reason in result.reasons)
    assert any("글자 수" in reason for reason in result.reasons)


def test_evaluation_is_deterministic_with_fixed_model_seed() -> None:
    baseline = BaselineState(
        conversation_quality_vectors=tuple(NORMAL for _ in range(20))
    )
    sessions = tuple(quality(index) for index in range(20)) + (
        quality(20, CHANGED),
    )

    assert evaluate(sessions, baseline) == evaluate(sessions, baseline)
