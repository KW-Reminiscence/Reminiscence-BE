"""Static validation for deployment safety checks."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_deploy_script_runs_real_supertonic_smoke() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    assert "SupertonicSynthesizer(config).synthesize" in deploy_script
    assert "result.audio[:4] == b'RIFF'" in deploy_script


def test_compose_mounts_writable_supertonic_parent_directory() -> None:
    compose = (PROJECT_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8")

    assert "SUPERTONIC_MODEL_DIR: /models/supertonic-3" in compose
    assert "        target: /models\n" in compose
    assert "        target: /models/supertonic-3\n" not in compose
