"""생애 주제(life themes) 감지·순환 검증. API 키가 필요 없다."""

from reminiscence.dialogue import SessionContext
from reminiscence.dialogue.flow import Phase
from reminiscence.dialogue.scenarios import Scenario
from reminiscence.dialogue.themes import LIFE_THEMES, detect_theme, next_theme


def test_life_themes_follow_the_cultural_life_script_order() -> None:
    # 회상 절정 시기의 생애 각본 순서: 어린 시절 → 학창 → 일 → 결혼 → 육아
    keys = [t.key for t in LIFE_THEMES]
    assert keys == [
        "childhood_home",
        "school_days",
        "youth_work",
        "marriage_family",
        "raising_children",
    ]


def test_every_theme_carries_sensory_and_people_cues() -> None:
    # 감각 단서 우선 원칙: 심화 단계가 쓸 재료가 주제마다 있어야 한다
    for theme in LIFE_THEMES:
        assert theme.sensory_cues, theme.key
        assert theme.people_cues, theme.key
        assert theme.entry_cues, theme.key


def test_detect_theme_follows_what_the_elder_brings_up() -> None:
    assert detect_theme("우리 학교 운동회 때 말이야").key == "school_days"  # type: ignore[union-attr]
    assert detect_theme("첫 월급 타서 시장에 갔지").key == "youth_work"  # type: ignore[union-attr]
    assert detect_theme("애들 도시락 싸던 게 생각나").key is not None  # type: ignore[union-attr]


def test_detect_theme_returns_none_without_cues() -> None:
    assert detect_theme("응 그래") is None


def test_next_theme_moves_along_the_life_script() -> None:
    assert next_theme("childhood_home").key == "school_days"
    assert next_theme("school_days").key == "youth_work"
    # 끝에서는 처음으로 돌아온다
    assert next_theme("raising_children").key == "childhood_home"
    # 모르는 값이면 처음부터
    assert next_theme(None).key == "childhood_home"


def test_context_follows_the_theme_the_elder_mentions() -> None:
    ctx = SessionContext(photo_meta="가족사진")
    ctx.advance_flow(Scenario.S1_PHOTO, "이거 뭐야", distress=False)
    assert ctx.active_theme_key is None  # 아직 단서 없음

    ctx.advance_flow(Scenario.S1_PHOTO, "학교 다닐 때 소풍 가서 찍었나", distress=False)
    assert ctx.active_theme_key == "school_days"


def test_theme_cues_appear_in_the_deepening_directive() -> None:
    from reminiscence.dialogue import prompts

    ctx = SessionContext(photo_meta="가족사진")
    ctx.active_theme_key = "school_days"
    ctx.phase = Phase.DEEPENING

    directive = prompts.build_turn_directive(Scenario.S1_PHOTO, ctx)

    assert "학창 시절" in directive
    assert "풍금" in directive or "교과서" in directive  # 감각 단서가 실려 있다


def test_broadening_directive_proposes_the_next_life_theme() -> None:
    from reminiscence.dialogue import prompts

    ctx = SessionContext(photo_meta="가족사진")
    ctx.active_theme_key = "school_days"
    ctx.phase = Phase.BROADENING

    directive = prompts.build_turn_directive(Scenario.S1_PHOTO, ctx)

    assert "[다음 주제]" in directive
    assert "젊은 날의 일" in directive  # 생애 각본에서 학창 다음은 일
