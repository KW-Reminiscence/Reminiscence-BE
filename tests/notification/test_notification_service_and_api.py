"""At-most-once notification episode and API behavior."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from reminiscence.anomaly.models import (
    AnomalyMode,
    AnomalyStatus,
    DomainEvaluation,
    PersonalEvaluation,
)
from reminiscence.anomaly.service import AnomalyEvaluationOutcome
from reminiscence.main import app
from reminiscence.notification.api import (
    get_current_time,
    get_notification_coordinator,
)
from reminiscence.notification.config import (
    CareRecipientConfig,
    GuardianConfig,
    NotificationConfig,
    NotificationConfigError,
    SmtpConfig,
)
from reminiscence.notification.service import (
    NotificationCoordinator,
    NotificationDeliveryStatus,
)
from reminiscence.notification.state import NotificationAttemptStore
from reminiscence.storage import JsonObjectStore

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 7, 27, 10, 0, tzinfo=SEOUL)


def evaluation(status: AnomalyStatus) -> PersonalEvaluation:
    routine = DomainEvaluation(
        status=status,
        mode=AnomalyMode.COLD_START,
        sample_count=3,
        score=None,
        reasons=(
            ("아침 약 루틴 3회 연속 미응답",)
            if status is AnomalyStatus.ANOMALOUS
            else ()
        ),
        feature_names=("not_answered_ratio",),
    )
    conversation = DomainEvaluation(
        status=AnomalyStatus.NORMAL,
        mode=AnomalyMode.INSUFFICIENT_DATA,
        sample_count=1,
        score=None,
        reasons=(),
        feature_names=("recent_7_day_user_turn_count",),
    )
    return PersonalEvaluation(
        evaluated_at=NOW,
        status=status,
        routine=routine,
        conversation=conversation,
    )


class FakeAnomalyService:
    def __init__(self, statuses: list[AnomalyStatus]) -> None:
        self._statuses = statuses

    def evaluate(self, evaluated_at: datetime) -> AnomalyEvaluationOutcome:
        del evaluated_at
        current = evaluation(self._statuses.pop(0))
        return AnomalyEvaluationOutcome(
            evaluation=current,
            became_anomalous=current.status is AnomalyStatus.ANOMALOUS,
        )


class FakeEmailSender:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[PersonalEvaluation] = []

    def send(
        self,
        config: NotificationConfig,
        current: PersonalEvaluation,
    ) -> None:
        del config
        self.sent.append(current)
        if self.fail:
            from reminiscence.notification.email_sender import GuardianEmailError

            raise GuardianEmailError("failed")


def config() -> NotificationConfig:
    return NotificationConfig(
        care_recipient=CareRecipientConfig(name="홍길동"),
        guardian=GuardianConfig(email="guardian@example.com"),
        smtp=SmtpConfig(
            host="smtp.gmail.com",
            port=587,
            username="sender@gmail.com",
            app_password="secret",
            from_name="Reminiscence",
        ),
    )


def coordinator(
    tmp_path: Path,
    statuses: list[AnomalyStatus],
    sender: FakeEmailSender,
) -> NotificationCoordinator:
    return NotificationCoordinator(
        FakeAnomalyService(statuses),
        NotificationAttemptStore(
            JsonObjectStore(
                tmp_path / "notification_state.json",
                missing_default={"anomaly_notification_attempted": False},
            )
        ),
        config,
        sender,
    )


def test_only_one_email_is_sent_during_active_anomaly(tmp_path: Path) -> None:
    sender = FakeEmailSender()
    service = coordinator(
        tmp_path,
        [AnomalyStatus.ANOMALOUS, AnomalyStatus.ANOMALOUS],
        sender,
    )

    first = service.evaluate_and_notify(NOW)
    second = service.evaluate_and_notify(NOW)

    assert first.notification_status is NotificationDeliveryStatus.SENT
    assert second.notification_status is NotificationDeliveryStatus.SKIPPED
    assert len(sender.sent) == 1


def test_normal_state_resets_marker_for_next_anomaly(tmp_path: Path) -> None:
    sender = FakeEmailSender()
    service = coordinator(
        tmp_path,
        [
            AnomalyStatus.ANOMALOUS,
            AnomalyStatus.NORMAL,
            AnomalyStatus.ANOMALOUS,
        ],
        sender,
    )

    service.evaluate_and_notify(NOW)
    normal = service.evaluate_and_notify(NOW)
    next_episode = service.evaluate_and_notify(NOW)

    assert normal.notification_status is NotificationDeliveryStatus.SKIPPED
    assert next_episode.notification_status is NotificationDeliveryStatus.SENT
    assert len(sender.sent) == 2


def test_failed_delivery_is_not_retried_in_same_episode(tmp_path: Path) -> None:
    from reminiscence.notification.email_sender import GuardianEmailError

    sender = FakeEmailSender(fail=True)
    service = coordinator(
        tmp_path,
        [AnomalyStatus.ANOMALOUS, AnomalyStatus.ANOMALOUS],
        sender,
    )

    try:
        service.evaluate_and_notify(NOW)
    except GuardianEmailError:
        pass
    else:
        raise AssertionError("expected delivery failure")
    second = service.evaluate_and_notify(NOW)

    assert second.notification_status is NotificationDeliveryStatus.SKIPPED
    assert len(sender.sent) == 1


def test_concurrent_coordinators_claim_one_delivery_attempt(
    tmp_path: Path,
) -> None:
    barrier = threading.Barrier(2)

    class BarrierAnomalyService:
        def evaluate(self, evaluated_at: datetime) -> AnomalyEvaluationOutcome:
            del evaluated_at
            barrier.wait(timeout=1)
            current = evaluation(AnomalyStatus.ANOMALOUS)
            return AnomalyEvaluationOutcome(
                evaluation=current,
                became_anomalous=True,
            )

    sender = FakeEmailSender()
    state_path = tmp_path / "notification_state.json"
    coordinators = [
        NotificationCoordinator(
            BarrierAnomalyService(),
            NotificationAttemptStore(
                JsonObjectStore(
                    state_path,
                    missing_default={"anomaly_notification_attempted": False},
                )
            ),
            config,
            sender,
        )
        for _ in range(2)
    ]
    outcomes = []

    def evaluate(coordinator: NotificationCoordinator) -> None:
        outcomes.append(coordinator.evaluate_and_notify(NOW))

    threads = [
        threading.Thread(target=evaluate, args=(coordinator,))
        for coordinator in coordinators
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1)

    assert sorted(outcome.notification_status for outcome in outcomes) == [
        NotificationDeliveryStatus.SENT,
        NotificationDeliveryStatus.SKIPPED,
    ]
    assert len(sender.sent) == 1


def test_invalid_configuration_does_not_consume_delivery_attempt(
    tmp_path: Path,
) -> None:
    state_store = NotificationAttemptStore(
        JsonObjectStore(
            tmp_path / "notification_state.json",
            missing_default={"anomaly_notification_attempted": False},
        )
    )
    sender = FakeEmailSender()

    def invalid_config() -> NotificationConfig:
        raise NotificationConfigError("invalid")

    invalid = NotificationCoordinator(
        FakeAnomalyService([AnomalyStatus.ANOMALOUS]),
        state_store,
        invalid_config,
        sender,
    )
    try:
        invalid.evaluate_and_notify(NOW)
    except NotificationConfigError:
        pass
    else:
        raise AssertionError("expected invalid configuration")

    valid = NotificationCoordinator(
        FakeAnomalyService([AnomalyStatus.ANOMALOUS]),
        state_store,
        config,
        sender,
    )
    outcome = valid.evaluate_and_notify(NOW)

    assert outcome.notification_status is NotificationDeliveryStatus.SENT
    assert len(sender.sent) == 1


def test_api_returns_delivery_result_and_detector_reason(
    tmp_path: Path,
) -> None:
    sender = FakeEmailSender()
    service = coordinator(
        tmp_path,
        [AnomalyStatus.ANOMALOUS],
        sender,
    )
    app.dependency_overrides[get_notification_coordinator] = lambda: service
    app.dependency_overrides[get_current_time] = lambda: NOW

    response = TestClient(app).post("/api/v1/notifications/evaluate")

    assert response.status_code == 200
    assert response.json()["notification_status"] == "SENT"
    assert response.json()["reasons"] == ["아침 약 루틴 3회 연속 미응답"]


def test_notification_endpoint_is_documented() -> None:
    assert "/api/v1/notifications/evaluate" in app.openapi()["paths"]


def teardown_function() -> None:
    app.dependency_overrides.clear()
