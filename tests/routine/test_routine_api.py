"""Tablet-facing API contract for routine prompts and confirmations."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from reminiscence.main import app
from reminiscence.routine.api import get_current_time, get_routine_scheduler
from reminiscence.routine.scheduler import RoutineScheduler
from reminiscence.routine.storage import JsonRoutineStore

SEOUL = ZoneInfo("Asia/Seoul")


def write_configuration(path: Path) -> None:
    path.write_text(
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


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 7, 27, hour, minute, tzinfo=SEOUL)


def client_at(tmp_path: Path, now: datetime) -> TestClient:
    configuration_path = tmp_path / "configuration.json"
    write_configuration(configuration_path)
    scheduler = RoutineScheduler(
        JsonRoutineStore(configuration_path, tmp_path / "activity_metrics.json"),
        SEOUL,
    )
    app.dependency_overrides[get_routine_scheduler] = lambda: scheduler
    app.dependency_overrides[get_current_time] = lambda: now
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_current_prompt_contains_display_and_spoken_text(tmp_path: Path) -> None:
    response = client_at(tmp_path, at(9, 0)).get("/api/v1/routines/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["server_time"] == "2026-07-27T09:00:00+09:00"
    assert len(payload["items"]) == 1
    prompt = payload["items"][0]
    assert prompt["execution_id"] == "morning-medication:2026-07-27"
    assert prompt["state"] == "REMINDING"
    assert prompt["display_text"] == "아침 약 시간입니다. 마치신 뒤 기록 버튼을 눌러 주세요."
    assert prompt["spoken_text"] == prompt["display_text"]
    assert prompt["confirm_label"] == "아침 약 기록하기"


def test_current_endpoint_does_not_duplicate_execution(tmp_path: Path) -> None:
    client = client_at(tmp_path, at(9, 0))

    first = client.get("/api/v1/routines/current")
    second = client.get("/api/v1/routines/current")
    history = client.get("/api/v1/routines/history")

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(history.json()) == 1


def test_confirm_uses_server_time_and_removes_current_prompt(tmp_path: Path) -> None:
    client = client_at(tmp_path, at(9, 0))
    client.get("/api/v1/routines/current")
    app.dependency_overrides[get_current_time] = lambda: at(9, 7)

    confirmed = client.post(
        "/api/v1/routines/morning-medication:2026-07-27/confirm"
    )
    current = client.get("/api/v1/routines/current")

    assert confirmed.status_code == 200
    assert confirmed.json()["state"] == "CONFIRMED"
    assert confirmed.json()["confirmation_delay_seconds"] == 420
    assert current.json()["items"] == []


def test_late_confirm_returns_conflict_and_persists_not_answered(
    tmp_path: Path,
) -> None:
    client = client_at(tmp_path, at(9, 0))
    client.get("/api/v1/routines/current")
    app.dependency_overrides[get_current_time] = lambda: at(9, 40)

    response = client.post(
        "/api/v1/routines/morning-medication:2026-07-27/confirm"
    )
    history = client.get("/api/v1/routines/history")

    assert response.status_code == 409
    assert history.json()[0]["state"] == "NOT_ANSWERED"


def test_unknown_execution_returns_not_found(tmp_path: Path) -> None:
    response = client_at(tmp_path, at(9, 0)).post(
        "/api/v1/routines/unknown/confirm"
    )

    assert response.status_code == 404


def test_invalid_configuration_returns_service_unavailable(tmp_path: Path) -> None:
    client = client_at(tmp_path, at(9, 0))
    (tmp_path / "configuration.json").write_text("not-json", encoding="utf-8")

    response = client.get("/api/v1/routines/current")

    assert response.status_code == 503


def test_routine_endpoints_are_documented() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/routines/current" in paths
    assert "/api/v1/routines/{execution_id}/confirm" in paths
    assert "/api/v1/routines/history" in paths
