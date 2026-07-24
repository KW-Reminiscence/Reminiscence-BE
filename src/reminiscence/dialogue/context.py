"""세션 컨텍스트. 설계서 4-1의 [입력 컨텍스트 변수]에 대응한다."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from reminiscence.dialogue import config
from reminiscence.dialogue.messages import ChatMessage

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

    photo_meta / music_meta / routine_type은 다른 팀원이 담당하는 모듈
    (디스플레이, 플레이어, 루틴 모니터)이 세팅해 준다. 대화 엔진은 읽기만 한다.
    """

    device_name: str = "하늘이"

    # 하드웨어·스케줄러가 채워주는 값
    photo_meta: str | None = None
    """예: "1998년 제주도, 본인과 딸, 여름"."""

    music_meta: str | None = None
    """예: "동백아가씨 (1964)"."""

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

    def add(self, turn: Turn) -> None:
        self.history.append(turn)

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
