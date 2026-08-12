"""Integrated tablet home state API tests."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from reminiscence.conversation.api import get_conversation_service
from reminiscence.conversation.models import ConversationSource
from reminiscence.conversation.service import ConversationService
from reminiscence.conversation.storage import JsonConversationStore
from reminiscence.main import app
from reminiscence.routine.api import get_current_time, get_routine_scheduler
from reminiscence.routine.scheduler import RoutineScheduler
from reminiscence.routine.storage import JsonRoutineStore
from reminiscence.storage import open_versioned_store

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 7, 27, 14, 0, tzinfo=SEOUL)
PHOTO_BASE64 = base64.b64encode(b"\x89PNG\r\n\x1a\nphoto").decode("ascii")
ORIGINAL_DATA_DIRECTORY = os.environ.get("REMINISCENCE_DATA_DIR")


def write_configuration(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "routines": [
                    {
                        "id": "lunch-medication",
                        "name": "점심 약",
                        "category": "MEDICATION",
                        "weekdays": list(range(7)),
                        "scheduled_time": "14:00",
                        "grace_minutes": 10,
                        "reminder_interval_minutes": 10,
                        "max_reminders": 3,
                    }
                ],
                "conversation": {"suggestion_time": "14:00"},
                "photos": [
                    {
                        "id": "family-1",
                        "image_base64": PHOTO_BASE64,
                        "image_media_type": "image/png",
                        "location": "제주도",
                        "people": ["가족"],
                        "event": "가족여행",
                        "description": "함께 찍은 사진",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def client_at(tmp_path: Path) -> tuple[TestClient, ConversationService]:
    configuration_path = tmp_path / "configuration.json"
    activity_path = tmp_path / "activity_metrics.json"
    write_configuration(configuration_path)
    scheduler = RoutineScheduler(
        JsonRoutineStore(configuration_path, activity_path),
        SEOUL,
    )
    conversations = ConversationService(
        JsonConversationStore(
            open_versioned_store(
                activity_path,
                missing_default={"conversation_sessions": []},
            )
        ),
        id_factory=lambda: "session-1",
    )
    app.dependency_overrides[get_routine_scheduler] = lambda: scheduler
    app.dependency_overrides[get_conversation_service] = lambda: conversations
    app.dependency_overrides[get_current_time] = lambda: NOW
    os.environ["REMINISCENCE_DATA_DIR"] = str(tmp_path)
    return TestClient(app), conversations


def teardown_function() -> None:
    if ORIGINAL_DATA_DIRECTORY is None:
        os.environ.pop("REMINISCENCE_DATA_DIR", None)
    else:
        os.environ["REMINISCENCE_DATA_DIR"] = ORIGINAL_DATA_DIRECTORY
    app.dependency_overrides.clear()


def test_state_combines_routine_suggestion_and_photo(tmp_path: Path) -> None:
    client, _ = client_at(tmp_path)
    response = client.get("/api/v1/tablet/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["server_time"] == "2026-07-27T14:00:00+09:00"
    assert payload["active_routines"][0]["name"] == "점심 약"
    assert payload["conversation_suggestion"]["suggested"] is True
    assert payload["photos"][0]["id"] == "family-1"
    assert payload["photos"][0]["image_base64"] == PHOTO_BASE64
    assert payload["active_conversation_session_id"] is None


def test_active_session_is_returned_and_suppresses_suggestion(tmp_path: Path) -> None:
    client, service = client_at(tmp_path)
    service.start_session(ConversationSource.VOLUNTARY, "family-1", NOW)

    response = client.get("/api/v1/tablet/state")

    assert response.status_code == 200
    assert response.json()["active_conversation_session_id"] == "session-1"
    assert response.json()["conversation_suggestion"]["suggested"] is False


def test_invalid_photo_configuration_fails_closed(tmp_path: Path) -> None:
    client, _ = client_at(tmp_path)
    configuration_path = tmp_path / "configuration.json"
    configuration = json.loads(configuration_path.read_text(encoding="utf-8"))
    configuration["photos"] = []
    configuration_path.write_text(json.dumps(configuration), encoding="utf-8")

    response = client.get("/api/v1/tablet/state")

    assert response.status_code == 503


def test_tablet_state_endpoint_is_documented() -> None:
    assert "/api/v1/tablet/state" in app.openapi()["paths"]
