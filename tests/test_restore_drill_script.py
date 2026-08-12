"""Static validation for isolated monthly restore drills."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_restore_drill_uses_latest_daily_snapshot_and_temporary_data() -> None:
    script = (PROJECT_ROOT / "scripts/restore-drill.sh").read_text(encoding="utf-8")

    assert "-type d -name 'daily-*'" in script
    assert 'snapshot_directory="${daily_snapshots[0]}"' in script
    assert 'mktemp -d "${deployment_directory}/.restore-drill.XXXXXX"' in script
    assert 'rm -rf -- "${drill_directory}"' in script
    assert '"${backup_directory}:/backups:ro"' in script
    assert "/data" not in script.split("mktemp", maxsplit=1)[0]


def test_restore_drill_recreates_excluded_auth_state_and_runs_real_preflight() -> None:
    script = (PROJECT_ROOT / "scripts/restore-drill.sh").read_text(encoding="utf-8")

    restore = script.index("reminiscence.storage.snapshot restore")
    migration = script.index("reminiscence.storage.migration --data-dir /data --apply")
    preflight = script.index("python -m reminiscence.preflight", migration)
    tts = script.index("get_speech_synthesizer().synthesize", preflight)
    assert restore < migration < preflight < tts
    assert "result.audio[:4] == b'RIFF'" in script
    assert "result.audio[8:12] == b'WAVE'" in script


def test_restore_drill_shares_deployment_lock_and_digest_contract() -> None:
    script = (PROJECT_ROOT / "scripts/restore-drill.sh").read_text(encoding="utf-8")

    assert 'exec 9>"${deployment_lock_file}"' in script
    assert "flock -n 9" in script
    assert "immutable GHCR digest" in script
    assert '"${application_secrets_file}:/run/secrets/application-secrets.json:ro"' in script
    assert '"${supertonic_model_directory}:/models:ro"' in script


def test_restore_drill_timer_runs_monthly_with_catch_up() -> None:
    service = (
        PROJECT_ROOT / "deploy/systemd/reminiscence-restore-drill.service"
    ).read_text(encoding="utf-8")
    timer = (
        PROJECT_ROOT / "deploy/systemd/reminiscence-restore-drill.timer"
    ).read_text(encoding="utf-8")

    assert "ExecStart=/usr/local/bin/reminiscence-restore-drill production" in service
    assert "OnCalendar=*-*-01 04:30:00 Asia/Seoul" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=30m" in timer
