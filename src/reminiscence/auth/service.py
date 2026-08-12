"""Credential comparison, lockout and role session orchestration."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from reminiscence.auth.models import AuthRole, AuthSession
from reminiscence.auth.secrets import AuthSecrets
from reminiscence.auth.storage import AuthAttemptStore, AuthSessionStore

GUARDIAN_SESSION_LIFETIME = timedelta(hours=12)
TABLET_SESSION_LIFETIME = timedelta(days=30)


class InvalidCredentialError(ValueError):
    """Raised without revealing which credential property failed."""


@dataclass(frozen=True, slots=True)
class AuthLockedError(RuntimeError):
    """Raised while a role's rolling brute-force lock is active."""

    locked_until: datetime


class AuthService:
    """Authenticate the single guardian and tablet against plaintext JSON."""

    def __init__(
        self,
        sessions: AuthSessionStore,
        attempts: AuthAttemptStore,
        secrets_loader: Callable[[], AuthSecrets],
    ) -> None:
        self._sessions = sessions
        self._attempts = attempts
        self._secrets_loader = secrets_loader

    def login_guardian(
        self,
        password: str,
        now: datetime,
    ) -> tuple[str, AuthSession]:
        """Compare and issue a guardian browser session."""

        secrets = self._load_secrets()
        return self._authenticate(
            AuthRole.GUARDIAN,
            password,
            secrets.guardian_password,
            now,
            GUARDIAN_SESSION_LIFETIME,
        )

    def pair_tablet(
        self,
        pairing_code: str,
        now: datetime,
    ) -> tuple[str, AuthSession]:
        """Compare and issue the one valid tablet session."""

        secrets = self._load_secrets()
        return self._authenticate(
            AuthRole.TABLET,
            pairing_code,
            secrets.tablet_pairing_code,
            now,
            TABLET_SESSION_LIFETIME,
        )

    def validate(
        self,
        token: str,
        role: AuthRole,
        now: datetime,
    ) -> AuthSession | None:
        """Validate a cookie and automatically revoke credential-changed sessions."""

        secrets = self._load_secrets()
        credential = (
            secrets.guardian_password
            if role is AuthRole.GUARDIAN
            else secrets.tablet_pairing_code
        )
        return self._sessions.validate(token, role, credential, now)

    def logout(self, token: str, role: AuthRole) -> None:
        """Revoke one role cookie if it currently exists."""

        self._sessions.revoke(token, role)

    def _authenticate(
        self,
        role: AuthRole,
        supplied: str,
        expected: str,
        now: datetime,
        lifetime: timedelta,
    ) -> tuple[str, AuthSession]:
        locked_until = self._attempts.locked_until(role, now)
        if locked_until is not None:
            raise AuthLockedError(locked_until)
        valid = isinstance(supplied, str) and hmac.compare_digest(
            supplied.encode("utf-8"),
            expected.encode("utf-8"),
        )
        if not valid:
            locked_until = self._attempts.record_failure(role, now)
            if locked_until is not None:
                raise AuthLockedError(locked_until)
            raise InvalidCredentialError("invalid credential")
        self._attempts.clear(role)
        return self._sessions.issue(role, expected, now, lifetime)

    def _load_secrets(self) -> AuthSecrets:
        value = self._secrets_loader()
        if not isinstance(value, AuthSecrets):
            raise TypeError("secrets_loader must return AuthSecrets")
        return value
