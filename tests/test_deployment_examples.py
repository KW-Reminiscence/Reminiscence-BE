"""Validation for checked-in runtime configuration examples."""

from __future__ import annotations

from pathlib import Path

from reminiscence.routine.storage import JsonRoutineStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_environment_example_covers_validated_settings() -> None:
    names = {
        line.split("=", maxsplit=1)[0]
        for line in (
            PROJECT_ROOT / "deploy/runtime.env.example"
        ).read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    }

    assert {
        "ETRI_API_KEY",
        "ETRI_CONNECT_TIMEOUT_SECONDS",
        "ETRI_READ_TIMEOUT_SECONDS",
        "REMINISCENCE_ANOMALY_CONFIRMATION_COUNT",
        "REMINISCENCE_ROUTINE_TICK_SECONDS",
        "REMINISCENCE_EVALUATION_SECONDS",
        "SUPERTONIC_AUTO_DOWNLOAD",
        "SUPERTONIC_MAX_TEXT_CHARS",
    } <= names


def test_configuration_example_is_accepted_by_routine_store(
    tmp_path: Path,
) -> None:
    definitions = JsonRoutineStore(
        PROJECT_ROOT / "deploy/configuration.example.json",
        tmp_path / "activity_metrics.json",
    ).load_definitions()

    assert len(definitions) == 2
    assert all(definition.active for definition in definitions)
