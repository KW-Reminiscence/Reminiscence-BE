"""대화 흐름 오케스트레이터.

한 턴의 흐름::

    발화 -> 라우터(S1~S6 선택) -> 상황 지시문 조립 -> LLM 스트리밍
         -> 문장 단위로 TTS 방출 -> 출력 가드레일 -> 이력/플래그 기록

가드레일이 스트리밍 뒤에 오는 것이 의도적이다. 검사를 먼저 하려면 응답
전체를 기다려야 하고, 그러면 스트리밍의 지연 이득이 사라진다. 다만 금지
표현만은 예외로 각 문장이 나가기 전에 검사한다.
"""

from collections.abc import Generator
from dataclasses import dataclass, field

from anthropic.types import MessageParam

from reminiscence.dialogue import guardrails, prompts
from reminiscence.dialogue.context import SessionContext, Turn
from reminiscence.dialogue.llm_client import DialogueLLM, ReplyStreamer
from reminiscence.dialogue.router import route
from reminiscence.dialogue.scenarios import Scenario


@dataclass
class TurnResult:
    """한 턴을 처리한 결과."""

    scenario: Scenario
    reply: str
    violations: list[str] = field(default_factory=list)
    guardian_flagged: bool = False


class DialogueManager:
    """세션 하나의 대화 흐름을 관리한다."""

    def __init__(self, ctx: SessionContext, llm: ReplyStreamer | None = None) -> None:
        self.ctx = ctx
        self.llm: ReplyStreamer = llm if llm is not None else DialogueLLM()

    def respond(self, utterance: str) -> TurnResult:
        """한 턴을 처리하고 결과만 돌려준다(테스트·배치용)."""
        stream = self.stream_turn(utterance)
        while True:
            try:
                next(stream)
            except StopIteration as stop:
                result: TurnResult = stop.value
                return result

    def stream_turn(self, utterance: str) -> Generator[str, None, TurnResult]:
        """한 턴을 처리하며 문장을 흘려보내고, 마지막에 결과를 반환한다.

        yield되는 문장은 그대로 TTS 큐에 넣으면 된다.
        """
        ctx = self.ctx
        ctx.note_stall(utterance)

        scenario, signal = route(utterance, ctx)

        guardian_flagged = False
        if scenario is Scenario.S6_SENSITIVE:
            ctx.flag_guardian("SENSITIVE", f"{signal.keyword} 관련 발화: {utterance}")
            guardian_flagged = True

        ctx.add(Turn(role="user", text=utterance))

        messages = self._build_messages(utterance, scenario)
        system = prompts.build_system_prompt(ctx.device_name)

        raw = ""
        muted = False
        stream = self.llm.stream_reply(system, messages)
        while True:
            try:
                sentence = next(stream)
            except StopIteration as stop:
                raw = stop.value
                break

            # TTS로 내보내기 전에 금지 표현만 즉시 검사한다. 한 번 발화된
            # "돌아가셨어요"는 되돌릴 수 없기 때문에, 전체 검증을 기다리지
            # 않고 여기서 막는다. 문자열 포함 검사라 지연은 사실상 없다.
            if guardrails.has_forbidden(sentence):
                muted = True
                stream.close()
                break
            yield sentence

        verdict = guardrails.check_output(raw)

        if muted:
            # 막힌 문장 대신 안전한 대체 문구를 내보내 흐름을 복구한다.
            yield verdict.text

        if verdict.violations:
            ctx.flag_guardian("GUARDRAIL", ", ".join(verdict.violations))

        ctx.add(
            Turn(
                role="assistant",
                text=verdict.text,
                scenario=scenario.value,
                violations=verdict.violations,
            )
        )

        # 루틴 알림은 한 번 전달하면 내린다. 재알림은 루틴 모니터가 결정한다.
        if scenario is Scenario.S4_ROUTINE:
            ctx.routine_pending = False

        return TurnResult(
            scenario=scenario,
            reply=verdict.text,
            violations=verdict.violations,
            guardian_flagged=guardian_flagged,
        )

    def _build_messages(self, utterance: str, scenario: Scenario) -> list[MessageParam]:
        """최근 이력에 이번 턴의 상황 지시문을 얹는다.

        지시문을 마지막 user 메시지에 덧붙이므로 시스템 프롬프트는 매 턴
        동일하게 유지되고, 프롬프트 캐시 접두사가 깨지지 않는다.
        """
        messages = self.ctx.recent_messages()
        directive = prompts.build_turn_directive(scenario, self.ctx)
        messages[-1] = MessageParam(
            role="user",
            content=f"{directive}\n\n[사용자 발화]\n{utterance}",
        )
        return messages
