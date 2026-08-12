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
    assert "NOTIFICATION_CONFIG_FILE" not in compose
    assert "NOTIFICATION_CONFIG_PATH" not in compose


def test_compose_uses_one_digest_reference_per_release_component() -> None:
    compose = (PROJECT_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")

    assert "image: ${API_IMAGE_REFERENCE:?API_IMAGE_REFERENCE is required}" in compose
    assert "image: ${WEB_IMAGE_REFERENCE:?WEB_IMAGE_REFERENCE is required}" in compose
    assert "${IMAGE_NAME" not in compose
    assert "${IMAGE_TAG" not in compose


def test_web_container_is_loopback_only_and_cannot_read_application_data() -> None:
    compose = (PROJECT_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")
    web = compose.split("\n  web:\n", maxsplit=1)[1]

    assert '"127.0.0.1:${WEB_HOST_PORT:?WEB_HOST_PORT is required}:8080"' in web
    assert "    read_only: true" in web
    assert "      - no-new-privileges:true" in web
    assert "      - ALL" in web
    assert "    volumes:" not in web
    assert "DATA_DIRECTORY" not in web
    assert "APPLICATION_SECRETS_FILE" not in web
    assert "http://127.0.0.1:8080/healthz" in web


def test_container_start_uses_strict_preflight_and_readiness() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")

    assert "USER app" in dockerfile
    assert '"reminiscence.preflight", "uvicorn"' in dockerfile
    assert "      - reminiscence.preflight" in compose
    assert "/api/health/ready" in dockerfile
    assert "/api/health/ready" in compose
