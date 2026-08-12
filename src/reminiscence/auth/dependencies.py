"""FastAPI role and same-origin dependencies shared by protected routers."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyCookie

from reminiscence.auth.models import AuthRole, AuthSession
from reminiscence.auth.secrets import ApplicationSecretsError, load_auth_secrets
from reminiscence.auth.service import AuthService
from reminiscence.auth.storage import (
    AuthAttemptStore,
    AuthSessionStore,
    AuthStorageError,
)
from reminiscence.runtime_config import (
    DEFAULT_PUBLIC_ORIGIN,
    data_directory,
    load_runtime_settings,
    server_timezone,
)
from reminiscence.storage import JsonStorageError, open_versioned_store

GUARDIAN_COOKIE = "reminiscence_guardian_session"
TABLET_COOKIE = "reminiscence_tablet_session"
DEFAULT_APPLICATION_ORIGIN = DEFAULT_PUBLIC_ORIGIN


def _data_directory() -> Path:
    return data_directory()


def get_auth_current_time() -> datetime:
    """Return current time in the configured appliance timezone."""

    return datetime.now(tz=server_timezone())


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    """Build the process-wide JSON authentication service."""

    data_directory = _data_directory()
    return AuthService(
        AuthSessionStore(
            open_versioned_store(
                data_directory / "auth_sessions.json",
                missing_default={"sessions": []},
            )
        ),
        AuthAttemptStore(
            open_versioned_store(
                data_directory / "auth_attempts.json",
                missing_default={"attempts": []},
            )
        ),
        load_auth_secrets,
    )


def require_same_origin(request: Request) -> None:
    """Reject every unsafe request without the exact configured web origin."""

    expected = load_runtime_settings().public_origin
    if request.headers.get("origin") != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="request origin is not allowed",
        )


def _require_role(
    token: str | None,
    role: AuthRole,
    service: AuthService,
    now: datetime,
) -> AuthSession:
    if not token or len(token) > 128:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    try:
        session = service.validate(token, role, now)
    except (ApplicationSecretsError, AuthStorageError, JsonStorageError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="authentication service is unavailable",
        ) from exc
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="session is invalid or expired",
        )
    return session


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
AuthCurrentTimeDependency = Annotated[datetime, Depends(get_auth_current_time)]
guardian_cookie_scheme = APIKeyCookie(
    name=GUARDIAN_COOKIE,
    scheme_name="GuardianSession",
    auto_error=False,
)
tablet_cookie_scheme = APIKeyCookie(
    name=TABLET_COOKIE,
    scheme_name="TabletSession",
    auto_error=False,
)
GuardianCookieDependency = Annotated[
    str | None,
    Security(guardian_cookie_scheme),
]
TabletCookieDependency = Annotated[
    str | None,
    Security(tablet_cookie_scheme),
]


def require_guardian_session(
    service: AuthServiceDependency,
    now: AuthCurrentTimeDependency,
    token: GuardianCookieDependency = None,
) -> AuthSession:
    """Require one valid guardian cookie."""

    return _require_role(token, AuthRole.GUARDIAN, service, now)


def require_tablet_session(
    service: AuthServiceDependency,
    now: AuthCurrentTimeDependency,
    token: TabletCookieDependency = None,
) -> AuthSession:
    """Require the currently paired tablet cookie."""

    return _require_role(token, AuthRole.TABLET, service, now)


GuardianSessionDependency = Annotated[
    AuthSession,
    Depends(require_guardian_session),
]
TabletSessionDependency = Annotated[
    AuthSession,
    Depends(require_tablet_session),
]
SameOriginDependency = Annotated[None, Depends(require_same_origin)]
