"""Conversation API and browser-TTS contract tests."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from reminiscence.asr import RecognitionResult
from reminiscence.conversation import ConversationService, JsonConversationStore
from reminiscence.conversation.api import (
    get_conversation_service,
    get_current_time,
    get_speech_recognizer,
)
from reminiscence.main import app
from reminiscence.storage import JsonObjectStore

SEOUL = ZoneInfo("Asia/Seoul")
ORIGINAL_DATA_DIRECTORY = os.environ.get("REMINISCENCE_DATA_DIR")


class FakeRecognizer:
    def __init__(self, transcript: str = "비밀 가족 이야기") -> None:
        self.transcript = transcript
        self.calls: list[tuple[bytes, str]] = []

    def recognize(self, audio: bytes, content_type: str) -> RecognitionResult:
        self.calls.append((audio, content_type))
        return RecognitionResult(
            transcript=self.transcript,
            latency_seconds=0.2,
            attempts=1,
            http_status=200,
        )


def at(minute: int = 0) -> datetime:
    return datetime(2026, 7, 27, 14, minute, tzinfo=SEOUL)


def client_with(
    tmp_path: Path,
    recognizer: FakeRecognizer | None = None,
) -> tuple[TestClient, Path, FakeRecognizer]:
    activity_path = tmp_path / "activity_metrics.json"
    configuration_path = tmp_path / "configuration.json"
    configuration_path.write_text(
        json.dumps(
            {
                "photos": [
                    {
                        "id": "family-1",
                        "image_url": "/media/family-1.jpg",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = ConversationService(
        JsonConversationStore(
            JsonObjectStore(
                activity_path,
                missing_default={"conversation_sessions": []},
            )
        ),
        id_factory=iter(["session-1", "turn-1", "turn-2"]).__next__,
    )
    fake_recognizer = recognizer or FakeRecognizer()
    app.dependency_overrides[get_conversation_service] = lambda: service
    app.dependency_overrides[get_speech_recognizer] = lambda: fake_recognizer
    app.dependency_overrides[get_current_time] = lambda: at()
    os.environ["REMINISCENCE_DATA_DIR"] = str(tmp_path)
    client = TestClient(app)
    return client, activity_path, fake_recognizer


def teardown_function() -> None:
    if ORIGINAL_DATA_DIRECTORY is not None:
        os.environ["REMINISCENCE_DATA_DIR"] = ORIGINAL_DATA_DIRECTORY
    else:
        os.environ.pop("REMINISCENCE_DATA_DIR", None)
    app.dependency_overrides.clear()


def start_session(client: TestClient) -> str:
    response = client.post(
        "/api/v1/conversations/sessions",
        json={"source": "VOLUNTARY"},
    )
    assert response.status_code == 201
    return response.json()["session_id"]


def test_start_returns_photo_and_browser_tts_question(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)

    response = client.post(
        "/api/v1/conversations/sessions",
        json={"source": "SCHEDULED"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["photo_id"] == "family-1"
    assert payload["image_url"] == "/media/family-1.jpg"
    assert payload["question"]["display_text"]
    assert payload["question"]["spoken_text"] == payload["question"]["display_text"]


def test_turn_reduces_audio_to_metrics_without_returning_or_storing_text(
    tmp_path: Path,
) -> None:
    client, activity_path, recognizer = client_with(tmp_path)
    session_id = start_session(client)

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 4},
        content=b"wav-audio",
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["utterance_chars"] == 7
    assert payload["chars_per_second"] == 1.75
    assert payload["next_question"]["spoken_text"] == payload["next_question"]["display_text"]
    assert "transcript" not in response.text
    persisted = activity_path.read_text(encoding="utf-8")
    assert "비밀 가족 이야기" not in persisted
    assert "wav-audio" not in persisted
    assert recognizer.calls == [(b"wav-audio", "audio/wav")]


def test_whitespace_transcript_is_recorded_as_no_response(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path, FakeRecognizer("  \n "))
    session_id = start_session(client)

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 10},
        content=b"wav",
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 200
    assert response.json()["no_response"] is True
    assert response.json()["chars_per_second"] is None


def test_complete_returns_metrics_only_summary(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)
    session_id = start_session(client)
    client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 4},
        content=b"wav",
        headers={"content-type": "audio/wav"},
    )
    app.dependency_overrides[get_current_time] = lambda: at() + timedelta(minutes=1)

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/complete"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["user_turn_count"] == 1
    assert payload["total_utterance_chars"] == 7
    assert "transcript" not in payload


def test_completed_session_rejects_another_turn(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)
    session_id = start_session(client)
    client.post(f"/api/v1/conversations/sessions/{session_id}/complete")

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 1},
        content=b"wav",
        headers={"content-type": "audio/wav"},
    )

    assert response.status_code == 409


def test_unknown_photo_is_not_found(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)

    response = client.post(
        "/api/v1/conversations/sessions",
        json={"source": "VOLUNTARY", "photo_id": "missing"},
    )

    assert response.status_code == 404


def test_unsupported_audio_type_is_rejected(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)
    session_id = start_session(client)

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 1},
        content=b"webm",
        headers={"content-type": "audio/webm"},
    )

    assert response.status_code == 415


def test_conversation_endpoints_are_documented() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/conversations/sessions" in paths
    assert "/api/v1/conversations/sessions/{session_id}/turns" in paths
    assert "/api/v1/conversations/sessions/{session_id}/complete" in paths
