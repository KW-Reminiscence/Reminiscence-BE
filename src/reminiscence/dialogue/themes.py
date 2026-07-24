"""회상 대화의 생애 주제(life themes)와 감각 단서.

근거
----
- 회상 절정(reminiscence bump): 치매에서도 아동기~초기 성인기(약 6~30세)
  기억은 상대적으로 잘 보존된다(Ribot의 법칙). 자유 대화에서도 이 시기
  기억이 가장 잘 인출된다. 따라서 대화의 축을 이 시기의 주제에 둔다.
- 문화적 생애 각본(cultural life scripts): 학교 입학, 첫 직장, 결혼, 육아
  같은 "누구나 겪는 삶의 순서"는 치매 중기까지 보존되어 기억 인출의 길잡이가
  된다. 주제 순서를 이 각본에 맞춘다.
- 감각 단서: 회상요법에서 냄새·맛·소리 단서는 사실 질문("언제였어요?")보다
  기억을 잘 깨운다. 각 주제에 그 시절의 감각 단서를 붙여 심화 단계에서 쓴다.
- TimeSlips(창작 이야기): 기억이 나지 않을 때 "기억해내기"에서 "상상하기"로
  전환하면 실패감 없이 대화가 이어진다. 정답 없는 열린 이야기를 유도한다.

주제는 데이터로 두었다. 사용성 조사(복지관·요양원 인터뷰)에서 세대·지역에
맞는 주제가 확인되면 이 파일만 고치면 된다.
"""

from dataclasses import dataclass, field
from typing import Final


@dataclass(frozen=True)
class LifeTheme:
    """회상 절정 시기의 생애 주제 하나."""

    key: str
    """주제 식별자."""

    label: str
    """짧은 이름(로그·지표용)."""

    era: str
    """생애 각본에서의 위치. 프롬프트에 그대로 들어간다."""

    entry_cues: tuple[str, ...]
    """진입용 실마리. 부담 없는 공동 경험."""

    sensory_cues: tuple[str, ...]
    """심화용 감각 단서. 냄새·맛·소리·촉감."""

    people_cues: tuple[str, ...]
    """심화용 사람 단서. 그 시절 곁에 있던 사람들."""

    keywords: tuple[str, ...] = field(default=())
    """발화에서 이 주제를 감지하는 단서 낱말."""


#: 회상 절정 시기(약 6~30세)를 문화적 생애 각본 순서로 늘어놓은 주제들.
#: 1940~60년대에 유년기를 보낸 세대 기준이며, 사용성 조사 후 조정한다.
LIFE_THEMES: Final[tuple[LifeTheme, ...]] = (
    LifeTheme(
        key="childhood_home",
        label="어린 시절 동네",
        era="어린 시절(예닐곱 살 무렵), 자란 동네와 집",
        entry_cues=("골목에서 하던 놀이", "동네 우물가나 개울", "명절 준비로 북적이던 집"),
        sensory_cues=(
            "아궁이 불 냄새", "가마솥 밥 냄새", "여름밤 마당의 모깃불", "겨울 아랫목의 온기",
        ),
        people_cues=("어머니", "형제자매", "동네 소꿉친구"),
        keywords=("어릴", "동네", "고향", "골목", "집", "놀이", "엄마", "어머니"),
    ),
    LifeTheme(
        key="school_days",
        label="학창 시절",
        era="학교 다니던 시절(열 살 안팎)",
        entry_cues=("등굣길 풍경", "운동회와 소풍", "도시락 시간"),
        sensory_cues=("새 교과서 냄새", "풍금 소리", "운동회 날 먼지 냄새", "도시락 반찬 냄새"),
        people_cues=("짝꿍", "담임 선생님", "같이 걷던 등굣길 친구"),
        keywords=("학교", "선생", "친구", "공부", "운동회", "소풍", "도시락"),
    ),
    LifeTheme(
        key="youth_work",
        label="젊은 날의 일",
        era="스무 살 무렵, 처음 일을 시작하던 때",
        entry_cues=("첫 일터의 첫날", "첫 월급으로 한 일", "장에 다녀오던 길"),
        sensory_cues=(
            "시장 골목의 부침개 냄새", "새벽일 나가던 길의 공기", "일 끝나고 마시던 막걸리",
        ),
        people_cues=("일터 동료", "장에서 만나던 단골", "그 시절 친구들"),
        keywords=("일", "직장", "월급", "시장", "장사", "농사", "공장"),
    ),
    LifeTheme(
        key="marriage_family",
        label="결혼과 새 식구",
        era="결혼하고 새 식구를 이루던 무렵",
        entry_cues=("혼례 날 풍경", "신혼 살림 장만", "처음 차린 밥상"),
        sensory_cues=("잔칫날 전 부치는 냄새", "새 이불의 감촉", "국수 삶는 김"),
        people_cues=("배우자", "시댁·처가 식구", "잔치에 온 손님들"),
        keywords=("결혼", "혼례", "잔치", "신혼", "남편", "아내", "시집", "장가"),
    ),
    LifeTheme(
        key="raising_children",
        label="아이 키우던 시절",
        era="아이들을 낳아 기르던 삼십 대 무렵",
        entry_cues=(
            "첫 아이 태어난 날", "아이들 소풍 도시락 싸던 아침", "명절에 온 식구가 모이던 날",
        ),
        sensory_cues=("갓난아기 냄새", "아이들 뛰노는 소리", "저녁 짓는 냄새에 모여들던 아이들"),
        people_cues=("아들딸", "아이 친구 엄마들", "온 가족"),
        keywords=("아이", "애들", "아들", "딸", "키우", "학부모", "도시락"),
    ),
)

_THEME_BY_KEY: Final[dict[str, LifeTheme]] = {t.key: t for t in LIFE_THEMES}


def get_theme(key: str) -> LifeTheme | None:
    return _THEME_BY_KEY.get(key)


def detect_theme(utterance: str) -> LifeTheme | None:
    """발화에서 생애 주제를 감지한다.

    SolCos 모델의 사람 중심 원칙: 진행자가 주제를 정해 끌고 가는 것이 아니라,
    어르신이 먼저 꺼낸 화제를 따라간다. 여기서 감지된 주제가 이후 심화·확장
    단계의 단서 선택을 이끈다.
    """
    best: LifeTheme | None = None
    best_hits = 0
    for theme in LIFE_THEMES:
        hits = sum(1 for kw in theme.keywords if kw in utterance)
        if hits > best_hits:
            best, best_hits = theme, hits
    return best


def next_theme(current_key: str | None) -> LifeTheme:
    """확장 단계에서 넘어갈 다음 주제를 생애 각본 순서로 고른다.

    문화적 생애 각본이 기억 인출의 길잡이가 된다는 근거에 따라, 무작위가
    아니라 삶의 순서(어린 시절 → 학창 → 일 → 결혼 → 육아)를 따라 옮겨간다.
    """
    if current_key is None:
        return LIFE_THEMES[0]
    keys = [t.key for t in LIFE_THEMES]
    try:
        idx = keys.index(current_key)
    except ValueError:
        return LIFE_THEMES[0]
    return LIFE_THEMES[(idx + 1) % len(LIFE_THEMES)]
