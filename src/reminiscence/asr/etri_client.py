"""Offline file adapter over the privacy-preserving in-memory ETRI client."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import urllib3
from dotenv import load_dotenv

from reminiscence.asr.audio_utils import analyze_audio, convert_to_etri_format
from reminiscence.asr.etri import (
    DEFAULT_API_URL,
    EtriRecognizer,
    EtriRecognizerConfig,
)
from reminiscence.asr.models import (
    RecognitionUnavailableError,
    RecognizeResult,
)


@dataclass(frozen=True, slots=True)
class ETRIClientConfig:
    """Compatibility configuration for the explicit offline baseline runner."""

    api_key: str
    api_url: str = DEFAULT_API_URL
    min_request_interval_sec: float = 1.5
    max_retries: int = 3
    retry_backoff_base_sec: float = 2.0
    log_dir: Path = field(default_factory=lambda: Path("logs"))

    @classmethod
    def from_env(cls) -> ETRIClientConfig:
        """Load the baseline credential without affecting the API runtime."""

        load_dotenv()
        api_key = os.getenv("ETRI_API_KEY")
        if not api_key:
            raise OSError("ETRI_API_KEY가 설정되어 있지 않습니다")
        return cls(
            api_key=api_key,
            api_url=os.getenv("ETRI_ASR_URL", DEFAULT_API_URL),
            min_request_interval_sec=float(
                os.getenv("ETRI_MIN_INTERVAL_SECONDS", "1.5")
            ),
            max_retries=int(os.getenv("ETRI_MAX_RETRIES", "3")),
            retry_backoff_base_sec=float(
                os.getenv("ETRI_RETRY_BACKOFF_SECONDS", "2.0")
            ),
        )


class ETRIClient:
    """Retain the contributor's file-based baseline API without debug retention."""

    def __init__(
        self,
        config: ETRIClientConfig,
        http: urllib3.PoolManager | None = None,
    ) -> None:
        self._config = config
        self._recognizer = EtriRecognizer(
            EtriRecognizerConfig(
                api_key=config.api_key,
                api_url=config.api_url,
                min_request_interval_seconds=config.min_request_interval_sec,
                max_retries=config.max_retries,
                retry_backoff_seconds=config.retry_backoff_base_sec,
            ),
            http=http,
        )

    @classmethod
    def from_env(cls) -> ETRIClient:
        return cls(ETRIClientConfig.from_env())

    def recognize_speech(
        self,
        audio_file_path: str | Path,
        *,
        auto_convert: bool = True,
    ) -> RecognizeResult:
        """Run one explicit baseline file without implicit logs or debug dumps."""

        source_path = Path(audio_file_path)
        target_path = (
            convert_to_etri_format(source_path)
            if auto_convert
            else source_path
        )
        diagnostics = None
        diagnostics_error = None
        try:
            diagnostics = analyze_audio(target_path)
        except Exception as exc:
            diagnostics_error = str(exc)
        try:
            result = self._recognizer.recognize(
                target_path.read_bytes(),
                "audio/wav",
            )
        except RecognitionUnavailableError as exc:
            return RecognizeResult(
                success=False,
                text="",
                latency_sec=0.0,
                http_status=None,
                fail_reason=str(exc),
                audio_info=diagnostics,
                audio_analysis_error=diagnostics_error,
                attempts=self._config.max_retries + 1,
            )
        return RecognizeResult(
            success=True,
            text=result.transcript,
            latency_sec=result.latency_seconds,
            http_status=result.http_status,
            fail_reason="OK",
            audio_info=diagnostics,
            audio_analysis_error=diagnostics_error,
            attempts=result.attempts,
        )
