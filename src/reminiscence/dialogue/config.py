"""회상 대화 엔진 설정값.

모든 값은 환경 변수로 덮어쓸 수 있다. 잘못된 값은 기동 시점에 걸러진다.
"""

import os
from typing import Final, Literal, cast

EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]

_VALID_EFFORT: Final[frozenset[str]] = frozenset(
    ("low", "medium", "high", "xhigh", "max")
)


def _read_effort() -> EffortLevel:
    raw = os.getenv("DIALOGUE_EFFORT", "low")
    if raw not in _VALID_EFFORT:
        valid = ", ".join(sorted(_VALID_EFFORT))
        raise ValueError(f"DIALOGUE_EFFORT must be one of: {valid} (got {raw!r})")
    return cast(EffortLevel, raw)


#: 모델. 라즈베리파이는 API 호출만 하므로 기기 성능과 무관하다.
MODEL: Final[str] = os.getenv("DIALOGUE_MODEL", "claude-opus-4-8")

#: Fast mode. Opus 4.8에서 출력 속도가 최대 2.5배 빨라진다(프리미엄 과금).
#: 음성 대화는 첫 문장이 나오는 속도가 체감 품질을 좌우하므로 켜볼 만하다.
FAST_MODE: Final[bool] = os.getenv("DIALOGUE_FAST_MODE", "0") == "1"
FAST_MODE_BETA: Final[str] = "fast-mode-2026-02-01"

#: 회상 대화 응답은 1~2문장이므로 크게 잡을 이유가 없다.
MAX_TOKENS: Final[int] = int(os.getenv("DIALOGUE_MAX_TOKENS", "300"))

#: 짧고 정서적인 응답에는 low가 가장 빠르고 충분하다.
#: 응답이 성의 없어지면 medium으로 올려 A/B 할 것.
EFFORT: Final[EffortLevel] = _read_effort()

#: 대화 이력 유지 턴 수. 이력이 길수록 지연이 늘어나므로 짧게 자른다.
HISTORY_TURNS: Final[int] = int(os.getenv("DIALOGUE_HISTORY_TURNS", "8"))

#: 요청 제한 시간(초). SDK 기본값 10분은 음성 대화에 쓸 수 없다.
#: 응답이 1~2문장이므로 이보다 오래 걸리면 이미 실패로 보는 편이 낫다.
REQUEST_TIMEOUT_SECONDS: Final[float] = float(
    os.getenv("DIALOGUE_TIMEOUT_SECONDS", "15")
)

#: 재시도 횟수. 어르신을 기다리게 하느니 대체 문구를 빨리 내보낸다.
MAX_RETRIES: Final[int] = int(os.getenv("DIALOGUE_MAX_RETRIES", "1"))

#: 가드레일 임계값. 설계서 1장의 설계 원칙에서 가져왔다.
MAX_SENTENCES: Final[int] = 2
MAX_QUESTIONS: Final[int] = 1
MAX_CHARS: Final[int] = 90

#: 이 턴 수 이상 진전이 없으면 마무리 문구로 전환한다(설계서 원칙 6).
STALL_TURNS: Final[int] = 3
