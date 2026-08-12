#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 3 ]]; then
    echo "Usage: $0 <development|production> <api-image@sha256:digest> <web-image@sha256:digest>" >&2
    exit 64
fi

readonly deployment_environment="$1"
readonly api_image_reference="$2"
readonly web_image_reference="$3"
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly project_root
readonly image_reference_pattern='^ghcr\.io/[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}$'
readonly apply_json_migrations="${APPLY_JSON_MIGRATIONS:-0}"

if [[ ! "${api_image_reference}" =~ ${image_reference_pattern} ]]; then
    echo "API image must be an immutable GHCR sha256 reference." >&2
    exit 64
fi
if [[ ! "${web_image_reference}" =~ ${image_reference_pattern} ]]; then
    echo "Web image must be an immutable GHCR sha256 reference." >&2
    exit 64
fi
if [[ "${apply_json_migrations}" != "0" && "${apply_json_migrations}" != "1" ]]; then
    echo "APPLY_JSON_MIGRATIONS must be 0 or 1." >&2
    exit 64
fi

case "${deployment_environment}" in
    production)
        readonly deployment_directory="/home/ubuntu/apps/reminiscence/production"
        readonly api_host_port="3010"
        readonly web_host_port="3011"
        readonly api_container_name="reminiscence-production-api"
        readonly web_container_name="reminiscence-production-web"
        readonly public_url="https://reminiscence.leehyowon14.dev"
        ;;
    development)
        readonly deployment_directory="/home/ubuntu/apps/reminiscence/development"
        readonly api_host_port="3012"
        readonly web_host_port="3013"
        readonly api_container_name="reminiscence-development-api"
        readonly web_container_name="reminiscence-development-web"
        readonly public_url=""
        ;;
    *)
        echo "Unsupported deployment environment: ${deployment_environment}" >&2
        exit 64
        ;;
esac

readonly compose_source_file="${project_root}/deploy/docker-compose.yml"
readonly compose_file="${deployment_directory}/docker-compose.yml"
readonly previous_compose_file="${deployment_directory}/docker-compose.previous.yml"
readonly application_secrets_file="${deployment_directory}/application-secrets.json"
readonly data_directory="${deployment_directory}/data"
readonly backup_directory="${deployment_directory}/backups"
readonly supertonic_model_directory="${deployment_directory}/supertonic3"
readonly configuration_file="${data_directory}/configuration.json"
readonly active_env_file="${deployment_directory}/.env"
readonly next_env_file="${deployment_directory}/.env.next"
readonly previous_env_file="${deployment_directory}/.env.previous"
readonly active_manifest_file="${deployment_directory}/release.json"
readonly next_manifest_file="${deployment_directory}/release.next.json"
readonly previous_manifest_file="${deployment_directory}/release.previous.json"
readonly maintenance_flag="${deployment_directory}/maintenance.flag"
readonly deployment_lock_file="${deployment_directory}/.deploy.lock"
deployed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
readonly deployed_at
readonly api_digest="${api_image_reference##*@sha256:}"
release_id="predeploy-$(date -u +%Y%m%dT%H%M%SZ)-${api_digest:0:12}"
readonly release_id
readonly snapshot_directory="${backup_directory}/${release_id}"
snapshot_kind="$([[ "${apply_json_migrations}" == "1" ]] && printf legacy || printf current)"
readonly snapshot_kind

had_active_deployment=false
deployment_swapped=false
migration_applied=false
traffic_released=false

compose() {
    local env_file="$1"
    local configuration="$2"
    shift 2

    docker compose \
        --project-name "reminiscence-${deployment_environment}" \
        --env-file "${env_file}" \
        --file "${configuration}" \
        "$@"
}

run_storage_tool() {
    docker run --rm \
        --network none \
        --read-only \
        --tmpfs /tmp \
        --security-opt no-new-privileges \
        --cap-drop ALL \
        --volume "${data_directory}:/data" \
        --volume "${backup_directory}:/backups" \
        "${api_image_reference}" \
        "$@"
}

