"""오케스트레이터 배선을 검증한다.

LLM을 스텁으로 갈아 끼워 API 키 없이 전체 턴 흐름을 돌린다.
"""

from collections.abc import Generator

import httpx
from openai import APIConnectionError

from reminiscence.dialogue import DialogueManager, SessionContext
from reminiscence.dialogue.messages import ChatMessage
from reminiscence.dialogue.scenarios import Scenario


class StubLLM:
    """정해진 응답을 문장 단위로 흘려보내는 가짜 LLM(ReplyStreamer 구현)."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.last_system: str | None = None
        self.last_messages: list[ChatMessage] | None = None

    def stream_reply(
        self, system: str, messages: list[ChatMessage]
    ) -> Generator[str, None, str]:
        self.last_system = system
        self.last_messages = messages
        for sentence in self.reply.split("|"):
            yield sentence.strip()
        return self.reply.replace("|", " ").strip()


class FailingLLM:
    """연결이 끊긴 상황을 흉내내는 가짜 LLM."""

    def stream_reply(
        self, system: str, messages: list[ChatMessage]
    ) -> Generator[str, None, str]:
        raise APIConnectionError(request=httpx.Request("POST", "https://x"))
        yield ""  # pragma: no cover - 제너레이터로 만들기 위한 구문


class MisconfiguredLLM:
    """API 키가 없을 때처럼 SDK가 아닌 예외가 나는 상황."""

    def stream_reply(
        self, system: str, messages: list[ChatMessage]
    ) -> Generator[str, None, str]:
        raise TypeError("api_key must be set")
        yield ""  # pragma: no cover - 제너레이터로 만들기 위한 구문


def test_a_turn_flows_end_to_end() -> None:
    ctx = SessionContext(photo_meta="1998년 제주도, 본인과 딸")
    manager = DialogueManager(ctx, StubLLM("바다 앞에서 활짝 웃고 계시네요."))

    result = manager.respond("이거 뭐야")

    assert result.scenario is Scenario.S1_PHOTO
    assert result.reply == "바다 앞에서 활짝 웃고 계시네요."
    assert not result.violations
    assert len(ctx.history) == 2  # user + assistant


def test_photo_metadata_reaches_the_prompt() -> None:
    ctx = SessionContext(photo_meta="1998년 제주도, 본인과 딸")
    llm = StubLLM("좋으시겠어요.")

    DialogueManager(ctx, llm).respond("이거 뭐야")

    assert llm.last_messages is not None
    injected = llm.last_messages[-1]["content"]
    assert "1998년 제주도" in injected
    assert "이거 뭐야" in injected


def test_a_sensitive_utterance_is_queued_for_the_guardian() -> None:
    ctx = SessionContext(photo_meta="가족사진")
    manager = DialogueManager(ctx, StubLLM("지금 남편분 생각이 많이 나시나 봐요."))

    result = manager.respond("우리 남편은 언제 와?")

    assert result.scenario is Scenario.S6_SENSITIVE
    assert result.guardian_flagged
    assert len(ctx.guardian_flags) == 1
    assert ctx.guardian_flags[0].kind == "SENSITIVE"


def test_a_banned_phrase_never_reaches_tts() -> None:
    ctx = SessionContext(photo_meta="가족사진")
    # LLM이 원칙을 어기고 사망 통보를 하려는 상황
    manager = DialogueManager(ctx, StubLLM("남편분은 돌아가셨어요.|기억이 안 나시나 봐요."))

    spoken = list(manager.stream_turn("남편 어디 갔어?"))

    assert all("돌아가셨" not in sentence for sentence in spoken)
    assert spoken  # 대신 안전한 대체 문구가 나간다


def test_a_routine_reminder_clears_after_delivery() -> None:
    ctx = SessionContext(routine_type="점심 복약", routine_pending=True)
    manager = DialogueManager(ctx, StubLLM("점심 드실 시간이에요."))

    first = manager.respond("응")

    assert first.scenario is Scenario.S4_ROUTINE
    assert not ctx.routine_pending

    # 다음 턴은 더 이상 루틴으로 가지 않는다
    ctx.photo_meta = "가족사진"
    assert manager.respond("그래").scenario is not Scenario.S4_ROUTINE


def test_the_frame_can_speak_first_for_a_routine_reminder() -> None:
    # 설계서 S4는 어르신이 말을 걸기 전에 액자가 먼저 말한다
    ctx = SessionContext(routine_type="점심 복약", routine_pending=True)
    llm = StubLLM("점심 드실 시간이에요.|이따 그 사진 얘기 더 해주실래요?")
    manager = DialogueManager(ctx, llm)

    result = manager.initiate(Scenario.S4_ROUTINE)

    assert result.scenario is Scenario.S4_ROUTINE
    assert not result.degraded
    assert not ctx.routine_pending
    # 사용자 발화가 없으므로 이력에는 어시스턴트 턴만 남는다
    assert [t.role for t in ctx.history] == ["assistant"]


def test_an_initiated_turn_sends_the_directive_without_a_user_utterance() -> None:
    ctx = SessionContext(routine_type="점심 복약", routine_pending=True)
    llm = StubLLM("점심 드실 시간이에요.")

    DialogueManager(ctx, llm).initiate(Scenario.S4_ROUTINE)

    assert llm.last_messages is not None
    sent = llm.last_messages[-1]["content"]
    assert "점심 복약" in sent
    assert "[사용자 발화]" not in sent


def test_a_routine_reminder_still_fires_when_the_api_fails() -> None:
    # 복약 알림은 안전과 직결되므로 LLM이 죽어도 나가야 한다
    ctx = SessionContext(routine_type="점심 복약", routine_pending=True)
    manager = DialogueManager(ctx, FailingLLM())

    spoken = list(manager.stream_initiate(Scenario.S4_ROUTINE))

    assert spoken
    assert "점심 복약" in " ".join(spoken)


def test_an_api_failure_degrades_instead_of_raising() -> None:
    ctx = SessionContext(photo_meta="가족사진")
    manager = DialogueManager(ctx, FailingLLM())

    result = manager.respond("이거 뭐야")

    assert result.degraded
    assert result.reply
    assert ctx.history[-1].role == "assistant"


def test_the_directive_carries_phase_guidance_as_the_arc_advances() -> None:
    ctx = SessionContext(photo_meta="1998년 제주도, 본인과 딸")
    llm = StubLLM("좋으시겠어요.")
    manager = DialogueManager(ctx, llm)

    first = manager.respond("이거 뭐야")
    assert first.phase == "opening"
    assert llm.last_messages is not None
    assert "대화 단계: 진입" in llm.last_messages[-1]["content"]

    second = manager.respond("딸이랑 제주도 바다 갔던 사진이야")
    assert second.phase == "deepening"
    assert "대화 단계: 심화" in llm.last_messages[-1]["content"]
    # 이어가기 원칙이 항상 붙는다
    assert "이어가기 원칙" in llm.last_messages[-1]["content"]


def test_non_reminiscence_turns_report_no_phase() -> None:
    ctx = SessionContext(routine_type="점심 복약", routine_pending=True)
    result = DialogueManager(ctx, StubLLM("점심 드실 시간이에요.")).respond("응")

    assert result.scenario is Scenario.S4_ROUTINE
    assert result.phase is None


def test_a_missing_api_key_still_produces_speech() -> None:
    # 키를 빠뜨렸을 때 SDK는 APIError가 아니라 TypeError를 낸다.
    # 원인이 무엇이든 액자는 침묵하면 안 된다.
    ctx = SessionContext(photo_meta="가족사진")
    manager = DialogueManager(ctx, MisconfiguredLLM())

    result = manager.respond("이거 뭐야")

    assert result.degraded
    assert result.reply


def test_guardrail_violations_are_recorded_in_history() -> None:
    ctx = SessionContext(photo_meta="가족사진")
    manager = DialogueManager(ctx, StubLLM("이 사진 좋네요. 이분 누구예요?"))

    result = manager.respond("이거 뭐야")

    assert result.violations
    assert ctx.history[-1].violations == result.violations
    assert "누구예요?" not in result.reply
