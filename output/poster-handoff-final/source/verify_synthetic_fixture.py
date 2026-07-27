"""Reproduce and export the varied synthetic fixture used in Figure 4."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from reminiscence.anomaly import (
    AnomalyStatus,
    ConversationMetric,
    PersonalAnomalyDetector,
)

SEOUL = ZoneInfo("Asia/Seoul")
START = datetime(2026, 1, 1, 9, 0, tzinfo=SEOUL)
ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).with_name("synthetic_anomaly_fixture.json")
CSV_OUTPUT = ROOT / "data" / "synthetic_anomaly_replay.csv"
WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def conversation(row: dict[str, int | float | str]) -> ConversationMetric:
    turns = int(row["user_turn_count"])
    chars = int(row["total_utterance_chars"])
    return ConversationMetric(
        session_id=f"session-{row['session']}",
        started_at=START + timedelta(days=int(row["day_offset"])),
        user_turn_count=turns,
        total_utterance_chars=chars,
        average_utterance_chars=round(chars / turns, 3),
        average_turn_duration_seconds=float(
            row["average_turn_duration_seconds"]
        ),
        no_response_count=int(row["no_response_count"]),
    )


def main() -> None:
    rows: list[dict[str, int | float | str]] = json.loads(
        FIXTURE.read_text(encoding="utf-8")
    )
    if len(rows) != 21:
        raise ValueError("fixture must contain 20 baseline rows and one current row")
    metrics = tuple(conversation(row) for row in rows)

    recent_turns = []
    for index, metric in enumerate(metrics):
        window_start = metric.started_at - timedelta(days=7)
        recent_turns.append(
            sum(
                candidate.user_turn_count
                for candidate in metrics[: index + 1]
                if candidate.started_at > window_start
            )
        )

    baseline_vectors = tuple(
        (
            recent_turns[index],
            metric.total_utterance_chars,
            metric.average_utterance_chars,
            metric.average_turn_duration_seconds,
            metric.no_response_count,
        )
        for index, metric in enumerate(metrics[:-1])
    )
    assert all(
        len({vector[index] for vector in baseline_vectors}) > 1
        for index in range(5)
    )

    result = PersonalAnomalyDetector().evaluate_conversations(metrics)
    assert result.status is AnomalyStatus.ANOMALOUS
    assert result.score == -0.048242
    assert result.reasons == (
        "최근 7일 회상 대화 사용자 턴 수가 개인 기준선보다 감소",
        "회상 대화 글자 수가 개인 기준선보다 감소",
        "회상 대화 무응답 횟수가 개인 기준선보다 증가",
    )

    CSV_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        "session",
        "date",
        "weekday",
        "role",
        "user_turn_count",
        "recent_7_day_user_turn_count",
        "total_utterance_chars",
        "average_utterance_chars",
        "average_turn_duration_seconds",
        "no_response_count",
    )
    with CSV_OUTPUT.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        for row, metric, rolling_turns in zip(
            rows,
            metrics,
            recent_turns,
            strict=True,
        ):
            writer.writerow(
                {
                    "session": row["session"],
                    "date": metric.started_at.date().isoformat(),
                    "weekday": WEEKDAYS[metric.started_at.weekday()],
                    "role": row["role"],
                    "user_turn_count": metric.user_turn_count,
                    "recent_7_day_user_turn_count": rolling_turns,
                    "total_utterance_chars": metric.total_utterance_chars,
                    "average_utterance_chars": metric.average_utterance_chars,
                    "average_turn_duration_seconds": (
                        metric.average_turn_duration_seconds
                    ),
                    "no_response_count": metric.no_response_count,
                }
            )

    print(f"status={result.status.value}")
    print(f"score={result.score:.6f}")
    for reason in result.reasons:
        print(f"reason={reason}")
    print(f"csv={CSV_OUTPUT}")


if __name__ == "__main__":
    main()
