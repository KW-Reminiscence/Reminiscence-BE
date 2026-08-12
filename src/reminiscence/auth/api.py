"""Public login/pairing and cookie lifecycle endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from reminiscence.auth.dependencies import (
    GUARDIAN_COOKIE,
    TABLET_COOKIE,
    GuardianCookieDependency,
    GuardianSessionDependency,
    SameOriginDependency,
    TabletCookieDependency,
    TabletSessionDependency,
    get_auth_current_time,
    get_auth_service,
)
from reminiscence.auth.models import AuthRole, AuthSession
from reminiscence.auth.secrets import ApplicationSecretsError
from reminiscence.auth.service import AuthLockedError, AuthService, InvalidCredentialError
from reminiscence.auth.storage import AuthStorageError
from reminiscence.storage import JsonStorageError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class GuardianLoginRequest(BaseModel):
    """Plaintext password accepted only over the production HTTPS origin."""

    password: str = Field(min_length=1, max_length=256)


class TabletPairingRequest(BaseModel):
    """One-time tablet pairing credential."""

    pairing_code: str = Field(min_length=1, max_length=256)


class SessionResponse(BaseModel):
    """Non-sensitive current session metadata."""

    role: AuthRole
    expires_at: datetime


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
CurrentTimeDependency = Annotated[datetime, Depends(get_auth_current_time)]


def _set_cookie(response: Response, name: str, token: str, expires_at: datetime) -> None:
    response.set_cookie(
        name,
        token,
        expires=expires_at.astimezone(UTC),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


def _session_response(session: AuthSession) -> SessionResponse:
    return SessionResponse(role=session.role, expires_at=session.expires_at)


def _authenticate(
    operation: object,
    credential: str,
    now: datetime,
) -> tuple[str, AuthSession]:
    if not callable(operation):
        raise TypeError("authentication operation must be callable")
    try:
        result = operation(credential, now)
    except InvalidCredentialError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credential",
        ) from exc
    except AuthLockedError as exc:
        retry_after = max(1, int((exc.locked_until - now).total_seconds()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="authentication temporarily locked",
            headers={"Retry-After": str(retry_after)},
        ) from exc
    except (ApplicationSecretsError, AuthStorageError, JsonStorageError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="authentication service is unavailable",
        ) from exc
    if (
        not isinstance(result, tuple)
        or len(result) != 2
        or not isinstance(result[0], str)
        or not isinstance(result[1], AuthSession)
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="authentication service is unavailable",
        )
    return result


@router.post("/guardian/login", response_model=SessionResponse)
async def guardian_login(
    payload: GuardianLoginRequest,
    response: Response,
    _: SameOriginDependency,
    service: AuthServiceDependency,
    now: CurrentTimeDependency,
) -> SessionResponse:
    """Issue a guardian session cookie after plaintext JSON comparison."""

    token, session = _authenticate(service.login_guardian, payload.password, now)
    _set_cookie(response, GUARDIAN_COOKIE, token, session.expires_at)
    return _session_response(session)


@router.get("/guardian/session", response_model=SessionResponse)
async def guardian_session(session: GuardianSessionDependency) -> SessionResponse:
    """Return current guardian session metadata."""

    return _session_response(session)


@router.post("/guardian/logout", status_code=status.HTTP_204_NO_CONTENT)
async def guardian_logout(
    response: Response,
    _: SameOriginDependency,
    __: GuardianSessionDependency,
    service: AuthServiceDependency,
    token: GuardianCookieDependency = None,
) -> None:
    """Revoke the guardian cookie hash and expire the browser cookie."""

    if token:
        service.logout(token, AuthRole.GUARDIAN)
    response.delete_cookie(GUARDIAN_COOKIE, path="/", secure=True, httponly=True)
    response.headers["Cache-Control"] = "no-store"


@router.post("/tablet/pair", response_model=SessionResponse)
async def tablet_pair(
    payload: TabletPairingRequest,
    response: Response,
    _: SameOriginDependency,
    service: AuthServiceDependency,
    now: CurrentTimeDependency,
) -> SessionResponse:
    """Pair one tablet and revoke any prior tablet session."""

    token, session = _authenticate(service.pair_tablet, payload.pairing_code, now)
    _set_cookie(response, TABLET_COOKIE, token, session.expires_at)
    return _session_response(session)


@router.get("/tablet/session", response_model=SessionResponse)
async def tablet_session(session: TabletSessionDependency) -> SessionResponse:
    """Return current paired-tablet session metadata."""

    return _session_response(session)


@router.post("/tablet/logout", status_code=status.HTTP_204_NO_CONTENT)
async def tablet_logout(
    response: Response,
    _: SameOriginDependency,
    __: TabletSessionDependency,
    service: AuthServiceDependency,
    token: TabletCookieDependency = None,
) -> None:
    """Revoke the tablet cookie hash and expire the browser cookie."""

    if token:
        service.logout(token, AuthRole.TABLET)
    response.delete_cookie(TABLET_COOKIE, path="/", secure=True, httponly=True)
    response.headers["Cache-Control"] = "no-store"
