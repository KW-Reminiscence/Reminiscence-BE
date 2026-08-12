"""Cross-domain test dependencies that keep unit tests focused on their domain."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from reminiscence.auth.dependencies import (
    require_guardian_session,
    require_same_origin,
    require_tablet_session,
)
from reminiscence.auth.models import AuthRole, AuthSession
from reminiscence.main import app

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=ZoneInfo("Asia/Seoul"))


@pytest.fixture(autouse=True)
def bypass_auth_for_domain_unit_tests():  # type: ignore[no-untyped-def]
    """Exercise auth in auth tests and bypass it in unrelated router unit tests."""

    app.dependency_overrides[require_guardian_session] = lambda: AuthSession(
        AuthRole.GUARDIAN,
        NOW,
        NOW + timedelta(hours=1),
    )
    app.dependency_overrides[require_tablet_session] = lambda: AuthSession(
        AuthRole.TABLET,
        NOW,
        NOW + timedelta(hours=1),
    )
    app.dependency_overrides[require_same_origin] = lambda: None
    yield
    for dependency in (
        require_guardian_session,
        require_tablet_session,
        require_same_origin,
    ):
        app.dependency_overrides.pop(dependency, None)
