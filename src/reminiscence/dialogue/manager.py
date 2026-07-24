"""대화 흐름 오케스트레이터.

턴은 두 종류다.

사용자 주도 턴 (:meth:`DialogueManager.stream_turn`)::

    발화 -> 라우터(S1~S6 선택) -> 상황 지시문 조립 -> LLM 스트리밍
         -> 문장 단위로 TTS 방출 -> 출력 가드레일 -> 이력/플래그 기록

기기 주도 턴 (:meth:`DialogueManager.stream_initiate`)::

    트리거(루틴 알림·인사) -> 상황 지시문 조립 -> 이하 동일

설계서 S4 예시처럼 복약 알림은 어르신이 말을 걸기 전에 액자가 먼저 말한다.
그래서 사용자 발화 없이 시작하는 경로가 따로 필요하다.

가드레일이 스트리밍 뒤에 오는 것은 의도적이다. 검사를 먼저 하려면 응답
전체를 기다려야 하고, 그러면 스트리밍의 지연 이득이 사라진다. 다만 금지
표현만은 예외로 각 문장이 나가기 전에 검사한다.
"""

import logging
from collections.abc import Generator
from dataclasses import dataclass, field

from reminiscence.dialogue import fallbacks, guardrails, prompts
from reminiscence.dialogue.context import SessionContext, Turn
from reminiscence.dialogue.llm_client import DialogueLLM, ReplyStreamer
from reminiscence.dialogue.messages import ChatMessage
from reminiscence.dialogue.router import route
from reminiscence.dialogue.scenarios import REMINISCENCE_SCENARIOS, Scenario

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    """한 턴을 처리한 결과."""

    scenario: Scenario
    reply: str
    violations: list[str] = field(default_factory=list)
    guardian_flagged: bool = False

    degraded: bool = False
    """LLM 응답을 받지 못해 대체 문구를 내보냈는가."""

    phase: str | None = None
    """회상 대화 아크의 현재 단계. 회상 시나리오(S1~S3)에서만 채워진다."""


class DialogueManager:
    """세션 하나의 대화 흐름을 관리한다."""

    def __init__(self, ctx: SessionContext, llm: ReplyStreamer | None = None) -> None:
        self.ctx = ctx
        self.llm: ReplyStreamer = llm if llm is not None else DialogueLLM()

    # -- 사용자 주도 턴 --------------------------------------------------

    def respond(self, utterance: str) -> TurnResult:
        """한 턴을 처리하고 결과만 돌려준다(테스트·배치용)."""
        return _drain(self.stream_turn(utterance))

    def stream_turn(self, utterance: str) -> Generator[str, None, TurnResult]:
        """사용자 발화에 응답하며 문장을 흘려보낸다.

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

        # 방금 발화의 적극성으로 대화 아크 단계를 갱신한 뒤 지시문을 만든다.
        ctx.advance_flow(scenario, utterance, distress=signal.distress)

        directive = prompts.build_turn_directive(scenario, ctx)
        messages = ctx.recent_messages()
        # 지시문을 마지막 user 메시지에 덧붙이므로 시스템 프롬프트는 매 턴
        # 동일하게 유지되고, 프롬프트 캐시 접두사가 깨지지 않는다.
        messages[-1] = ChatMessage(
            role="user",
            content=f"{directive}\n\n[사용자 발화]\n{utterance}",
        )

        return (yield from self._run(scenario, messages, guardian_flagged))

    # -- 기기 주도 턴 ----------------------------------------------------

    def initiate(self, scenario: Scenario) -> TurnResult:
        """기기가 먼저 말을 걸고 결과만 돌려준다."""
        return _drain(self.stream_initiate(scenario))

    def stream_initiate(self, scenario: Scenario) -> Generator[str, None, TurnResult]:
        """사용자 발화 없이 액자가 먼저 말을 건다.

        루틴 모니터가 알림 시각을 알려왔을 때(S4)나, 사진이 바뀌어 말을
        걸고 싶을 때(S1~S3) 쓴다. 라우터를 거치지 않고 호출 측이 시나리오를
        직접 지정한다. 트리거를 아는 쪽은 하드웨어이기 때문이다.
        """
        # 액자가 먼저 말을 거는 턴. 회상 주제면 진입 단계에서 시작한다.
        self.ctx.begin_initiation(scenario)

        directive = prompts.build_turn_directive(scenario, self.ctx)
        messages = self.ctx.recent_messages()
        messages.append(ChatMessage(role="user", content=directive))

        return (yield from self._run(scenario, messages, guardian_flagged=False))

    # -- 공통 처리 -------------------------------------------------------

    def _run(
        self,
        scenario: Scenario,
        messages: list[ChatMessage],
        guardian_flagged: bool,
    ) -> Generator[str, None, TurnResult]:
        """스트리밍, 가드레일, 이력 기록을 한다."""
        ctx = self.ctx
        system = prompts.build_system_prompt(ctx.device_name)

        raw = ""
        muted = False
        degraded = False
        stream = self.llm.stream_reply(system, messages)

        while True:
            try:
                sentence = next(stream)
            except StopIteration as stop:
                raw = stop.value
                break
            except Exception:  # noqa: BLE001 - 액자는 어떤 경우에도 침묵하면 안 된다
                # 네트워크 단절, 타임아웃, 과부하, 설정 누락(API 키 없음) 등.
                # 원인이 무엇이든 어르신 앞의 액자가 아무 말도 하지 않으면
                # 고장으로 받아들이므로, 대체 문구를 내보내고 원인은 로그로 남긴다.
                logger.exception("대화 응답 생성 실패 (scenario=%s)", scenario.value)
                stream.close()
                degraded = True
                raw = fallbacks.utterance_for(scenario, ctx)
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

        # 이미 내보낸 문장 뒤에 이어 붙인다. 정상 스트림은 문장을 그때그때
        # 내보냈으므로 여기서 다시 말할 필요가 없다.
        if muted or degraded:
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

        phase = ctx.phase.value if scenario in REMINISCENCE_SCENARIOS else None

        return TurnResult(
            scenario=scenario,
            reply=verdict.text,
            violations=verdict.violations,
            guardian_flagged=guardian_flagged,
            degraded=degraded,
            phase=phase,
        )


def _drain(stream: Generator[str, None, TurnResult]) -> TurnResult:
    """문장을 모두 소비하고 결과만 꺼낸다."""
    while True:
        try:
            next(stream)
        except StopIteration as stop:
            result: TurnResult = stop.value
            return result
