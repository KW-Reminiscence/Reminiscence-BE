"""Tablet-facing Supertonic 3 WAV endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from reminiscence.main import create_app
from reminiscence.tts.api import get_speech_synthesizer
from reminiscence.tts.models import (
    SpeechSynthesisResult,
    SpeechSynthesisUnavailableError,
)


class FakeSynthesizer:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.texts: list[str] = []

    def synthesize(self, text: str) -> SpeechSynthesisResult:
        self.texts.append(text)
        if self.should_fail:
            raise SpeechSynthesisUnavailableError("offline")
        return SpeechSynthesisResult(
            audio=b"RIFF-test-wav",
            duration_seconds=1.25,
            sample_rate=44_100,
            engine="supertonic-3",
        )


def test_speech_endpoint_returns_non_cached_wav() -> None:
    app = create_app()
    synthesizer = FakeSynthesizer()
    app.dependency_overrides[get_speech_synthesizer] = lambda: synthesizer

    response = TestClient(app).post(
        "/api/v1/tts/speech",
        json={"text": "  아침 약 시간입니다.  "},
    )

    assert response.status_code == 200
    assert response.content == b"RIFF-test-wav"
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-audio-duration-seconds"] == "1.25"
    assert response.headers["x-audio-sample-rate"] == "44100"
    assert response.headers["x-tts-engine"] == "supertonic-3"
    assert synthesizer.texts == ["아침 약 시간입니다."]


def test_speech_endpoint_rejects_blank_text_before_synthesis() -> None:
    app = create_app()
    synthesizer = FakeSynthesizer()
    app.dependency_overrides[get_speech_synthesizer] = lambda: synthesizer

    response = TestClient(app).post(
        "/api/v1/tts/speech",
        json={"text": "   "},
    )

    assert response.status_code == 422
    assert synthesizer.texts == []


def test_speech_endpoint_maps_model_failure_to_503() -> None:
    app = create_app()
    synthesizer = FakeSynthesizer(should_fail=True)
    app.dependency_overrides[get_speech_synthesizer] = lambda: synthesizer

    response = TestClient(app).post(
        "/api/v1/tts/speech",
        json={"text": "안내 문구"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "speech synthesis is temporarily unavailable"
    }
