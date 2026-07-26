"""Provider-neutral text-to-speech contracts."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SpeechSynthesisResult:
    """One complete PCM WAV generated from display-safe text."""

    audio: bytes
    duration_seconds: float
    sample_rate: int
    engine: str

    def __post_init__(self) -> None:
        if not self.audio:
            raise ValueError("audio must not be empty")
        if not isfinite(self.duration_seconds) or self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be finite and positive")
        if (
            not isinstance(self.sample_rate, int)
            or isinstance(self.sample_rate, bool)
            or self.sample_rate <= 0
        ):
            raise ValueError("sample_rate must be a positive integer")
        if not self.engine.strip():
            raise ValueError("engine must not be blank")


class SpeechSynthesisUnavailableError(RuntimeError):
    """Raised when local speech synthesis cannot produce audio."""


class SpeechSynthesizer(Protocol):
    """Synthesize one utterance without exposing provider controls to clients."""

    def synthesize(self, text: str) -> SpeechSynthesisResult:
        """Return a self-contained WAV for the supplied text."""

        ...
