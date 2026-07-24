"""회상 대화 엔진 설정값.

모든 값은 환경 변수로 덮어쓸 수 있다.
"""

import os
from typing import Final

#: 모델. 액자는 API 호출만 하므로 기기 성능과 무관하다.
#: 팀 게이트웨이가 제공하는 모델로 기본값을 둔다(/v1/models 로 확인 가능).
MODEL: Final[str] = os.getenv("DIALOGUE_MODEL", "gpt-5.6-luna")

#: 요청에 실을 User-Agent.
#:
#: 팀 게이트웨이(chat-api.leehyowon14.dev) 앞의 Cloudflare가 OpenAI SDK 기본
#: User-Agent를 403으로 막는다. 브라우저 형태의 값을 쓰면 통과한다. 게이트웨이
#: 쪽에서 SDK를 허용하도록 고치면 이 우회는 필요 없다.
USER_AGENT: Final[str] = os.getenv(
    "DIALOGUE_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)

#: 회상 대화 응답은 1~2문장이므로 크게 잡을 이유가 없다.
MAX_TOKENS: Final[int] = int(os.getenv("DIALOGUE_MAX_TOKENS", "300"))

#: 표현의 다양성. 0에 가까우면 딱딱하고, 높으면 산만해진다.
#: 따뜻하되 원칙을 벗어나지 않는 선에서 중간값을 쓴다.
TEMPERATURE: Final[float] = float(os.getenv("DIALOGUE_TEMPERATURE", "0.7"))

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
