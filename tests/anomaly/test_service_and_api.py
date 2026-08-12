"""Observation persistence, fixed baseline, service and anomaly API tests."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from reminiscence.anomaly.api import get_anomaly_service, get_current_time
from reminiscence.anomaly.service import AnomalyService
from reminiscence.anomaly.storage import (
    ActivityObservationStore,
    AnomalyStorageError,
    BaselineStore,
    PersonalStateStore,
)
from reminiscence.main import app
from reminiscence.storage import JsonObjectStore
from reminiscence.storage.migration import migrate_data_directory

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 7, 27, 18, 0, tzinfo=SEOUL)


def build_service(
    tmp_path: Path,
    *,
    configuration: dict[str, object] | None = None,
) -> tuple[AnomalyService, Path, Path, Path]:
    activity_path = tmp_path / "activity_metrics.json"
    baseline_path = tmp_path / "anomaly_baseline.json"
    state_path = tmp_path / "personal_state.json"
    configuration_store = None
    if configuration is not None:
        configuration_path = tmp_path / "configuration.json"
        configuration_path.write_text(json.dumps(configuration), encoding="utf-8")
        configuration_store = JsonObjectStore(configuration_path, read_only=True)
    return (
        AnomalyService(
            ActivityObservationStore(
                JsonObjectStore(activity_path),
                configuration_store,
            ),
            BaselineStore(JsonObjectStore(baseline_path)),
            PersonalStateStore(JsonObjectStore(state_path)),
        ),
        activity_path,
        baseline_path,
        state_path,
    )


def routine_execution(
    days_ago: int,
    state: str,
    *,
    routine_id: str = "medication",
    category: str = "MEDICATION",
) -> dict[str, object]:
    scheduled_at = NOW - timedelta(days=days_ago, hours=9)
    confirmed = state == "CONFIRMED"
    delay = 300 if confirmed else None
    return {
        "execution_id": f"{routine_id}:{scheduled_at.date().isoformat()}",
        "routine_id": routine_id,
        "scheduled_at": scheduled_at.isoformat(),
        "state": state,
        "reminder_count": 0,
        "last_prompted_at": scheduled_at.isoformat(),
        "routine_name": routine_id,
        "category": category,
        "policy": None,
        "confirmed_at": (
            (scheduled_at + timedelta(seconds=delay)).isoformat()
            if delay is not None
            else None
        ),
        "confirmation_delay_seconds": delay,
        "closed_at": (
            (scheduled_at + timedelta(seconds=delay or 0)).isoformat()
            if state != "REMINDING"
            else None
        ),
    }


def completed_session(index: int, *, turns: int = 5) -> dict[str, object]:
    started_at = NOW - timedelta(days=30 - index)
    completed_at = started_at + timedelta(minutes=10)
    return {
        "session_id": f"session-{index}",
        "source": "VOLUNTARY",
        "photo_id": None,
        "started_at": started_at.isoformat(),
        "status": "COMPLETED",
        "completed_at": completed_at.isoformat(),
        "turns": [],
        "summary": {
            "user_turn_count": turns,
            "total_utterance_chars": turns * 20,
            "average_utterance_chars": 20.0 if turns else None,
            "average_turn_duration_seconds": 8.0 if turns else None,
            "no_response_count": 0,
        },
    }


def write_activity(path: Path, **sections: object) -> None:
    path.write_text(json.dumps(sections), encoding="utf-8")


def test_evaluate_persists_cold_start_consensus_once_per_observation(
    tmp_path: Path,
) -> None:
    service, activity_path, _, state_path = build_service(tmp_path)
    write_activity(
        activity_path,
        routine_executions=[
            routine_execution(day, "NOT_ANSWERED") for day in (3, 2, 1)
        ],
        conversation_sessions=[],
    )

    first = service.evaluate(NOW)
    second = service.evaluate(NOW + timedelta(minutes=1))
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    activity = json.loads(activity_path.read_text(encoding="utf-8"))

    assert first.evaluation.status.value == "ANOMALOUS"
    assert first.became_anomalous is True
    assert second.evaluation.status.value == "ANOMALOUS"
    assert second.became_anomalous is False
    assert second.evaluation.routine.signal_count == 2
    assert persisted["consecutive_anomalous_evaluations"] == 1
    assert len(activity["routine_observations"]) == 3


def test_confirmation_resets_same_routine_miss_streak(tmp_path: Path) -> None:
    service, activity_path, _, _ = build_service(tmp_path)
    write_activity(
        activity_path,
        routine_executions=[
            routine_execution(4, "NOT_ANSWERED"),
            routine_execution(3, "NOT_ANSWERED"),
            routine_execution(2, "CONFIRMED"),
            routine_execution(1, "NOT_ANSWERED"),
        ],
        conversation_sessions=[],
    )

    result = service.evaluate(NOW).evaluation.routine

    assert result.rule_based_signal is True
    assert result.persistence_signal is False
    assert result.status.value == "NORMAL"


def test_confirmation_clears_previous_three_miss_feature(tmp_path: Path) -> None:
    service, activity_path, _, _ = build_service(tmp_path)
    write_activity(
        activity_path,
        routine_executions=[
            routine_execution(4, "NOT_ANSWERED"),
            routine_execution(3, "NOT_ANSWERED"),
            routine_execution(2, "NOT_ANSWERED"),
            routine_execution(1, "CONFIRMED"),
        ],
        conversation_sessions=[],
    )

    service.evaluate(NOW)
    service.evaluate(NOW + timedelta(days=1))
    activity = json.loads(activity_path.read_text(encoding="utf-8"))

    assert [item["values"][5] for item in activity["routine_observations"]] == [
        1.0,
        2.0,
        3.0,
        0.0,
    ]
    assert service.current_state().routine.persistence_signal is False  # type: ignore[union-attr]


def test_routine_day_waits_for_every_configured_execution(tmp_path: Path) -> None:
    configuration = {
        "routines": [
            {
                "id": routine_id,
                "category": category,
                "weekdays": list(range(7)),
            }
            for routine_id, category in (
                ("meal", "MEAL"),
                ("medication", "MEDICATION"),
            )
        ]
    }
    service, activity_path, _, _ = build_service(
        tmp_path,
        configuration=configuration,
    )
    write_activity(
        activity_path,
        routine_executions=[routine_execution(1, "CONFIRMED")],
        conversation_sessions=[],
    )

    outcome = service.evaluate(NOW)

    assert outcome.evaluation.routine.sample_count == 0


def test_incomplete_current_date_is_excluded(tmp_path: Path) -> None:
    service, activity_path, _, _ = build_service(tmp_path)
    current = routine_execution(0, "NOT_ANSWERED")
    current["scheduled_at"] = (NOW - timedelta(hours=1)).isoformat()
    write_activity(
        activity_path,
        routine_executions=[current],
        conversation_sessions=[],
    )

    outcome = service.evaluate(NOW)

    assert outcome.evaluation.routine.sample_count == 0


def test_daily_observation_uses_evaluation_timezone_at_midnight_boundary(
    tmp_path: Path,
) -> None:
    service, activity_path, _, _ = build_service(tmp_path)
    execution = routine_execution(1, "CONFIRMED")
    execution["scheduled_at"] = "2026-07-27T15:30:00+00:00"
    execution["last_prompted_at"] = "2026-07-27T15:30:00+00:00"
    execution["confirmed_at"] = "2026-07-27T15:35:00+00:00"
    execution["closed_at"] = "2026-07-27T15:35:00+00:00"
    write_activity(
        activity_path,
        routine_executions=[execution],
        conversation_sessions=[],
    )

    service.evaluate(datetime(2026, 7, 29, 1, 0, tzinfo=SEOUL))
    activity = json.loads(activity_path.read_text(encoding="utf-8"))

    assert activity["routine_observations"][0]["target_date"] == "2026-07-28"


def test_first_28_routine_vectors_are_fixed_after_more_data(tmp_path: Path) -> None:
    service, activity_path, baseline_path, _ = build_service(tmp_path)
    executions = [routine_execution(day, "CONFIRMED") for day in range(29, 0, -1)]
    write_activity(
        activity_path,
        routine_executions=executions,
        conversation_sessions=[],
    )
    service.evaluate(NOW)
    initial = json.loads(baseline_path.read_text(encoding="utf-8"))[
        "routine_vectors"
    ]
    activity = json.loads(activity_path.read_text(encoding="utf-8"))
    future = routine_execution(0, "NOT_ANSWERED", routine_id="meal", category="MEAL")
    scheduled = NOW + timedelta(days=1, hours=-9)
    future["execution_id"] = f"meal:{scheduled.date().isoformat()}"
    future["scheduled_at"] = scheduled.isoformat()
    future["last_prompted_at"] = scheduled.isoformat()
    future["closed_at"] = scheduled.isoformat()
    activity["routine_executions"].append(future)
    activity_path.write_text(json.dumps(activity), encoding="utf-8")

    service.evaluate(NOW + timedelta(days=2))

    assert json.loads(baseline_path.read_text(encoding="utf-8"))[
        "routine_vectors"
    ] == initial


def test_completed_sessions_create_quality_and_zero_participation_days(
    tmp_path: Path,
) -> None:
    service, activity_path, baseline_path, _ = build_service(tmp_path)
    sessions = [completed_session(index) for index in range(20)]
    write_activity(
        activity_path,
        routine_executions=[],
        conversation_sessions=sessions,
    )

    service.evaluate(NOW)
    activity = json.loads(activity_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    assert len(activity["conversation_quality_observations"]) == 20
    assert len(activity["participation_observations"]) == 30
    assert activity["participation_observations"][-1][
        "recent_7_day_user_turn_count"
    ] == 0
    assert len(baseline["conversation_quality_vectors"]) == 20
    assert baseline["participation_weekly_turn_mean"] >= 0


def test_no_conversation_days_begin_at_first_evaluation(tmp_path: Path) -> None:
    service, activity_path, _, _ = build_service(tmp_path)
    write_activity(
        activity_path,
        routine_executions=[],
        conversation_sessions=[],
    )

    service.evaluate(NOW)
    service.evaluate(NOW + timedelta(days=1))
    activity = json.loads(activity_path.read_text(encoding="utf-8"))

    assert activity["anomaly_observation_started_on"] == NOW.date().isoformat()
    assert activity["participation_observations"] == [
        {
            "target_date": NOW.date().isoformat(),
            "recent_7_day_user_turn_count": 0,
        }
    ]


def test_quality_baseline_uses_completion_order_not_session_id(tmp_path: Path) -> None:
    service, activity_path, baseline_path, _ = build_service(tmp_path)
    sessions = [completed_session(index) for index in range(21)]
    sessions[9] = completed_session(9, turns=9)
    sessions[9]["session_id"] = "session-z"
    sessions[20] = completed_session(20, turns=1)
    sessions[20]["session_id"] = "session-a"
    write_activity(
        activity_path,
        routine_executions=[],
        conversation_sessions=sessions,
    )

    service.evaluate(NOW)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    assert len(baseline["conversation_quality_vectors"]) == 20
    assert any(vector[0] == 9.0 for vector in baseline["conversation_quality_vectors"])
    assert not any(
        vector[0] == 1.0 for vector in baseline["conversation_quality_vectors"]
    )
    activity = json.loads(activity_path.read_text(encoding="utf-8"))
    ordered_ids = [
        item["session_id"]
        for item in activity["conversation_quality_observations"]
    ]
    assert ordered_ids[9] == "session-z"
    assert ordered_ids[-1] == "session-a"


def test_repeated_evaluation_does_not_duplicate_observation_keys(tmp_path: Path) -> None:
    service, activity_path, _, _ = build_service(tmp_path)
    write_activity(
        activity_path,
        routine_executions=[routine_execution(1, "CONFIRMED")],
        conversation_sessions=[],
    )

    service.evaluate(NOW)
    first = json.loads(activity_path.read_text(encoding="utf-8"))
    service.evaluate(NOW + timedelta(minutes=1))
    second = json.loads(activity_path.read_text(encoding="utf-8"))

    assert first["routine_observations"] == second["routine_observations"]
    assert first["participation_observations"] == second["participation_observations"]


def test_participation_does_not_freeze_incomplete_current_date(tmp_path: Path) -> None:
    service, activity_path, _, _ = build_service(tmp_path)
    write_activity(
        activity_path,
        routine_executions=[routine_execution(1, "CONFIRMED")],
        conversation_sessions=[],
    )
    service.evaluate(NOW)
    first = json.loads(activity_path.read_text(encoding="utf-8"))
    assert first["participation_observations"][-1]["target_date"] == (
        NOW.date() - timedelta(days=1)
    ).isoformat()

    first["conversation_sessions"].append(completed_session(30, turns=5))
    activity_path.write_text(json.dumps(first), encoding="utf-8")

    service.evaluate(NOW + timedelta(days=1))
    updated = json.loads(activity_path.read_text(encoding="utf-8"))
    assert updated["participation_observations"][-1]["target_date"] == NOW.date().isoformat()
    assert updated["participation_observations"][-1][
        "recent_7_day_user_turn_count"
    ] == 5


def test_active_session_does_not_block_later_zero_participation_days(
    tmp_path: Path,
) -> None:
    service, activity_path, _, _ = build_service(tmp_path)
    started_at = NOW - timedelta(days=1, hours=-5)
    active = {
        "session_id": "overnight",
        "source": "VOLUNTARY",
        "photo_id": None,
        "started_at": started_at.isoformat(),
        "status": "ACTIVE",
        "completed_at": None,
        "turns": [],
    }
    write_activity(
        activity_path,
        routine_executions=[],
        conversation_sessions=[active],
    )

    service.evaluate(NOW)
    service.evaluate(NOW + timedelta(days=1))
    activity = json.loads(activity_path.read_text(encoding="utf-8"))
    assert activity["participation_observations"] == [
        {
            "target_date": (NOW.date() - timedelta(days=1)).isoformat(),
            "recent_7_day_user_turn_count": 0,
        },
        {
            "target_date": NOW.date().isoformat(),
            "recent_7_day_user_turn_count": 0,
        }
    ]


def test_overnight_session_is_counted_on_completion_date(tmp_path: Path) -> None:
    service, activity_path, _, _ = build_service(tmp_path)
    seed = routine_execution(2, "CONFIRMED")
    overnight = completed_session(29, turns=5)
    overnight["started_at"] = (NOW - timedelta(days=1, hours=-5)).isoformat()
    overnight["completed_at"] = (NOW + timedelta(hours=1)).isoformat()
    write_activity(
        activity_path,
        routine_executions=[seed],
        conversation_sessions=[overnight],
    )

    service.evaluate(NOW + timedelta(days=1))
    activity = json.loads(activity_path.read_text(encoding="utf-8"))

    by_date = {
        item["target_date"]: item["recent_7_day_user_turn_count"]
        for item in activity["participation_observations"]
    }
    assert by_date[(NOW.date() - timedelta(days=1)).isoformat()] == 0
    assert by_date[NOW.date().isoformat()] == 5


def test_date_reversal_is_rejected(tmp_path: Path) -> None:
    service, activity_path, _, _ = build_service(tmp_path)
    write_activity(
        activity_path,
        routine_executions=[routine_execution(1, "CONFIRMED")],
        conversation_sessions=[],
    )
    service.evaluate(NOW)

    with pytest.raises(ValueError, match="backwards"):
        service.evaluate(NOW - timedelta(days=1))


def test_malformed_activity_metrics_are_rejected(tmp_path: Path) -> None:
    service, activity_path, _, _ = build_service(tmp_path)
    write_activity(activity_path, routine_executions={}, conversation_sessions=[])

    with pytest.raises(AnomalyStorageError, match="routine_executions"):
        service.evaluate(NOW)


def test_concurrent_evaluations_are_serialized() -> None:
    class EmptyObservationStore:
        active = 0
        maximum = 0
        lock = threading.Lock()

        def materialize(self, evaluated_at: datetime):  # type: ignore[no-untyped-def]
            from reminiscence.anomaly.models import AnomalyObservations

            del evaluated_at
            with self.lock:
                self.active += 1
                self.maximum = max(self.maximum, self.active)
            time.sleep(0.02)
            with self.lock:
                self.active -= 1
            return AnomalyObservations((), (), ())

    class EmptyBaselineStore:
        def load_or_initialize(self, observations):  # type: ignore[no-untyped-def]
            from reminiscence.anomaly.models import BaselineState

            del observations
            return BaselineState()

    class MemoryStateStore:
        value = None

        def load(self):  # type: ignore[no-untyped-def]
            return self.value

        def save(self, value):  # type: ignore[no-untyped-def]
            self.value = value

    observations = EmptyObservationStore()
    service = AnomalyService(
        observations,  # type: ignore[arg-type]
        EmptyBaselineStore(),  # type: ignore[arg-type]
        MemoryStateStore(),  # type: ignore[arg-type]
    )
    errors: list[BaseException] = []

    def evaluate() -> None:
        try:
            service.evaluate(NOW)
        except BaseException as exc:  # pragma: no cover - assertion aid
            errors.append(exc)

    threads = [threading.Thread(target=evaluate) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1)

    assert errors == []
    assert observations.maximum == 1


def test_api_evaluates_and_reads_current_state(tmp_path: Path) -> None:
    service, activity_path, _, _ = build_service(tmp_path)
    write_activity(
        activity_path,
        routine_executions=[
            routine_execution(day, "NOT_ANSWERED") for day in (3, 2, 1)
        ],
        conversation_sessions=[],
    )
    app.dependency_overrides[get_anomaly_service] = lambda: service
    app.dependency_overrides[get_current_time] = lambda: NOW
    client = TestClient(app)

    evaluated = client.post("/api/v1/anomaly/evaluate")
    current = client.get("/api/v1/anomaly/state")

    assert evaluated.status_code == 200
    assert evaluated.json()["became_anomalous"] is True
    assert evaluated.json()["routine"]["signal_count"] == 2
    assert current.status_code == 200
    assert current.json()["became_anomalous"] is False


def test_state_is_not_found_before_first_evaluation(tmp_path: Path) -> None:
    service, _, _, _ = build_service(tmp_path)
    app.dependency_overrides[get_anomaly_service] = lambda: service

    assert TestClient(app).get("/api/v1/anomaly/state").status_code == 404


def test_migrated_empty_personal_state_is_not_an_evaluation(tmp_path: Path) -> None:
    migrate_data_directory(tmp_path, apply=True)
    store = PersonalStateStore(
        JsonObjectStore(tmp_path / "personal_state.json", schema_version=1)
    )

    assert store.load() is None


def test_anomaly_endpoints_are_documented() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/anomaly/evaluate" in paths
    assert "/api/v1/anomaly/state" in paths


def teardown_function() -> None:
    app.dependency_overrides.clear()
