"""
conversation_metrics.py
------------------------
대화 세션 지표를 기록하는 모듈.

다른 팀원(STT/대화 파이프라인 담당)이 매 대화 턴마다 log_turn()을 한 번 호출해주면 됩니다.
무응답 여부는 이 모듈이 추측하지 않고, 호출하는 쪽에서 직접 True/False로 알려줍니다
(파이프라인 쪽이 타임아웃 등 자기만의 무응답 판정 로직을 갖고 있을 수 있으므로).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ConversationTurn:
    timestamp: datetime
    utterance_text: str                      # STT로 변환된 발화 텍스트
    utterance_duration_sec: Optional[float]  # 발화 자체의 길이 (초)
    no_response: bool = False                # 무응답이면 True (호출 측에서 직접 판정)

    @property
    def utterance_length(self) -> int:
        """발화 길이 (글자 수, 공백 제외)"""
        if self.no_response:
            return 0
        return len(self.utterance_text.replace(" ", ""))

    @property
    def speaking_rate_per_min(self) -> Optional[float]:
        """말하기 속도 (분당 글자 수)"""
        if self.no_response or not self.utterance_duration_sec or self.utterance_duration_sec <= 0:
            return None
        return round(self.utterance_length / (self.utterance_duration_sec / 60), 1)


class ConversationLog:
    def __init__(self):
        self._turns: list[ConversationTurn] = []

    def log_turn(
        self,
        timestamp: datetime,
        utterance_text: str,
        utterance_duration_sec: Optional[float],
        no_response: bool = False,
    ) -> None:
        """
        대화 파이프라인 쪽에서 매 턴마다 호출.
        무응답이었으면 no_response=True로 호출 (이때 text/duration은 무시됨)
        예: log_turn(datetime.now(), "네 그때 설악산 갔었지", 1.8, no_response=False)
        """
        self._turns.append(ConversationTurn(timestamp, utterance_text, utterance_duration_sec, no_response))

    def daily_turns(self) -> list[ConversationTurn]:
        return list(self._turns)
