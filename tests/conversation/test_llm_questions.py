"""Photo-aware codex-lb question provider tests."""

from __future__ import annotations

import base64
import json
from math import inf, nan
from typing import Any, cast

import pytest
import urllib3

from reminiscence.conversation.llm_questions import (
    DEFAULT_RESPONSE_MODEL,
    CodexLbFollowUpQuestionProvider,
    CodexLbQuestionConfig,
    QuestionGenerationUnavailableError,
)
from reminiscence.conversation.photos import PhotoMemory


class FakeResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self.data = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if not isinstance(payload, bytes)
            else payload
        )


class FakeHttp:
    def __init__(
        self,
        response: FakeResponse | None = None,
        error: urllib3.exceptions.HTTPError | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.requests: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def photo() -> PhotoMemory:
    return PhotoMemory(
        photo_id="family-1",
        image_base64=base64.b64encode(b"\x89PNG\r\n\x1a\nphoto").decode("ascii"),
        image_media_type="image/png",
        location="제주도 성산일출봉",
        people=("딸 영희", "손자 민준"),
        event="2022년 봄 가족여행",
        description="성산일출봉에 오르기 전에 함께 찍은 사진",
    )


def success_response(text: str = "이날 가장 즐거웠던 순간은 언제였나요?") -> FakeResponse:
    return FakeResponse(
        200,
        {
            "output": [
                {"type": "reasoning", "summary": []},
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": text}],
                },
            ]
        },
    )


def config(**overrides: Any) -> CodexLbQuestionConfig:
    values = {
        "api_key": "proxy-secret",
        "base_url": "https://codex-lb.example/v1",
    }
    values.update(overrides)
    return CodexLbQuestionConfig(**values)


def provider(http: FakeHttp) -> CodexLbFollowUpQuestionProvider:
    return CodexLbFollowUpQuestionProvider(
        config(),
        http=cast(urllib3.PoolManager, http),
    )


def request_payload(http: FakeHttp) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(http.requests[0]["body"]))


def test_follow_up_sends_photo_and_family_context() -> None:
    http = FakeHttp(success_response())

    result = provider(http).follow_up_question(
        photo(),
        "바람이 많이 불었지만 즐거웠어요.",
        1,
    )

    assert result.display_text == "이날 가장 즐거웠던 순간은 언제였나요?"
    assert result.spoken_text == result.display_text
    request = http.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == "https://codex-lb.example/v1/responses"
    assert request["headers"] == {
        "Authorization": "Bearer proxy-secret",
        "Content-Type": "application/json",
    }
    payload = request_payload(http)
    assert payload["model"] == DEFAULT_RESPONSE_MODEL
    assert payload["reasoning"] == {"effort": "none"}
    assert payload["store"] is False
    content = payload["input"][0]["content"]
    assert content[1] == {
        "type": "input_image",
        "image_url": photo().data_url,
        "detail": "low",
    }
    assert "제주도 성산일출봉" in content[0]["text"]
    assert "딸 영희, 손자 민준" in content[0]["text"]
    assert "2022년 봄 가족여행" in content[0]["text"]


def test_follow_up_uses_current_transcript_without_retaining_history() -> None:
    http = FakeHttp(success_response("그때 누구와 가장 많이 웃으셨나요?"))

    result = provider(http).follow_up_question(
        photo(),
        "민준이가 장난을 쳐서 많이 웃었어요.",
        2,
    )

    assert result.display_text == "그때 누구와 가장 많이 웃으셨나요?"
    prompt = request_payload(http)["input"][0]["content"][0]["text"]
    assert "사용자 응답 2번째" in prompt
    assert "민준이가 장난을 쳐서 많이 웃었어요." in prompt


def test_no_response_requests_a_low_pressure_question() -> None:
    http = FakeHttp(success_response())

    provider(http).follow_up_question(photo(), " \n", 1)

    prompt = request_payload(http)["input"][0]["content"][0]["text"]
    assert "답하지 않았습니다" in prompt


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not-json", "invalid JSON"),
        ([], "must be an object"),
        ({}, "missing output"),
        ({"output": []}, "no output text"),
        (
            {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "refusal", "refusal": "no"}],
                    }
                ]
            },
            "no output text",
        ),
    ],
)
def test_invalid_response_is_rejected(payload: object, message: str) -> None:
    with pytest.raises(QuestionGenerationUnavailableError, match=message):
        provider(FakeHttp(FakeResponse(200, payload))).follow_up_question(
            photo(),
            "즐거웠어요.",
            1,
        )


def test_overlong_question_is_rejected() -> None:
    with pytest.raises(QuestionGenerationUnavailableError, match="exceeds"):
        provider(FakeHttp(success_response("가" * 301))).follow_up_question(
            photo(),
            "즐거웠어요.",
            1,
        )


def test_non_success_status_does_not_expose_response_body() -> None:
    client = provider(
        FakeHttp(
            FakeResponse(
                401,
                {"error": {"message": "secret upstream detail"}},
            )
        )
    )

    with pytest.raises(QuestionGenerationUnavailableError, match="HTTP 401") as raised:
        client.follow_up_question(photo(), "즐거웠어요.", 1)

    assert "secret upstream detail" not in str(raised.value)


def test_transport_error_is_mapped_to_unavailable() -> None:
    client = provider(
        FakeHttp(error=urllib3.exceptions.HTTPError("connection failed"))
    )

    with pytest.raises(QuestionGenerationUnavailableError, match="request failed"):
        client.follow_up_question(photo(), "즐거웠어요.", 1)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"api_key": "  "}, "api_key"),
        ({"base_url": "https://codex.example"}, "ending in /v1"),
        ({"base_url": "ftp://codex.example/v1"}, "ending in /v1"),
        ({"model": ""}, "model"),
        ({"connect_timeout_seconds": 0}, "connect_timeout_seconds"),
        ({"connect_timeout_seconds": nan}, "connect_timeout_seconds"),
        ({"read_timeout_seconds": inf}, "read_timeout_seconds"),
    ],
)
def test_config_rejects_invalid_values(
    overrides: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        config(**overrides)