smoke_loopback() {
    curl --fail --silent --show-error --retry 10 --retry-connrefused \
        "http://127.0.0.1:${api_host_port}/api/health/ready" >/dev/null \
        && curl --fail --silent --show-error --retry 10 --retry-connrefused \
            "http://127.0.0.1:${web_host_port}/healthz" >/dev/null
}

write_environment() {
    local env_file="$1"

    umask 077
    {
        printf 'API_IMAGE_REFERENCE=%s\n' "${api_image_reference}"
        printf 'WEB_IMAGE_REFERENCE=%s\n' "${web_image_reference}"
        printf 'API_CONTAINER_NAME=%s\n' "${api_container_name}"
        printf 'WEB_CONTAINER_NAME=%s\n' "${web_container_name}"
        printf 'API_HOST_PORT=%s\n' "${api_host_port}"
        printf 'WEB_HOST_PORT=%s\n' "${web_host_port}"
        printf 'DATA_DIRECTORY=%s\n' "${data_directory}"
        printf 'SUPERTONIC_MODEL_DIRECTORY=%s\n' "${supertonic_model_directory}"
        printf 'APPLICATION_SECRETS_FILE=%s\n' "${application_secrets_file}"
    } >"${env_file}"
}

write_release_manifest() {
    local manifest_file="$1"

    umask 077
    {
        printf '{\n'
        printf '  "schema_version": 1,\n'
        printf '  "environment": "%s",\n' "${deployment_environment}"
        printf '  "deployed_at": "%s",\n' "${deployed_at}"
        printf '  "api_image": "%s",\n' "${api_image_reference}"
        printf '  "web_image": "%s",\n' "${web_image_reference}"
        printf '  "predeploy_snapshot_kind": "%s",\n' "${snapshot_kind}"
        printf '  "predeploy_snapshot": "%s"\n' "${snapshot_directory}"
        printf '}\n'
    } >"${manifest_file}"
}

remove_maintenance_flag() {
    rm -f "${maintenance_flag}"
}

rollback() {
    local exit_code=$?
    trap - ERR

    echo "Deployment failed; entering rollback." >&2
    touch "${maintenance_flag}"
    rm -f "${next_env_file}" "${next_manifest_file}"

    if [[ "${migration_applied}" == true && "${traffic_released}" == true ]]; then
        echo "Migration received public traffic; automatic data and image rollback is unsafe." >&2
        echo "Maintenance remains enabled. Follow the manual recovery runbook." >&2
        exit "${exit_code}"
    fi

    if [[ "${deployment_swapped}" == true ]]; then
        compose "${active_env_file}" "${compose_file}" down --remove-orphans || true
    fi

    if [[ "${migration_applied}" == true ]]; then
        if ! run_storage_tool python -m reminiscence.storage.legacy_snapshot restore \
            "/backups/${release_id}" --data-dir /data; then
            echo "Snapshot restore failed; maintenance remains enabled." >&2
            exit "${exit_code}"
        fi
    fi

    if [[ "${had_active_deployment}" == true ]]; then
        cp -p "${previous_env_file}" "${active_env_file}"
        cp -p "${previous_compose_file}" "${compose_file}"
        if [[ -f "${previous_manifest_file}" ]]; then
            cp -p "${previous_manifest_file}" "${active_manifest_file}"
        else
            rm -f "${active_manifest_file}"
        fi
        if ! compose "${active_env_file}" "${compose_file}" \
            up -d --wait --wait-timeout 180 --remove-orphans; then
            echo "Previous Compose failed to start; maintenance remains enabled." >&2
            exit "${exit_code}"
        fi
        if ! smoke_loopback; then
            echo "Previous release loopback smoke failed; maintenance remains enabled." >&2
            exit "${exit_code}"
        fi
    else
        rm -f "${active_env_file}" "${active_manifest_file}"
        echo "No previous release is available; maintenance remains enabled." >&2
        exit "${exit_code}"
    fi

    remove_maintenance_flag
    exit "${exit_code}"
}

install -d -m 0750 "${deployment_directory}"
exec 9>"${deployment_lock_file}"
if ! flock -n 9; then
    echo "Another Reminiscence deployment is already running." >&2
    exit 75
