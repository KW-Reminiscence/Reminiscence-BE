"""시나리오 라우팅 우선순위를 검증한다. API 키가 필요 없다."""

from reminiscence.dialogue import SessionContext
from reminiscence.dialogue.router import route
from reminiscence.dialogue.scenarios import Scenario


def test_route_picks_photo_scenario_when_a_photo_is_shown() -> None:
    ctx = SessionContext(photo_meta="1998년 제주도, 본인과 딸")

    scenario, _ = route("이거 뭐야", ctx)

    assert scenario is Scenario.S1_PHOTO


def test_route_distinguishes_an_era_photo() -> None:
    ctx = SessionContext(photo_meta="1970년대 시대자료사진, 남대문 시장")

    scenario, _ = route("이거 뭐야", ctx)

    assert scenario is Scenario.S2_ERA_PHOTO


def test_route_prefers_music_over_photo() -> None:
    ctx = SessionContext(photo_meta="가족사진", music_meta="동백아가씨 (1964)")

    scenario, _ = route("좋네", ctx)

    assert scenario is Scenario.S3_MUSIC


def test_route_prefers_a_pending_routine_over_reminiscence() -> None:
    ctx = SessionContext(
        photo_meta="가족사진", routine_type="점심 복약", routine_pending=True
    )

    scenario, _ = route("응", ctx)

    assert scenario is Scenario.S4_ROUTINE


def test_route_puts_sensitive_topics_ahead_of_every_trigger() -> None:
    # 루틴 알림이 걸려 있어도 고인 언급이 나오면 S6가 이겨야 한다
    ctx = SessionContext(
        photo_meta="가족사진", routine_type="점심 복약", routine_pending=True
    )

    scenario, signal = route("우리 남편은 언제 와?", ctx)

    assert scenario is Scenario.S6_SENSITIVE
    assert signal.keyword == "남편"
    assert ctx.affect_state == "부정"


def test_route_handles_distress_as_affect_care() -> None:
    ctx = SessionContext(photo_meta="가족사진")

    scenario, _ = route("무서워", ctx)

    assert scenario is Scenario.S5_AFFECT


def test_route_switches_to_closing_when_the_conversation_stalls() -> None:
    ctx = SessionContext(photo_meta="가족사진")
    for _ in range(3):
        ctx.note_stall("응")

    scenario, _ = route("응", ctx)

    assert scenario is Scenario.CLOSING


def test_note_stall_resets_on_a_meaningful_utterance() -> None:
    ctx = SessionContext()

    ctx.note_stall("응")
    ctx.note_stall("네")
    ctx.note_stall("그때 딸이랑 바다 갔었지")

    assert ctx.stall_count == 0
    assert not ctx.stalled
