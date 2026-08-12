#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 1 || "$1" != "production" ]]; then
    echo "Usage: $0 production" >&2
    exit 64
fi

readonly deployment_directory="/home/ubuntu/apps/reminiscence/production"
readonly backup_directory="${deployment_directory}/backups"
readonly release_manifest="${deployment_directory}/release.json"
readonly application_secrets_file="${deployment_directory}/application-secrets.json"
readonly supertonic_model_directory="${deployment_directory}/supertonic3"
readonly deployment_lock_file="${deployment_directory}/.deploy.lock"
readonly image_reference_pattern='^ghcr\.io/[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}$'

if [[ ! -f "${release_manifest}" || ! -f "${application_secrets_file}" ]]; then
    echo "Release manifest and application secrets are required." >&2
    exit 78
fi

api_image_reference="$(python3 -c '
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if manifest.get("schema_version") != 1 or manifest.get("environment") != "production":
    raise SystemExit("invalid production release manifest")
value = manifest.get("api_image")
if not isinstance(value, str):
    raise SystemExit("release manifest api_image must be a string")
print(value)
' "${release_manifest}")"
readonly api_image_reference

if [[ ! "${api_image_reference}" =~ ${image_reference_pattern} ]]; then
    echo "Release manifest API image is not an immutable GHCR digest." >&2
    exit 78
fi

exec 9>"${deployment_lock_file}"
if ! flock -n 9; then
    echo "Deployment is active; skipping restore drill." >&2
    exit 75
fi

mapfile -t daily_snapshots < <(
    find "${backup_directory}" \
        -mindepth 1 -maxdepth 1 -type d -name 'daily-*' -print \
        | LC_ALL=C sort -r
)
if [[ "${#daily_snapshots[@]}" -eq 0 ]]; then
    echo "No daily snapshot is available for a restore drill." >&2
    exit 78
fi
readonly snapshot_directory="${daily_snapshots[0]}"
snapshot_name="$(basename "${snapshot_directory}")"
readonly snapshot_name
if [[ ! "${snapshot_name}" =~ ^daily-[0-9]{8}$ ]]; then
    echo "Unexpected snapshot path: ${snapshot_directory}" >&2
    exit 78
fi

drill_directory="$(mktemp -d "${deployment_directory}/.restore-drill.XXXXXX")"
readonly drill_directory
cleanup() {
    rm -rf -- "${drill_directory}"
}
trap cleanup EXIT

docker run --rm \
    --network none \
    --read-only \
    --tmpfs /tmp \
    --security-opt no-new-privileges \
    --cap-drop ALL \
    --volume "${backup_directory}:/backups:ro" \
    --volume "${drill_directory}:/drill" \
    "${api_image_reference}" \
    python -m reminiscence.storage.snapshot restore \
    "/backups/${snapshot_name}" --data-dir /drill/data

docker run --rm \
    --network none \
    --read-only \
    --tmpfs /tmp \
    --security-opt no-new-privileges \
    --cap-drop ALL \
    --volume "${drill_directory}/data:/data" \
    "${api_image_reference}" \
    python -m reminiscence.storage.migration --data-dir /data --apply

docker run --rm \
    --network none \
    --read-only \
    --tmpfs /tmp \
    --security-opt no-new-privileges \
    --cap-drop ALL \
    --env REMINISCENCE_DATA_DIR=/data \
    --env REMINISCENCE_SECRETS_PATH=/run/secrets/application-secrets.json \
    --volume "${drill_directory}/data:/data" \
    --volume "${application_secrets_file}:/run/secrets/application-secrets.json:ro" \
    --volume "${supertonic_model_directory}:/models:ro" \
    "${api_image_reference}" \
    python -m reminiscence.preflight python -c \
    "from reminiscence.tts.api import get_speech_synthesizer; result = get_speech_synthesizer().synthesize('복구 점검입니다.'); assert result.audio[:4] == b'RIFF' and result.audio[8:12] == b'WAVE'"

echo "Restore drill passed: ${snapshot_name}"
