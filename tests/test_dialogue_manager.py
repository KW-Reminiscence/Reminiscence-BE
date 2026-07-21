"""오케스트레이터 배선을 검증한다.

LLM을 스텁으로 갈아 끼워 API 키 없이 전체 턴 흐름을 돌린다.
"""

from collections.abc import Generator

from anthropic.types import MessageParam

from reminiscence.dialogue import DialogueManager, SessionContext
from reminiscence.dialogue.scenarios import Scenario


class StubLLM:
    """정해진 응답을 문장 단위로 흘려보내는 가짜 LLM(ReplyStreamer 구현)."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.last_system: str | None = None
        self.last_messages: list[MessageParam] | None = None

    def stream_reply(
        self, system: str, messages: list[MessageParam]
    ) -> Generator[str, None, str]:
        self.last_system = system
        self.last_messages = messages
        for sentence in self.reply.split("|"):
            yield sentence.strip()
        return self.reply.replace("|", " ").strip()


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


def test_guardrail_violations_are_recorded_in_history() -> None:
    ctx = SessionContext(photo_meta="가족사진")
    manager = DialogueManager(ctx, StubLLM("이 사진 좋네요. 이분 누구예요?"))

    result = manager.respond("이거 뭐야")

    assert result.violations
    assert ctx.history[-1].violations == result.violations
    assert "누구예요?" not in result.reply
