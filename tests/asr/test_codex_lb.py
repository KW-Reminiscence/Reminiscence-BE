"""codex-lb OpenAI-compatible transcription client tests."""

from __future__ import annotations

import json
from math import inf, nan
from typing import Any, cast

import pytest
import urllib3

from reminiscence.asr import (
    CodexLbRecognizer,
    CodexLbRecognizerConfig,
    RecognitionUnavailableError,
)
from reminiscence.asr.codex_lb import (
    CLIENT_USER_AGENT,
    TRANSCRIPTION_MODEL,
    TRANSCRIPTION_PROMPT,
)


class FakeResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self.data = (
            json.dumps(payload).encode("utf-8")
            if not isinstance(payload, bytes)
            else payload
        )


class FakeHttp:
    def __init__(
        self,
        response: FakeResponse | None = None,
        error: urllib3.exceptions.HTTPError | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.requests: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def config(**overrides: Any) -> CodexLbRecognizerConfig:
    values = {
        "api_key": "proxy-secret",
        "base_url": "https://codex-lb.example/v1",
    }
    values.update(overrides)
    return CodexLbRecognizerConfig(**values)


def recognizer(fake_http: FakeHttp) -> CodexLbRecognizer:
    return CodexLbRecognizer(
        config(),
        http=cast(urllib3.PoolManager, fake_http),
        audio_normalizer=lambda value: b"normalized-" + value,
    )


def test_success_sends_fixed_model_and_wav_multipart() -> None:
    http = FakeHttp(FakeResponse(200, {"text": "안녕하세요"}))

    result = recognizer(http).recognize(b"audio", "audio/x-wav")

    assert result.transcript == "안녕하세요"
    assert result.attempts == 1
    assert result.http_status == 200
    request = http.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == "https://codex-lb.example/v1/audio/transcriptions"
    assert request["headers"] == {
        "Authorization": "Bearer proxy-secret",
        "User-Agent": CLIENT_USER_AGENT,
        "Accept": "application/json",
    }
    assert request["fields"] == {
        "model": TRANSCRIPTION_MODEL,
        "prompt": TRANSCRIPTION_PROMPT,
        "file": ("speech.wav", b"normalized-audio", "audio/wav"),
    }
    assert request["encode_multipart"] is True
    assert request["retries"] is False
    assert request["redirect"] is False


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not-json", "invalid JSON"),
        ([], "must be an object"),
        ({"usage": {}}, "missing text"),
        ({"text": 7}, "missing text"),
    ],
)
def test_invalid_response_is_rejected(payload: object, message: str) -> None:
    with pytest.raises(RecognitionUnavailableError, match=message):
        recognizer(FakeHttp(FakeResponse(200, payload))).recognize(
            b"audio",
            "audio/wav",
        )


def test_non_success_status_does_not_expose_response_body() -> None:
    client = recognizer(
        FakeHttp(
            FakeResponse(
                401,
                {"error": {"message": "secret upstream detail"}},
            )
        )
    )

    with pytest.raises(RecognitionUnavailableError, match="HTTP 401") as raised:
        client.recognize(b"audio", "audio/wav")

    assert "secret upstream detail" not in str(raised.value)


def test_transport_error_is_mapped_to_unavailable() -> None:
    client = recognizer(
        FakeHttp(error=urllib3.exceptions.HTTPError("connection failed"))
    )

    with pytest.raises(RecognitionUnavailableError, match="request failed"):
        client.recognize(b"audio", "audio/wav")


@pytest.mark.parametrize(
    ("audio", "content_type", "message"),
    [
        (b"", "audio/wav", "empty"),
        (b"audio", "audio/webm", "WAV"),
        (b"x" * (10 * 1024 * 1024 + 1), "audio/wav", "exceed"),
    ],
)
def test_invalid_audio_is_rejected(
    audio: bytes,
    content_type: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        recognizer(FakeHttp()).recognize(audio, content_type)


def test_environment_reads_proxy_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_LB_API_KEY", "proxy-secret")
    monkeypatch.setenv("CODEX_LB_BASE_URL", "https://codex.example/v1/")
    monkeypatch.setenv("CODEX_LB_CONNECT_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setenv("CODEX_LB_READ_TIMEOUT_SECONDS", "120")

    value = CodexLbRecognizerConfig.from_environment()

    assert value.api_key == "proxy-secret"
    assert value.transcription_url == (
        "https://codex.example/v1/audio/transcriptions"
    )
    assert value.connect_timeout_seconds == 3.5
    assert value.read_timeout_seconds == 120


def test_environment_requires_proxy_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODEX_LB_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="CODEX_LB_API_KEY"):
        CodexLbRecognizerConfig.from_environment()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"api_key": "  "}, "api_key"),
        ({"base_url": "https://codex.example"}, "ending in /v1"),
        ({"base_url": "ftp://codex.example/v1"}, "ending in /v1"),
        ({"base_url": "https://user:secret@codex.example/v1"}, "ending in /v1"),
        ({"base_url": "https://codex.example/v1?key=value"}, "ending in /v1"),
        ({"connect_timeout_seconds": 0}, "connect_timeout_seconds"),
        ({"connect_timeout_seconds": nan}, "connect_timeout_seconds"),
        ({"read_timeout_seconds": inf}, "read_timeout_seconds"),
    ],
)
def test_config_rejects_invalid_values(
    overrides: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        config(**overrides)
