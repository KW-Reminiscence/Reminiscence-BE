"""설계서 2장의 시나리오 분류 체계(S1~S6)."""

from enum import StrEnum


class Scenario(StrEnum):
    """회상 대화가 취할 수 있는 상황 유형."""

    S1_PHOTO = "S1"
    """사진 기반 회상 대화."""

    S2_ERA_PHOTO = "S2"
    """시대별 사진 회상."""

    S3_MUSIC = "S3"
    """음악 기반 회상."""

    S4_ROUTINE = "S4"
    """루틴-회상 연계 알림."""

    S5_AFFECT = "S5"
    """정서 케어 대화."""

    S6_SENSITIVE = "S6"
    """민감 상황 대응."""

    CLOSING = "CLOSING"
    """마무리(설계서 원칙 6)."""


LABELS: dict[Scenario, str] = {
    Scenario.S1_PHOTO: "사진 기반 회상 대화",
    Scenario.S2_ERA_PHOTO: "시대별 사진 회상",
    Scenario.S3_MUSIC: "음악 기반 회상",
    Scenario.S4_ROUTINE: "루틴-회상 연계 알림",
    Scenario.S5_AFFECT: "정서 케어 대화",
    Scenario.S6_SENSITIVE: "민감 상황 대응",
    Scenario.CLOSING: "마무리",
}

#: 대화 아크(진입→심화→확장→마무리)를 갖는 시나리오.
#: 나머지(루틴·정서·민감·마무리)는 단발성/반응성이라 단계 개념이 없다.
REMINISCENCE_SCENARIOS: frozenset[Scenario] = frozenset(
    {Scenario.S1_PHOTO, Scenario.S2_ERA_PHOTO, Scenario.S3_MUSIC}
)
