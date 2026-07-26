"""Regression tests retained from the original novelty-score contribution."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from reminiscence.anomaly import (
    AnomalyMode,
    AnomalyStatus,
    ConversationMetric,
    PersonalAnomalyDetector,
)

SEOUL = ZoneInfo("Asia/Seoul")
START = datetime(2026, 1, 1, 14, 0, tzinfo=SEOUL)


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


def test_insufficient_history_defers_model_decision() -> None:
    result = PersonalAnomalyDetector().evaluate_conversations(
        tuple(conversation(index) for index in range(20))
    )

    assert result.mode is AnomalyMode.INSUFFICIENT_DATA
    assert result.status is AnomalyStatus.NORMAL
    assert result.score is None


def test_constant_baseline_still_flags_sudden_change() -> None:
    baseline = tuple(conversation(index) for index in range(20))

    result = PersonalAnomalyDetector().evaluate_conversations(
        (
            *baseline,
            conversation(
                20,
                turns=0,
                chars=0,
                average_chars=0,
                duration=0,
                no_response=50,
            ),
        )
    )

    assert result.status is AnomalyStatus.ANOMALOUS
    assert result.mode is AnomalyMode.ISOLATION_FOREST


def test_explanation_names_the_largest_observable_changes() -> None:
    baseline = tuple(conversation(index) for index in range(20))

    result = PersonalAnomalyDetector().evaluate_conversations(
        (
            *baseline,
            conversation(
                20,
                turns=0,
                chars=0,
                average_chars=0,
                duration=0,
                no_response=10,
            ),
        )
    )

    assert any("사용자 턴 수" in reason for reason in result.reasons)
    assert any("글자 수" in reason for reason in result.reasons)
    assert any("무응답" in reason for reason in result.reasons)


def test_evaluation_is_deterministic_with_fixed_model_seed() -> None:
    metrics = (
        *(conversation(index) for index in range(20)),
        conversation(20, turns=0, chars=0, duration=0, no_response=5),
    )
    detector = PersonalAnomalyDetector()

    assert detector.evaluate_conversations(metrics) == detector.evaluate_conversations(
        metrics
    )
