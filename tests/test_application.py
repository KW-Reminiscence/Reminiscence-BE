from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reminiscence import main
from reminiscence.main import app, create_app
from reminiscence.storage.migration import migrate_data_directory


def test_openapi_document_describes_the_application() -> None:
    response = TestClient(app).get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Reminiscence API"


def test_application_lifespan_starts_and_stops_background_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    routine_scheduler = object()
    notification_coordinator = object()
    events: list[str] = []
    received: list[tuple[object, object, Callable[[], datetime]]] = []

    class FakeRuntime:
        is_running = True

        def start(self) -> None:
            events.append("started")

        async def stop(self) -> None:
            events.append("stopped")

    def build_runtime(
        routine: object,
        notification: object,
        clock: Callable[[], datetime],
    ) -> FakeRuntime:
        received.append((routine, notification, clock))
        return FakeRuntime()

    monkeypatch.setattr(main, "get_routine_scheduler", lambda: routine_scheduler)
    monkeypatch.setattr(
        main,
        "get_notification_coordinator",
        lambda: notification_coordinator,
    )
    monkeypatch.setattr(main, "build_background_runtime", build_runtime)
    monkeypatch.setenv("REMINISCENCE_DATA_DIR", str(tmp_path))
    migrate_data_directory(tmp_path, apply=True)

    application = create_app()
    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert events == ["started"]
        assert application.state.instance_lock.acquired is True
        assert application.state.background_runtime.is_running is True

    assert events == ["started", "stopped"]
    assert not hasattr(application.state, "instance_lock")
    assert not hasattr(application.state, "background_runtime")
    assert len(received) == 1
    assert received[0][0] is routine_scheduler
    assert received[0][1] is notification_coordinator
    assert received[0][2] is main.get_current_time
