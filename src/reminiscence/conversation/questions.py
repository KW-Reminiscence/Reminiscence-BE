"""Safe, provider-neutral question generation for reminiscence sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from reminiscence.conversation.photos import PhotoMemory


@dataclass(frozen=True, slots=True)
class SpeechText:
    """Text displayed by the web app and synthesized by Supertonic 3."""

    display_text: str
    spoken_text: str


class QuestionProvider(Protocol):
    """Boundary for photo-aware question generation."""

    def initial_question(self, photo: PhotoMemory) -> SpeechText:
        """Return a non-leading opening question."""

        ...

    def follow_up_question(
        self,
        photo: PhotoMemory,
        transcript: str,
        turn_count: int,
        session_context: tuple[str, ...] = (),
    ) -> SpeechText:
        """Return a follow-up using transient current-session context."""

        ...


class FollowUpQuestionProvider(Protocol):
    """Boundary for an AI-backed follow-up implementation."""

    def follow_up_question(
        self,
        photo: PhotoMemory,
        transcript: str,
        turn_count: int,
        session_context: tuple[str, ...] = (),
    ) -> SpeechText:
        """Return a follow-up using transient current-session context."""

        ...


class SafeTemplateQuestionProvider:
    """Deterministic MVP fallback that never asserts facts about a photo."""

    _FOLLOW_UPS = (
        "이 사진에서 가장 먼저 눈에 들어오는 것은 무엇인가요?",
        "이 사진을 보면 어떤 기분이나 분위기가 떠오르시나요?",
        "이 사진과 함께 떠오르는 이야기가 있다면 들려주세요.",
    )

    def initial_question(self, photo: PhotoMemory) -> SpeechText:
        text = "이 사진을 천천히 보시고, 떠오르는 이야기가 있으면 들려주세요."
        return SpeechText(display_text=text, spoken_text=text)

    def follow_up_question(
        self,
        photo: PhotoMemory,
        transcript: str,
        turn_count: int,
        session_context: tuple[str, ...] = (),
    ) -> SpeechText:
        index = max(0, turn_count - 1) % len(self._FOLLOW_UPS)
        text = self._FOLLOW_UPS[index]
        return SpeechText(display_text=text, spoken_text=text)


class TemplateOpeningQuestionProvider:
    """Use a deterministic opening and delegate only follow-up turns to AI."""

    _OPENING_TEXT = (
        "이 사진을 천천히 보시고, 떠오르는 이야기가 있으면 들려주세요."
    )

    def __init__(self, follow_up_provider: FollowUpQuestionProvider) -> None:
        self._follow_up_provider = follow_up_provider

    def initial_question(self, photo: PhotoMemory) -> SpeechText:
        return SpeechText(
            display_text=self._OPENING_TEXT,
            spoken_text=self._OPENING_TEXT,
        )

    def follow_up_question(
        self,
        photo: PhotoMemory,
        transcript: str,
        turn_count: int,
        session_context: tuple[str, ...] = (),
    ) -> SpeechText:
        return self._follow_up_provider.follow_up_question(
            photo,
            transcript,
            turn_count,
            session_context,
        )
