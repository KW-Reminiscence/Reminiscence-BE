"""ETRI WiseASR speech recognition client with rate limiting, retries, and call logging.

ETRI API keys are typically limited to one concurrent request. Calls are
therefore serialized with a minimum interval, and transient failures (429/5xx,
connection errors) are retried with exponential backoff. Every call is logged
to a CSV (latency, HTTP status, failure reason) plus a per-call debug JSON
dump, so failure causes can be read from logs rather than guessed.
"""

from __future__ import annotations

import base64
import csv
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import urllib3
from dotenv import load_dotenv

from reminiscence.asr.audio_utils import analyze_audio, convert_to_etri_format
from reminiscence.asr.models import RecognizeResult

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "http://epretx.etri.re.kr:8000/api/WiseASR_Recognition"

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_CSV_FIELDNAMES = [
    "call_id",
    "audio_file",
    "request_time_utc",
    "response_time_utc",
    "latency_sec",
    "http_status",
    "recognized_text",
    "error_message",
    "fail_reason",
    "attempts",
]


@dataclass(frozen=True)
class ETRIClientConfig:
    """Runtime configuration for ETRIClient, normally sourced from environment variables."""

    api_key: str
    api_url: str = DEFAULT_API_URL
    min_request_interval_sec: float = 1.5
    max_retries: int = 3
    retry_backoff_base_sec: float = 2.0
    log_dir: Path = field(default_factory=lambda: Path("logs"))

    @classmethod
    def from_env(cls) -> ETRIClientConfig:
        """Build a config from ETRI_API_KEY and the optional ETRI_* tuning env vars."""
        load_dotenv()
        api_key = os.getenv("ETRI_API_KEY")
        if not api_key:
            raise OSError(
                "ETRI_API_KEY가 .env에 설정되어 있지 않습니다. "
                ".env 파일에 ETRI_API_KEY=발급받은키 를 추가하세요."
            )
        return cls(
            api_key=api_key,
            min_request_interval_sec=float(os.getenv("ETRI_MIN_INTERVAL_SEC", "1.5")),
            max_retries=int(os.getenv("ETRI_MAX_RETRIES", "3")),
            retry_backoff_base_sec=float(os.getenv("ETRI_RETRY_BACKOFF_SEC", "2.0")),
        )


def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]} (len={len(key)})"


