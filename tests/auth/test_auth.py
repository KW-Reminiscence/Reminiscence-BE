"""Guardian login, tablet pairing, lockout and role-cookie integration tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from reminiscence.auth.api import router
from reminiscence.auth.dependencies import (
    GUARDIAN_COOKIE,
    TABLET_COOKIE,
    GuardianSessionDependency,
    TabletSessionDependency,
    get_auth_current_time,
    get_auth_service,
)
from reminiscence.auth.models import AuthRole
from reminiscence.auth.secrets import (
    ApplicationSecretsError,
    AuthSecrets,
    load_auth_secrets,
)
from reminiscence.auth.service import AuthService
from reminiscence.auth.storage import AuthAttemptStore, AuthSessionStore, hash_secret
from reminiscence.storage import JsonObjectStore

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 8, 13, 12, 0, tzinfo=SEOUL)
ORIGIN = "https://reminiscence.leehyowon14.dev"
PASSWORD = "guardian-password"
PAIRING_CODE = "tablet-pairing-code"


def build_service(tmp_path: Path, secrets: dict[str, AuthSecrets]) -> AuthService:
    return AuthService(
        AuthSessionStore(
            JsonObjectStore(tmp_path / "auth_sessions.json", schema_version=1)
        ),
        AuthAttemptStore(
            JsonObjectStore(tmp_path / "auth_attempts.json", schema_version=1)
        ),
        lambda: secrets["value"],
    )


def build_app(service: AuthService, now: datetime = NOW) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_auth_service] = lambda: service
    application.dependency_overrides[get_auth_current_time] = lambda: now
    return application


def auth_secrets() -> dict[str, AuthSecrets]:
    return {"value": AuthSecrets(PASSWORD, PAIRING_CODE)}


def test_secret_loader_requires_0600_and_never_returns_unrelated_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "application-secrets.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "guardian_password": PASSWORD,
                "tablet_pairing_code": PAIRING_CODE,
                "codex_lb_api_key": "not-returned",
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o644)

    with pytest.raises(ApplicationSecretsError, match="0600"):
        load_auth_secrets(path)

    path.chmod(0o600)
    assert load_auth_secrets(path) == AuthSecrets(PASSWORD, PAIRING_CODE)


def test_guardian_login_cookie_session_and_logout(tmp_path: Path) -> None:
    service = build_service(tmp_path, auth_secrets())
    client = TestClient(build_app(service), base_url=ORIGIN)

    login = client.post(
        "/api/v1/auth/guardian/login",
        headers={"Origin": ORIGIN},
        json={"password": PASSWORD},
    )
    current = client.get("/api/v1/auth/guardian/session")
    logout = client.post(
        "/api/v1/auth/guardian/logout",
        headers={"Origin": ORIGIN},
    )
    expired = client.get("/api/v1/auth/guardian/session")

    assert login.status_code == 200
    cookie = login.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
    assert current.json()["role"] == "GUARDIAN"
    assert logout.status_code == 204
    assert expired.status_code == 401


def test_auth_rejects_missing_or_wrong_origin(tmp_path: Path) -> None:
    client = TestClient(build_app(build_service(tmp_path, auth_secrets())), base_url=ORIGIN)

    missing = client.post(
        "/api/v1/auth/guardian/login",
        json={"password": PASSWORD},
    )
    wrong = client.post(
        "/api/v1/auth/guardian/login",
        headers={"Origin": "https://evil.example"},
        json={"password": PASSWORD},
    )

    assert missing.status_code == 403
    assert wrong.status_code == 403


def test_fifth_failed_password_locks_guardian_and_success_clears_attempts(
    tmp_path: Path,
) -> None:
    service = build_service(tmp_path, auth_secrets())
    client = TestClient(build_app(service), base_url=ORIGIN)

    responses = [
        client.post(
            "/api/v1/auth/guardian/login",
            headers={"Origin": ORIGIN},
            json={"password": "wrong-password"},
        )
        for _ in range(5)
    ]
    locked_correct = client.post(
        "/api/v1/auth/guardian/login",
        headers={"Origin": ORIGIN},
        json={"password": PASSWORD},
    )

    assert [response.status_code for response in responses] == [401, 401, 401, 401, 429]
    assert locked_correct.status_code == 429
    assert int(locked_correct.headers["retry-after"]) > 0
    attempts = json.loads(
        (tmp_path / "auth_attempts.json").read_text(encoding="utf-8")
    )
    assert len(attempts["attempts"]) == 5
    assert PASSWORD not in json.dumps(attempts)

    later = TestClient(
        build_app(service, NOW + timedelta(minutes=16)),
        base_url=ORIGIN,
    )
    success = later.post(
        "/api/v1/auth/guardian/login",
        headers={"Origin": ORIGIN},
        json={"password": PASSWORD},
    )
    assert success.status_code == 200
    assert json.loads(
        (tmp_path / "auth_attempts.json").read_text(encoding="utf-8")
    )["attempts"] == []


def test_second_pairing_revokes_first_tablet_session(tmp_path: Path) -> None:
    service = build_service(tmp_path, auth_secrets())
    application = build_app(service)
    first_client = TestClient(application, base_url=ORIGIN)
    second_client = TestClient(application, base_url=ORIGIN)

    first = first_client.post(
        "/api/v1/auth/tablet/pair",
        headers={"Origin": ORIGIN},
        json={"pairing_code": PAIRING_CODE},
    )
    second = second_client.post(
        "/api/v1/auth/tablet/pair",
        headers={"Origin": ORIGIN},
        json={"pairing_code": PAIRING_CODE},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first_client.get("/api/v1/auth/tablet/session").status_code == 401
    assert second_client.get("/api/v1/auth/tablet/session").status_code == 200


def test_plaintext_credentials_and_raw_tokens_are_not_persisted(tmp_path: Path) -> None:
    service = build_service(tmp_path, auth_secrets())
    token, _ = service.login_guardian(PASSWORD, NOW)
    persisted = (tmp_path / "auth_sessions.json").read_text(encoding="utf-8")

    assert PASSWORD not in persisted
    assert PAIRING_CODE not in persisted
    assert token not in persisted
    assert hash_secret(token) in persisted


def test_secret_change_revokes_existing_session(tmp_path: Path) -> None:
    mutable = auth_secrets()
    service = build_service(tmp_path, mutable)
    client = TestClient(build_app(service), base_url=ORIGIN)
    client.post(
        "/api/v1/auth/guardian/login",
        headers={"Origin": ORIGIN},
        json={"password": PASSWORD},
    )

    mutable["value"] = AuthSecrets("new-guardian-password", PAIRING_CODE)

    assert client.get("/api/v1/auth/guardian/session").status_code == 401
    assert json.loads(
        (tmp_path / "auth_sessions.json").read_text(encoding="utf-8")
    )["sessions"] == []


def test_guardian_validation_does_not_revoke_tablet_session(tmp_path: Path) -> None:
    service = build_service(tmp_path, auth_secrets())
    guardian_token, _ = service.login_guardian(PASSWORD, NOW)
    tablet_token, _ = service.pair_tablet(PAIRING_CODE, NOW)

    assert service.validate(
        guardian_token,
        AuthRole.GUARDIAN,
        NOW,
    ) is not None
    assert service.validate(tablet_token, AuthRole.TABLET, NOW) is not None
    sessions = json.loads(
        (tmp_path / "auth_sessions.json").read_text(encoding="utf-8")
    )["sessions"]
    assert {session["role"] for session in sessions} == {"GUARDIAN", "TABLET"}


def test_role_dependencies_reject_cross_role_cookie(tmp_path: Path) -> None:
    service = build_service(tmp_path, auth_secrets())
    application = build_app(service)

    @application.get("/guardian-only")
    async def guardian_only(_: GuardianSessionDependency) -> dict[str, str]:
        return {"role": "guardian"}

    @application.get("/tablet-only")
    async def tablet_only(_: TabletSessionDependency) -> dict[str, str]:
        return {"role": "tablet"}

    client = TestClient(application, base_url=ORIGIN)
    client.post(
        "/api/v1/auth/guardian/login",
        headers={"Origin": ORIGIN},
        json={"password": PASSWORD},
    )

    assert client.get("/guardian-only").status_code == 200
    assert client.get("/tablet-only").status_code == 401
    assert GUARDIAN_COOKIE in client.cookies
    assert TABLET_COOKIE not in client.cookies
