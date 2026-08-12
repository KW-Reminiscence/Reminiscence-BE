"""Tablet-facing Supertonic 3 WAV endpoint tests."""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from reminiscence.auth.dependencies import require_same_origin, require_tablet_session
from reminiscence.main import create_app
from reminiscence.tts import api as tts_api
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


def bypass_tablet_auth(application):  # type: ignore[no-untyped-def]
    application.dependency_overrides[require_tablet_session] = lambda: None
    application.dependency_overrides[require_same_origin] = lambda: None


def test_speech_endpoint_returns_non_cached_wav() -> None:
    app = create_app()
    synthesizer = FakeSynthesizer()
    app.dependency_overrides[get_speech_synthesizer] = lambda: synthesizer
    bypass_tablet_auth(app)

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
    bypass_tablet_auth(app)

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
    bypass_tablet_auth(app)

    response = TestClient(app).post(
        "/api/v1/tts/speech",
        json={"text": "안내 문구"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "speech synthesis is temporarily unavailable"
    }


def test_cold_start_initializes_supertonic_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthesizer = FakeSynthesizer()
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def build(_: object) -> FakeSynthesizer:
        nonlocal calls
        with calls_lock:
            calls += 1
        entered.set()
        assert release.wait(timeout=2)
        return synthesizer

    monkeypatch.setattr(
        tts_api.SupertonicConfig,
        "from_environment",
        staticmethod(lambda: object()),
    )
    monkeypatch.setattr(tts_api, "SupertonicSynthesizer", build)
    tts_api._build_speech_synthesizer.cache_clear()
    results: list[object] = []
    errors: list[BaseException] = []

    def resolve() -> None:
        try:
            results.append(tts_api.get_speech_synthesizer())
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=resolve) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        assert entered.wait(timeout=2)
        release.set()
        for thread in threads:
            thread.join()
    finally:
        release.set()
        tts_api._build_speech_synthesizer.cache_clear()

    assert errors == []
    assert results == [synthesizer, synthesizer]
    assert calls == 1


def test_failed_initialization_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fail(_: object) -> FakeSynthesizer:
        nonlocal calls
        calls += 1
        raise SpeechSynthesisUnavailableError("missing model")

    monkeypatch.setattr(
        tts_api.SupertonicConfig,
        "from_environment",
        staticmethod(lambda: object()),
    )
    monkeypatch.setattr(tts_api, "SupertonicSynthesizer", fail)
    tts_api._build_speech_synthesizer.cache_clear()
    try:
        with pytest.raises(Exception, match="503"):
            tts_api.get_speech_synthesizer()
        with pytest.raises(Exception, match="503"):
            tts_api.get_speech_synthesizer()
    finally:
        tts_api._build_speech_synthesizer.cache_clear()

    assert calls == 1
