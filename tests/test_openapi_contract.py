"""Checked-in API contract drift test."""

from pathlib import Path

from reminiscence.main import app
from reminiscence.openapi_contract import render_openapi

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_openapi_snapshot_matches_application() -> None:
    snapshot = (PROJECT_ROOT / "openapi.json").read_text(encoding="utf-8")

    assert snapshot == render_openapi(app.openapi())
    assert '"/api/v1/tablet/state"' in snapshot
    assert '"/api/health/ready"' in snapshot
    assert app.openapi()["info"]["version"] == "0.1.0"
