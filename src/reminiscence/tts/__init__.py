"""Local Supertonic 3 text-to-speech integration."""

from reminiscence.tts.models import (
    SpeechSynthesisResult,
    SpeechSynthesisUnavailableError,
    SpeechSynthesizer,
)
from reminiscence.tts.supertonic import (
    SupertonicConfig,
    SupertonicSynthesizer,
)

__all__ = [
    "SpeechSynthesisResult",
    "SpeechSynthesisUnavailableError",
    "SpeechSynthesizer",
    "SupertonicConfig",
    "SupertonicSynthesizer",
]
