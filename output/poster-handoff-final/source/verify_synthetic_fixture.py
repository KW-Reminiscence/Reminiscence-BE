"""Reproduce and export the varied synthetic fixture used in Figure 4."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from reminiscence.anomaly import (
    AnomalyStatus,
    ConversationMetric,
    PersonalAnomalyDetector,
    PersonalEvaluation,
)
from reminiscence.anomaly.service import AnomalyService
from reminiscence.anomaly.storage import ActivityMetricReader, PersonalStateStore
from reminiscence.notification.config import (
    CareRecipientConfig,
    GuardianConfig,
    NotificationConfig,
    SmtpConfig,
)
from reminiscence.notification.service import (
    NotificationCoordinator,
    NotificationDeliveryStatus,
)
from reminiscence.notification.state import NotificationAttemptStore
from reminiscence.storage import JsonObjectStore

SEOUL = ZoneInfo("Asia/Seoul")
START = datetime(2026, 1, 1, 9, 0, tzinfo=SEOUL)
ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).with_name("synthetic_anomaly_fixture.json")
CSV_OUTPUT = ROOT / "data" / "synthetic_anomaly_replay.csv"
RESULT_OUTPUT = ROOT / "evidence" / "synthetic_anomaly_result.json"
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


class RecordingEmailSender:
    """Record fixture deliveries without opening an SMTP connection."""

    def __init__(self) -> None:
        self.sent: list[PersonalEvaluation] = []

    def send(
        self,
        config: NotificationConfig,
        current: PersonalEvaluation,
    ) -> None:
        del config
        self.sent.append(current)


def notification_config() -> NotificationConfig:
    return NotificationConfig(
        care_recipient=CareRecipientConfig(name="합성 사용자"),
        guardian=GuardianConfig(email="fixture@example.com"),
        smtp=SmtpConfig(
            host="smtp.example.com",
            port=587,
            username="fixture@example.com",
            app_password="fixture-only",
            from_name="Reminiscence",
        ),
    )


def activity_payload(
    metrics: tuple[ConversationMetric, ...],
) -> dict[str, list[dict[str, object]]]:
    return {
        "routine_executions": [],
        "conversation_sessions": [
            {
                "session_id": metric.session_id,
                "started_at": metric.started_at.isoformat(),
                "status": "COMPLETED",
                "summary": {
                    "user_turn_count": metric.user_turn_count,
                    "total_utterance_chars": metric.total_utterance_chars,
                    "average_utterance_chars": metric.average_utterance_chars,
                    "average_turn_duration_seconds": (
                        metric.average_turn_duration_seconds
                    ),
                    "no_response_count": metric.no_response_count,
                },
            }
            for metric in metrics
        ],
    }


def replay_service(
    metrics: tuple[ConversationMetric, ...],
) -> tuple[list[dict[str, object]], int]:
    evaluated_at = metrics[-1].started_at + timedelta(hours=1)
    with TemporaryDirectory(prefix="reminiscence-poster-") as temporary:
        root = Path(temporary)
        activity_path = root / "activity_metrics.json"
        activity_path.write_text(
            json.dumps(
                activity_payload(metrics),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        anomaly_service = AnomalyService(
            ActivityMetricReader(JsonObjectStore(activity_path)),
            PersonalStateStore(JsonObjectStore(root / "personal_state.json")),
        )
        sender = RecordingEmailSender()
        coordinator = NotificationCoordinator(
            anomaly_service,
            NotificationAttemptStore(
                JsonObjectStore(
                    root / "notification_state.json",
                    missing_default={"anomaly_notification_attempted": False},
                )
            ),
            notification_config,
            sender,
        )
        evaluations: list[dict[str, object]] = []
        for index in range(4):
            outcome = coordinator.evaluate_and_notify(
                evaluated_at + timedelta(seconds=60 * index)
            )
            evaluation = outcome.anomaly.evaluation
            candidate_status = (
                AnomalyStatus.ANOMALOUS
                if AnomalyStatus.ANOMALOUS
                in {
                    evaluation.routine.status,
                    evaluation.conversation.status,
                }
                else AnomalyStatus.NORMAL
            )
            evaluations.append(
                {
                    "evaluation": index + 1,
                    "candidate_status": candidate_status.value,
                    "stored_status": evaluation.status.value,
                    "consecutive_count": (
                        evaluation.consecutive_anomalous_evaluations
                    ),
                    "became_anomalous": outcome.anomaly.became_anomalous,
                    "notification_status": outcome.notification_status.value,
                }
            )

    assert [row["stored_status"] for row in evaluations] == [
        "NORMAL",
        "NORMAL",
        "ANOMALOUS",
        "ANOMALOUS",
    ]
    assert [row["consecutive_count"] for row in evaluations] == [1, 2, 3, 3]
    assert [row["notification_status"] for row in evaluations] == [
        NotificationDeliveryStatus.SKIPPED.value,
        NotificationDeliveryStatus.SKIPPED.value,
        NotificationDeliveryStatus.SENT.value,
        NotificationDeliveryStatus.SKIPPED.value,
    ]
    assert evaluations[2]["became_anomalous"] is True
    assert evaluations[3]["became_anomalous"] is False
    assert len(sender.sent) == 1
    return evaluations, len(sender.sent)


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
    evaluations, smtp_attempts = replay_service(metrics)

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

    RESULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RESULT_OUTPUT.write_text(
        json.dumps(
            {
                "fixture": {
                    "baseline_sessions": 20,
                    "current_session": 21,
                    "displayed_features": 3,
                    "model_features": 5,
                },
                "domain_result": {
                    "status": result.status.value,
                    "mode": result.mode.value,
                    "decision_function": result.score,
                    "reasons": list(result.reasons),
                },
                "service_replay": {
                    "interval_seconds": 60,
                    "confirmation_count": 3,
                    "evaluations": evaluations,
                    "smtp_attempts": smtp_attempts,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"status={result.status.value}")
    print(f"score={result.score:.6f}")
    for reason in result.reasons:
        print(f"reason={reason}")
    print(f"csv={CSV_OUTPUT}")
    print(f"result={RESULT_OUTPUT}")


if __name__ == "__main__":
    main()
