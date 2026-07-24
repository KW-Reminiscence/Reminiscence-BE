"""시나리오 라우터.

규칙 기반이다. LLM에게 "어떤 시나리오인지 고르라"고 한 번 더 물으면 왕복이
하나 늘어 음성 대화 지연이 두 배가 된다. 트리거는 대부분 하드웨어 상태
(사진 표시 중/알림 시각)라서 규칙으로 충분하다.

우선순위는 안전 순이다. 민감 상황이 어떤 트리거보다 앞선다.
"""

from reminiscence.dialogue.context import SessionContext
from reminiscence.dialogue.guardrails import InputSignal, scan_input
from reminiscence.dialogue.scenarios import Scenario


def route(utterance: str, ctx: SessionContext) -> tuple[Scenario, InputSignal]:
    """발화와 컨텍스트로 이번 턴의 시나리오를 고른다."""
    signal = scan_input(utterance)

    # S6 - 민감 상황. 어떤 트리거보다 우선한다.
    if signal.sensitive:
        ctx.last_sensitive_keyword = signal.keyword
        ctx.affect_state = "부정"
        return Scenario.S6_SENSITIVE, signal

    # 마무리 - 대화가 정체됨 (설계서 원칙 6)
    if ctx.stalled:
        return Scenario.CLOSING, signal

    # S5 - 혼란/불안 신호
    if signal.distress:
        ctx.affect_state = "혼란"
        return Scenario.S5_AFFECT, signal

    # S4 - 미이행 루틴이 걸려 있으면 회상 대화에 얹는다
    if ctx.routine_pending:
        return Scenario.S4_ROUTINE, signal

    # S1 / S2 - 사진 표시 중. 개인 사진인지 시대 사진인지로 갈린다.
    if ctx.photo_meta is not None:
        if _is_era_photo(ctx.photo_meta):
            return Scenario.S2_ERA_PHOTO, signal
        return Scenario.S1_PHOTO, signal

    # 기본값 - 단서 없이 말을 거신 경우
    return Scenario.S5_AFFECT, signal


def _is_era_photo(photo_meta: str) -> bool:
    """시대별 사진 세트인지 판별한다.

    사진 DB가 메타데이터에 태그를 넣어주는 것이 정석이므로, 여기 문자열
    검사는 태그가 없을 때의 임시 대비책이다.
    """
    return "시대" in photo_meta or "자료사진" in photo_meta
