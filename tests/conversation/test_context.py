"""Transient conversation context bounds and cleanup tests."""

from __future__ import annotations

import pytest

from reminiscence.conversation.context import TransientConversationContextStore


def test_context_normalizes_and_bounds_recent_answers() -> None:
    context = TransientConversationContextStore(max_turns=2, max_chars_per_turn=4)

    context.remember("session-1", "  첫 번째   응답  ")
    assert context.history("session-1") == ("첫 번째",)

    context.remember("session-1", "두번째응답")
    context.remember("session-1", "세번째응답")

    assert context.history("session-1") == ("두번째응", "세번째응")


def test_context_ignores_empty_answers_and_clears_idempotently() -> None:
    context = TransientConversationContextStore()

    context.remember("session-1", " \n ")
    context.clear("session-1")
    context.clear("session-1")

    assert context.history("session-1") == ()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_turns": 0}, "max_turns"),
        ({"max_turns": True}, "max_turns"),
        ({"max_chars_per_turn": 0}, "max_chars_per_turn"),
        ({"max_chars_per_turn": False}, "max_chars_per_turn"),
    ],
)
def test_context_rejects_invalid_bounds(
    kwargs: dict[str, int | bool],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        TransientConversationContextStore(**kwargs)
