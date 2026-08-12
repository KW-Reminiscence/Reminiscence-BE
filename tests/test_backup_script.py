"""Static validation for scheduled JSON backup operations."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_backup_uses_current_digest_and_shared_deployment_lock() -> None:
    script = (PROJECT_ROOT / "scripts/backup.sh").read_text(encoding="utf-8")

    assert 'release_manifest="${deployment_directory}/release.json"' in script
    assert 'manifest.get("schema_version") != 1' in script
    assert "immutable GHCR digest" in script
    assert 'exec 9>"${deployment_lock_file}"' in script
    assert "flock -n 9" in script
    assert "docker image inspect" in script


def test_backup_creates_and_verifies_versioned_json_snapshots() -> None:
    script = (PROJECT_ROOT / "scripts/backup.sh").read_text(encoding="utf-8")

    assert "reminiscence.storage.snapshot" in script
    assert 'create_snapshot_once "daily-${calendar_date}"' in script
    assert 'create_snapshot_once "weekly-${calendar_week}"' in script
    assert 'create_snapshot_once "monthly-${calendar_month}"' in script
    assert 'run_snapshot verify "/backups/${snapshot_name}"' in script


def test_backup_retention_is_daily_7_weekly_4_monthly_6() -> None:
    script = (PROJECT_ROOT / "scripts/backup.sh").read_text(encoding="utf-8")

    assert "prune_snapshots daily 7" in script
    assert "prune_snapshots weekly 4" in script
    assert "prune_snapshots monthly 6" in script
    assert "Refusing to prune unexpected snapshot path" in script


def test_backup_timer_is_persistent_and_low_priority() -> None:
    service = (
        PROJECT_ROOT / "deploy/systemd/reminiscence-backup.service"
    ).read_text(encoding="utf-8")
    timer = (
        PROJECT_ROOT / "deploy/systemd/reminiscence-backup.timer"
    ).read_text(encoding="utf-8")

    assert "User=ubuntu" in service
    assert "ExecStart=/usr/local/bin/reminiscence-backup production" in service
    assert "IOSchedulingPriority=7" in service
    assert "OnCalendar=*-*-* 03:15:00 Asia/Seoul" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=15m" in timer
