"""Conversation API and Supertonic text contract tests."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from reminiscence.asr import CodexLbRecognizer, RecognitionResult
from reminiscence.asr.models import MAX_AUDIO_BYTES
from reminiscence.conversation import ConversationService, JsonConversationStore
from reminiscence.conversation.api import (
    get_conversation_service,
    get_current_time,
    get_question_provider,
    get_speech_recognizer,
)
from reminiscence.conversation.llm_questions import (
    QuestionGenerationUnavailableError,
)
from reminiscence.conversation.photos import PhotoMemory
from reminiscence.conversation.questions import (
    SpeechText,
    TemplateOpeningQuestionProvider,
)
from reminiscence.main import app
from reminiscence.storage import JsonObjectStore

SEOUL = ZoneInfo("Asia/Seoul")
ORIGINAL_DATA_DIRECTORY = os.environ.get("REMINISCENCE_DATA_DIR")
PHOTO_BASE64 = base64.b64encode(b"\x89PNG\r\n\x1a\nphoto").decode("ascii")
TURN_HEADERS = {"content-type": "audio/wav", "X-Turn-ID": "client-turn-1"}


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


class FakeQuestionProvider:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.initial_photos: list[PhotoMemory] = []
        self.follow_ups: list[tuple[PhotoMemory, str, int]] = []

    def initial_question(self, photo: PhotoMemory) -> SpeechText:
        self.initial_photos.append(photo)
        if self.error is not None:
            raise self.error
        return SpeechText(
            display_text="제주도 가족여행에서 무엇이 가장 기억에 남으시나요?",
            spoken_text="제주도 가족여행에서 무엇이 가장 기억에 남으시나요?",
        )

    def follow_up_question(
        self,
        photo: PhotoMemory,
        transcript: str,
        turn_count: int,
    ) -> SpeechText:
        self.follow_ups.append((photo, transcript, turn_count))
        if self.error is not None:
            raise self.error
        return SpeechText(
            display_text="그때 함께 웃었던 일도 들려주시겠어요?",
            spoken_text="그때 함께 웃었던 일도 들려주시겠어요?",
        )


def at(minute: int = 0) -> datetime:
    return datetime(2026, 7, 27, 14, minute, tzinfo=SEOUL)


def client_with(
    tmp_path: Path,
    recognizer: FakeRecognizer | None = None,
    questions: FakeQuestionProvider | None = None,
) -> tuple[TestClient, Path, FakeRecognizer]:
    activity_path = tmp_path / "activity_metrics.json"
    configuration_path = tmp_path / "configuration.json"
    configuration_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "photos": [
                    {
                        "id": "family-1",
                        "image_base64": PHOTO_BASE64,
                        "image_media_type": "image/png",
                        "location": "제주도 성산일출봉",
                        "people": ["딸 영희", "손자 민준"],
                        "event": "2022년 봄 가족여행",
                        "description": "성산일출봉에 오르기 전에 함께 찍은 사진",
                    }
                ],
                "conversation": {"suggestion_time": "14:00"},
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
    app.dependency_overrides[get_question_provider] = lambda: (
        questions or FakeQuestionProvider()
    )
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
    session_id = response.json()["session_id"]
    assert isinstance(session_id, str)
    return session_id


def test_default_recognizer_uses_codex_lb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LB_API_KEY", "proxy-secret")
    monkeypatch.setenv("CODEX_LB_BASE_URL", "https://codex-lb.example/v1")
    monkeypatch.delenv("ETRI_API_KEY", raising=False)
    get_speech_recognizer.cache_clear()

    try:
        recognizer = get_speech_recognizer()
    finally:
        get_speech_recognizer.cache_clear()

    assert isinstance(recognizer, CodexLbRecognizer)


def test_default_question_provider_uses_codex_lb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LB_API_KEY", "proxy-secret")
    monkeypatch.setenv("CODEX_LB_BASE_URL", "https://codex-lb.example/v1")
    get_question_provider.cache_clear()

    try:
        provider = get_question_provider()
    finally:
        get_question_provider.cache_clear()

    assert isinstance(provider, TemplateOpeningQuestionProvider)


def test_start_returns_photo_and_synthesizable_question(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)

    response = client.post(
        "/api/v1/conversations/sessions",
        json={"source": "SCHEDULED"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["photo"] == {
        "id": "family-1",
        "image_base64": PHOTO_BASE64,
        "image_media_type": "image/png",
        "location": "제주도 성산일출봉",
        "people": ["딸 영희", "손자 민준"],
        "event": "2022년 봄 가족여행",
        "description": "성산일출봉에 오르기 전에 함께 찍은 사진",
    }
    assert payload["question"]["display_text"]
    assert payload["question"]["spoken_text"] == payload["question"]["display_text"]


def test_start_passes_photo_context_to_question_provider(tmp_path: Path) -> None:
    questions = FakeQuestionProvider()
    client, _, _ = client_with(tmp_path, questions=questions)

    response = client.post(
        "/api/v1/conversations/sessions",
        json={"source": "SCHEDULED"},
    )

    assert response.status_code == 201
    assert len(questions.initial_photos) == 1
    assert questions.initial_photos[0].location == "제주도 성산일출봉"
    assert questions.initial_photos[0].people == ("딸 영희", "손자 민준")


def test_start_rejects_a_second_active_session(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)
    start_session(client)

    response = client.post(
        "/api/v1/conversations/sessions",
        json={"source": "SCHEDULED"},
    )

    assert response.status_code == 409


def test_suggestion_returns_synthesizable_text_at_scheduled_time(
    tmp_path: Path,
) -> None:
    client, _, _ = client_with(tmp_path)

    response = client.get("/api/v1/conversations/suggestion")

    assert response.status_code == 200
    payload = response.json()
    assert payload["suggested"] is True
    assert payload["scheduled_time"] == "14:00:00"
    assert payload["spoken_text"] == payload["display_text"]
    assert payload["start_label"] == "이야기 시작하기"


def test_suggestion_is_suppressed_after_voluntary_session(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)
    start_session(client)

    response = client.get("/api/v1/conversations/suggestion")

    assert response.status_code == 200
    assert response.json()["suggested"] is False
    assert response.json()["spoken_text"] is None


def test_invalid_suggestion_configuration_is_unavailable(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)
    configuration_path = tmp_path / "configuration.json"
    configuration = json.loads(configuration_path.read_text(encoding="utf-8"))
    configuration["conversation"]["suggestion_time"] = "25:00"
    configuration_path.write_text(json.dumps(configuration), encoding="utf-8")

    response = client.get("/api/v1/conversations/suggestion")

    assert response.status_code == 503


def test_turn_reduces_audio_to_metrics_without_returning_or_storing_text(
    tmp_path: Path,
) -> None:
    questions = FakeQuestionProvider()
    client, activity_path, recognizer = client_with(tmp_path, questions=questions)
    session_id = start_session(client)

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 4, "has_speech": True},
        content=b"wav-audio",
        headers=TURN_HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["utterance_chars"] == 7
    assert payload["chars_per_second"] == 1.75
    assert payload["speech_detected"] is True
    assert payload["next_question"]["spoken_text"] == payload["next_question"]["display_text"]
    assert "transcript" not in response.text
    persisted = activity_path.read_text(encoding="utf-8")
    assert "비밀 가족 이야기" not in persisted
    assert "wav-audio" not in persisted
    assert recognizer.calls == [(b"wav-audio", "audio/wav")]
    assert len(questions.follow_ups) == 1
    photo, transcript, turn_count = questions.follow_ups[0]
    assert photo.photo_id == "family-1"
    assert transcript == "비밀 가족 이야기"
    assert turn_count == 1


def test_duplicate_turn_id_skips_providers_and_metrics(tmp_path: Path) -> None:
    questions = FakeQuestionProvider()
    client, activity_path, recognizer = client_with(tmp_path, questions=questions)
    session_id = start_session(client)
    first = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 4, "has_speech": True},
        content=b"first-wav",
        headers=TURN_HEADERS,
    )

    repeated = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 99, "has_speech": False},
        content=b"repeated-wav",
        headers=TURN_HEADERS,
    )

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json()["turn_id"] == first.json()["turn_id"]
    assert repeated.json()["utterance_chars"] == first.json()["utterance_chars"]
    assert recognizer.calls == [(b"first-wav", "audio/wav")]
    assert len(questions.follow_ups) == 1
    persisted = json.loads(activity_path.read_text(encoding="utf-8"))
    assert len(persisted["conversation_sessions"][0]["turns"]) == 1


def test_question_failure_does_not_persist_turn(tmp_path: Path) -> None:
    questions = FakeQuestionProvider(
        QuestionGenerationUnavailableError("provider unavailable")
    )
    client, activity_path, _ = client_with(tmp_path)
    session_id = start_session(client)
    app.dependency_overrides[get_question_provider] = lambda: questions

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 4, "has_speech": True},
        content=b"wav",
        headers=TURN_HEADERS,
    )

    assert response.status_code == 503
    persisted = json.loads(activity_path.read_text(encoding="utf-8"))
    assert persisted["conversation_sessions"][0]["turns"] == []


def test_question_failure_does_not_create_session(tmp_path: Path) -> None:
    questions = FakeQuestionProvider(
        QuestionGenerationUnavailableError("provider unavailable")
    )
    client, activity_path, _ = client_with(tmp_path, questions=questions)

    response = client.post(
        "/api/v1/conversations/sessions",
        json={"source": "VOLUNTARY"},
    )

    assert response.status_code == 503
    assert not activity_path.exists()


def test_whitespace_transcript_is_recorded_as_no_response(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path, FakeRecognizer("  \n "))
    session_id = start_session(client)

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 10, "has_speech": True},
        content=b"wav",
        headers=TURN_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["no_response"] is True
    assert response.json()["chars_per_second"] is None


def test_recorder_no_speech_suppresses_hallucinated_transcript(
    tmp_path: Path,
) -> None:
    recognizer = FakeRecognizer("ASR 환각 문장")
    questions = FakeQuestionProvider()
    client, activity_path, _ = client_with(
        tmp_path,
        recognizer,
        questions,
    )
    session_id = start_session(client)

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 3, "has_speech": False},
        content=b"silent-wav",
        headers=TURN_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["speech_detected"] is False
    assert response.json()["utterance_chars"] == 0
    assert response.json()["no_response"] is True
    assert questions.follow_ups[0][1] == ""
    persisted = activity_path.read_text(encoding="utf-8")
    assert "ASR 환각 문장" not in persisted


def test_complete_returns_metrics_only_summary(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)
    session_id = start_session(client)
    client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 4, "has_speech": True},
        content=b"wav",
        headers=TURN_HEADERS,
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


def test_complete_returns_the_original_summary_when_repeated(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)
    session_id = start_session(client)
    app.dependency_overrides[get_current_time] = lambda: at() + timedelta(minutes=1)
    first = client.post(f"/api/v1/conversations/sessions/{session_id}/complete")
    app.dependency_overrides[get_current_time] = lambda: at() + timedelta(minutes=2)

    repeated = client.post(f"/api/v1/conversations/sessions/{session_id}/complete")

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json() == first.json()


def test_completed_session_rejects_another_turn(tmp_path: Path) -> None:
    client, _, recognizer = client_with(tmp_path)
    session_id = start_session(client)
    client.post(f"/api/v1/conversations/sessions/{session_id}/complete")

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 1, "has_speech": True},
        content=b"wav",
        headers=TURN_HEADERS,
    )

    assert response.status_code == 409
    assert recognizer.calls == []


def test_unknown_session_is_rejected_before_asr(tmp_path: Path) -> None:
    client, _, recognizer = client_with(tmp_path)

    response = client.post(
        "/api/v1/conversations/sessions/missing/turns",
        params={"turn_duration_seconds": 1, "has_speech": True},
        content=b"wav",
        headers=TURN_HEADERS,
    )

    assert response.status_code == 404
    assert recognizer.calls == []


def test_completion_before_session_start_is_rejected(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)
    session_id = start_session(client)
    app.dependency_overrides[get_current_time] = lambda: at() - timedelta(seconds=1)

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/complete"
    )

    assert response.status_code == 422


def test_completion_persists_tablet_end_reason(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)
    session_id = start_session(client)

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/complete",
        json={"reason": "INACTIVITY_TIMEOUT"},
    )

    assert response.status_code == 200
    assert response.json()["completion_reason"] == "INACTIVITY_TIMEOUT"


def test_unknown_photo_is_not_found(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)

    response = client.post(
        "/api/v1/conversations/sessions",
        json={"source": "VOLUNTARY", "photo_id": "missing"},
    )

    assert response.status_code == 404


def test_invalid_photo_configuration_is_unavailable(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)
    configuration_path = tmp_path / "configuration.json"
    configuration = json.loads(configuration_path.read_text(encoding="utf-8"))
    configuration["photos"][0]["image_base64"] = "invalid!"
    configuration_path.write_text(json.dumps(configuration), encoding="utf-8")

    response = client.post(
        "/api/v1/conversations/sessions",
        json={"source": "VOLUNTARY"},
    )

    assert response.status_code == 503


def test_unsupported_audio_type_is_rejected(tmp_path: Path) -> None:
    client, _, _ = client_with(tmp_path)
    session_id = start_session(client)

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 1, "has_speech": True},
        content=b"webm",
        headers={"content-type": "audio/webm", "X-Turn-ID": "client-turn-1"},
    )

    assert response.status_code == 415


def test_oversized_audio_is_rejected_before_asr(tmp_path: Path) -> None:
    client, _, recognizer = client_with(tmp_path)
    session_id = start_session(client)

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 1, "has_speech": True},
        content=b"x" * (MAX_AUDIO_BYTES + 1),
        headers=TURN_HEADERS,
    )

    assert response.status_code == 413
    assert recognizer.calls == []


def test_invalid_content_length_is_rejected_before_asr(tmp_path: Path) -> None:
    client, _, recognizer = client_with(tmp_path)
    session_id = start_session(client)

    response = client.post(
        f"/api/v1/conversations/sessions/{session_id}/turns",
        params={"turn_duration_seconds": 1, "has_speech": True},
        content=b"wav",
        headers={
            "content-type": "audio/wav",
            "content-length": "invalid",
            "X-Turn-ID": "client-turn-1",
        },
    )

    assert response.status_code == 400
    assert recognizer.calls == []


def test_conversation_endpoints_are_documented() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/conversations/suggestion" in paths
    assert "/api/v1/conversations/sessions" in paths
    assert "/api/v1/conversations/sessions/{session_id}/turns" in paths
    assert "/api/v1/conversations/sessions/{session_id}/complete" in paths
