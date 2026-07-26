"""Daily conversation suggestion policy tests."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from reminiscence.conversation.models import (
    ConversationSession,
    ConversationSource,
    ConversationStatus,
)
from reminiscence.conversation.suggestion import ConversationSuggestionPolicy

SEOUL = ZoneInfo("Asia/Seoul")
UTC = ZoneInfo("UTC")


def session_at(started_at: datetime) -> ConversationSession:
    return ConversationSession(
        session_id="session-1",
        source=ConversationSource.VOLUNTARY,
        photo_id=None,
        started_at=started_at,
        status=ConversationStatus.ACTIVE,
        turns=(),
    )


def test_exact_scheduled_time_is_suggested() -> None:
    outcome = ConversationSuggestionPolicy(time(14, 0)).evaluate(
        datetime(2026, 7, 27, 14, 0, tzinfo=SEOUL),
        (),
    )

    assert outcome.suggested is True


def test_before_scheduled_time_is_not_suggested() -> None:
    outcome = ConversationSuggestionPolicy(time(14, 0)).evaluate(
        datetime(2026, 7, 27, 13, 59, 59, tzinfo=SEOUL),
        (),
    )

    assert outcome.suggested is False


@pytest.mark.parametrize("source", list(ConversationSource))
def test_any_session_started_today_suppresses_suggestion(
    source: ConversationSource,
) -> None:
    session = session_at(datetime(2026, 7, 27, 9, 0, tzinfo=SEOUL))
    session = ConversationSession(
        session_id=session.session_id,
        source=source,
        photo_id=session.photo_id,
        started_at=session.started_at,
        status=session.status,
        turns=session.turns,
    )

    outcome = ConversationSuggestionPolicy(time(14, 0)).evaluate(
        datetime(2026, 7, 27, 15, 0, tzinfo=SEOUL),
        (session,),
    )

    assert outcome.suggested is False


def test_session_date_is_compared_in_server_timezone() -> None:
    session = session_at(datetime(2026, 7, 26, 23, 30, tzinfo=UTC))

    outcome = ConversationSuggestionPolicy(time(14, 0)).evaluate(
        datetime(2026, 7, 27, 15, 0, tzinfo=SEOUL),
        (session,),
    )

    assert outcome.suggested is False


def test_previous_day_session_does_not_suppress_suggestion() -> None:
    outcome = ConversationSuggestionPolicy(time(14, 0)).evaluate(
        datetime(2026, 7, 27, 15, 0, tzinfo=SEOUL),
        (session_at(datetime(2026, 7, 26, 23, 59, tzinfo=SEOUL)),),
    )

    assert outcome.suggested is True


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ConversationSuggestionPolicy(time(14, 0)).evaluate(
            datetime(2026, 7, 27, 14, 0),
            (),
        )
