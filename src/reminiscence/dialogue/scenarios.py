"""시나리오 분류 체계.

설계서 2장에서 출발했고, 회상요법 문헌을 반영해 다음이 바뀌었다.

- S3(음악 회상) 제거. 액자는 사진 중심 기기이고, 음악 재생은 하드웨어
  범위에서 빠졌다. 음악은 별도 시나리오가 아니라 회상 대화 속 청각 단서
  (그 시절 유행가 이야기)로 자연스럽게 다뤄진다.
- S1/S2는 생애 주제(life themes) 위에서 진행된다. 치매에서 젊은 시절
  (약 6~30세) 기억이 가장 잘 보존된다는 회상 절정(reminiscence bump)
  연구에 따라, 대화는 그 시기의 문화적 생애 각본(학창 시절, 첫 직장,
  결혼, 육아 등)을 축으로 삼는다. themes.py 참고.
"""

from enum import StrEnum


class Scenario(StrEnum):
    """회상 대화가 취할 수 있는 상황 유형."""

    S1_PHOTO = "S1"
    """개인 사진 회상: 가족사진 등 본인 삶의 장면에서 출발한다."""

    S2_ERA_PHOTO = "S2"
    """시대 사진 회상: 그 세대가 공유하는 시절 장면(시장, 학교, 골목)에서
    출발한다. 개인 사진이 없거나 반응이 없을 때의 대안 경로다."""

    S4_ROUTINE = "S4"
    """루틴-회상 연계 알림."""

    S5_AFFECT = "S5"
    """정서 케어 대화."""

    S6_SENSITIVE = "S6"
    """민감 상황 대응."""

    CLOSING = "CLOSING"
    """마무리(설계서 원칙 6)."""


LABELS: dict[Scenario, str] = {
    Scenario.S1_PHOTO: "개인 사진 회상",
    Scenario.S2_ERA_PHOTO: "시대 사진 회상",
    Scenario.S4_ROUTINE: "루틴-회상 연계 알림",
    Scenario.S5_AFFECT: "정서 케어 대화",
    Scenario.S6_SENSITIVE: "민감 상황 대응",
    Scenario.CLOSING: "마무리",
}

#: 대화 아크(진입→심화→확장→마무리)를 갖는 시나리오.
#: 나머지(루틴·정서·민감·마무리)는 단발성/반응성이라 단계 개념이 없다.
REMINISCENCE_SCENARIOS: frozenset[Scenario] = frozenset(
    {Scenario.S1_PHOTO, Scenario.S2_ERA_PHOTO}
)
