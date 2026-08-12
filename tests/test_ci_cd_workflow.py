"""Static validation for the production GitHub Actions workflow."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_ci_cd_runs_for_main_and_explicit_manual_release() -> None:
    workflow = (
        PROJECT_ROOT / ".github/workflows/ci-cd.yml"
    ).read_text(encoding="utf-8")

    assert workflow.count("      - main") == 2
    assert "      - develop" not in workflow
    assert "workflow_dispatch:" in workflow
    assert "apply_json_migrations:" in workflow
    assert "type: boolean" in workflow
    assert "./scripts/deploy.sh production" in workflow
    assert '"${API_IMAGE_REFERENCE}" "${WEB_IMAGE_REFERENCE}"' in workflow
    assert '"${API_COMMIT}" "${WEB_COMMIT}" "${OPENAPI_SHA256}"' in workflow
    assert "DEPLOYMENT_ENVIRONMENT:" not in workflow
    assert "uv run python scripts/export_openapi.py --check" in workflow


def test_production_deploy_requires_gate_or_manual_dispatch() -> None:
    workflow = (
        PROJECT_ROOT / ".github/workflows/ci-cd.yml"
    ).read_text(encoding="utf-8")

    assert "vars.ENABLE_PRODUCTION_DEPLOY == 'true'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "github.event_name != 'pull_request' && github.ref == 'refs/heads/main'" in workflow
    assert workflow.count("github.ref == 'refs/heads/main'") == 2
    assert "inputs.apply_json_migrations" in workflow
    assert "APPLY_JSON_MIGRATIONS:" in workflow
    assert "&& '1' || '0'" in workflow


def test_workflow_deploys_api_and_web_by_immutable_digest() -> None:
    workflow = (
        PROJECT_ROOT / ".github/workflows/ci-cd.yml"
    ).read_text(encoding="utf-8")

    assert "api-image-reference:" in workflow
    assert "web-image-reference:" in workflow
    assert "steps.api-image.outputs.digest" in workflow
    assert "steps.web-image.outputs.digest" in workflow
    assert "needs.build.outputs.api-image-reference" in workflow
    assert "needs.build.outputs.web-image-reference" in workflow
    assert workflow.count("platforms: linux/arm64") == 2
    assert workflow.count("provenance: mode=max") == 2
    assert workflow.count("sbom: true") == 2
    assert "repository: KW-Reminiscence/Reminiscence-FE" in workflow
    assert "git -C frontend-release rev-parse HEAD" in workflow
    assert "OPENAPI_SCHEMA_PATH: ../openapi.json" in workflow
    assert "pnpm api:check" in workflow
    assert "pnpm test" in workflow
    assert "pnpm lint" in workflow
    assert "pnpm typecheck" in workflow
    assert "pnpm build" in workflow
    assert "pnpm exec playwright install --with-deps chromium" in workflow
    assert "pnpm test:e2e" in workflow
    assert "context: frontend-release" in workflow
    assert "reminiscence-web-release" in workflow
    assert "WEB_IMAGE_NAME }}:${{ steps.web-source.outputs.commit }}" in workflow
    assert (
        "org.opencontainers.image.source=${{ github.server_url }}/${{ github.repository }}"
        in workflow
    )
    assert "org.opencontainers.image.revision=${{ steps.web-source.outputs.commit }}" in workflow
    assert "sha256sum openapi.json" in workflow
