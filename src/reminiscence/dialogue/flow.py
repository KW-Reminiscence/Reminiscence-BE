"""회상 대화의 진행 흐름(대화 아크).

시나리오(S1~S6)가 "무엇에 대해 말하는가"라면, 여기 정의하는 단계(Phase)는
"대화의 어느 지점에 와 있는가"이다. 두 축은 직교한다. 같은 사진 회상(S1)
안에서도 이제 막 말을 꺼낸 진입 단계일 수도, 한참 깊어진 심화 단계일 수도
있다.

회상요법의 대화는 아래 아크를 그린다.

    진입 -> 심화 -> 확장 -> 마무리

  - 진입: 부담 없는 단서를 던지고 긍정적 반응을 유도한다.
  - 심화: 어르신이 반응하면 감각·사람·감정으로 한 걸음씩 파고든다.
  - 확장: 충분히 이야기했으면 이어지는 다른 기억으로 넓힌다.
  - 마무리: 반응이 잦아들면 실패감 없이 따뜻하게 닫는다.

전이는 규칙 기반이다. 어르신의 직전 발화가 얼마나 적극적이었는지(engagement)로
판단하며, LLM에 다시 묻지 않는다. 왕복이 늘면 음성 대화 지연이 두 배가 되기
때문이다.
"""

from enum import StrEnum
from typing import Final

#: 진입에서 심화로 넘어간 뒤, 확장으로 넘어가기까지 머무는 최소 턴 수.
#: 바로 확장으로 가면 방금 꺼낸 이야기를 충분히 나누지 못한다.
_DEEPEN_BEFORE_BROADEN: Final[int] = 2

#: 짧은 반응이 이만큼 연속되면 마무리로 접어든다.
_MINIMAL_TO_WRAP: Final[int] = 2

#: 진전 없는 짧은 발화. 심화의 계기가 되지 못한다.
_FILLER: Final[frozenset[str]] = frozenset(
    ("응", "네", "어", "아", "몰라", "글쎄", "그래", "됐어")
)


class Phase(StrEnum):
    """회상 대화 아크의 현재 위치."""

    OPENING = "opening"
    """진입: 부담 없이 단서를 던지고 첫 반응을 유도한다."""

    DEEPENING = "deepening"
    """심화: 방금 하신 말에서 감각·사람·감정으로 한 걸음 더 들어간다."""

    BROADENING = "broadening"
    """확장: 이어지는 다른 기억으로 넓힌다."""

    WRAPPING = "wrapping"
    """마무리: 새 질문 없이 따뜻하게 정리한다."""


class Engagement(StrEnum):
    """어르신 발화가 얼마나 적극적이었는가."""

    ENGAGED = "engaged"
    """내용이 담긴 반응. 대화를 이어갈 실마리가 있다."""

    MINIMAL = "minimal"
    """짧거나 형식적인 반응. 밀어붙이면 부담이 된다."""

    CONFUSED = "confused"
    """혼란·불안. 회상보다 안정이 먼저다."""


def classify_engagement(utterance: str, *, distress: bool) -> Engagement:
    """발화의 적극성을 판정한다."""
    if distress:
        return Engagement.CONFUSED
    text = utterance.strip()
    if len(text) <= 3 or text in _FILLER:
        return Engagement.MINIMAL
    return Engagement.ENGAGED


def next_phase(
    current: Phase,
    engagement: Engagement,
    *,
    phase_turns: int,
    minimal_streak: int,
) -> Phase:
    """직전 발화의 적극성으로 다음 단계를 정한다(순수 함수).

    - 혼란: 곧바로 마무리로 접어든다.
    - 짧은 반응: 한두 번은 같은 단계에 머물며 각도를 바꿔 다시 유도하고,
      그래도 이어지지 않으면 마무리로 간다.
    - 적극적 반응: 진입에서 심화로, 심화가 무르익으면 확장으로 나아간다.
      마무리 단계에서 다시 적극적으로 답하시면 심화로 되돌린다(회복).
    """
    if engagement is Engagement.CONFUSED:
        return Phase.WRAPPING

    if engagement is Engagement.MINIMAL:
        if minimal_streak >= _MINIMAL_TO_WRAP:
            return Phase.WRAPPING
        return current

    # ENGAGED
    if current is Phase.OPENING:
        return Phase.DEEPENING
    if current is Phase.DEEPENING:
        return Phase.BROADENING if phase_turns >= _DEEPEN_BEFORE_BROADEN else current
    if current is Phase.WRAPPING:
        return Phase.DEEPENING
    return current
