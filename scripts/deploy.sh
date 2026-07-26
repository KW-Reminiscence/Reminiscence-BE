#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "Usage: $0 <development|production> <image-tag>" >&2
    exit 64
fi

readonly deployment_environment="$1"
readonly image_tag="$2"
readonly image_name="${IMAGE_NAME:?IMAGE_NAME is required}"
readonly project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "${deployment_environment}" in
    production)
        readonly deployment_directory="/home/ubuntu/apps/reminiscence/production"
        readonly host_port="3010"
        readonly container_name="reminiscence-production-api"
        ;;
    development)
        readonly deployment_directory="/home/ubuntu/apps/reminiscence/development"
        readonly host_port="3011"
        readonly container_name="reminiscence-development-api"
        ;;
    *)
        echo "Unsupported deployment environment: ${deployment_environment}" >&2
        exit 64
        ;;
esac

readonly compose_source_file="${project_root}/deploy/docker-compose.yml"
readonly compose_file="${deployment_directory}/docker-compose.yml"
readonly notification_config_file="${deployment_directory}/notification-config.json"
readonly runtime_env_file="${deployment_directory}/runtime.env"
readonly data_directory="${deployment_directory}/data"
readonly supertonic_model_directory="${deployment_directory}/supertonic3"
readonly configuration_file="${data_directory}/configuration.json"
readonly active_env_file="${deployment_directory}/.env"
readonly next_env_file="${deployment_directory}/.env.next"
readonly previous_env_file="${deployment_directory}/.env.previous"
deployment_swapped=false
had_active_deployment=false

compose() {
    local env_file="$1"
    shift

    docker compose \
        --project-name "reminiscence-${deployment_environment}" \
        --env-file "${env_file}" \
        --file "${compose_file}" \
        "$@"
}

write_environment() {
    local env_file="$1"

    umask 077
    {
        printf 'IMAGE_NAME=%s\n' "${image_name}"
        printf 'IMAGE_TAG=%s\n' "${image_tag}"
        printf 'CONTAINER_NAME=%s\n' "${container_name}"
        printf 'HOST_PORT=%s\n' "${host_port}"
        printf 'DATA_DIRECTORY=%s\n' "${data_directory}"
        printf 'SUPERTONIC_MODEL_DIRECTORY=%s\n' "${supertonic_model_directory}"
        printf 'NOTIFICATION_CONFIG_FILE=%s\n' "${notification_config_file}"
        printf 'RUNTIME_ENV_FILE=%s\n' "${runtime_env_file}"
    } >"${env_file}"
}

rollback() {
    local exit_code=$?
    trap - ERR

    echo "Deployment failed; restoring the previous image."
    rm -f "${next_env_file}"

    if [[ "${deployment_swapped}" == true ]]; then
        if [[ "${had_active_deployment}" == true ]]; then
            mv -f "${previous_env_file}" "${active_env_file}"
            compose "${active_env_file}" up -d --wait --wait-timeout 120 || true
        else
            compose "${active_env_file}" down --remove-orphans || true
            rm -f "${active_env_file}"
        fi
    fi

    exit "${exit_code}"
}

trap rollback ERR

mkdir -p "${deployment_directory}"
mkdir -p "${data_directory}"
mkdir -p "${supertonic_model_directory}"
if [[ ! -f "${notification_config_file}" ]]; then
    echo "Missing notification configuration: ${notification_config_file}" >&2
    echo "Create it from deploy/notification-config.example.json with mode 0600." >&2
    exit 78
fi
if [[ ! -f "${runtime_env_file}" ]]; then
    echo "Missing runtime environment: ${runtime_env_file}" >&2
    echo "Create it from deploy/runtime.env.example with mode 0600." >&2
    exit 78
fi
if [[ ! -f "${configuration_file}" ]]; then
    echo "Missing application configuration: ${configuration_file}" >&2
    echo "Create it from deploy/configuration.example.json." >&2
    exit 78
fi
install -m 0644 "${compose_source_file}" "${compose_file}"
write_environment "${next_env_file}"

compose "${next_env_file}" pull
compose "${next_env_file}" run --rm --no-deps api \
    python -c \
    "from supertonic import TTS; TTS(model='supertonic-3', model_dir='/models/supertonic-3', auto_download=True)"

if [[ -f "${active_env_file}" ]]; then
    cp -p "${active_env_file}" "${previous_env_file}"
    had_active_deployment=true
fi

mv -f "${next_env_file}" "${active_env_file}"
deployment_swapped=true
compose "${active_env_file}" up -d --wait --wait-timeout 120
curl --fail --silent --show-error --retry 10 --retry-connrefused \
    "http://127.0.0.1:${host_port}/health" >/dev/null

rm -f "${previous_env_file}"
trap - ERR

compose "${active_env_file}" ps
