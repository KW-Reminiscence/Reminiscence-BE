"""ETRI ASR integration: audio format conversion, API client, and baseline evaluation."""

from reminiscence.asr.audio_utils import (
    analyze_audio,
    batch_convert,
    convert_to_etri_format,
    get_audio_info,
    is_already_target_format,
)
from reminiscence.asr.calc_wer import load_pairs
from reminiscence.asr.etri_client import ETRIClient, ETRIClientConfig
from reminiscence.asr.models import (
    AudioDiagnostics,
    AudioInfo,
    RecognizeResult,
    ResultRow,
    WerPair,
)
from reminiscence.asr.run_baseline import run_batch

__all__ = [
    "AudioDiagnostics",
    "AudioInfo",
    "ETRIClient",
    "ETRIClientConfig",
    "RecognizeResult",
    "ResultRow",
    "WerPair",
    "analyze_audio",
    "batch_convert",
    "convert_to_etri_format",
    "get_audio_info",
    "is_already_target_format",
    "load_pairs",
    "run_batch",
]
