"""Privacy-preserving transcription through codex-lb's OpenAI-compatible API."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

import urllib3

from reminiscence.asr.audio_utils import normalize_wav_bytes
from reminiscence.asr.models import (
    MAX_AUDIO_BYTES,
    SUPPORTED_CONTENT_TYPES,
    RecognitionResult,
    RecognitionUnavailableError,
)

DEFAULT_BASE_URL = "http://127.0.0.1:2455/v1"
TRANSCRIPTION_MODEL = "gpt-4o-transcribe"
TRANSCRIPTION_PROMPT = "한국어로 말한 어르신의 회상 대화입니다."
CLIENT_USER_AGENT = "Reminiscence-API/0.1"


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


@dataclass(frozen=True, slots=True)
class CodexLbRecognizerConfig:
    """Validated codex-lb endpoint, proxy credential, and timeout settings."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 150.0

    def __post_init__(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ValueError("api_key must not be blank")
        if not isinstance(self.base_url, str):
            raise ValueError("base_url must be a valid HTTP URL ending in /v1")
        parsed_url = urlsplit(self.base_url)
        try:
            port = parsed_url.port
        except ValueError as exc:
            raise ValueError(
                "base_url must be a valid HTTP URL ending in /v1"
            ) from exc
        if (
            parsed_url.scheme not in {"http", "https"}
            or parsed_url.hostname is None
            or parsed_url.username is not None
            or parsed_url.password is not None
            or port == 0
            or parsed_url.query
            or parsed_url.fragment
            or not parsed_url.path.rstrip("/").endswith("/v1")
        ):
            raise ValueError("base_url must be a valid HTTP URL ending in /v1")
        for field_name, value in (
            ("connect_timeout_seconds", self.connect_timeout_seconds),
            ("read_timeout_seconds", self.read_timeout_seconds),
        ):
            if not _is_finite_number(value) or value <= 0:
                raise ValueError(f"{field_name} must be finite and positive")

    @property
    def transcription_url(self) -> str:
        """Return the fixed OpenAI-compatible transcription endpoint."""

        return f"{self.base_url.rstrip('/')}/audio/transcriptions"

class CodexLbRecognizer:
    """Send transient WAV bytes to codex-lb and retain only request metadata."""

    def __init__(
        self,
        config: CodexLbRecognizerConfig,
        http: urllib3.PoolManager | None = None,
        audio_normalizer: Callable[[bytes], bytes] = normalize_wav_bytes,
    ) -> None:
        self._config = config
        self._http = http if http is not None else urllib3.PoolManager()
        self._audio_normalizer = audio_normalizer

    def recognize(self, audio: bytes, content_type: str) -> RecognitionResult:
        """Transcribe one WAV without persisting audio or returned text."""

        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValueError("only WAV audio is supported")
        if not audio:
            raise ValueError("audio must not be empty")
        if len(audio) > MAX_AUDIO_BYTES:
            raise ValueError(f"audio must not exceed {MAX_AUDIO_BYTES} bytes")
        normalized_audio = self._audio_normalizer(audio)
        started = time.monotonic()
        try:
            response = self._http.request(
                "POST",
                self._config.transcription_url,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "User-Agent": CLIENT_USER_AGENT,
                    "Accept": "application/json",
                },
                fields={
                    "model": TRANSCRIPTION_MODEL,
                    "prompt": TRANSCRIPTION_PROMPT,
                    "file": (
                        "speech.wav",
                        normalized_audio,
                        "audio/wav",
                    ),
                },
                encode_multipart=True,
                timeout=urllib3.Timeout(
                    connect=self._config.connect_timeout_seconds,
                    read=self._config.read_timeout_seconds,
                ),
                retries=False,
                redirect=False,
            )
        except urllib3.exceptions.HTTPError as exc:
            raise RecognitionUnavailableError(
                "codex-lb transcription request failed"
            ) from exc
        if response.status != 200:
            raise RecognitionUnavailableError(
                f"codex-lb transcription failed with HTTP {response.status}"
            )
        return RecognitionResult(
            transcript=self._parse_transcript(response.data),
            latency_seconds=round(time.monotonic() - started, 3),
            attempts=1,
            http_status=response.status,
        )

    @staticmethod
    def _parse_transcript(response_body: bytes) -> str:
        try:
            payload: Any = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecognitionUnavailableError(
                "codex-lb returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise RecognitionUnavailableError(
                "codex-lb transcription response must be an object"
            )
        transcript = payload.get("text")
        if not isinstance(transcript, str):
            raise RecognitionUnavailableError(
                "codex-lb transcription response is missing text"
            )
        return transcript
