"""Validation for checked-in runtime configuration examples."""

from __future__ import annotations

import shutil
from pathlib import Path

from reminiscence.conversation.photos import parse_photos
from reminiscence.routine.storage import JsonRoutineStore
from reminiscence.storage import JsonObjectStore

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
        "CODEX_LB_API_KEY",
        "CODEX_LB_BASE_URL",
        "CODEX_LB_CONNECT_TIMEOUT_SECONDS",
        "CODEX_LB_READ_TIMEOUT_SECONDS",
        "CODEX_LB_RESPONSE_MODEL",
        "CODEX_LB_RESPONSE_READ_TIMEOUT_SECONDS",
        "REMINISCENCE_PUBLIC_ORIGIN",
        "REMINISCENCE_ROUTINE_TICK_SECONDS",
        "REMINISCENCE_EVALUATION_SECONDS",
        "SUPERTONIC_AUTO_DOWNLOAD",
        "SUPERTONIC_MAX_TEXT_CHARS",
    } <= names
    assert not {
        "ETRI_API_KEY",
        "ETRI_ASR_URL",
    } & names


def test_configuration_example_is_accepted_by_routine_store(
    tmp_path: Path,
) -> None:
    configuration_path = tmp_path / "configuration.json"
    shutil.copyfile(
        PROJECT_ROOT / "deploy/configuration.example.json",
        configuration_path,
    )
    definitions = JsonRoutineStore(
        configuration_path,
        tmp_path / "activity_metrics.json",
    ).load_definitions()

    assert len(definitions) == 2
    assert all(definition.active for definition in definitions)


def test_configuration_example_contains_valid_photo_memories() -> None:
    configuration = JsonObjectStore(
        PROJECT_ROOT / "deploy/configuration.example.json",
        schema_version=1,
        read_only=True,
        locking=False,
    ).read()

    photos = parse_photos(configuration["photos"])

    assert len(photos) == 1
    assert photos[0].photo_id == "family-photo-1"
    assert photos[0].location == "제주도 성산일출봉"
    assert photos[0].people == ("딸 영희", "손자 민준")
