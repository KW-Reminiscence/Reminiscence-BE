"""Batch-run ETRI ASR over a folder of audio files and write results.csv for WER/CER scoring.

Usage:
    1) Put test wav files in test_audio/.
    2) Run `python -m reminiscence.asr.run_baseline`.
    3) Fill in the "reference_text" column of results.csv by ear.
    4) Run `python -m reminiscence.asr.calc_wer` to compute WER/CER.
"""

from __future__ import annotations

import csv
import logging
from collections import Counter
from pathlib import Path

from reminiscence.asr.etri_client import ETRIClient
from reminiscence.asr.models import ResultRow

logger = logging.getLogger(__name__)

DEFAULT_TEST_AUDIO_DIR = Path("test_audio")
DEFAULT_RESULTS_FILE = Path("results.csv")

_SUPPORTED_EXTENSIONS = (".wav", ".mp3", ".m4a")
_RESULT_FIELDNAMES = [
    "audio_file",
    "recognized_text",
    "reference_text",
    "latency_sec",
    "success",
    "http_status",
    "attempts",
    "fail_reason",
    "duration_sec",
    "sample_rate",
    "channels",
    "subtype",
    "rms",
    "dbfs",
    "is_silent",
]


def run_batch(
    client: ETRIClient,
    test_dir: Path = DEFAULT_TEST_AUDIO_DIR,
    results_file: Path = DEFAULT_RESULTS_FILE,
) -> list[ResultRow]:
    """Recognize every audio file in test_dir and write a results.csv summary."""
    if not test_dir.exists():
        test_dir.mkdir(parents=True)
        logger.info(
            "'%s' 폴더를 새로 만들었습니다. 여기에 테스트용 오디오 파일을 넣고 다시 실행하세요.",
            test_dir,
        )
        return []

    audio_files = sorted(
        p for p in test_dir.iterdir() if p.suffix.lower() in _SUPPORTED_EXTENSIONS
    )
    if not audio_files:
        logger.warning("'%s' 폴더에 오디오 파일이 없습니다.", test_dir)
        return []

    logger.info("총 %d개 파일 처리 시작", len(audio_files))

    results: list[ResultRow] = []
    fail_reason_counter: Counter[str] = Counter()

    for index, file_path in enumerate(audio_files, start=1):
        logger.info("[%d/%d] 처리 중: %s", index, len(audio_files), file_path.name)
        result = client.recognize_speech(file_path)
        audio_info = result.audio_info

        logger.info(
            "%s: success=%s http_status=%s latency=%ss recognized=%r fail_reason=%s",
            file_path.name,
            result.success,
            result.http_status,
            result.latency_sec,
            result.text,
            result.fail_reason,
        )

        results.append(
            ResultRow(
                audio_file=file_path.name,
                recognized_text=result.text,
                reference_text="",
                latency_sec=result.latency_sec,
                success=result.success,
                http_status=result.http_status,
                attempts=result.attempts,
                fail_reason=result.fail_reason,
                duration_sec=audio_info.duration_sec if audio_info else None,
                sample_rate=audio_info.sample_rate if audio_info else None,
                channels=audio_info.channels if audio_info else None,
                subtype=audio_info.subtype if audio_info else None,
                rms=audio_info.rms if audio_info else None,
                dbfs=audio_info.dbfs if audio_info else None,
                is_silent=audio_info.is_silent if audio_info else None,
            )
        )

        if not result.success:
            category = result.fail_reason.split(":")[0].split(" ->")[0]
            fail_reason_counter[category] += 1

    with results_file.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=_RESULT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(results)

    success_count = sum(1 for r in results if r["success"])
    avg_latency = sum(r["latency_sec"] for r in results) / len(results)

    logger.info(
        "처리 완료: %d개 중 %d개 성공 (평균 레이턴시 %.3f초)",
        len(results),
        success_count,
        avg_latency,
    )
    logger.info("결과 저장 위치: %s", results_file)

    if len(results) - success_count > 0:
        for category, count in fail_reason_counter.most_common():
            logger.info("실패 원인 - %s: %d건", category, count)

    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = ETRIClient.from_env()
    run_batch(client)


if __name__ == "__main__":
    main()
