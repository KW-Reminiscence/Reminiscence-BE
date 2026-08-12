"""Static validation for the production-only GitHub Actions workflow."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_ci_cd_runs_only_for_main() -> None:
    workflow = (
        PROJECT_ROOT / ".github/workflows/ci-cd.yml"
    ).read_text(encoding="utf-8")

    assert workflow.count("      - main") == 2
    assert "      - develop" not in workflow
    assert "workflow_dispatch:" not in workflow
    assert './scripts/deploy.sh production "${IMAGE_TAG}"' in workflow
    assert "DEPLOYMENT_ENVIRONMENT:" not in workflow
    assert "uv run python scripts/export_openapi.py --check" in workflow
