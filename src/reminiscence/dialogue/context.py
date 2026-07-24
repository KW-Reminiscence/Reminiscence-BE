"""세션 컨텍스트. 설계서 4-1의 [입력 컨텍스트 변수]에 대응한다."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from reminiscence.dialogue import config, flow, themes
from reminiscence.dialogue.messages import ChatMessage
from reminiscence.dialogue.scenarios import REMINISCENCE_SCENARIOS, Scenario

Role = Literal["user", "assistant"]
AffectState = Literal["긍정", "중립", "부정", "혼란"]

#: 진전 없는 짧은 응답. 정체 판정에 쓴다.
_FILLER: frozenset[str] = frozenset(("응", "네", "어", "몰라", "글쎄", "그래"))


@dataclass
class Turn:
    """대화 한 턴."""

    role: Role
    text: str
    scenario: str | None = None
    violations: list[str] = field(default_factory=list)
    at: datetime = field(default_factory=datetime.now)


@dataclass
class GuardianFlag:
    """보호자 알림 큐에 쌓이는 항목."""

    kind: Literal["SENSITIVE", "GUARDRAIL"]
    detail: str
    at: datetime = field(default_factory=datetime.now)


@dataclass
class SessionContext:
    """액자가 현재 알고 있는 모든 것.

    photo_meta / routine_type은 다른 팀원이 담당하는 모듈(디스플레이,
    루틴 모니터)이 세팅해 준다. 대화 엔진은 읽기만 한다.
    """

    device_name: str = "하늘이"

    # 프론트엔드·스케줄러가 채워주는 값
    photo_meta: str | None = None
    """예: "1998년 제주도, 본인과 딸, 여름"."""

    routine_type: str | None = None
    """예: "점심 복약"."""

    routine_pending: bool = False
    """알림이 아직 미이행 상태인가."""

    # 대화 중 추론되는 값
    affect_state: AffectState = "중립"
    last_sensitive_keyword: str | None = None

    history: list[Turn] = field(default_factory=list)
    guardian_flags: list[GuardianFlag] = field(default_factory=list)
    stall_count: int = 0

    # 회상 대화 아크 상태(flow.py 참고). 회상 시나리오(S1~S2)에서만 의미가 있다.
    phase: flow.Phase = flow.Phase.OPENING
    phase_turns: int = 0
    minimal_streak: int = 0
    active_scenario: str | None = None
    """지금 진행 중인 회상 시나리오. 바뀌면 대화 아크를 진입부터 다시 시작한다."""

    active_theme_key: str | None = None
    """지금 이야기 중인 생애 주제(themes.py). 어르신 발화에서 감지해 따라간다."""

    def add(self, turn: Turn) -> None:
        self.history.append(turn)

    def advance_flow(self, scenario: Scenario, utterance: str, *, distress: bool) -> None:
        """사용자 발화에 따라 대화 아크 단계를 갱신한다.

        회상 시나리오가 아니면 단계 개념이 없으므로 건드리지 않는다. 회상
        시나리오라도 방금 다른 주제(다른 사진·음악)로 바뀐 첫 턴이면 진입
        단계로 시작하고, 같은 주제를 이어가는 중이면 적극성에 따라 전이한다.
        """
        if scenario not in REMINISCENCE_SCENARIOS:
            self.active_scenario = scenario.value
            return

        if self.active_scenario != scenario.value:
            self.active_scenario = scenario.value
            self._reset_phase()
            self._follow_theme(utterance)
            return

        # 사람 중심(SolCos): 어르신이 먼저 꺼낸 화제를 따라간다.
        self._follow_theme(utterance)

        engagement = flow.classify_engagement(utterance, distress=distress)
        if engagement is flow.Engagement.MINIMAL:
            self.minimal_streak += 1
        else:
            self.minimal_streak = 0

        new_phase = flow.next_phase(
            self.phase,
            engagement,
            phase_turns=self.phase_turns,
            minimal_streak=self.minimal_streak,
        )
        if new_phase is self.phase:
            self.phase_turns += 1
        else:
            self.phase = new_phase
            self.phase_turns = 0

    def begin_initiation(self, scenario: Scenario) -> None:
        """액자가 먼저 말을 거는 턴의 단계를 맞춘다.

        회상 주제로 먼저 말을 걸면 진입 단계에서 시작한다.
        """
        self.active_scenario = scenario.value
        if scenario in REMINISCENCE_SCENARIOS:
            self._reset_phase()

    def _reset_phase(self) -> None:
        self.phase = flow.Phase.OPENING
        self.phase_turns = 0
        self.minimal_streak = 0

    def _follow_theme(self, utterance: str) -> None:
        detected = themes.detect_theme(utterance)
        if detected is not None:
            self.active_theme_key = detected.key

    def recent_messages(self) -> list[ChatMessage]:
        """최근 이력을 대화 메시지 형식으로 반환한다."""
        window = self.history[-config.HISTORY_TURNS :]
        return [ChatMessage(role=t.role, content=t.text) for t in window]

    def flag_guardian(self, kind: Literal["SENSITIVE", "GUARDRAIL"], detail: str) -> None:
        """보호자 알림 큐에 기록한다.

        설계서 S6 설계 포인트대로 즉시 알림이 아니라 누적 기록이다.
        실제 발송 여부는 보호자 연동 모듈이 이 큐를 읽어 결정한다.
        """
        self.guardian_flags.append(GuardianFlag(kind=kind, detail=detail))

    def note_stall(self, user_text: str) -> None:
        """진전 없는 발화가 반복되는지 센다."""
        stripped = user_text.strip()
        if len(stripped) <= 3 or stripped in _FILLER:
            self.stall_count += 1
        else:
            self.stall_count = 0

    @property
    def stalled(self) -> bool:
        return self.stall_count >= config.STALL_TURNS
