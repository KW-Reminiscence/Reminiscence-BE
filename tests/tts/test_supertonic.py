"""Supertonic 3 configuration and in-memory WAV synthesis tests."""

from __future__ import annotations

from io import BytesIO
from math import inf, nan
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from numpy.typing import NDArray

from reminiscence.tts import (
    SpeechSynthesisUnavailableError,
    SupertonicConfig,
    SupertonicSynthesizer,
)


class FakeEngine:
    sample_rate = 44_100

    def __init__(self) -> None:
        self.voice_name: str | None = None
        self.calls: list[tuple[str, int, float, str | None]] = []

    def get_voice_style(self, voice_name: str) -> object:
        self.voice_name = voice_name
        return {"voice": voice_name}

    def synthesize(
        self,
        text: str,
        voice_style: object,
        total_steps: int = 8,
        speed: float = 1.05,
        max_chunk_length: int | None = None,
        silence_duration: float = 0.3,
        lang: str | None = None,
        verbose: bool = False,
    ) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        del voice_style, max_chunk_length, silence_duration, verbose
        self.calls.append((text, total_steps, speed, lang))
        waveform = np.zeros((1, self.sample_rate), dtype=np.float32)
        return waveform, np.asarray([1.0], dtype=np.float32)


def test_synthesizer_returns_pcm_wav_without_writing_audio(
    tmp_path: Path,
) -> None:
    engine = FakeEngine()
    synthesizer = SupertonicSynthesizer(
        SupertonicConfig(
            model_dir=tmp_path / "model",
            auto_download=False,
            voice="F1",
            speed=0.9,
        ),
        engine_factory=lambda **_: engine,
    )

    result = synthesizer.synthesize("  안녕하세요.  ")

    assert engine.voice_name == "F1"
    assert engine.calls == [("안녕하세요.", 8, 0.9, "ko")]
    assert result.audio.startswith(b"RIFF")
    assert result.duration_seconds == 1.0
    assert result.sample_rate == 44_100
    assert result.engine == "supertonic-3"
    audio, sample_rate = sf.read(
        file=BytesIO(result.audio),
        dtype="float32",
    )
    assert sample_rate == 44_100
    assert audio.shape == (44_100,)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "text must not be blank"),
        ("   ", "text must not be blank"),
        ("가나다라", "text must not exceed 3 characters"),
    ],
)
def test_synthesizer_rejects_invalid_text(text: str, message: str) -> None:
    synthesizer = SupertonicSynthesizer(
        SupertonicConfig(max_text_chars=3),
        engine_factory=lambda **_: FakeEngine(),
    )

    with pytest.raises(ValueError, match=message):
        synthesizer.synthesize(text)


def test_synthesizer_rejects_invalid_waveform() -> None:
    engine = FakeEngine()

    def invalid_synthesis(
        text: str,
        voice_style: object,
        total_steps: int = 8,
        speed: float = 1.05,
        max_chunk_length: int | None = None,
        silence_duration: float = 0.3,
        lang: str | None = None,
        verbose: bool = False,
    ) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        del (
            text,
            voice_style,
            total_steps,
            speed,
            max_chunk_length,
            silence_duration,
            lang,
            verbose,
        )
        return (
            np.asarray([np.nan], dtype=np.float32),
            np.asarray([0.0], dtype=np.float32),
        )

    engine.synthesize = invalid_synthesis  # type: ignore[method-assign]
    synthesizer = SupertonicSynthesizer(
        SupertonicConfig(),
        engine_factory=lambda **_: engine,
    )

    with pytest.raises(
        SpeechSynthesisUnavailableError,
        match="synthesis failed",
    ):
        synthesizer.synthesize("안내")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("total_steps", True, "total_steps"),
        ("speed", nan, "speed"),
        ("speed", inf, "speed"),
        ("speed", -inf, "speed"),
        ("max_text_chars", True, "max_text_chars"),
        ("max_text_chars", 501, "max_text_chars"),
        ("intra_op_num_threads", True, "intra_op_num_threads"),
        ("inter_op_num_threads", 0, "inter_op_num_threads"),
    ],
)
def test_config_rejects_invalid_runtime_values(
    field: str,
    value: object,
    message: str,
) -> None:
    values: dict[str, object] = {field: value}

    with pytest.raises(ValueError, match=message):
        SupertonicConfig(**values)  # type: ignore[arg-type]


def test_synthesizer_rejects_invalid_sample_rate() -> None:
    engine = FakeEngine()
    engine.sample_rate = 0
    synthesizer = SupertonicSynthesizer(
        SupertonicConfig(),
        engine_factory=lambda **_: engine,
    )

    with pytest.raises(
        SpeechSynthesisUnavailableError,
        match="synthesis failed",
    ):
        synthesizer.synthesize("안내")
