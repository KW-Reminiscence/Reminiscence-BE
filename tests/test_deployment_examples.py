"""Validation for checked-in runtime configuration examples."""

from __future__ import annotations

import shutil
from pathlib import Path

from reminiscence.conversation.photos import parse_photos
from reminiscence.routine.storage import JsonRoutineStore
from reminiscence.runtime_config import parse_runtime_settings
from reminiscence.storage import JsonObjectStore
from reminiscence.storage.documents import APPLIANCE_RUNTIME_DEFAULTS

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_configuration_example_covers_validated_settings() -> None:
    root = JsonObjectStore(
        PROJECT_ROOT / "deploy/configuration.example.json",
        schema_version=1,
        read_only=True,
        locking=False,
    ).read()

    settings = parse_runtime_settings(root, require_explicit=True)

    assert settings.timezone == "Asia/Seoul"
    assert settings.public_origin == "https://reminiscence.leehyowon14.dev"
    assert settings.codex_lb.base_url == "https://codex-api.leehyowon14.dev/v1"
    assert settings.supertonic.model_dir == Path("/models/supertonic-3")
    assert root["runtime"] == APPLIANCE_RUNTIME_DEFAULTS
    assert not (PROJECT_ROOT / "deploy/runtime.env.example").exists()


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
