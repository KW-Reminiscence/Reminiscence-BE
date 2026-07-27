"""Reproduce the synthetic conversation fixture used in Figure 4."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from reminiscence.anomaly import (
    AnomalyStatus,
    ConversationMetric,
    PersonalAnomalyDetector,
)

SEOUL = ZoneInfo("Asia/Seoul")
START = datetime(2026, 1, 1, 9, 0, tzinfo=SEOUL)


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
        session_id=f"session-{index + 1}",
        started_at=START + timedelta(days=index),
        user_turn_count=turns,
        total_utterance_chars=chars,
        average_utterance_chars=average_chars,
        average_turn_duration_seconds=duration,
        no_response_count=no_response,
    )


def main() -> None:
    metrics = (
        *(conversation(index) for index in range(20)),
        conversation(
            20,
            turns=0,
            chars=0,
            average_chars=0,
            duration=0,
            no_response=5,
        ),
    )
    result = PersonalAnomalyDetector().evaluate_conversations(metrics)
    assert result.status is AnomalyStatus.ANOMALOUS
    assert result.score == -0.001109
    print(f"status={result.status.value}")
    print(f"score={result.score:.6f}")
    for reason in result.reasons:
        print(f"reason={reason}")


if __name__ == "__main__":
    main()
