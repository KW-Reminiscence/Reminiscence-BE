"""Serialized, in-memory Supertonic 3 synthesis for Raspberry Pi."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from math import isfinite
from pathlib import Path
from typing import Protocol, cast

import numpy as np
import soundfile as sf
from numpy.typing import NDArray

from reminiscence.tts.models import (
    SpeechSynthesisResult,
    SpeechSynthesisUnavailableError,
)

SUPERTONIC_MODEL = "supertonic-3"
DEFAULT_VOICE = "F1"
DEFAULT_LANGUAGE = "ko"
DEFAULT_TOTAL_STEPS = 8
DEFAULT_SPEED = 0.9
DEFAULT_MAX_TEXT_CHARS = 500


class _SupertonicEngine(Protocol):
    """Subset of the official SDK used by the application."""

    sample_rate: int

    def get_voice_style(self, voice_name: str) -> object:
        """Load one bundled or custom voice style."""

        ...

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
        """Generate waveform and duration arrays."""

        ...


EngineFactory = Callable[..., _SupertonicEngine]


def _parse_boolean_environment(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


def _optional_positive_integer(name: str) -> int | None:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class SupertonicConfig:
    """Validated local model and voice settings."""

    model_dir: Path | None = None
    auto_download: bool = True
    voice: str = DEFAULT_VOICE
    language: str = DEFAULT_LANGUAGE
    total_steps: int = DEFAULT_TOTAL_STEPS
    speed: float = DEFAULT_SPEED
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS
    intra_op_num_threads: int | None = None
    inter_op_num_threads: int | None = None

    def __post_init__(self) -> None:
        if not self.voice.strip():
            raise ValueError("voice must not be blank")
        if self.language != DEFAULT_LANGUAGE:
            raise ValueError("language must be ko")
        if (
            not isinstance(self.total_steps, int)
            or isinstance(self.total_steps, bool)
            or not 5 <= self.total_steps <= 12
        ):
            raise ValueError("total_steps must be between 5 and 12")
        if not isfinite(self.speed) or not 0.7 <= self.speed <= 2.0:
            raise ValueError("speed must be between 0.7 and 2.0")
        if (
            not isinstance(self.max_text_chars, int)
            or isinstance(self.max_text_chars, bool)
            or not 1 <= self.max_text_chars <= DEFAULT_MAX_TEXT_CHARS
        ):
            raise ValueError(
                f"max_text_chars must be between 1 and {DEFAULT_MAX_TEXT_CHARS}"
            )
        for field_name, value in (
            ("intra_op_num_threads", self.intra_op_num_threads),
            ("inter_op_num_threads", self.inter_op_num_threads),
        ):
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"{field_name} must be positive")

    @classmethod
    def from_environment(cls) -> SupertonicConfig:
        """Read Raspberry Pi model settings without loading the model."""

        model_dir_value = os.environ.get("SUPERTONIC_MODEL_DIR", "").strip()
        try:
            total_steps = int(
                os.environ.get(
                    "SUPERTONIC_TOTAL_STEPS",
                    str(DEFAULT_TOTAL_STEPS),
                )
            )
            speed = float(
                os.environ.get("SUPERTONIC_SPEED", str(DEFAULT_SPEED))
            )
            max_text_chars = int(
                os.environ.get(
                    "SUPERTONIC_MAX_TEXT_CHARS",
                    str(DEFAULT_MAX_TEXT_CHARS),
                )
            )
        except ValueError as exc:
            raise RuntimeError(
                "Supertonic numeric environment values are invalid"
            ) from exc
        return cls(
            model_dir=Path(model_dir_value) if model_dir_value else None,
            auto_download=_parse_boolean_environment(
                "SUPERTONIC_AUTO_DOWNLOAD",
                True,
            ),
            voice=os.environ.get("SUPERTONIC_VOICE", DEFAULT_VOICE),
            language=os.environ.get(
                "SUPERTONIC_LANGUAGE",
                DEFAULT_LANGUAGE,
            ),
            total_steps=total_steps,
            speed=speed,
            max_text_chars=max_text_chars,
            intra_op_num_threads=_optional_positive_integer(
                "SUPERTONIC_INTRA_OP_THREADS"
            ),
            inter_op_num_threads=_optional_positive_integer(
                "SUPERTONIC_INTER_OP_THREADS"
            ),
        )


def _official_engine_factory(**kwargs: object) -> _SupertonicEngine:
    from supertonic import TTS

    return cast(_SupertonicEngine, TTS(**kwargs))


class SupertonicSynthesizer:
    """Generate Korean WAV audio locally through one serialized ONNX session."""

    def __init__(
        self,
        config: SupertonicConfig,
        *,
        engine_factory: EngineFactory = _official_engine_factory,
    ) -> None:
        self._config = config
        try:
            self._engine = engine_factory(
                model=SUPERTONIC_MODEL,
                model_dir=config.model_dir,
                auto_download=config.auto_download,
                intra_op_num_threads=config.intra_op_num_threads,
                inter_op_num_threads=config.inter_op_num_threads,
            )
            self._voice_style = self._engine.get_voice_style(config.voice)
        except Exception as exc:
            raise SpeechSynthesisUnavailableError(
                "failed to load Supertonic 3"
            ) from exc
        self._synthesis_lock = threading.Lock()

    @property
    def max_text_chars(self) -> int:
        """Maximum request length accepted by this instance."""

        return self._config.max_text_chars

    def synthesize(self, text: str) -> SpeechSynthesisResult:
        """Synthesize one Korean utterance and encode it as PCM 16-bit WAV."""

        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError("text must not be blank")
        if len(normalized_text) > self._config.max_text_chars:
            raise ValueError(
                f"text must not exceed {self._config.max_text_chars} characters"
            )
        try:
            with self._synthesis_lock:
                waveform, _ = self._engine.synthesize(
                    normalized_text,
                    voice_style=self._voice_style,
                    total_steps=self._config.total_steps,
                    speed=self._config.speed,
                    lang=self._config.language,
                    verbose=False,
                )
            samples = np.asarray(waveform, dtype=np.float32).reshape(-1)
            if samples.size == 0 or not np.isfinite(samples).all():
                raise ValueError("Supertonic returned an invalid waveform")
            sample_rate = self._engine.sample_rate
            if (
                not isinstance(sample_rate, int)
                or isinstance(sample_rate, bool)
                or sample_rate <= 0
            ):
                raise ValueError("Supertonic returned an invalid sample rate")
            audio_buffer = BytesIO()
            sf.write(
                audio_buffer,
                samples,
                sample_rate,
                format="WAV",
                subtype="PCM_16",
            )
        except Exception as exc:
            raise SpeechSynthesisUnavailableError(
                "Supertonic 3 synthesis failed"
            ) from exc
        return SpeechSynthesisResult(
            audio=audio_buffer.getvalue(),
            duration_seconds=round(
                samples.size / sample_rate,
                3,
            ),
            sample_rate=sample_rate,
            engine=SUPERTONIC_MODEL,
        )
