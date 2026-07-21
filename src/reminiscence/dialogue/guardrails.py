"""설계서 1장의 설계 원칙을 코드로 강제하는 계층.

두 지점에서 동작한다.
  - 입력 가드레일: 사용자 발화에서 민감 소재를 탐지 (S6 라우팅 근거)
  - 출력 가드레일: LLM 응답이 원칙을 어겼는지 검사하고 보수(repair)

출력 가드레일은 재생성 대신 보수를 택했다. 음성 대화에서 재생성은 지연을
두 배로 만들고, 어르신은 그 침묵을 고장으로 인식하기 때문이다.
"""

import re
from dataclasses import dataclass, field
from typing import Final

from reminiscence.dialogue import config

# ---------------------------------------------------------------------------
# 입력 가드레일 - 민감 소재 탐지
# ---------------------------------------------------------------------------

#: 고인·상실 관련. 어르신이 직접 언급했을 때 S6로 라우팅한다.
_BEREAVEMENT: Final[tuple[str, ...]] = (
    "돌아가", "죽었", "죽은", "죽어", "장례", "무덤", "산소", "제사", "하늘나라",
)

#: 호칭. "우리 남편은 언제 와?"처럼 고인을 산 사람으로 찾는 발화를 잡는 데 쓴다.
_KIN: Final[tuple[str, ...]] = (
    "남편", "아내", "엄마", "어머니", "아버지", "아빠",
    "형", "누나", "언니", "오빠", "동생",
)

_ABSENCE: Final[tuple[str, ...]] = (
    "언제 와", "언제 오", "어디 갔", "어디 있", "안 와", "안 오", "왜 안",
)

#: 혼란·불안. S5 경계 신호.
_DISTRESS: Final[tuple[str, ...]] = (
    "무서", "겁나", "여기가 어디", "집에 갈래", "집에 가고",
    "누구세요", "모르겠어", "모르겠는데", "답답",
)


@dataclass
class InputSignal:
    """사용자 발화에서 읽어낸 신호."""

    sensitive: bool = False
    keyword: str | None = None
    distress: bool = False


def scan_input(utterance: str) -> InputSignal:
    """사용자 발화에서 민감 신호를 탐지한다."""
    text = utterance.strip()

    if any(word in text for word in _BEREAVEMENT):
        return InputSignal(sensitive=True, keyword=_nearest_kin(text) or "그분")

    # 호칭 + 부재 표현 = 고인을 찾는 발화일 가능성
    kin = _nearest_kin(text)
    if kin is not None and any(a in text for a in _ABSENCE):
        return InputSignal(sensitive=True, keyword=kin)

    if any(d in text for d in _DISTRESS):
        return InputSignal(distress=True)

    return InputSignal()


def _nearest_kin(text: str) -> str | None:
    for kin in _KIN:
        if kin in text:
            return kin
    return None


# ---------------------------------------------------------------------------
# 출력 가드레일 - 응답 검증 및 보수
# ---------------------------------------------------------------------------

#: 사실 정정·사망 통보 계열. 설계서에서 명시적으로 금지한 표현.
_FORBIDDEN: Final[tuple[str, ...]] = (
    "돌아가셨", "돌아가신", "사망", "세상을 떠", "고인",
    "그건 아니", "틀리셨", "잘못 아시", "사실은",
    "기억 안 나시", "치매",
)

#: 시험형 질문. 설계서 원칙 6(시험 보는 느낌 회피).
_QUIZ_PATTERNS: Final[tuple[str, ...]] = (
    r"누구(예요|세요|입니까|야)\?",
    r"언제(예요|였어요|입니까)\?",
    r"어디(예요|였어요|입니까)\?",
    r"기억\s*(나|하)세요\?",
    r"맞[히춰]\s*보",
)

#: 금지 표현에 걸렸을 때 내보낼 안전한 대체 문구.
_SAFE_FALLBACK: Final[str] = "지금 그 생각이 많이 나시나 봐요. 어떤 모습이 제일 먼저 떠오르세요?"

_SENT_SPLIT: Final[re.Pattern[str]] = re.compile(
    r"(?<=[.!?。])\s+|(?<=[다요])\s+(?=[가-힣])"
)


@dataclass
class Verdict:
    """출력 가드레일 판정 결과."""

    text: str
    violations: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.violations


def has_forbidden(text: str) -> bool:
    """금지 표현 포함 여부만 즉시 검사한다.

    스트리밍 중 문장 하나를 TTS로 내보내기 전에 호출한다. 한 번 발화된 말은
    되돌릴 수 없으므로 이 검사만 스트림 앞에 둔다.
    """
    return any(word in text for word in _FORBIDDEN)


def check_output(reply: str) -> Verdict:
    """응답을 검사하고, 위반이 있으면 보수한 텍스트를 돌려준다.

    반환된 violations는 설계서 5장 사용성 테스트의 '가드레일 위반 횟수'
    지표로 그대로 집계할 수 있다.
    """
    text = reply.strip().strip('"').strip("'")
    violations: list[str] = []

    # 1. 금지 표현 - 보수 불가. 안전한 대체 문구로 교체한다.
    for word in _FORBIDDEN:
        if word in text:
            violations.append(f"금지표현:{word}")
            return Verdict(text=_SAFE_FALLBACK, violations=violations)

    # 2. 시험형 질문 - 진술형으로 바꿀 수 없으므로 질문절을 잘라낸다.
    for pattern in _QUIZ_PATTERNS:
        if re.search(pattern, text):
            violations.append(f"시험형질문:{pattern}")
            text = re.sub(pattern, "", text).strip()
            break

    # 3. 문장 수 초과 - 앞의 두 문장만 남긴다.
    sentences = [s for s in _SENT_SPLIT.split(text) if s.strip()]
    if len(sentences) > config.MAX_SENTENCES:
        violations.append(f"문장수:{len(sentences)}")
        text = " ".join(sentences[: config.MAX_SENTENCES])

    # 4. 질문 개수 초과 - 마지막 질문 하나만 남긴다.
    if text.count("?") > config.MAX_QUESTIONS:
        violations.append(f"질문수:{text.count('?')}")
        head, _, tail = text.rpartition("?")
        kept = head.split("?")[-1].strip()
        if kept:
            text = f"{kept}?{tail}".strip()

    # 5. 길이 초과 - 지표로만 기록하고 자르지 않는다.
    #    문장 중간을 자르면 TTS가 어색해져 오히려 혼란을 준다.
    if len(text) > config.MAX_CHARS:
        violations.append(f"길이:{len(text)}")

    return Verdict(text=text.strip(), violations=violations)
