"""Compute WER/CER from a run_baseline results.csv using jiwer.

Rows without a filled-in reference_text, and rows where the ETRI call itself
failed (success=False), are excluded from the WER calculation (and counted
separately) so failures don't distort the accuracy metric.

Usage:
    python -m reminiscence.asr.calc_wer
    python -m reminiscence.asr.calc_wer --results results.csv
"""

from __future__ import annotations

import argparse
import csv
import importlib
import logging
from pathlib import Path
from typing import Any, cast

from reminiscence.asr.models import WerPair

logger = logging.getLogger(__name__)

DEFAULT_RESULTS_FILE = Path("results.csv")


def _load_jiwer() -> Any:
    try:
        return importlib.import_module("jiwer")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "WER/CER 계산에는 evaluation dependency group이 필요합니다"
        ) from exc


def _cer(reference: str | list[str], hypothesis: str | list[str]) -> float:
    """Wrap jiwer.cer(); its return type is a union only due to a deprecated return_dict flag."""
    jiwer = _load_jiwer()
    return cast(float, jiwer.cer(reference, hypothesis))


def load_pairs(results_file: Path) -> tuple[list[WerPair], int, int]:
    """Extract (reference, hypothesis) pairs, skipping rows without a reference or a failed call."""
    pairs: list[WerPair] = []
    skipped_no_reference = 0
    skipped_failed = 0

    with results_file.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            reference = (row.get("reference_text") or "").strip()
            success = (row.get("success") or "").strip().lower() in ("true", "1")

            if not success:
                skipped_failed += 1
                continue
            if not reference:
                skipped_no_reference += 1
                continue

            pairs.append(
                WerPair(
                    audio_file=row.get("audio_file") or "",
                    reference=reference,
                    hypothesis=(row.get("recognized_text") or "").strip(),
                )
            )

    return pairs, skipped_no_reference, skipped_failed


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="results.csv 기반 WER/CER 계산")
    parser.add_argument(
        "--results", type=Path, default=DEFAULT_RESULTS_FILE, help="results.csv 경로"
    )
    args = parser.parse_args(argv)

    pairs, skipped_no_reference, skipped_failed = load_pairs(args.results)

    logger.info("입력 파일: %s", args.results)
    logger.info("WER 계산 대상: %d건", len(pairs))
    logger.info("제외 - success=False: %d건", skipped_failed)
    logger.info("제외 - reference_text 미기입: %d건", skipped_no_reference)

    if not pairs:
        logger.warning(
            "WER을 계산할 수 있는 행이 없습니다. "
            "results.csv에서 success=True인 행의 'reference_text' 컬럼을 먼저 채워주세요."
        )
        return

    references = [pair["reference"] for pair in pairs]
    hypotheses = [pair["hypothesis"] for pair in pairs]

    jiwer = _load_jiwer()
    wer = jiwer.wer(references, hypotheses)
    cer = _cer(references, hypotheses)

    logger.info("전체 WER (Word Error Rate): %.4f (%.2f%%)", wer, wer * 100)
    logger.info("전체 CER (Character Error Rate): %.4f (%.2f%%)", cer, cer * 100)

    for pair in pairs:
        file_wer = jiwer.wer(pair["reference"], pair["hypothesis"])
        file_cer = _cer(pair["reference"], pair["hypothesis"])
        logger.info(
            "%s: WER=%.3f CER=%.3f 정답=%r 인식=%r",
            pair["audio_file"],
            file_wer,
            file_cer,
            pair["reference"],
            pair["hypothesis"],
        )


if __name__ == "__main__":
    main()
