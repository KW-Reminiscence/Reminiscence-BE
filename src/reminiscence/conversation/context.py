"""Bounded in-memory context for one active reminiscence session."""

from __future__ import annotations

import threading
from collections import deque

MAX_CONTEXT_TURNS = 32
MAX_CONTEXT_CHARS_PER_TURN = 2_000


class TransientConversationContextStore:
    """Keep recent user answers in memory and never serialize them."""

    def __init__(
        self,
        *,
        max_turns: int = MAX_CONTEXT_TURNS,
        max_chars_per_turn: int = MAX_CONTEXT_CHARS_PER_TURN,
    ) -> None:
        if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns < 1:
            raise ValueError("max_turns must be a positive integer")
        if (
            not isinstance(max_chars_per_turn, int)
            or isinstance(max_chars_per_turn, bool)
            or max_chars_per_turn < 1
        ):
            raise ValueError("max_chars_per_turn must be a positive integer")
        self._max_turns = max_turns
        self._max_chars_per_turn = max_chars_per_turn
        self._histories: dict[str, deque[str]] = {}
        self._lock = threading.RLock()

    def history(self, session_id: str) -> tuple[str, ...]:
        """Return an immutable snapshot of the session's prior answers."""

        with self._lock:
            return tuple(self._histories.get(session_id, ()))

    def remember(self, session_id: str, transcript: str) -> None:
        """Append one normalized non-empty answer within configured bounds."""

        normalized = " ".join(transcript.split())
        if not normalized:
            return
        bounded = normalized[: self._max_chars_per_turn]
        with self._lock:
            history = self._histories.setdefault(
                session_id,
                deque(maxlen=self._max_turns),
            )
            history.append(bounded)

    def clear(self, session_id: str) -> None:
        """Forget all transient text associated with a completed session."""

        with self._lock:
            self._histories.pop(session_id, None)
