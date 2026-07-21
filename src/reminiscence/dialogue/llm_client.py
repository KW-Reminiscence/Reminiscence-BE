"""Anthropic Messages API 래퍼.

음성 대화라서 지연이 곧 품질이다. 세 가지를 한다.

1. 스트리밍 - 첫 문장이 완성되는 즉시 TTS로 넘긴다. 응답 전체를 기다리면
   어르신 입장에서는 기기가 멈춘 것처럼 느껴진다.
2. thinking 미사용 - 1~2문장 공감 응답에 추론 단계는 지연만 늘린다. 대신
   시스템 프롬프트에 "최종 발화문만 출력" 규칙을 넣었다.
3. effort=low - 같은 이유.
"""

import re
from collections.abc import Generator
from typing import Final, Protocol

import anthropic
from anthropic.lib.streaming import MessageStream, MessageStreamManager
from anthropic.lib.streaming._beta_messages import BetaMessageStream, BetaMessageStreamManager
from anthropic.types import MessageParam
from anthropic.types.beta import BetaMessageParam

from reminiscence.dialogue import config

#: 표준·beta 스트림 모두 text_stream만 쓰므로 한 경로로 처리한다.
StreamManager = MessageStreamManager | BetaMessageStreamManager
Stream = MessageStream | BetaMessageStream

#: 한국어 문장 끝. TTS로 넘길 단위를 자르는 기준이다.
_SENTENCE_END: Final[re.Pattern[str]] = re.compile(
    r".*?(?:[.!?…]|[다요죠])(?=\s|$)", re.DOTALL
)


class ReplyStreamer(Protocol):
    """대화 엔진이 LLM에 요구하는 최소 인터페이스.

    테스트는 이 프로토콜을 만족하는 스텁을 끼워 API 호출 없이 돈다.
    """

    def stream_reply(
        self, system: str, messages: list[MessageParam]
    ) -> Generator[str, None, str]:
        """문장을 순서대로 yield하고, 마지막에 전체 응답을 반환한다."""
        ...


class DialogueLLM:
    """Anthropic API로 회상 대화 응답을 받아오는 기본 구현."""

    def __init__(self, client: anthropic.Anthropic | None = None) -> None:
        # 인자 없는 생성자는 ANTHROPIC_API_KEY 또는 `ant auth login` 프로필을
        # 자동으로 찾는다. 키를 코드에 박지 않는다.
        self._client = client if client is not None else anthropic.Anthropic()

    def stream_reply(
        self, system: str, messages: list[MessageParam]
    ) -> Generator[str, None, str]:
        """응답을 문장 단위로 스트리밍하고 전체 텍스트를 반환한다."""
        if config.FAST_MODE:
            try:
                return (yield from self._pump(self._fast(system, messages)))
            except anthropic.RateLimitError:
                # fast mode는 표준 Opus와 별도 한도를 쓴다. 429는 연결 시점,
                # 즉 첫 yield 이전에 발생하므로 재시도해도 중복 출력이 없다.
                pass
        return (yield from self._pump(self._standard(system, messages)))

    def _pump(self, manager: StreamManager) -> Generator[str, None, str]:
        buffer = ""
        full = ""

        with manager as stream:
            for delta in self._deltas(stream):
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
    def _deltas(stream: Stream) -> Generator[str, None, None]:
        yield from stream.text_stream

    def _standard(self, system: str, messages: list[MessageParam]) -> StreamManager:
        return self._client.messages.stream(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=system,
            messages=messages,
            output_config={"effort": config.EFFORT},
        )

    def _fast(self, system: str, messages: list[MessageParam]) -> StreamManager:
        """Fast mode는 beta 엔드포인트 + beta 플래그 + speed가 모두 필요하다."""
        return self._client.beta.messages.stream(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=system,
            messages=self._to_beta(messages),
            output_config={"effort": config.EFFORT},
            speed="fast",
            betas=[config.FAST_MODE_BETA],
        )

    @staticmethod
    def _to_beta(messages: list[MessageParam]) -> list[BetaMessageParam]:
        """beta 엔드포인트용 파라미터로 옮긴다.

        회상 대화는 텍스트만 주고받으므로 content가 str인 경우만 다룬다.
        사진을 이미지 블록으로 직접 넘기게 되면 여기를 확장해야 한다.
        """
        beta: list[BetaMessageParam] = []
        for message in messages:
            content = message["content"]
            if not isinstance(content, str):
                raise TypeError("대화 엔진은 텍스트 메시지만 지원한다")
            beta.append(BetaMessageParam(role=message["role"], content=content))
        return beta
