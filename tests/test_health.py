"""Liveness and dependency-aware readiness contract tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from reminiscence.health import (
    AtomicWriteProbe,
    ReadinessChecker,
    ReadinessError,
    get_readiness_checker,
)
from reminiscence.main import app
from reminiscence.storage.migration import migrate_data_directory

client = TestClient(app)


def test_liveness_returns_without_application_lifespan() -> None:
    response = client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_named_successful_checks() -> None:
    class ReadyChecker:
        def check(self, application: object) -> dict[str, str]:
            del application
            return {
                "instance_lock": "ok",
                "background_runtime": "ok",
                "json_documents": "ok",
                "atomic_write": "ok",
                "tts_model": "ok",
            }

    app.dependency_overrides[get_readiness_checker] = ReadyChecker
    try:
        response = client.get("/api/health/ready")
    finally:
        app.dependency_overrides.pop(get_readiness_checker, None)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"]["tts_model"] == "ok"


def test_readiness_reports_only_failed_check_names() -> None:
    class FailedChecker:
        def check(self, application: object) -> dict[str, str]:
            del application
            raise ReadinessError(("json_documents", "tts_model"))

    app.dependency_overrides[get_readiness_checker] = FailedChecker
    try:
        response = client.get("/api/health/ready")
    finally:
        app.dependency_overrides.pop(get_readiness_checker, None)

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "status": "not_ready",
            "failed_checks": ["json_documents", "tts_model"],
        }
    }


def test_real_readiness_checks_json_and_atomic_write(tmp_path: Path) -> None:
    migrate_data_directory(tmp_path, apply=True)
    application = SimpleNamespace(
        state=SimpleNamespace(
            instance_lock=SimpleNamespace(acquired=True),
            background_runtime=SimpleNamespace(is_running=True),
        )
    )
    checker = ReadinessChecker(
        tmp_path,
        atomic_write_probe=AtomicWriteProbe(cache_seconds=0),
        tts_probe=lambda: object(),
    )

    checks = checker.check(application)

    assert checks == {
        "instance_lock": "ok",
        "background_runtime": "ok",
        "json_documents": "ok",
        "atomic_write": "ok",
        "tts_model": "ok",
    }
    assert not list(tmp_path.glob(".readiness*"))


def test_readiness_fails_when_runtime_owners_are_missing(tmp_path: Path) -> None:
    checker = ReadinessChecker(
        tmp_path,
        atomic_write_probe=AtomicWriteProbe(cache_seconds=0),
        tts_probe=lambda: object(),
    )

    try:
        checker.check(SimpleNamespace(state=SimpleNamespace()))
    except ReadinessError as exc:
        assert exc.failed_checks == ("instance_lock", "background_runtime")
    else:
        raise AssertionError("expected readiness failure")


def test_legacy_health_path_remains_compatible() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_endpoints_allow_only_get_requests() -> None:
    assert client.post("/api/health/live").status_code == 405
    assert client.post("/api/health/ready").status_code == 405


def test_health_endpoints_are_documented() -> None:
    paths = app.openapi()["paths"]

    assert "/api/health/live" in paths
    assert "/api/health/ready" in paths
    assert paths["/health"]["get"]["deprecated"] is True
