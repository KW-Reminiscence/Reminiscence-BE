"""Convert audio files to the ETRI ASR required format (16kHz, mono, 16-bit PCM WAV).

Uses soundfile + scipy only (no ffmpeg): the project's audio sources (AI Hub
datasets, team members' laptop mic recordings, Raspberry Pi mic input) are all
WAV-family formats, so decoding compressed formats like mp3/aac is unnecessary.
Avoiding ffmpeg keeps setup to `pip install` across platforms, including
Raspberry Pi.
"""

from __future__ import annotations

import logging
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from numpy.typing import NDArray
from scipy.signal import resample_poly

from reminiscence.asr.models import AudioDiagnostics, AudioInfo

logger = logging.getLogger(__name__)

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
TARGET_SUBTYPE = "PCM_16"

_SUPPORTED_EXTENSIONS = (".wav", ".flac", ".ogg")
_SILENCE_DBFS_THRESHOLD = -50.0


def get_audio_info(file_path: str | Path) -> AudioInfo:
    """Read the current spec of an audio file (used to skip unnecessary conversion)."""
    info = sf.info(str(file_path))
    return AudioInfo(
        sample_rate=info.samplerate,
        channels=info.channels,
        subtype=info.subtype,
        duration_sec=info.duration,
    )


def analyze_audio(file_path: str | Path) -> AudioDiagnostics:
    """Diagnose whether an audio file itself is the problem (silence, corruption, odd spec).

    dBFS is relative to 16-bit PCM full scale; below -50dBFS is treated as
    effectively silent (typical conversational speech sits around -30~-15dBFS).
    """
    file_path = Path(file_path)
    info = sf.info(str(file_path))
    data, _ = sf.read(str(file_path), dtype="float64", always_2d=False)
    mono = _to_mono(np.asarray(data, dtype=np.float64))

    rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
    dbfs = 20 * np.log10(rms) if rms > 0 else float("-inf")
    max_amplitude = float(np.max(np.abs(mono))) if mono.size else 0.0
    is_silent = dbfs < _SILENCE_DBFS_THRESHOLD

    return AudioDiagnostics(
        duration_sec=round(info.duration, 3),
        sample_rate=info.samplerate,
        channels=info.channels,
        subtype=info.subtype,
        rms=round(rms, 6),
        dbfs=round(dbfs, 2),
        max_amplitude=round(max_amplitude, 6),
        file_size_bytes=file_path.stat().st_size,
        is_silent=bool(is_silent),
    )


def is_already_target_format(file_path: str | Path) -> bool:
    """Return True if the file is already 16kHz/mono/PCM_16, to skip re-conversion."""
    try:
        info = get_audio_info(file_path)
    except Exception:
        logger.warning("오디오 포맷 확인 실패, 변환이 필요한 것으로 간주합니다: %s", file_path)
        return False
    return (
        info.sample_rate == TARGET_SAMPLE_RATE
        and info.channels == TARGET_CHANNELS
        and info.subtype == TARGET_SUBTYPE
    )


def _to_mono(audio: NDArray[np.float64]) -> NDArray[np.float64]:
    """Average multi-channel audio down to mono; mono input is returned unchanged."""
    if audio.ndim == 1:
        return audio
    return np.asarray(audio.mean(axis=1), dtype=np.float64)


def _resample(audio: NDArray[np.float64], orig_sr: int, target_sr: int) -> NDArray[np.float64]:
    """Resample with scipy's polyphase filter (fewer edge artifacts than FFT resampling)."""
    if orig_sr == target_sr:
        return audio

    divisor = gcd(orig_sr, target_sr)
    up = target_sr // divisor
    down = orig_sr // divisor
    return np.asarray(resample_poly(audio, up, down), dtype=np.float64)


def convert_to_etri_format(input_path: str | Path, output_path: str | Path | None = None) -> Path:
    """Convert an input audio file to the ETRI-required format (16kHz, mono, 16-bit PCM WAV).

    Args:
        input_path: Source audio file (wav, flac, ogg, or another libsndfile-supported format).
        output_path: Destination path. Defaults to "{input_stem}_16k.wav" next to the input.

    Returns:
        Path to the converted file, or the original path if it was already in the target format.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"입력 파일을 찾을 수 없습니다: {input_path}")

    resolved_output_path = (
        Path(output_path)
        if output_path is not None
        else input_path.with_name(f"{input_path.stem}_16k.wav")
    )

    if is_already_target_format(input_path):
        logger.info("이미 16kHz/mono/PCM_16 포맷입니다. 변환 생략: %s", input_path)
        return input_path

    audio, orig_sr = sf.read(str(input_path), dtype="float64")
    audio = _to_mono(np.asarray(audio, dtype=np.float64))
    audio = _resample(audio, orig_sr, TARGET_SAMPLE_RATE)
    audio = np.clip(audio, -1.0, 1.0)
    sf.write(str(resolved_output_path), audio, TARGET_SAMPLE_RATE, subtype=TARGET_SUBTYPE)

    logger.info(
        "변환 완료: %s (%sHz) -> %s (%sHz, mono, PCM_16) [ffmpeg 미사용]",
        input_path,
        orig_sr,
        resolved_output_path,
        TARGET_SAMPLE_RATE,
    )
    return resolved_output_path


def batch_convert(input_dir: str | Path, output_dir: str | Path) -> list[Path]:
    """Convert every supported audio file (.wav/.flac/.ogg) in a folder.

    mp3/m4a are skipped since libsndfile generally cannot read them directly;
    AI Hub datasets are provided as wav, so this is not a current limitation.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    converted_files: list[Path] = []
    for entry in sorted(input_dir.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            continue
        output_path = output_dir / f"{entry.stem}_16k.wav"
        try:
            converted_files.append(convert_to_etri_format(entry, output_path))
        except Exception:
            logger.exception("변환 실패: %s", entry.name)

    return converted_files
