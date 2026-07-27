"""Provider-neutral runtime and baseline-only ASR data types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypedDict

from pydantic import BaseModel

MAX_AUDIO_BYTES = 10 * 1024 * 1024
SUPPORTED_CONTENT_TYPES = frozenset({"audio/wav", "audio/x-wav"})


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


class AudioInfo(BaseModel):
    """Basic audio specification reported by libsndfile."""

    sample_rate: int
    channels: int
    subtype: str
    duration_sec: float


class AudioDiagnostics(BaseModel):
    """Audio diagnostics used only by the opt-in baseline tool."""

    duration_sec: float
    sample_rate: int
    channels: int
    subtype: str
    rms: float
    dbfs: float
    max_amplitude: float
    file_size_bytes: int
    is_silent: bool


class RecognizeResult(BaseModel):
    """Compatibility result for the offline baseline runner."""

    success: bool
    text: str
    latency_sec: float
    http_status: int | None
    fail_reason: str
    audio_info: AudioDiagnostics | None
    audio_analysis_error: str | None = None
    attempts: int


class ResultRow(TypedDict):
    """One row of the explicit offline baseline results file."""

    audio_file: str
    recognized_text: str
    reference_text: str
    latency_sec: float
    success: bool
    http_status: int | None
    attempts: int
    fail_reason: str
    duration_sec: float | None
    sample_rate: int | None
    channels: int | None
    subtype: str | None
    rms: float | None
    dbfs: float | None
    is_silent: bool | None


class WerPair(TypedDict):
    """A reference and hypothesis pair for offline WER/CER scoring."""

    audio_file: str
    reference: str
    hypothesis: str
