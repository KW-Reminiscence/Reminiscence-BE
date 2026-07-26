"""ETRI client behavior without retaining speech content."""

from __future__ import annotations

import json
import threading
from math import inf, nan
from typing import Any, cast

import pytest
import urllib3

from reminiscence.asr import (
    EtriRecognizer,
    EtriRecognizerConfig,
    RecognitionUnavailableError,
)


class FakeResponse:
    def __init__(self, status: int, payload: dict[str, Any] | str) -> None:
        self.status = status
        body = json.dumps(payload) if isinstance(payload, dict) else payload
        self.data = body.encode("utf-8")


class FakeHttp:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.requests: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        return self._responses.pop(0)


def config(**overrides: Any) -> EtriRecognizerConfig:
    values: dict[str, Any] = {
        "api_key": "secret-key",
        "min_request_interval_seconds": 0,
        "max_retries": 2,
        "retry_backoff_seconds": 0,
    }
    values.update(overrides)
    return EtriRecognizerConfig(**values)


def recognizer(fake_http: FakeHttp, **overrides: Any) -> EtriRecognizer:
    return EtriRecognizer(
        config(**overrides),
        http=cast(urllib3.PoolManager, fake_http),
        audio_normalizer=lambda value: value,
    )


def test_success_returns_transient_transcript() -> None:
    http = FakeHttp(
        [FakeResponse(200, {"result": 0, "return_object": {"recognized": "안녕하세요"}})]
    )

    result = recognizer(http).recognize(b"wav-bytes", "audio/wav")

    assert result.transcript == "안녕하세요"
    assert result.attempts == 1
    assert result.http_status == 200
    request = http.requests[0]
    assert request["headers"]["Authorization"] == "secret-key"
    assert b"wav-bytes" not in request["body"]


def test_retryable_status_is_retried() -> None:
    http = FakeHttp(
        [
            FakeResponse(429, "busy"),
            FakeResponse(200, {"result": 0, "return_object": {"recognized": "성공"}}),
        ]
    )

    result = recognizer(http).recognize(b"wav", "audio/x-wav")

    assert result.transcript == "성공"
    assert result.attempts == 2
    assert len(http.requests) == 2


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(400, "bad request"),
        FakeResponse(200, "not-json"),
        FakeResponse(200, {"result": 7, "reason": "failed"}),
        FakeResponse(200, {"result": 0}),
        FakeResponse(200, {"result": 0, "return_object": {"recognized": 1}}),
    ],
)
def test_invalid_provider_response_is_rejected(response: FakeResponse) -> None:
    with pytest.raises(RecognitionUnavailableError):
        recognizer(FakeHttp([response])).recognize(b"wav", "audio/wav")


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
        recognizer(FakeHttp([])).recognize(audio, content_type)


def test_environment_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ETRI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ETRI_API_KEY"):
        EtriRecognizerConfig.from_environment()


def test_environment_reads_request_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ETRI_API_KEY", "secret-key")
    monkeypatch.setenv("ETRI_CONNECT_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setenv("ETRI_READ_TIMEOUT_SECONDS", "12")

    value = EtriRecognizerConfig.from_environment()

    assert value.connect_timeout_seconds == 3.5
    assert value.read_timeout_seconds == 12


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"api_key": "  "}, "api_key"),
        ({"api_url": "ftp://etri.example/speech"}, "api_url"),
        ({"api_url": 7}, "api_url"),
        ({"api_url": "https://user:secret@etri.example/speech"}, "api_url"),
        ({"api_url": "https://etri.example:0/speech"}, "api_url"),
        ({"min_request_interval_seconds": nan}, "min_request_interval_seconds"),
        ({"min_request_interval_seconds": inf}, "min_request_interval_seconds"),
        ({"min_request_interval_seconds": "1"}, "min_request_interval_seconds"),
        ({"max_retries": True}, "max_retries"),
        ({"max_retries": -1}, "max_retries"),
        ({"retry_backoff_seconds": -inf}, "retry_backoff_seconds"),
        ({"connect_timeout_seconds": 0}, "connect_timeout_seconds"),
        ({"read_timeout_seconds": nan}, "read_timeout_seconds"),
    ],
)
def test_config_rejects_invalid_runtime_values(
    overrides: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        config(**overrides)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ETRI_MIN_INTERVAL_SECONDS", "not-a-number"),
        ("ETRI_MAX_RETRIES", "1.5"),
        ("ETRI_CONNECT_TIMEOUT_SECONDS", "invalid"),
        ("ETRI_READ_TIMEOUT_SECONDS", "invalid"),
    ],
)
def test_environment_rejects_malformed_numeric_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv("ETRI_API_KEY", "secret-key")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        EtriRecognizerConfig.from_environment()


def test_complete_provider_calls_are_serialized() -> None:
    first_request_entered = threading.Event()
    release_first_request = threading.Event()

    class BlockingHttp:
        def __init__(self) -> None:
            self.active = 0
            self.maximum_active = 0
            self.calls = 0
            self._lock = threading.Lock()

        def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
            del method, url, kwargs
            with self._lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
                self.calls += 1
                call_number = self.calls
            if call_number == 1:
                first_request_entered.set()
                assert release_first_request.wait(timeout=1)
            with self._lock:
                self.active -= 1
            return FakeResponse(
                200,
                {"result": 0, "return_object": {"recognized": "완료"}},
            )

    # The first call intentionally waits for the test thread before completing.
    http = BlockingHttp()
    client = EtriRecognizer(
        config(),
        http=cast(urllib3.PoolManager, http),
        audio_normalizer=lambda value: value,
    )
    results: list[str] = []

    first = threading.Thread(
        target=lambda: results.append(
            client.recognize(b"first", "audio/wav").transcript
        )
    )
    first.start()
    assert first_request_entered.wait(timeout=1)
    second = threading.Thread(
        target=lambda: results.append(
            client.recognize(b"second", "audio/wav").transcript
        )
    )
    second.start()
    release_first_request.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert results == ["완료", "완료"]
    assert http.maximum_active == 1
