"""Provider-neutral text-to-speech contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SpeechSynthesisResult:
    """One complete PCM WAV generated from display-safe text."""

    audio: bytes
    duration_seconds: float
    sample_rate: int
    engine: str


class SpeechSynthesisUnavailableError(RuntimeError):
    """Raised when local speech synthesis cannot produce audio."""


class SpeechSynthesizer(Protocol):
    """Synthesize one utterance without exposing provider controls to clients."""

    def synthesize(self, text: str) -> SpeechSynthesisResult:
        """Return a self-contained WAV for the supplied text."""

        ...
