"""JSON persistence for hashed sessions and brute-force attempt timestamps."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Any

from reminiscence.auth.models import AuthRole, AuthSession
from reminiscence.storage import JsonObjectStore, JsonStorageError

SESSION_TOKEN_BYTES = 32


class AuthStorageError(JsonStorageError):
    """Raised when persisted authentication state is malformed."""


def hash_secret(value: str) -> str:
    """Return the non-reversible SHA-256 representation stored in data JSON."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthStorageError(f"{field_name} must be a non-empty string")
    return value


def _timestamp(value: Any, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, field_name))
    except ValueError as exc:
        raise AuthStorageError(f"{field_name} must be a valid datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuthStorageError(f"{field_name} must be timezone-aware")
    return parsed


def _parse_session(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuthStorageError("each auth session must be an object")
    required = {
        "token_hash",
        "credential_fingerprint",
        "role",
        "created_at",
        "expires_at",
    }
    if set(value) != required:
        raise AuthStorageError("auth session fields are invalid")
    token_hash = _text(value["token_hash"], "token_hash")
    fingerprint = _text(value["credential_fingerprint"], "credential_fingerprint")
    if len(token_hash) != 64 or len(fingerprint) != 64:
        raise AuthStorageError("auth hashes must be 64 hexadecimal characters")
    try:
        int(token_hash, 16)
        int(fingerprint, 16)
        role = AuthRole(_text(value["role"], "role"))
    except ValueError as exc:
        raise AuthStorageError("auth session hash or role is invalid") from exc
    created_at = _timestamp(value["created_at"], "created_at")
    expires_at = _timestamp(value["expires_at"], "expires_at")
    if expires_at <= created_at:
        raise AuthStorageError("auth session must expire after creation")
    return {
        "token_hash": token_hash,
        "credential_fingerprint": fingerprint,
        "role": role,
        "created_at": created_at,
        "expires_at": expires_at,
    }


class AuthSessionStore:
    """Issue and validate raw-cookie/hash-in-JSON sessions."""

    def __init__(self, store: JsonObjectStore) -> None:
        self._store = store

    def issue(
        self,
        role: AuthRole,
        credential: str,
        now: datetime,
        lifetime: timedelta,
    ) -> tuple[str, AuthSession]:
        """Issue a session and revoke the previous tablet session."""

        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        session = AuthSession(role, now, now + lifetime)

        def mutate(root: dict[str, Any]) -> None:
            values = root.get("sessions", [])
            if not isinstance(values, list):
                raise AuthStorageError("sessions must be an array")
            current = [_parse_session(value) for value in values]
            kept = [
                value
                for value in current
                if value["expires_at"] > now
                and not (role is AuthRole.TABLET and value["role"] is role)
            ]
            kept.append(
                {
                    "token_hash": hash_secret(token),
                    "credential_fingerprint": hash_secret(credential),
                    "role": role,
                    "created_at": session.created_at,
                    "expires_at": session.expires_at,
                }
            )
            root["sessions"] = [self._serialize(value) for value in kept]

        self._store.update(mutate)
        return token, session

    def validate(
        self,
        token: str,
        role: AuthRole,
        credential: str,
        now: datetime,
    ) -> AuthSession | None:
        """Return a matching unexpired session and prune invalid credentials."""

        token_hash = hash_secret(token)
        fingerprint = hash_secret(credential)
        result: AuthSession | None = None

        def mutate(root: dict[str, Any]) -> None:
            nonlocal result
            values = root.get("sessions", [])
            if not isinstance(values, list):
                raise AuthStorageError("sessions must be an array")
            current = [_parse_session(value) for value in values]
            kept: list[dict[str, Any]] = []
            for value in current:
                if value["expires_at"] <= now:
                    continue
                if (
                    value["role"] is role
                    and not hmac.compare_digest(
                        value["credential_fingerprint"],
                        fingerprint,
                    )
                ):
                    continue
                kept.append(value)
                if (
                    value["role"] is role
                    and hmac.compare_digest(value["token_hash"], token_hash)
                ):
                    result = AuthSession(
                        value["role"],
                        value["created_at"],
                        value["expires_at"],
                    )
            root["sessions"] = [self._serialize(value) for value in kept]

        self._store.update(mutate)
        return result

    def revoke(self, token: str, role: AuthRole) -> None:
        """Remove one matching session hash; repeated logout is harmless."""

        token_hash = hash_secret(token)

        def mutate(root: dict[str, Any]) -> None:
            values = root.get("sessions", [])
            if not isinstance(values, list):
                raise AuthStorageError("sessions must be an array")
            current = [_parse_session(value) for value in values]
            root["sessions"] = [
                self._serialize(value)
                for value in current
                if not (
                    hmac.compare_digest(value["token_hash"], token_hash)
                    and value["role"] is role
                )
            ]

        self._store.update(mutate)

    @staticmethod
    def _serialize(value: dict[str, Any]) -> dict[str, str]:
        return {
            "token_hash": value["token_hash"],
            "credential_fingerprint": value["credential_fingerprint"],
            "role": value["role"].value,
            "created_at": value["created_at"].isoformat(),
            "expires_at": value["expires_at"].isoformat(),
        }


def _parse_attempt(value: Any) -> tuple[AuthRole, datetime]:
    if not isinstance(value, dict) or set(value) != {"role", "failed_at"}:
        raise AuthStorageError("each auth attempt must contain role and failed_at")
    try:
        role = AuthRole(_text(value["role"], "role"))
    except ValueError as exc:
        raise AuthStorageError("auth attempt role is invalid") from exc
    return role, _timestamp(value["failed_at"], "failed_at")


class AuthAttemptStore:
    """Persist a bounded rolling window of failed credential attempts."""

    def __init__(
        self,
        store: JsonObjectStore,
        *,
        maximum_failures: int = 5,
        window: timedelta = timedelta(minutes=15),
    ) -> None:
        self._store = store
        self._maximum_failures = maximum_failures
        self._window = window

    def locked_until(self, role: AuthRole, now: datetime) -> datetime | None:
        """Return the rolling lock deadline for one role, if active."""

        attempts = self._read_recent(role, now)
        if len(attempts) < self._maximum_failures:
            return None
        deadline = attempts[-1] + self._window
        return deadline if deadline > now else None

    def record_failure(self, role: AuthRole, now: datetime) -> datetime | None:
        """Append one failure and return a newly active lock deadline."""

        def mutate(root: dict[str, Any]) -> None:
            values = root.get("attempts", [])
            if not isinstance(values, list):
                raise AuthStorageError("attempts must be an array")
            parsed = [_parse_attempt(value) for value in values]
            cutoff = now - self._window
            recent = [
                (item_role, failed_at)
                for item_role, failed_at in parsed
                if failed_at > cutoff
            ]
            recent.append((role, now))
            root["attempts"] = [
                {"role": item_role.value, "failed_at": failed_at.isoformat()}
                for item_role, failed_at in recent
            ]

        self._store.update(mutate)
        return self.locked_until(role, now)

    def clear(self, role: AuthRole) -> None:
        """Clear failures for one successfully authenticated role."""

        def mutate(root: dict[str, Any]) -> None:
            values = root.get("attempts", [])
            if not isinstance(values, list):
                raise AuthStorageError("attempts must be an array")
            parsed = [_parse_attempt(value) for value in values]
            root["attempts"] = [
                {"role": item_role.value, "failed_at": failed_at.isoformat()}
                for item_role, failed_at in parsed
                if item_role is not role
            ]

        self._store.update(mutate)

    def _read_recent(self, role: AuthRole, now: datetime) -> list[datetime]:
        root = self._store.read()
        values = root.get("attempts", [])
        if not isinstance(values, list):
            raise AuthStorageError("attempts must be an array")
        cutoff = now - self._window
        return sorted(
            failed_at
            for item_role, failed_at in (_parse_attempt(value) for value in values)
            if item_role is role and failed_at > cutoff
        )
