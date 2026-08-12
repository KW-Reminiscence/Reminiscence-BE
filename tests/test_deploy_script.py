"""Static validation for deployment safety checks."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_deploy_script_runs_real_supertonic_smoke() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    assert "get_speech_synthesizer().synthesize" in deploy_script
    assert "result.audio[:4] == b'RIFF'" in deploy_script
    assert "result.audio[8:12] == b'WAVE'" in deploy_script


def test_deploy_script_wires_required_application_secret() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    assert (
        'application_secrets_file="${deployment_directory}/application-secrets.json"'
        in deploy_script
    )
    assert "printf 'APPLICATION_SECRETS_FILE=%s\\n'" in deploy_script
    assert '[[ ! -f "${application_secrets_file}" ]]' in deploy_script
    assert "deploy/application-secrets.example.json" in deploy_script


def test_deploy_script_requires_two_immutable_image_references() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    assert 'if [[ "$#" -ne 6 ]]' in deploy_script
    assert "<api-image@sha256:digest> <web-image@sha256:digest>" in deploy_script
    assert deploy_script.count("immutable GHCR sha256 reference") == 2
    assert "API_IMAGE_REFERENCE" in deploy_script
    assert "WEB_IMAGE_REFERENCE" in deploy_script
    assert "API commit must be a full 40-character Git SHA." in deploy_script
    assert "Web commit must be a full 40-character Git SHA." in deploy_script
    assert "OpenAPI contract hash must be a SHA-256 hex digest." in deploy_script


def test_deploy_script_snapshots_before_explicit_migration() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    stop = deploy_script.index('stop api')
    snapshot = deploy_script.index("reminiscence.storage.legacy_snapshot create")
    migration = deploy_script.index("reminiscence.storage.migration --data-dir /data --apply")
    start = deploy_script.index('up -d --wait --wait-timeout 180 --remove-orphans', migration)
    assert stop < snapshot < migration < start
    assert 'apply_json_migrations="${APPLY_JSON_MIGRATIONS:-0}"' in deploy_script


def test_deploy_script_rolls_back_both_images_and_migrated_data_before_traffic() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    assert "release.previous.json" in deploy_script
    assert "docker-compose.previous.yml" in deploy_script
    assert "reminiscence.storage.legacy_snapshot restore" in deploy_script
    assert "Snapshot restore failed; maintenance remains enabled." in deploy_script
    assert 'migration_attempted}" == true && "${traffic_released}" == true' in deploy_script
    assert "automatic data and image rollback is unsafe" in deploy_script


def test_deploy_script_restores_legacy_snapshot_after_any_migration_attempt() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    snapshot = deploy_script.index("reminiscence.storage.legacy_snapshot create")
    attempted = deploy_script.index("migration_attempted=true", snapshot)
    migration = deploy_script.index(
        "reminiscence.storage.migration --data-dir /data --apply", attempted
    )
    rollback = deploy_script.index("rollback()")
    restore_guard = deploy_script.index(
        'if [[ "${migration_attempted}" == true ]]', rollback
    )
    restore = deploy_script.index("reminiscence.storage.legacy_snapshot restore", restore_guard)

    assert snapshot < attempted < migration
    assert rollback < restore_guard < restore


def test_deploy_script_keeps_maintenance_when_previous_release_is_not_healthy() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    assert "Previous Compose failed to start; maintenance remains enabled." in deploy_script
    assert "Previous release loopback smoke failed; maintenance remains enabled." in deploy_script
    assert "No previous release is available; maintenance remains enabled." in deploy_script
    rollback = deploy_script.index("rollback()")
    previous_up = deploy_script.index("up -d --wait --wait-timeout 180", rollback)
    smoke = deploy_script.index("smoke_loopback", previous_up)
    clear = deploy_script.index("remove_maintenance_flag", smoke)
    assert rollback < previous_up < smoke < clear


def test_deploy_script_uses_schema_agnostic_snapshot_only_for_migration() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    assert 'snapshot_kind="$([[ "${apply_json_migrations}" == "1" ]]' in deploy_script
    assert "reminiscence.storage.legacy_snapshot create" in deploy_script
    assert "reminiscence.storage.snapshot create" in deploy_script
    assert "Candidate migration code import passed" in deploy_script
    assert '"predeploy_snapshot_kind"' in deploy_script


def test_deploy_script_holds_maintenance_until_loopback_smoke_passes() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    maintenance = deploy_script.index('touch "${maintenance_flag}"')
    start = deploy_script.index('up -d --wait --wait-timeout 180 --remove-orphans', maintenance)
    smoke = deploy_script.index("smoke_loopback", start)
    release = deploy_script.index("traffic_released=true", smoke)
    clear = deploy_script.index("remove_maintenance_flag", release)
    assert maintenance < start < smoke < release < clear
    assert "release.json" in deploy_script
    assert '"schema_version": 1' in deploy_script
    assert '"api_commit"' in deploy_script
    assert '"web_commit"' in deploy_script
    assert '"openapi_sha256"' in deploy_script
    assert "sha256(render_openapi(app.openapi()).encode()).hexdigest()" in deploy_script
    assert "== '${openapi_sha256}'" in deploy_script


def test_deploy_script_serializes_host_level_releases() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    assert 'deployment_lock_file="${deployment_directory}/.deploy.lock"' in deploy_script
    assert 'exec 9>"${deployment_lock_file}"' in deploy_script
    assert "flock -n 9" in deploy_script
    assert "Another Reminiscence deployment is already running." in deploy_script


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


def test_api_image_uses_host_ubuntu_uid_for_read_only_secret() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "groupadd --gid 1000 app" in dockerfile
    assert "useradd --uid 1000 --gid app" in dockerfile
    assert "USER app" in dockerfile
