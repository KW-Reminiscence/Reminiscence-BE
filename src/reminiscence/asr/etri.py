"""Privacy-preserving ETRI speech recognition client."""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import urllib3

from reminiscence.asr.models import RecognitionResult, RecognitionUnavailableError

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "http://epretx.etri.re.kr:8000/api/WiseASR_Recognition"
MAX_AUDIO_BYTES = 10 * 1024 * 1024
SUPPORTED_CONTENT_TYPES = frozenset({"audio/wav", "audio/x-wav"})
RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class EtriRecognizerConfig:
    """Runtime settings for serialized ETRI recognition calls."""

    api_key: str
    api_url: str = DEFAULT_API_URL
    min_request_interval_seconds: float = 1.5
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("api_key must not be blank")
        if self.min_request_interval_seconds < 0:
            raise ValueError("min_request_interval_seconds must not be negative")
        if self.max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")

    @classmethod
    def from_environment(cls) -> EtriRecognizerConfig:
        """Read credentials and tuning values without loading local files."""

        api_key = os.environ.get("ETRI_API_KEY", "")
        if not api_key:
            raise RuntimeError("ETRI_API_KEY is required")
        return cls(
            api_key=api_key,
            api_url=os.environ.get("ETRI_ASR_URL", DEFAULT_API_URL),
            min_request_interval_seconds=float(
                os.environ.get("ETRI_MIN_INTERVAL_SECONDS", "1.5")
            ),
            max_retries=int(os.environ.get("ETRI_MAX_RETRIES", "2")),
            retry_backoff_seconds=float(
                os.environ.get("ETRI_RETRY_BACKOFF_SECONDS", "1.0")
            ),
        )


class EtriRecognizer:
    """Call ETRI with no audio, transcript, or raw-response persistence."""

    def __init__(
        self,
        config: EtriRecognizerConfig,
        http: urllib3.PoolManager | None = None,
    ) -> None:
        self._config = config
        self._http = http if http is not None else urllib3.PoolManager()
        self._request_lock = threading.Lock()
        self._last_request_finished = 0.0

    def recognize(self, audio: bytes, content_type: str) -> RecognitionResult:
        """Recognize a WAV payload while serializing the complete provider call."""

        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValueError("only WAV audio is supported")
        if not audio:
            raise ValueError("audio must not be empty")
        if len(audio) > MAX_AUDIO_BYTES:
            raise ValueError(f"audio must not exceed {MAX_AUDIO_BYTES} bytes")

        request_body = json.dumps(
            {
                "argument": {
                    "language_code": "korean",
                    "audio": base64.b64encode(audio).decode("ascii"),
                }
            }
        ).encode("utf-8")

        with self._request_lock:
            self._wait_for_rate_limit()
            return self._recognize_locked(request_body)

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_finished
        remaining = self._config.min_request_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _recognize_locked(self, request_body: bytes) -> RecognitionResult:
        started = time.monotonic()
        last_reason = "provider request failed"
        last_status = 0
        total_attempts = self._config.max_retries + 1
        try:
            for attempt in range(1, total_attempts + 1):
                try:
                    response = self._http.request(
                        "POST",
                        self._config.api_url,
                        headers={
                            "Authorization": self._config.api_key,
                            "Content-Type": "application/json; charset=UTF-8",
                        },
                        body=request_body,
                        timeout=urllib3.Timeout(
                            connect=self._config.connect_timeout_seconds,
                            read=self._config.read_timeout_seconds,
                        ),
                    )
                except urllib3.exceptions.HTTPError as exc:
                    last_reason = type(exc).__name__
                    if attempt < total_attempts:
                        self._backoff(attempt)
                        continue
                    raise RecognitionUnavailableError(
                        f"ETRI request failed after {attempt} attempts: {last_reason}"
                    ) from exc

                last_status = response.status
                if response.status in RETRYABLE_HTTP_STATUSES and attempt < total_attempts:
                    last_reason = f"HTTP {response.status}"
                    self._backoff(attempt)
                    continue
                if response.status != 200:
                    raise RecognitionUnavailableError(
                        f"ETRI request failed with HTTP {response.status}"
                    )

                transcript = self._parse_transcript(response.data)
                latency = time.monotonic() - started
                logger.info(
                    "ETRI recognition completed status=%s attempts=%s latency_seconds=%.3f",
                    response.status,
                    attempt,
                    latency,
                )
                return RecognitionResult(
                    transcript=transcript,
                    latency_seconds=round(latency, 3),
                    attempts=attempt,
                    http_status=response.status,
                )
        finally:
            self._last_request_finished = time.monotonic()

        raise RecognitionUnavailableError(
            f"ETRI request failed with {last_reason}, last status {last_status}"
        )

    def _backoff(self, attempt: int) -> None:
        delay = self._config.retry_backoff_seconds * 2 ** (attempt - 1)
        if delay > 0:
            time.sleep(delay)

    @staticmethod
    def _parse_transcript(response_body: bytes) -> str:
        try:
            payload: Any = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecognitionUnavailableError("ETRI returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RecognitionUnavailableError("ETRI response must be an object")
        if payload.get("result") != 0:
            raise RecognitionUnavailableError("ETRI returned a recognition error")
        return_object = payload.get("return_object")
        if not isinstance(return_object, dict):
            raise RecognitionUnavailableError("ETRI response is missing return_object")
        transcript = return_object.get("recognized")
        if not isinstance(transcript, str):
            raise RecognitionUnavailableError("ETRI response is missing recognized text")
        return transcript
