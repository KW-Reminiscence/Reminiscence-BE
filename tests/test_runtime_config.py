"""JSON-only runtime configuration parsing tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from reminiscence.runtime_config import (
    RuntimeConfigurationError,
    parse_runtime_settings,
)


def runtime(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "timezone": "Asia/Seoul",
        "public_origin": "https://reminiscence.leehyowon14.dev",
        "cors_origins": [],
        "routine_tick_seconds": 5,
        "evaluation_seconds": 60,
        "codex_lb": {"base_url": "https://codex.example/v1"},
        "supertonic": {
            "model_dir": "/models/supertonic-3",
            "auto_download": False,
        },
    }
    value.update(overrides)
    return {"runtime": value}


def test_parses_all_application_runtime_settings_from_json() -> None:
    settings = parse_runtime_settings(runtime(), require_explicit=True)

    assert settings.timezone == "Asia/Seoul"
    assert settings.routine_tick_seconds == 5
    assert settings.evaluation_seconds == 60
    assert settings.codex_lb.base_url == "https://codex.example/v1"
    assert settings.supertonic.model_dir == Path("/models/supertonic-3")
    assert settings.supertonic.auto_download is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"timezone": "Unknown/Zone"}, "timezone"),
        ({"public_origin": "https://example.com/path"}, "public_origin"),
        ({"routine_tick_seconds": 0}, "routine_tick_seconds"),
        ({"evaluation_seconds": float("inf")}, "evaluation_seconds"),
        ({"codex_lb": {"base_url": "ftp://example.com/v1"}}, "base_url"),
        ({"codex_lb": {"base_url": "http://example.com:bad/v1"}}, "base_url"),
        ({"codex_lb": {"base_url": "http://example.com:0/v1"}}, "base_url"),
        ({"supertonic": {"speed": 0.1}}, "speed"),
    ],
)
def test_rejects_invalid_runtime_json(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(RuntimeConfigurationError, match=message):
        parse_runtime_settings(runtime(**overrides), require_explicit=True)


def test_legacy_configuration_uses_safe_defaults_outside_preflight() -> None:
    settings = parse_runtime_settings({})

    assert settings.timezone == "Asia/Seoul"
    with pytest.raises(RuntimeConfigurationError, match="runtime is required"):
        parse_runtime_settings({}, require_explicit=True)
