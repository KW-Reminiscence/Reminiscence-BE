import csv
from pathlib import Path

from reminiscence.asr.calc_wer import load_pairs

_FIELDNAMES = [
    "audio_file",
    "recognized_text",
    "reference_text",
    "success",
]


def _write_results_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def test_load_pairs_keeps_only_successful_rows_with_a_reference(tmp_path: Path) -> None:
    results_file = tmp_path / "results.csv"
    _write_results_csv(
        results_file,
        [
            {
                "audio_file": "a.wav",
                "recognized_text": "안녕",
                "reference_text": "안녕하세요",
                "success": "True",
            },
            {
                "audio_file": "b.wav",
                "recognized_text": "",
                "reference_text": "",
                "success": "False",
            },
            {
                "audio_file": "c.wav",
                "recognized_text": "정답 없음",
                "reference_text": "",
                "success": "True",
            },
        ],
    )

    pairs, skipped_no_reference, skipped_failed = load_pairs(results_file)

    assert len(pairs) == 1
    assert pairs[0]["audio_file"] == "a.wav"
    assert pairs[0]["reference"] == "안녕하세요"
    assert pairs[0]["hypothesis"] == "안녕"
    assert skipped_failed == 1
    assert skipped_no_reference == 1


def test_load_pairs_returns_empty_list_when_nothing_qualifies(tmp_path: Path) -> None:
    results_file = tmp_path / "results.csv"
    _write_results_csv(
        results_file,
        [{"audio_file": "a.wav", "recognized_text": "x", "reference_text": "", "success": "True"}],
    )

    pairs, skipped_no_reference, skipped_failed = load_pairs(results_file)

    assert pairs == []
    assert skipped_no_reference == 1
    assert skipped_failed == 0
