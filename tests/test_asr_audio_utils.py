from pathlib import Path

import numpy as np
import soundfile as sf

from reminiscence.asr.audio_utils import (
    analyze_audio,
    batch_convert,
    convert_to_etri_format,
    get_audio_info,
    is_already_target_format,
    normalize_wav_bytes,
)


def _write_wav(path: Path, *, sample_rate: int, channels: int, amplitude: float = 0.5) -> None:
    duration_sec = 0.1
    samples = int(sample_rate * duration_sec)
    tone = amplitude * np.sin(2 * np.pi * 440 * np.arange(samples) / sample_rate)
    if channels > 1:
        tone = np.tile(tone[:, None], (1, channels))
    sf.write(str(path), tone, sample_rate, subtype="PCM_16")


def test_get_audio_info_reports_the_actual_spec(tmp_path: Path) -> None:
    wav_path = tmp_path / "mono_16k.wav"
    _write_wav(wav_path, sample_rate=16000, channels=1)

    info = get_audio_info(wav_path)

    assert info.sample_rate == 16000
    assert info.channels == 1
    assert info.subtype == "PCM_16"


def test_is_already_target_format_is_true_for_16k_mono_pcm16(tmp_path: Path) -> None:
    wav_path = tmp_path / "mono_16k.wav"
    _write_wav(wav_path, sample_rate=16000, channels=1)

    assert is_already_target_format(wav_path) is True


def test_is_already_target_format_is_false_for_other_sample_rates(tmp_path: Path) -> None:
    wav_path = tmp_path / "mono_8k.wav"
    _write_wav(wav_path, sample_rate=8000, channels=1)

    assert is_already_target_format(wav_path) is False


def test_is_already_target_format_is_false_for_missing_file(tmp_path: Path) -> None:
    assert is_already_target_format(tmp_path / "missing.wav") is False


def test_convert_to_etri_format_skips_conversion_when_already_target(tmp_path: Path) -> None:
    wav_path = tmp_path / "mono_16k.wav"
    _write_wav(wav_path, sample_rate=16000, channels=1)

    result_path = convert_to_etri_format(wav_path)

    assert result_path == wav_path


def test_convert_to_etri_format_resamples_and_downmixes(tmp_path: Path) -> None:
    wav_path = tmp_path / "stereo_44k.wav"
    _write_wav(wav_path, sample_rate=44100, channels=2)
    output_path = tmp_path / "converted.wav"

    result_path = convert_to_etri_format(wav_path, output_path)

    assert result_path == output_path
    info = get_audio_info(result_path)
    assert info.sample_rate == 16000
    assert info.channels == 1
    assert info.subtype == "PCM_16"


def test_convert_to_etri_format_raises_for_missing_input(tmp_path: Path) -> None:
    try:
        convert_to_etri_format(tmp_path / "missing.wav")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


def test_normalize_wav_bytes_resamples_without_creating_file(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "stereo_44k.wav"
    _write_wav(source_path, sample_rate=44100, channels=2)

    normalized = normalize_wav_bytes(source_path.read_bytes())
    output_path = tmp_path / "inspection.wav"
    output_path.write_bytes(normalized)

    info = get_audio_info(output_path)
    assert info.sample_rate == 16000
    assert info.channels == 1
    assert info.subtype == "PCM_16"


def test_normalize_wav_bytes_rejects_invalid_payload() -> None:
    try:
        normalize_wav_bytes(b"not-wav")
    except ValueError:
        return
    raise AssertionError("expected invalid WAV payload to fail")


def test_analyze_audio_flags_silence(tmp_path: Path) -> None:
    silent_path = tmp_path / "silent.wav"
    _write_wav(silent_path, sample_rate=16000, channels=1, amplitude=0.0)

    diagnostics = analyze_audio(silent_path)

    assert diagnostics.is_silent is True
    assert diagnostics.dbfs == float("-inf")


def test_analyze_audio_does_not_flag_normal_level_audio(tmp_path: Path) -> None:
    loud_path = tmp_path / "loud.wav"
    _write_wav(loud_path, sample_rate=16000, channels=1, amplitude=0.5)

    diagnostics = analyze_audio(loud_path)

    assert diagnostics.is_silent is False
    assert diagnostics.dbfs > -50.0


def test_batch_convert_only_processes_supported_extensions(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    _write_wav(input_dir / "a.wav", sample_rate=8000, channels=1)
    _write_wav(input_dir / "b.wav", sample_rate=8000, channels=1)
    (input_dir / "notes.txt").write_text("not audio", encoding="utf-8")

    converted = batch_convert(input_dir, output_dir)

    assert len(converted) == 2
    assert all(path.exists() for path in converted)
