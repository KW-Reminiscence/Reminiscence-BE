#!/usr/bin/env bash

set -Eeuo pipefail

if [[ "$#" -ne 1 || "$1" != "production" ]]; then
    echo "Usage: $0 production" >&2
    exit 64
fi

readonly deployment_directory="/home/ubuntu/apps/reminiscence/production"
readonly data_directory="${deployment_directory}/data"
readonly backup_directory="${deployment_directory}/backups"
readonly release_manifest="${deployment_directory}/release.json"
readonly deployment_lock_file="${deployment_directory}/.deploy.lock"
readonly image_reference_pattern='^ghcr\.io/[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}$'

if [[ ! -f "${release_manifest}" ]]; then
    echo "Missing release manifest: ${release_manifest}" >&2
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
    echo "Deployment is active; skipping scheduled backup." >&2
    exit 75
fi

docker image inspect "${api_image_reference}" >/dev/null
install -d -m 0750 "${backup_directory}"

run_snapshot() {
    docker run --rm \
        --network none \
        --read-only \
        --tmpfs /tmp \
        --security-opt no-new-privileges \
        --cap-drop ALL \
        --volume "${data_directory}:/data" \
        --volume "${backup_directory}:/backups" \
        "${api_image_reference}" \
        python -m reminiscence.storage.snapshot "$@"
}

create_snapshot_once() {
    local snapshot_id="$1"

    if [[ -d "${backup_directory}/${snapshot_id}" ]]; then
        echo "Snapshot already exists: ${snapshot_id}"
        return
    fi
    run_snapshot create \
        --data-dir /data \
        --backup-dir /backups \
        --snapshot-id "${snapshot_id}"
}

prune_snapshots() {
    local prefix="$1"
    local keep="$2"
    local -a snapshots
    local snapshot_path
    local snapshot_name

    mapfile -t snapshots < <(
        find "${backup_directory}" \
            -mindepth 1 -maxdepth 1 -type d -name "${prefix}-*" -print \
            | LC_ALL=C sort -r
    )
    for snapshot_path in "${snapshots[@]:keep}"; do
        snapshot_name="$(basename "${snapshot_path}")"
        if [[ ! "${snapshot_name}" =~ ^${prefix}-[0-9A-Z-]+$ ]]; then
            echo "Refusing to prune unexpected snapshot path: ${snapshot_path}" >&2
            exit 78
        fi
        run_snapshot verify "/backups/${snapshot_name}"
        rm -rf -- "${snapshot_path}"
        echo "Pruned snapshot: ${snapshot_name}"
    done
}

calendar_date="$(TZ=Asia/Seoul date +%Y%m%d)"
calendar_week="$(TZ=Asia/Seoul date +%G-W%V)"
calendar_month="$(TZ=Asia/Seoul date +%Y%m)"
readonly calendar_date calendar_week calendar_month

create_snapshot_once "daily-${calendar_date}"
create_snapshot_once "weekly-${calendar_week}"
create_snapshot_once "monthly-${calendar_month}"

prune_snapshots daily 7
prune_snapshots weekly 4
prune_snapshots monthly 6
