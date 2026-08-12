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
    assert (
        './scripts/deploy.sh production "${API_IMAGE_REFERENCE}" '
        '"${WEB_IMAGE_REFERENCE}"'
    ) in workflow
    assert "DEPLOYMENT_ENVIRONMENT:" not in workflow
    assert "uv run python scripts/export_openapi.py --check" in workflow


def test_workflow_deploys_api_and_web_by_immutable_digest() -> None:
    workflow = (
        PROJECT_ROOT / ".github/workflows/ci-cd.yml"
    ).read_text(encoding="utf-8")

    assert "api-image-reference:" in workflow
    assert "web-image-reference:" in workflow
    assert "steps.api-image.outputs.digest" in workflow
    assert "docker buildx imagetools inspect" in workflow
    assert "^sha256:[a-f0-9]{64}$" in workflow
    assert "needs.build.outputs.api-image-reference" in workflow
    assert "needs.build.outputs.web-image-reference" in workflow
    assert "platforms: linux/arm64" in workflow
    assert "provenance: mode=max" in workflow
    assert "sbom: true" in workflow
