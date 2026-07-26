"""ETRI ASR runtime boundary and opt-in baseline evaluation tools."""

from reminiscence.asr.audio_utils import (
    analyze_audio,
    batch_convert,
    convert_to_etri_format,
    get_audio_info,
    is_already_target_format,
    normalize_wav_bytes,
)
from reminiscence.asr.etri import EtriRecognizer, EtriRecognizerConfig
from reminiscence.asr.models import (
    AudioDiagnostics,
    AudioInfo,
    RecognitionResult,
    RecognitionUnavailableError,
    RecognizeResult,
    ResultRow,
    SpeechRecognizer,
    WerPair,
)

__all__ = [
    "AudioDiagnostics",
    "AudioInfo",
    "EtriRecognizer",
    "EtriRecognizerConfig",
    "RecognitionResult",
    "RecognitionUnavailableError",
    "RecognizeResult",
    "ResultRow",
    "SpeechRecognizer",
    "WerPair",
    "analyze_audio",
    "batch_convert",
    "convert_to_etri_format",
    "get_audio_info",
    "is_already_target_format",
    "normalize_wav_bytes",
]
