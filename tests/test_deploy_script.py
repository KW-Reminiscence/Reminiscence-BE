"""Static validation for deployment safety checks."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_deploy_script_runs_real_supertonic_smoke() -> None:
    deploy_script = (PROJECT_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")

    assert "SupertonicSynthesizer(config).synthesize" in deploy_script
    assert "result.audio[:4] == b'RIFF'" in deploy_script
