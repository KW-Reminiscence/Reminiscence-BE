"""Provider-neutral speech recognition types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    """Transient transcript and non-sensitive request metadata."""

    transcript: str
    latency_seconds: float
    attempts: int
    http_status: int


class RecognitionUnavailableError(RuntimeError):
    """Raised when a speech provider cannot produce a valid result."""


class SpeechRecognizer(Protocol):
    """Interchangeable ASR provider used by the conversation service."""

    def recognize(self, audio: bytes, content_type: str) -> RecognitionResult:
        """Recognize one in-memory audio payload without retaining it."""

        ...
