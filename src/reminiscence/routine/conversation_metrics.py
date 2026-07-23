"""
conversation_metrics.py
------------------------
대화 세션 지표를 기록하는 모듈.

이번 리뷰 반영 사항:
    daily_turns()가 이제 target_date를 받아서 그 날짜에 해당하는 턴만 반환.
    (프로세스가 자정을 넘겨 계속 실행돼도 어제 대화가 오늘 지표에 안 섞이도록)
"""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class ConversationTurn:
    timestamp: datetime
    utterance_text: str
    utterance_duration_sec: float | None
    no_response: bool = False

    @property
    def utterance_length(self) -> int:
        if self.no_response:
            return 0
        return len(self.utterance_text.replace(" ", ""))

    @property
    def speaking_rate_per_min(self) -> float | None:
        if self.no_response or not self.utterance_duration_sec or self.utterance_duration_sec <= 0:
            return None
        return round(self.utterance_length / (self.utterance_duration_sec / 60), 1)


class ConversationLog:
    def __init__(self) -> None:
        self._turns: list[ConversationTurn] = []

    def log_turn(
        self,
        timestamp: datetime,
        utterance_text: str,
        utterance_duration_sec: float | None,
        no_response: bool = False,
    ) -> None:
        self._turns.append(
            ConversationTurn(timestamp, utterance_text, utterance_duration_sec, no_response)
        )

    def daily_turns(self, target_date: date) -> list[ConversationTurn]:
        """target_date에 해당하는 턴만 필터링해서 반환"""
        return [t for t in self._turns if t.timestamp.date() == target_date]
