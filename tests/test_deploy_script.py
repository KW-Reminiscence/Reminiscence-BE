"""Static validation for deployment safety checks."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_deploy_script_runs_real_supertonic_smoke() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    assert "get_speech_synthesizer().synthesize" in deploy_script
    assert "result.audio[:4] == b'RIFF'" in deploy_script


def test_deploy_script_wires_required_application_secret() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    assert (
        'application_secrets_file="${deployment_directory}/application-secrets.json"'
        in deploy_script
    )
    assert "printf 'APPLICATION_SECRETS_FILE=%s\\n'" in deploy_script
    assert '[[ ! -f "${application_secrets_file}" ]]' in deploy_script
    assert "deploy/application-secrets.example.json" in deploy_script


def test_compose_mounts_writable_supertonic_parent_directory() -> None:
    compose = (PROJECT_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")

    assert "HF_HOME:" not in compose
    assert "SUPERTONIC_MODEL_DIR:" not in compose
    assert "        target: /models\n" in compose
    assert "        target: /models/supertonic-3\n" not in compose


def test_container_start_uses_strict_preflight_and_readiness() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")

    assert "USER app" in dockerfile
    assert '"reminiscence.preflight", "uvicorn"' in dockerfile
    assert "      - reminiscence.preflight" in compose
    assert "/api/health/ready" in dockerfile
    assert "/api/health/ready" in compose
