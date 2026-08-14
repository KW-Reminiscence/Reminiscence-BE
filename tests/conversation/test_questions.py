"""Question routing tests for the poster-defined conversation flow."""

from __future__ import annotations

import base64

from reminiscence.conversation.photos import PhotoMemory
from reminiscence.conversation.questions import (
    SpeechText,
    TemplateOpeningQuestionProvider,
)


class RecordingFollowUpProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[PhotoMemory, str, int, tuple[str, ...]]] = []

    def follow_up_question(
        self,
        photo: PhotoMemory,
        transcript: str,
        turn_count: int,
        session_context: tuple[str, ...] = (),
    ) -> SpeechText:
        self.calls.append((photo, transcript, turn_count, session_context))
        return SpeechText(
            display_text="그때 어떤 기분이 드셨나요?",
            spoken_text="그때 어떤 기분이 드셨나요?",
        )


def photo() -> PhotoMemory:
    return PhotoMemory(
        photo_id="family-1",
        image_base64=base64.b64encode(b"\x89PNG\r\n\x1a\nphoto").decode("ascii"),
        image_media_type="image/png",
        location="제주도",
        people=("딸 영희",),
        event="가족여행",
        description="함께 웃고 있는 사진",
    )


def test_initial_question_is_fixed_without_calling_llm() -> None:
    llm = RecordingFollowUpProvider()
    provider = TemplateOpeningQuestionProvider(llm)

    question = provider.initial_question(photo())

    assert question.display_text == (
        "이 사진을 천천히 보시고, 떠오르는 이야기가 있으면 들려주세요."
    )
    assert question.spoken_text == question.display_text
    assert llm.calls == []


def test_follow_up_question_is_delegated_to_llm() -> None:
    llm = RecordingFollowUpProvider()
    provider = TemplateOpeningQuestionProvider(llm)
    configured_photo = photo()

    question = provider.follow_up_question(
        configured_photo,
        "바람이 많이 불었지만 즐거웠어요.",
        1,
        ("딸과 제주도에 갔어요.",),
    )

    assert question.display_text == "그때 어떤 기분이 드셨나요?"
    assert llm.calls == [
        (
            configured_photo,
            "바람이 많이 불었지만 즐거웠어요.",
            1,
            ("딸과 제주도에 갔어요.",),
        )
    ]
