"""Container preflight and command handoff tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reminiscence.auth.secrets import ApplicationSecretsError
from reminiscence.preflight import run_preflight
from reminiscence.storage.migration import migrate_data_directory


def write_secret_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def configure_valid_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    migrate_data_directory(tmp_path, apply=True)
    configuration_path = tmp_path / "configuration.json"
    configuration = json.loads(configuration_path.read_text(encoding="utf-8"))
    configuration["runtime"] = {
        "timezone": "Asia/Seoul",
        "public_origin": "https://reminiscence.leehyowon14.dev",
        "cors_origins": [],
        "routine_tick_seconds": 5,
        "evaluation_seconds": 60,
        "codex_lb": {"base_url": "https://codex.example/v1"},
        "supertonic": {"model_dir": "/models/supertonic-3", "auto_download": False},
    }
    configuration_path.write_text(json.dumps(configuration), encoding="utf-8")
    application_secrets = tmp_path / "application-secrets.json"
    notification_config = tmp_path / "notification-config.json"
    write_secret_json(
        application_secrets,
        {
            "schema_version": 1,
            "guardian_password": "guardian-password",
            "tablet_pairing_code": "pairing-code",
            "codex_lb_api_key": "codex-lb-key",
        },
    )
    write_secret_json(
        notification_config,
        {
            "schema_version": 1,
            "care_recipient": {"name": "홍길동"},
            "guardian": {"email": "guardian@example.com"},
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "username": "sender@example.com",
                "app_password": "smtp-password",
                "from_name": "Reminiscence",
            },
        },
    )
    monkeypatch.setenv("REMINISCENCE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("REMINISCENCE_SECRETS_PATH", str(application_secrets))
    monkeypatch.setenv("NOTIFICATION_CONFIG_PATH", str(notification_config))
    return application_secrets


def test_preflight_executes_command_only_after_all_json_is_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_valid_runtime(tmp_path, monkeypatch)
    executed: list[tuple[str, list[str]]] = []

    result = run_preflight(
        ["uvicorn", "reminiscence.main:app"],
        executor=lambda executable, command: executed.append((executable, command)),
    )

    assert result == 0
    assert executed == [
        ("uvicorn", ["uvicorn", "reminiscence.main:app"]),
    ]


def test_preflight_without_command_is_a_validation_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_valid_runtime(tmp_path, monkeypatch)

    assert run_preflight([]) == 0


def test_preflight_never_executes_after_invalid_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_path = configure_valid_runtime(tmp_path, monkeypatch)
    secret_path.chmod(0o644)
    executed: list[str] = []

    with pytest.raises(ApplicationSecretsError, match="0600"):
        run_preflight(
            ["uvicorn"],
            executor=lambda executable, command: executed.append(executable),
        )

    assert executed == []