fi
install -d -m 0750 "${data_directory}"
install -d -m 0750 "${backup_directory}"
install -d -m 0750 "${supertonic_model_directory}"
if [[ ! -f "${application_secrets_file}" ]]; then
    echo "Missing application secrets: ${application_secrets_file}" >&2
    echo "Create it from deploy/application-secrets.example.json with mode 0600." >&2
    exit 78
fi
if [[ ! -f "${configuration_file}" ]]; then
    echo "Missing application configuration: ${configuration_file}" >&2
    echo "Create it from deploy/configuration.example.json." >&2
    exit 78
fi
if [[ -f "${active_env_file}" || -f "${compose_file}" ]]; then
    if [[ ! -f "${active_env_file}" || ! -f "${compose_file}" ]]; then
        echo "Active deployment metadata is incomplete; refusing to overwrite it." >&2
        exit 78
    fi
    cp -p "${active_env_file}" "${previous_env_file}"
    cp -p "${compose_file}" "${previous_compose_file}"
    if [[ -f "${active_manifest_file}" ]]; then
        cp -p "${active_manifest_file}" "${previous_manifest_file}"
    else
        rm -f "${previous_manifest_file}"
    fi
    had_active_deployment=true
fi

install -m 0644 "${compose_source_file}" "${compose_file}"
write_environment "${next_env_file}"
write_release_manifest "${next_manifest_file}"
trap rollback ERR

compose "${next_env_file}" "${compose_file}" pull
compose "${next_env_file}" "${compose_file}" run --rm --no-deps web nginx -t

if [[ "${apply_json_migrations}" == "0" ]]; then
    compose "${next_env_file}" "${compose_file}" run --rm --no-deps api \
        python -m reminiscence.preflight python -c \
        "from reminiscence.tts.api import get_speech_synthesizer; result = get_speech_synthesizer().synthesize('오늘 사진을 보며 이야기 나눠 보실래요?'); assert result.audio[:4] == b'RIFF' and result.audio[8:12] == b'WAVE'; print(f'Supertonic smoke passed: {result.sample_rate} Hz, {result.duration_seconds} s')"
else
    compose "${next_env_file}" "${compose_file}" run --rm --no-deps api \
        python -c "from reminiscence.storage.migration import migrate_data_directory; print('Candidate migration code import passed')"
fi

touch "${maintenance_flag}"
if [[ "${had_active_deployment}" == true ]]; then
    compose "${previous_env_file}" "${previous_compose_file}" stop api
fi

if [[ "${apply_json_migrations}" == "1" ]]; then
    run_storage_tool \
        python -m reminiscence.storage.legacy_snapshot create \
        --data-dir /data --backup-dir /backups --snapshot-id "${release_id}"
    run_storage_tool \
        python -m reminiscence.storage.migration --data-dir /data --apply
    migration_applied=true
else
    run_storage_tool \
        python -m reminiscence.storage.snapshot create \
        --data-dir /data --backup-dir /backups --snapshot-id "${release_id}"
fi

compose "${next_env_file}" "${compose_file}" run --rm --no-deps api \
    python -m reminiscence.preflight python -c \
    "from reminiscence.tts.api import get_speech_synthesizer; result = get_speech_synthesizer().synthesize('오늘 사진을 보며 이야기 나눠 보실래요?'); assert result.audio[:4] == b'RIFF' and result.audio[8:12] == b'WAVE'"

mv -f "${next_env_file}" "${active_env_file}"
mv -f "${next_manifest_file}" "${active_manifest_file}"
deployment_swapped=true
compose "${active_env_file}" "${compose_file}" \
    up -d --wait --wait-timeout 180 --remove-orphans

smoke_loopback

traffic_released=true
remove_maintenance_flag
if [[ -n "${public_url}" ]]; then
    curl --fail --silent --show-error --retry 5 --retry-all-errors \
        "${public_url}/api/health/live" >/dev/null
    curl --fail --silent --show-error --retry 5 --retry-all-errors \
        "${public_url}/" >/dev/null
fi

trap - ERR
compose "${active_env_file}" "${compose_file}" ps
echo "Release manifest: ${active_manifest_file}"
echo "Predeploy snapshot: ${snapshot_directory}"
