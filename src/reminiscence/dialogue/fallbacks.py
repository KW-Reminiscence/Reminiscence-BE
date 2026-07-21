"""LLM 호출이 실패했을 때 대신 내보낼 문구.

액자는 어르신 앞에 놓인 기기다. 네트워크가 끊기거나 API가 느리다고 해서
아무 말도 하지 않으면, 어르신은 그것을 고장이나 무시로 받아들인다.
그래서 모든 시나리오에 LLM 없이도 나갈 수 있는 문장을 둔다.

특히 S4(복약·식사 알림)는 안전과 직결된다. LLM이 죽어도 알림 자체는
반드시 나가야 하므로, 여기서는 회상 유도를 빼고 알림만 전달한다.
"""

from typing import Final

from reminiscence.dialogue.context import SessionContext
from reminiscence.dialogue.scenarios import Scenario

#: 발화를 알아듣지 못했거나 응답을 못 받았을 때. 어르신을 탓하지 않는 문장을 쓴다.
_GENERIC: Final[str] = "제가 잠깐 딴생각을 했네요. 다시 한번 말씀해 주시겠어요?"

_BY_SCENARIO: Final[dict[Scenario, str]] = {
    Scenario.S5_AFFECT: "그러셨군요. 저는 여기 있어요.",
    Scenario.S6_SENSITIVE: "그 생각이 많이 나시나 봐요. 제가 옆에 있을게요.",
    Scenario.CLOSING: "오늘 이야기 나눠서 좋았어요. 편히 쉬세요.",
}


def utterance_for(scenario: Scenario, ctx: SessionContext) -> str:
    """LLM 없이 내보낼 문장을 고른다."""
    if scenario is Scenario.S4_ROUTINE:
        # 알림은 반드시 전달되어야 하므로 회상 유도를 빼고 용건만 말한다.
        return f"{ctx.routine_type or '약'} 드실 시간이에요."
    return _BY_SCENARIO.get(scenario, _GENERIC)
