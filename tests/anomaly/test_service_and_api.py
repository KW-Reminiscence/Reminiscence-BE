"""Activity parsing, state persistence, and anomaly API tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from reminiscence.anomaly.api import get_anomaly_service, get_current_time
from reminiscence.anomaly.service import AnomalyService
from reminiscence.anomaly.storage import ActivityMetricReader, PersonalStateStore
from reminiscence.main import app
from reminiscence.storage import JsonObjectStore

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 7, 27, 18, 0, tzinfo=SEOUL)


def build_service(
    tmp_path: Path,
    *,
    confirmation_count: int = 3,
) -> tuple[AnomalyService, Path, Path]:
    activity_path = tmp_path / "activity_metrics.json"
    state_path = tmp_path / "personal_state.json"
    return (
        AnomalyService(
            ActivityMetricReader(JsonObjectStore(activity_path)),
            PersonalStateStore(JsonObjectStore(state_path)),
            confirmation_count=confirmation_count,
        ),
        activity_path,
        state_path,
    )


def routine_execution(day: int, state: str) -> dict[str, object]:
    scheduled_at = NOW - timedelta(days=3 - day, hours=9)
    return {
        "execution_id": f"medication:{scheduled_at.date().isoformat()}",
        "routine_id": "medication",
        "scheduled_at": scheduled_at.isoformat(),
        "state": state,
        "reminder_count": 3 if state == "NOT_ANSWERED" else 0,
        "last_prompted_at": scheduled_at.isoformat(),
        "confirmed_at": None,
        "confirmation_delay_seconds": None,
        "closed_at": scheduled_at.isoformat(),
    }


def test_evaluate_persists_explainable_cold_start_anomaly(tmp_path: Path) -> None:
    service, activity_path, state_path = build_service(tmp_path)
    activity_path.write_text(
        json.dumps(
            {
                "routine_executions": [
                    routine_execution(day, "NOT_ANSWERED")
                    for day in range(3)
                ]
            }
        ),
        encoding="utf-8",
    )

    first = service.evaluate(NOW)
    second = service.evaluate(NOW + timedelta(minutes=1))
    third = service.evaluate(NOW + timedelta(minutes=2))
    fourth = service.evaluate(NOW + timedelta(minutes=3))
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert first.evaluation.status.value == "NORMAL"
    assert first.evaluation.consecutive_anomalous_evaluations == 1
    assert first.became_anomalous is False
    assert second.evaluation.status.value == "NORMAL"
    assert second.became_anomalous is False
    assert third.evaluation.status.value == "ANOMALOUS"
    assert third.became_anomalous is True
    assert fourth.evaluation.status.value == "ANOMALOUS"
    assert fourth.became_anomalous is False
    assert persisted["consecutive_anomalous_evaluations"] == 3
    assert persisted["routine"]["mode"] == "COLD_START"
    assert persisted["routine"]["reasons"] == [
        "medication 루틴 3회 연속 미응답"
    ]
    assert persisted["model_metadata"]["routine_baseline_days"] == 28


def test_future_metrics_and_active_conversations_are_ignored(
    tmp_path: Path,
) -> None:
    service, activity_path, _ = build_service(tmp_path)
    future = routine_execution(3, "NOT_ANSWERED")
    future["scheduled_at"] = (NOW + timedelta(days=1)).isoformat()
    activity_path.write_text(
        json.dumps(
            {
                "routine_executions": [future],
                "conversation_sessions": [
                    {
                        "session_id": "active",
                        "status": "ACTIVE",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    outcome = service.evaluate(NOW)

    assert outcome.evaluation.routine.sample_count == 0
    assert outcome.evaluation.conversation.sample_count == 0
    assert outcome.evaluation.status.value == "NORMAL"


def test_active_routine_is_ignored_after_model_baseline(tmp_path: Path) -> None:
    service, activity_path, _ = build_service(tmp_path)
    baseline = []
    for day in range(28):
        execution = routine_execution(day, "CONFIRMED")
        execution["scheduled_at"] = (
            NOW - timedelta(days=28 - day)
        ).isoformat()
        execution["confirmation_delay_seconds"] = 300
        baseline.append(execution)
    active = routine_execution(3, "REMINDING")
    active["scheduled_at"] = NOW.isoformat()
    activity_path.write_text(
        json.dumps({"routine_executions": [*baseline, active]}),
        encoding="utf-8",
    )

    outcome = service.evaluate(NOW)

    assert outcome.evaluation.routine.sample_count == 28
    assert outcome.evaluation.routine.status.value == "NORMAL"
    assert outcome.evaluation.status.value == "NORMAL"


def test_normal_candidate_resets_persisted_confirmation_count(
    tmp_path: Path,
) -> None:
    service, activity_path, state_path = build_service(tmp_path)
    activity_path.write_text(
        json.dumps(
            {
                "routine_executions": [
                    routine_execution(day, "NOT_ANSWERED")
                    for day in range(3)
                ]
            }
        ),
        encoding="utf-8",
    )
    service.evaluate(NOW)
    restarted = AnomalyService(
        ActivityMetricReader(JsonObjectStore(activity_path)),
        PersonalStateStore(JsonObjectStore(state_path)),
    )
    restarted.evaluate(NOW + timedelta(minutes=1))
    activity_path.write_text(
        json.dumps({"routine_executions": []}),
        encoding="utf-8",
    )

    normal = restarted.evaluate(NOW + timedelta(minutes=2))

    assert normal.evaluation.status.value == "NORMAL"
    assert normal.evaluation.consecutive_anomalous_evaluations == 0
    assert json.loads(state_path.read_text(encoding="utf-8"))[
        "consecutive_anomalous_evaluations"
    ] == 0


def test_malformed_activity_metrics_are_rejected(tmp_path: Path) -> None:
    service, activity_path, _ = build_service(tmp_path)
    activity_path.write_text(
        json.dumps({"routine_executions": {}}),
        encoding="utf-8",
    )

    try:
        service.evaluate(NOW)
    except RuntimeError as exc:
        assert "routine_executions" in str(exc)
    else:
        raise AssertionError("expected malformed activity metrics to fail")


def test_semantically_invalid_activity_metric_is_rejected(
    tmp_path: Path,
) -> None:
    service, activity_path, _ = build_service(tmp_path)
    invalid = routine_execution(0, "CONFIRMED")
    invalid["confirmation_delay_seconds"] = None
    activity_path.write_text(
        json.dumps({"routine_executions": [invalid]}),
        encoding="utf-8",
    )

    try:
        service.evaluate(NOW)
    except RuntimeError as exc:
        assert "confirmation_delay_seconds" in str(exc)
    else:
        raise AssertionError("expected invalid routine metric to fail")


def test_api_evaluates_and_reads_current_state(tmp_path: Path) -> None:
    service, activity_path, _ = build_service(tmp_path)
    activity_path.write_text(
        json.dumps(
            {
                "routine_executions": [
                    routine_execution(day, "NOT_ANSWERED")
                    for day in range(3)
                ]
            }
        ),
        encoding="utf-8",
    )
    app.dependency_overrides[get_anomaly_service] = lambda: service
    app.dependency_overrides[get_current_time] = lambda: NOW
    client = TestClient(app)

    pending_one = client.post("/api/v1/anomaly/evaluate")
    pending_two = client.post("/api/v1/anomaly/evaluate")
    evaluated = client.post("/api/v1/anomaly/evaluate")
    current = client.get("/api/v1/anomaly/state")

    assert pending_one.json()["status"] == "NORMAL"
    assert pending_one.json()["consecutive_anomalous_evaluations"] == 1
    assert pending_two.json()["status"] == "NORMAL"
    assert evaluated.status_code == 200
    assert evaluated.json()["became_anomalous"] is True
    assert evaluated.json()["consecutive_anomalous_evaluations"] == 3
    assert evaluated.json()["routine"]["reasons"]
    assert current.status_code == 200
    assert current.json()["became_anomalous"] is False


def test_state_is_not_found_before_first_evaluation(tmp_path: Path) -> None:
    service, _, _ = build_service(tmp_path)
    app.dependency_overrides[get_anomaly_service] = lambda: service

    response = TestClient(app).get("/api/v1/anomaly/state")

    assert response.status_code == 404


def test_anomaly_endpoints_are_documented() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/anomaly/evaluate" in paths
    assert "/api/v1/anomaly/state" in paths


def teardown_function() -> None:
    app.dependency_overrides.clear()
