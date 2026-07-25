"""Typed data models for ASR audio diagnostics and ETRI recognition results."""

from __future__ import annotations

from typing import Any, TypedDict

from pydantic import BaseModel


class AudioInfo(BaseModel):
    """Basic spec of an audio file as reported by libsndfile."""

    sample_rate: int
    channels: int
    subtype: str
    duration_sec: float


class AudioDiagnostics(BaseModel):
    """Diagnostic info used to tell audio-content issues (silence, odd spec) from API issues."""

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
    """Outcome of a single ETRI ASR recognition call."""

    success: bool
    text: str
    latency_sec: float
    http_status: int | None
    raw_response: dict[str, Any]
    raw_response_text: str
    fail_reason: str
    audio_info: AudioDiagnostics | None
    audio_analysis_error: str | None = None
    attempts: int


class ResultRow(TypedDict):
    """One row of the baseline run's results.csv."""

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
    """A (reference, hypothesis) pair extracted from results.csv for WER/CER scoring."""

    audio_file: str
    reference: str
    hypothesis: str
