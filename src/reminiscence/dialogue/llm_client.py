"""OpenAI(ChatGPT) Chat Completions API 래퍼.

음성 대화라서 지연이 곧 품질이다. 세 가지를 한다.

1. 스트리밍 - 첫 문장이 완성되는 즉시 TTS로 넘긴다. 응답 전체를 기다리면
   어르신 입장에서는 기기가 멈춘 것처럼 느껴진다.
2. 짧은 max_tokens - 회상 응답은 1~2문장이라 길게 뽑을 이유가 없다.
3. 짧은 타임아웃 - 기본값(10분)은 음성 대화에 쓸 수 없다. 빨리 실패하고
   대체 문구를 내보낸다.

제공자 교체를 대비해 대화 엔진은 ReplyStreamer 프로토콜에만 의존한다.
OpenAI 고유 타입은 이 파일 밖으로 새지 않는다.
"""

import logging
import os
import re
from collections.abc import Generator, Iterable
from typing import Final, Protocol

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from reminiscence.dialogue import config
from reminiscence.dialogue.messages import ChatMessage

logger = logging.getLogger(__name__)

#: 한국어 문장 끝. TTS로 넘길 단위를 자르는 기준이다.
#:
#: 구두점으로만 판별한다. 종결어미(다/요/죠)까지 경계로 삼으면 "바다 앞에서"의
#: "바다"에서 끊겨 TTS가 한 문장을 두 번에 나눠 읽는다. 구두점 없이 끝나는
#: 마지막 조각은 스트림이 끝날 때 남은 버퍼로 함께 내보낸다.
_SENTENCE_END: Final[re.Pattern[str]] = re.compile(r".*?[.!?…。](?=\s|$)", re.DOTALL)


def _has_credentials() -> bool:
    """SDK가 찾아 쓸 자격 증명이 환경에 있는지 본다."""
    return bool(os.getenv("OPENAI_API_KEY"))


class ReplyStreamer(Protocol):
    """대화 엔진이 LLM에 요구하는 최소 인터페이스.

    테스트는 이 프로토콜을 만족하는 스텁을 끼워 API 호출 없이 돈다.
    """

    def stream_reply(
        self, system: str, messages: list[ChatMessage]
    ) -> Generator[str, None, str]:
        """문장을 순서대로 yield하고, 마지막에 전체 응답을 반환한다."""
        ...


class DialogueLLM:
    """OpenAI Chat Completions API로 회상 대화 응답을 받아오는 기본 구현."""

    def __init__(self, client: OpenAI | None = None) -> None:
        # 키가 없어도 앱은 떠야 한다(/health가 죽으면 배포가 실패한다). 그런데
        # OpenAI 클라이언트는 생성 시점에 키가 없으면 바로 예외를 던진다. 그래서
        # 여기서 만들지 않고 첫 요청 때 만든다(_ensure_client). 키 누락은 그때
        # 예외로 드러나고, manager가 잡아 대체 문구로 응답한다.
        self._client = client

        if client is None and not _has_credentials():
            # 첫 대화에서야 알아채면 원인을 찾기 어려우므로 기동 시 알린다.
            logger.warning(
                "OPENAI_API_KEY가 설정되지 않았습니다. "
                "대화 요청은 모두 대체 문구로 응답합니다."
            )

    def _ensure_client(self) -> OpenAI:
        """클라이언트를 지연 생성한다.

        OPENAI_API_KEY와 OPENAI_BASE_URL은 환경에서 찾는다. 프록시/게이트웨이를
        쓰면 OPENAI_BASE_URL로 엔드포인트를 지정한다. 키를 코드에 박지 않는다.

        기본 타임아웃(10분)과 재시도(2회)는 음성 대화에 맞지 않아 줄인다.
        """
        if self._client is None:
            self._client = OpenAI(
                timeout=config.REQUEST_TIMEOUT_SECONDS,
                max_retries=config.MAX_RETRIES,
                # 게이트웨이 앞 Cloudflare가 SDK 기본 User-Agent를 막는다.
                default_headers={"User-Agent": config.USER_AGENT},
            )
        return self._client

    def stream_reply(
        self, system: str, messages: list[ChatMessage]
    ) -> Generator[str, None, str]:
        """응답을 문장 단위로 스트리밍하고 전체 텍스트를 반환한다."""
        buffer = ""
        full = ""

        # 키가 없으면 여기서 OpenAIError가 난다. manager가 잡아 대체 문구로
        # 응답하므로 액자는 침묵하지 않는다.
        stream = self._ensure_client().chat.completions.create(
            model=config.MODEL,
            messages=self._to_openai(system, messages),
            max_tokens=config.MAX_TOKENS,
            temperature=config.TEMPERATURE,
            stream=True,
        )

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if not delta:
                continue

            buffer += delta
            full += delta

            while True:
                match = _SENTENCE_END.match(buffer)
                if match is None:
                    break
                sentence = match.group(0).strip()
                buffer = buffer[match.end() :].lstrip()
                if sentence:
                    yield sentence

        tail = buffer.strip()
        if tail:
            yield tail
        return full.strip()

    @staticmethod
    def _to_openai(
        system: str, messages: list[ChatMessage]
    ) -> Iterable[ChatCompletionMessageParam]:
        """system 프롬프트를 맨 앞에 붙여 OpenAI 형식으로 옮긴다."""
        result: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system}
        ]
        for message in messages:
            if message["role"] == "user":
                result.append({"role": "user", "content": message["content"]})
            else:
                result.append({"role": "assistant", "content": message["content"]})
        return result
