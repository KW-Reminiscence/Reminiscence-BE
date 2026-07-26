"""Safe, provider-neutral question generation for reminiscence sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SpeechText:
    """Text displayed by the web app and spoken by browser TTS."""

    display_text: str
    spoken_text: str


class QuestionProvider(Protocol):
    """Boundary for future AI-backed question generation."""

    def initial_question(self) -> SpeechText:
        """Return a non-leading opening question."""

        ...

    def follow_up_question(self, turn_count: int) -> SpeechText:
        """Return a non-leading follow-up without requiring transcript retention."""

        ...


class SafeTemplateQuestionProvider:
    """Deterministic MVP fallback that never asserts facts about a photo."""

    _FOLLOW_UPS = (
        "이 사진에서 가장 먼저 눈에 들어오는 것은 무엇인가요?",
        "이 사진을 보면 어떤 기분이나 분위기가 떠오르시나요?",
        "이 사진과 함께 떠오르는 이야기가 있다면 들려주세요.",
    )

    def initial_question(self) -> SpeechText:
        text = "이 사진을 천천히 보시고, 떠오르는 이야기가 있으면 들려주세요."
        return SpeechText(display_text=text, spoken_text=text)

    def follow_up_question(self, turn_count: int) -> SpeechText:
        index = max(0, turn_count - 1) % len(self._FOLLOW_UPS)
        text = self._FOLLOW_UPS[index]
        return SpeechText(display_text=text, spoken_text=text)
