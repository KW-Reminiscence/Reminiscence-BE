"""End-to-end backend domain flow over the Raspberry Pi JSON files."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from reminiscence.anomaly.models import AnomalyStatus, PersonalEvaluation
from reminiscence.anomaly.service import AnomalyService
from reminiscence.anomaly.storage import ActivityMetricReader, PersonalStateStore
from reminiscence.asr import RecognitionResult
from reminiscence.conversation import (
    ConversationService,
    ConversationSource,
    JsonConversationStore,
)
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
from reminiscence.routine import RoutineState
from reminiscence.routine.scheduler import RoutineScheduler
from reminiscence.routine.storage import JsonRoutineStore
from reminiscence.storage import JsonObjectStore

SEOUL = ZoneInfo("Asia/Seoul")


class RecordingEmailSender:
    """Capture generated notification inputs without an SMTP connection."""

    def __init__(self) -> None:
        self.sent: list[PersonalEvaluation] = []

    def send(
        self,
        config: NotificationConfig,
        current: PersonalEvaluation,
    ) -> None:
        assert config.guardian.email == "guardian@example.com"
        self.sent.append(current)


def notification_config() -> NotificationConfig:
    return NotificationConfig(
        care_recipient=CareRecipientConfig(name="홍길동"),
        guardian=GuardianConfig(email="guardian@example.com"),
        smtp=SmtpConfig(
            host="smtp.gmail.com",
            port=587,
            username="sender@gmail.com",
            app_password="app-password",
            from_name="Reminiscence",
        ),
    )


def test_missed_routines_trigger_one_notification_without_losing_conversation(
    tmp_path: Path,
) -> None:
    configuration_path = tmp_path / "configuration.json"
    activity_path = tmp_path / "activity_metrics.json"
    configuration_path.write_text(
        json.dumps(
            {
                "routines": [
                    {
                        "id": "morning-medication",
                        "name": "아침 약",
                        "category": "MEDICATION",
                        "weekdays": list(range(7)),
                        "scheduled_time": "09:00",
                        "grace_minutes": 10,
                        "reminder_interval_minutes": 10,
                        "max_reminders": 3,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    routine_scheduler = RoutineScheduler(
        JsonRoutineStore(configuration_path, activity_path),
        SEOUL,
    )
    conversation_service = ConversationService(
        JsonConversationStore(
            JsonObjectStore(activity_path, missing_default={})
        ),
        id_factory=iter(["session-1", "turn-1"]).__next__,
    )

    session = conversation_service.start_session(
        ConversationSource.VOLUNTARY,
        None,
        datetime(2026, 7, 27, 14, 0, tzinfo=SEOUL),
    )
    conversation_service.record_turn(
        session.session_id,
        RecognitionResult(
            transcript="가족과 함께한 비밀 이야기",
            latency_seconds=0.2,
            attempts=1,
            http_status=200,
        ),
        4.0,
        datetime(2026, 7, 27, 14, 1, tzinfo=SEOUL),
    )
    conversation_service.complete_session(
        session.session_id,
        datetime(2026, 7, 27, 14, 2, tzinfo=SEOUL),
    )
    for day in (27, 28, 29):
        routine_scheduler.tick(
            datetime(2026, 7, day, 10, 0, tzinfo=SEOUL)
        )

    anomaly_service = AnomalyService(
        ActivityMetricReader(JsonObjectStore(activity_path)),
        PersonalStateStore(JsonObjectStore(tmp_path / "personal_state.json")),
    )
    sender = RecordingEmailSender()
    coordinator = NotificationCoordinator(
        anomaly_service,
        NotificationAttemptStore(
            JsonObjectStore(
                tmp_path / "notification_state.json",
                missing_default={"anomaly_notification_attempted": False},
            )
        ),
        notification_config,
        sender,
    )
    evaluated_at = datetime(2026, 7, 29, 18, 0, tzinfo=SEOUL)

    pending_one = coordinator.evaluate_and_notify(evaluated_at)
    pending_two = coordinator.evaluate_and_notify(evaluated_at)
    first = coordinator.evaluate_and_notify(evaluated_at)
    second = coordinator.evaluate_and_notify(evaluated_at)
    persisted = activity_path.read_text(encoding="utf-8")
    activity = json.loads(persisted)

    assert pending_one.anomaly.evaluation.status is AnomalyStatus.NORMAL
    assert pending_one.notification_status is NotificationDeliveryStatus.SKIPPED
    assert pending_two.anomaly.evaluation.status is AnomalyStatus.NORMAL
    assert pending_two.notification_status is NotificationDeliveryStatus.SKIPPED
    assert first.anomaly.evaluation.status is AnomalyStatus.ANOMALOUS
    assert first.notification_status is NotificationDeliveryStatus.SENT
    assert second.notification_status is NotificationDeliveryStatus.SKIPPED
    assert len(sender.sent) == 1
    assert all(
        execution.state is RoutineState.NOT_ANSWERED
        for execution in routine_scheduler.list_executions()
    )
    assert len(activity["routine_executions"]) == 3
    assert len(activity["conversation_sessions"]) == 1
    assert "가족과 함께한 비밀 이야기" not in persisted
    assert "transcript" not in persisted