class ETRIClient:
    """Calls the ETRI WiseASR recognition API and logs each call's latency to CSV."""

    def __init__(self, config: ETRIClientConfig, http: urllib3.PoolManager | None = None) -> None:
        self._config = config
        self._http = http if http is not None else urllib3.PoolManager()
        self._rate_limit_lock = threading.Lock()
        self._last_call_end_time = 0.0

    @classmethod
    def from_env(cls) -> ETRIClient:
        return cls(ETRIClientConfig.from_env())

    @property
    def log_file(self) -> Path:
        return self._config.log_dir / "latency_log.csv"

    @property
    def debug_dir(self) -> Path:
        return self._config.log_dir / "debug"

    def recognize_speech(
        self, audio_file_path: str | Path, *, auto_convert: bool = True
    ) -> RecognizeResult:
        """Recognize a single audio file via the ETRI ASR API, retrying transient failures."""
        audio_file_path = Path(audio_file_path)
        logger.debug("오디오 진단 중: %s", audio_file_path)

        target_path = convert_to_etri_format(audio_file_path) if auto_convert else audio_file_path

        audio_info = None
        audio_analysis_error = None
        try:
            audio_info = analyze_audio(target_path)
            if audio_info.is_silent:
                logger.warning("무음 의심: %s", target_path)
            logger.debug(
                "duration=%ss sr=%sHz ch=%s subtype=%s rms=%s dBFS=%s size=%sB",
                audio_info.duration_sec,
                audio_info.sample_rate,
                audio_info.channels,
                audio_info.subtype,
                audio_info.rms,
                audio_info.dbfs,
                audio_info.file_size_bytes,
            )
        except Exception as exc:
            audio_analysis_error = str(exc)
            logger.warning("오디오 분석 실패: %s", exc)

        raw_bytes = target_path.read_bytes()
        audio_contents = base64.b64encode(raw_bytes).decode("utf8")
        if base64.b64decode(audio_contents) != raw_bytes:
            logger.error("base64 왕복 검증 실패: %s", target_path)

        request_json: dict[str, Any] = {
            "argument": {
                "language_code": "korean",
                "audio": audio_contents,
            }
        }
        request_body = json.dumps(request_json)
        logger.debug("Authorization 헤더: %s", _mask_key(self._config.api_key))

        call_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        request_time = datetime.now(UTC)
        perf_start = time.perf_counter()

        http_status: int | None = None
        recognized_text = ""
        error_message = ""
        raw_response: dict[str, Any] = {}
        raw_response_text = ""
        success = False
        fail_reason = ""
        attempts = 0

        for attempt in range(1, self._config.max_retries + 2):
            attempts = attempt
            self._wait_for_rate_limit()
            logger.debug("API 호출 시도 %s/%s", attempt, self._config.max_retries + 1)

            try:
                response = self._http.request(
                    "POST",
                    self._config.api_url,
                    headers={
                        "Content-Type": "application/json; charset=UTF-8",
                        "Authorization": self._config.api_key,
                    },
                    body=request_body,
                    timeout=urllib3.Timeout(connect=10.0, read=30.0),
                )
                http_status = response.status
                raw_response_text = response.data.decode("utf-8", errors="replace")
                self._mark_call_end()
                logger.debug("HTTP Status: %s, Body: %s", http_status, raw_response_text[:1000])

                if http_status != 200:
                    error_message = raw_response_text[:300]
                    if http_status in _RETRYABLE_STATUSES and attempt <= self._config.max_retries:
                        wait = self._backoff_seconds(attempt)
                        fail_reason = (
                            f"HTTP {http_status}: {error_message or '(빈 응답)'} "
                            f"-> {wait:.1f}초 후 재시도"
                        )
                        logger.warning(fail_reason)
                        time.sleep(wait)
                        continue
                    fail_reason = f"HTTP {http_status}: {error_message or '(빈 응답)'}"
                    break

                try:
                    raw_response = json.loads(raw_response_text) if raw_response_text else {}
                except json.JSONDecodeError as exc:
                    error_message = f"JSON Parse Error: {exc}"
                    if attempt <= self._config.max_retries:
                        wait = self._backoff_seconds(attempt)
                        fail_reason = (
                            f"JSON Parse Error (raw body={raw_response_text[:200]!r}) "
                            f"-> {wait:.1f}초 후 재시도"
                        )
                        logger.warning(fail_reason)
                        time.sleep(wait)
                        continue
                    fail_reason = f"JSON Parse Error: {exc} (raw body={raw_response_text[:200]!r})"
                    break

                result_code = raw_response.get("result")
                reason_field = raw_response.get("reason")

                if result_code == 0:
                    recognized_text = raw_response.get("return_object", {}).get("recognized", "")
                    success = True
                    fail_reason = (
                        "Recognized empty (result=0이지만 인식된 텍스트가 빈 문자열 - "
                        "무음/짧은 음성 의심)"
                        if recognized_text.strip() == ""
                        else "OK"
                    )
                    break

                error_message = (
                    str(reason_field) if reason_field is not None else "unknown ETRI error"
                )
                fail_reason = f"ETRI Error (result={result_code}): {error_message}"
                break

            except urllib3.exceptions.HTTPError as exc:
                error_message = f"{type(exc).__name__}: {exc}"
                self._mark_call_end()
                if attempt <= self._config.max_retries:
                    wait = self._backoff_seconds(attempt)
                    fail_reason = f"Network/HTTP Error: {error_message} -> {wait:.1f}초 후 재시도"
                    logger.warning(fail_reason)
                    time.sleep(wait)
                    continue
                fail_reason = f"Network/HTTP Error: {error_message}"
                break

            except Exception as exc:
                error_message = f"{type(exc).__name__}: {exc}"
                fail_reason = f"Unexpected Error: {error_message}"
                self._mark_call_end()
                break

        perf_end = time.perf_counter()
        response_time = datetime.now(UTC)
        latency_sec = round(perf_end - perf_start, 3)

        logger.info(
            "인식 결과: success=%s fail_reason=%s latency=%ss", success, fail_reason, latency_sec
        )

        self._append_log(
            {
                "call_id": call_id,
                "audio_file": audio_file_path.name,
                "request_time_utc": request_time.isoformat(),
                "response_time_utc": response_time.isoformat(),
                "latency_sec": latency_sec,
                "http_status": http_status,
                "recognized_text": recognized_text,
                "error_message": error_message,
                "fail_reason": fail_reason,
                "attempts": attempts,
            }
        )

        self._dump_debug_json(
            call_id,
            audio_file_path,
            {
                "audio_file": audio_file_path.name,
                "request_json_meta": {
                    "language_code": request_json["argument"]["language_code"],
                    "audio_base64_len": len(audio_contents),
                    "audio_raw_bytes": len(raw_bytes),
                    "request_body_bytes": len(request_body),
                },
                "http_status": http_status,
                "raw_response_text": raw_response_text,
                "raw_response": raw_response,
                "audio_info": audio_info.model_dump() if audio_info else None,
                "audio_analysis_error": audio_analysis_error,
                "fail_reason": fail_reason,
                "attempts": attempts,
                "latency_sec": latency_sec,
            },
        )

        return RecognizeResult(
            success=success,
            text=recognized_text,
            latency_sec=latency_sec,
            http_status=http_status,
            raw_response=raw_response,
            raw_response_text=raw_response_text,
            fail_reason=fail_reason,
            audio_info=audio_info,
            audio_analysis_error=audio_analysis_error,
            attempts=attempts,
        )

    def _backoff_seconds(self, attempt: int) -> float:
        return self._config.retry_backoff_base_sec * (2.0 ** (attempt - 1))

    def _wait_for_rate_limit(self) -> None:
        with self._rate_limit_lock:
            elapsed = time.perf_counter() - self._last_call_end_time
            wait = self._config.min_request_interval_sec - elapsed
            if wait > 0:
                logger.debug("이전 호출 후 %.2f초 경과 -> %.2f초 대기", elapsed, wait)
                time.sleep(wait)

    def _mark_call_end(self) -> None:
        with self._rate_limit_lock:
            self._last_call_end_time = time.perf_counter()

    def _ensure_log_file(self) -> None:
        self._config.log_dir.mkdir(parents=True, exist_ok=True)
        if not self.log_file.exists():
            with self.log_file.open("w", newline="", encoding="utf-8-sig") as handle:
                csv.writer(handle).writerow(_CSV_FIELDNAMES)

    def _append_log(self, row: dict[str, Any]) -> None:
        self._ensure_log_file()
        with self.log_file.open("a", newline="", encoding="utf-8-sig") as handle:
            csv.DictWriter(handle, fieldnames=_CSV_FIELDNAMES).writerow(row)

    def _dump_debug_json(self, call_id: str, audio_file: Path, payload: dict[str, Any]) -> None:
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        path = self.debug_dir / f"{call_id}_{audio_file.stem}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
