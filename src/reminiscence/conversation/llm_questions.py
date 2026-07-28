"""Photo-aware reminiscence questions through a codex-lb Responses API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

import urllib3

from reminiscence.conversation.photos import PhotoMemory
from reminiscence.conversation.questions import SpeechText

DEFAULT_BASE_URL = "http://127.0.0.1:2455/v1"
DEFAULT_RESPONSE_MODEL = "gpt-5.6-sol"
MAX_QUESTION_CHARS = 300

SYSTEM_INSTRUCTIONS = """\
당신은 어르신과 사진을 보며 따뜻한 회상 대화를 나누는 한국어 대화 도우미입니다.
가족이 제공한 사진 정보와 사진에 보이는 내용을 참고하되, 사실을 단정하거나 기억을
시험하지 마세요. 사용자의 기억이 제공 정보와 다르더라도 정정하거나 논쟁하지 마세요.
한 번에 하나의 짧고 열린 질문만 하세요. 질문은 존댓말로 자연스럽게 작성하고,
의학적 진단·치료 조언이나 평가를 하지 마세요. 설명이나 머리말 없이 질문만 출력하세요.
"""


class QuestionGenerationUnavailableError(RuntimeError):
    """Raised when the configured LLM cannot generate a safe question."""


def _is_finite_positive(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
        and value > 0
    )


@dataclass(frozen=True, slots=True)
class CodexLbQuestionConfig:
    """Validated codex-lb Responses API settings."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_RESPONSE_MODEL
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ValueError("api_key must not be blank")
        if not isinstance(self.base_url, str):
            raise ValueError("base_url must be a valid HTTP URL ending in /v1")
        parsed_url = urlsplit(self.base_url)
        try:
            port = parsed_url.port
        except ValueError as exc:
            raise ValueError(
                "base_url must be a valid HTTP URL ending in /v1"
            ) from exc
        if (
            parsed_url.scheme not in {"http", "https"}
            or parsed_url.hostname is None
            or parsed_url.username is not None
            or parsed_url.password is not None
            or port == 0
            or parsed_url.query
            or parsed_url.fragment
            or not parsed_url.path.rstrip("/").endswith("/v1")
        ):
            raise ValueError("base_url must be a valid HTTP URL ending in /v1")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model must not be blank")
        for field_name, value in (
            ("connect_timeout_seconds", self.connect_timeout_seconds),
            ("read_timeout_seconds", self.read_timeout_seconds),
        ):
            if not _is_finite_positive(value):
                raise ValueError(f"{field_name} must be finite and positive")

    @property
    def responses_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/responses"

    @classmethod
    def from_environment(cls) -> CodexLbQuestionConfig:
        """Read the existing codex-lb proxy settings without persisting them."""

        api_key = os.environ.get("CODEX_LB_API_KEY", "")
        if not api_key:
            raise RuntimeError("CODEX_LB_API_KEY is required")
        try:
            connect_timeout = float(
                os.environ.get("CODEX_LB_CONNECT_TIMEOUT_SECONDS", "10.0")
            )
            read_timeout = float(
                os.environ.get("CODEX_LB_RESPONSE_READ_TIMEOUT_SECONDS", "60.0")
            )
        except ValueError as exc:
            raise RuntimeError(
                "codex-lb question timeout environment values are invalid"
            ) from exc
        return cls(
            api_key=api_key,
            base_url=os.environ.get("CODEX_LB_BASE_URL", DEFAULT_BASE_URL),
            model=os.environ.get("CODEX_LB_RESPONSE_MODEL", DEFAULT_RESPONSE_MODEL),
            connect_timeout_seconds=connect_timeout,
            read_timeout_seconds=read_timeout,
        )


class CodexLbQuestionProvider:
    """Generate transient, photo-aware questions without retaining transcripts."""

    def __init__(
        self,
        config: CodexLbQuestionConfig,
        http: urllib3.PoolManager | None = None,
    ) -> None:
        self._config = config
        self._http = http if http is not None else urllib3.PoolManager()

    def initial_question(self, photo: PhotoMemory) -> SpeechText:
        """Generate an opening question from the configured memory."""

        prompt = (
            "다음 사진과 가족 제공 정보를 바탕으로 회상 대화를 시작하는 질문을 만드세요.\n"
            f"{self._photo_context(photo)}"
        )
        return self._generate(photo, prompt)

    def follow_up_question(
        self,
        photo: PhotoMemory,
        transcript: str,
        turn_count: int,
    ) -> SpeechText:
        """Generate one follow-up from the current answer and photo context."""

        normalized_transcript = transcript.strip()
        if not normalized_transcript:
            prompt = (
                "사용자가 이번에는 답하지 않았습니다. 부담을 주지 않는 다른 질문을 "
                "하나 만드세요.\n"
                f"{self._photo_context(photo)}"
            )
        else:
            prompt = (
                f"현재 대화는 사용자 응답 {turn_count}번째입니다. 다음 사진 정보와 "
                "방금 답변을 자연스럽게 이어가는 질문을 하나 만드세요.\n"
                f"{self._photo_context(photo)}\n"
                f"방금 사용자 답변: {normalized_transcript}"
            )
        return self._generate(photo, prompt)

    @staticmethod
    def _photo_context(photo: PhotoMemory) -> str:
        return "\n".join(
            (
                f"장소: {photo.location}",
                f"함께한 사람: {', '.join(photo.people)}",
                f"일어난 일: {photo.event}",
                f"가족 설명: {photo.description}",
            )
        )

    def _generate(self, photo: PhotoMemory, prompt: str) -> SpeechText:
        request_body = {
            "model": self._config.model,
            "reasoning": {"effort": "none"},
            "instructions": SYSTEM_INSTRUCTIONS,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": photo.data_url,
                            "detail": "low",
                        },
                    ],
                }
            ],
            "max_output_tokens": 200,
            "store": False,
        }
        try:
            response = self._http.request(
                "POST",
                self._config.responses_url,
                headers={
                    "Authorization": f"Bearer {self._config.api_key}",
                    "Content-Type": "application/json",
                },
                body=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
                timeout=urllib3.Timeout(
                    connect=self._config.connect_timeout_seconds,
                    read=self._config.read_timeout_seconds,
                ),
                retries=False,
                redirect=False,
            )
        except urllib3.exceptions.HTTPError as exc:
            raise QuestionGenerationUnavailableError(
                "codex-lb question request failed"
            ) from exc
        if response.status != 200:
            raise QuestionGenerationUnavailableError(
                f"codex-lb question generation failed with HTTP {response.status}"
            )
        text = self._parse_output_text(response.data)
        return SpeechText(display_text=text, spoken_text=text)

    @staticmethod
    def _parse_output_text(response_body: bytes) -> str:
        try:
            payload: Any = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QuestionGenerationUnavailableError(
                "codex-lb question response was invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise QuestionGenerationUnavailableError(
                "codex-lb question response must be an object"
            )
        output = payload.get("output")
        if not isinstance(output, list):
            raise QuestionGenerationUnavailableError(
                "codex-lb question response is missing output"
            )
        texts: list[str] = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "output_text":
                    continue
                value = part.get("text")
                if isinstance(value, str):
                    texts.append(value)
        text = "\n".join(texts).strip()
        if not text:
            raise QuestionGenerationUnavailableError(
                "codex-lb question response has no output text"
            )
        if len(text) > MAX_QUESTION_CHARS:
            raise QuestionGenerationUnavailableError(
                f"generated question exceeds {MAX_QUESTION_CHARS} characters"
            )
        return text
