"""Opt-in synthesis test against real Supertonic 3 model weights."""

from __future__ import annotations

import os
from io import BytesIO

import pytest
import soundfile as sf

from reminiscence.tts import SupertonicConfig, SupertonicSynthesizer

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SUPERTONIC_SMOKE") != "1",
    reason="set RUN_SUPERTONIC_SMOKE=1 with a configured model directory",
)


def test_real_supertonic_synthesizes_playable_korean_wav() -> None:
    synthesizer = SupertonicSynthesizer(SupertonicConfig.from_environment())

    result = synthesizer.synthesize("오늘 사진을 보며 이야기 나눠 보실래요?")
    audio, sample_rate = sf.read(BytesIO(result.audio), dtype="float32")

    assert result.audio.startswith(b"RIFF")
    assert result.audio[8:12] == b"WAVE"
    assert sample_rate == result.sample_rate
    assert audio.size > 0
    assert 0 < result.duration_seconds < 60
