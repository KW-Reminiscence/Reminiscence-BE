"""Daily scheduled conversation suggestion policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from reminiscence.conversation.models import ConversationSession


@dataclass(frozen=True, slots=True)
class ConversationSuggestion:
    """Whether the tablet should offer today's reminiscence session."""

    suggested: bool
    scheduled_time: time


class ConversationSuggestionPolicy:
    """Suggest once the daily time arrives unless a session already started."""

    def __init__(self, scheduled_time: time) -> None:
        if scheduled_time.tzinfo is not None:
            raise ValueError("scheduled_time must not include timezone information")
        self._scheduled_time = scheduled_time

    def evaluate(
        self,
        now: datetime,
        sessions: tuple[ConversationSession, ...],
    ) -> ConversationSuggestion:
        """Evaluate using the server-local calendar day."""

        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        local_sessions = (
            session.started_at.astimezone(now.tzinfo) for session in sessions
        )
        already_started_today = any(
            started_at.date() == now.date() for started_at in local_sessions
        )
        return ConversationSuggestion(
            suggested=(
                now.time().replace(tzinfo=None) >= self._scheduled_time
                and not already_started_today
            ),
            scheduled_time=self._scheduled_time,
        )
