"""대화 아크(진입→심화→확장→마무리) 상태 기계 검증. API 키가 필요 없다."""

from reminiscence.dialogue import SessionContext
from reminiscence.dialogue.flow import Engagement, Phase, classify_engagement, next_phase
from reminiscence.dialogue.scenarios import Scenario

# --- 적극성 판정 --------------------------------------------------------


def test_substantive_reply_is_engaged() -> None:
    assert classify_engagement("그때 딸이랑 바다 갔었지", distress=False) is Engagement.ENGAGED


def test_short_filler_is_minimal() -> None:
    assert classify_engagement("응", distress=False) is Engagement.MINIMAL
    assert classify_engagement("글쎄", distress=False) is Engagement.MINIMAL


def test_distress_is_confused_regardless_of_content() -> None:
    assert classify_engagement("여기가 어디야 무서워", distress=True) is Engagement.CONFUSED


# --- 단계 전이 (순수 함수) ---------------------------------------------


def test_engaged_opening_moves_to_deepening() -> None:
    result = next_phase(Phase.OPENING, Engagement.ENGAGED, phase_turns=0, minimal_streak=0)
    assert result is Phase.DEEPENING


def test_deepening_broadens_only_after_a_couple_turns() -> None:
    stay = next_phase(Phase.DEEPENING, Engagement.ENGAGED, phase_turns=1, minimal_streak=0)
    assert stay is Phase.DEEPENING

    go = next_phase(Phase.DEEPENING, Engagement.ENGAGED, phase_turns=2, minimal_streak=0)
    assert go is Phase.BROADENING


def test_repeated_minimal_replies_wind_down_to_wrapping() -> None:
    stay = next_phase(Phase.DEEPENING, Engagement.MINIMAL, phase_turns=1, minimal_streak=1)
    assert stay is Phase.DEEPENING

    wrap = next_phase(Phase.DEEPENING, Engagement.MINIMAL, phase_turns=1, minimal_streak=2)
    assert wrap is Phase.WRAPPING


def test_confusion_jumps_straight_to_wrapping() -> None:
    result = next_phase(Phase.DEEPENING, Engagement.CONFUSED, phase_turns=1, minimal_streak=0)
    assert result is Phase.WRAPPING


def test_re_engaging_from_wrapping_recovers_to_deepening() -> None:
    result = next_phase(Phase.WRAPPING, Engagement.ENGAGED, phase_turns=3, minimal_streak=0)
    assert result is Phase.DEEPENING


# --- 컨텍스트 연동 ------------------------------------------------------


def test_a_new_reminiscence_topic_starts_at_opening() -> None:
    ctx = SessionContext(photo_meta="1998년 제주도")
    ctx.advance_flow(Scenario.S1_PHOTO, "이거 뭐야", distress=False)

    assert ctx.phase is Phase.OPENING
    assert ctx.active_scenario == Scenario.S1_PHOTO.value


def test_engagement_deepens_the_conversation_over_turns() -> None:
    ctx = SessionContext(photo_meta="1998년 제주도")

    ctx.advance_flow(Scenario.S1_PHOTO, "이거 뭐야", distress=False)  # 진입
    assert ctx.phase is Phase.OPENING

    ctx.advance_flow(Scenario.S1_PHOTO, "딸이랑 제주도 갔던 사진이야", distress=False)
    assert ctx.phase is Phase.DEEPENING

    # 심화 단계에 몇 턴 머물며 이야기를 나눈 뒤에야 확장으로 넘어간다
    ctx.advance_flow(Scenario.S1_PHOTO, "그때 바다가 참 맑았어", distress=False)
    ctx.advance_flow(Scenario.S1_PHOTO, "회 먹고 물놀이도 했지", distress=False)
    assert ctx.phase is Phase.DEEPENING

    ctx.advance_flow(Scenario.S1_PHOTO, "저녁엔 노을이 참 붉었어", distress=False)
    assert ctx.phase is Phase.BROADENING


def test_switching_topic_resets_the_arc() -> None:
    ctx = SessionContext(photo_meta="1998년 제주도")
    ctx.advance_flow(Scenario.S1_PHOTO, "이거 뭐야", distress=False)
    ctx.advance_flow(Scenario.S1_PHOTO, "딸이랑 갔던 바다야", distress=False)
    assert ctx.phase is Phase.DEEPENING

    # 음악으로 주제가 바뀌면 진입부터 다시 시작한다
    ctx.music_meta = "동백아가씨 (1964)"
    ctx.advance_flow(Scenario.S3_MUSIC, "이 노래 좋네", distress=False)
    assert ctx.phase is Phase.OPENING
    assert ctx.active_scenario == Scenario.S3_MUSIC.value


def test_non_reminiscence_scenarios_do_not_touch_the_phase() -> None:
    ctx = SessionContext(routine_type="점심 복약", routine_pending=True)
    ctx.phase = Phase.DEEPENING

    ctx.advance_flow(Scenario.S4_ROUTINE, "응", distress=False)

    assert ctx.phase is Phase.DEEPENING  # 그대로 둔다


def test_initiation_opens_a_reminiscence_arc() -> None:
    ctx = SessionContext(photo_meta="1998년 제주도")
    ctx.phase = Phase.BROADENING

    ctx.begin_initiation(Scenario.S1_PHOTO)

    assert ctx.phase is Phase.OPENING
