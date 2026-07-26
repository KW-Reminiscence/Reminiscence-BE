from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
import urllib3

from reminiscence.asr.etri_client import ETRIClient, ETRIClientConfig


class _FakeResponse:
    def __init__(self, status: int, payload: dict[str, Any] | str) -> None:
        self.status = status
        body = payload if isinstance(payload, str) else json.dumps(payload)
        self.data = body.encode("utf-8")


class _FakeHTTP:
    """Stand-in for urllib3.PoolManager that returns canned responses in order."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: str,
        timeout: urllib3.Timeout,
    ) -> _FakeResponse:
        self.requests.append({"method": method, "url": url, "headers": headers, "body": body})
        return self._responses.pop(0)


def _make_config(tmp_path: Path) -> ETRIClientConfig:
    return ETRIClientConfig(
        api_key="test-key",
        min_request_interval_sec=0.0,
        max_retries=2,
        retry_backoff_base_sec=0.0,
        log_dir=tmp_path / "logs",
    )


def _write_wav(path: Path) -> None:
    sample_rate = 16000
    samples = int(sample_rate * 0.1)
    tone = 0.3 * np.sin(2 * np.pi * 440 * np.arange(samples) / sample_rate)
    sf.write(str(path), tone, sample_rate, subtype="PCM_16")


def test_recognize_speech_returns_recognized_text_on_success(tmp_path: Path) -> None:
    audio_path = tmp_path / "sample.wav"
    _write_wav(audio_path)
    fake_http = _FakeHTTP(
        [_FakeResponse(200, {"result": 0, "return_object": {"recognized": "안녕하세요"}})]
    )
    client = ETRIClient(_make_config(tmp_path), http=fake_http)  # type: ignore[arg-type]

    result = client.recognize_speech(audio_path, auto_convert=False)

    assert result.success is True
    assert result.text == "안녕하세요"
    assert result.attempts == 1
    assert result.http_status == 200


def test_recognize_speech_retries_on_retryable_status_then_succeeds(tmp_path: Path) -> None:
    audio_path = tmp_path / "sample.wav"
    _write_wav(audio_path)
    fake_http = _FakeHTTP(
        [
            _FakeResponse(429, "Concurrent Limit Exceeded"),
            _FakeResponse(200, {"result": 0, "return_object": {"recognized": "재시도 성공"}}),
        ]
    )
    client = ETRIClient(_make_config(tmp_path), http=fake_http)  # type: ignore[arg-type]

    result = client.recognize_speech(audio_path, auto_convert=False)

    assert result.success is True
    assert result.attempts == 2
    assert len(fake_http.requests) == 2


def test_recognize_speech_gives_up_after_max_retries(tmp_path: Path) -> None:
    audio_path = tmp_path / "sample.wav"
    _write_wav(audio_path)
    fake_http = _FakeHTTP([_FakeResponse(503, "Service Unavailable")] * 3)
    client = ETRIClient(_make_config(tmp_path), http=fake_http)  # type: ignore[arg-type]

    result = client.recognize_speech(audio_path, auto_convert=False)

    assert result.success is False
    assert result.attempts == 3
    assert "HTTP 503" in result.fail_reason


def test_recognize_speech_reports_etri_error_result_as_failure(tmp_path: Path) -> None:
    audio_path = tmp_path / "sample.wav"
    _write_wav(audio_path)
    fake_http = _FakeHTTP([_FakeResponse(200, {"result": 7, "reason": "Input Text Too Long"})])
    client = ETRIClient(_make_config(tmp_path), http=fake_http)  # type: ignore[arg-type]

    result = client.recognize_speech(audio_path, auto_convert=False)

    assert result.success is False
    assert "result=7" in result.fail_reason


def test_recognize_speech_does_not_write_transcript_or_debug_log(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "sample.wav"
    _write_wav(audio_path)
    fake_http = _FakeHTTP(
        [_FakeResponse(200, {"result": 0, "return_object": {"recognized": "로그"}})]
    )
    client = ETRIClient(_make_config(tmp_path), http=fake_http)  # type: ignore[arg-type]

    result = client.recognize_speech(audio_path, auto_convert=False)

    assert result.text == "로그"
    assert not (tmp_path / "logs").exists()


def test_from_env_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("reminiscence.asr.etri_client.load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("ETRI_API_KEY", raising=False)

    with pytest.raises(OSError):
        ETRIClientConfig.from_env()
