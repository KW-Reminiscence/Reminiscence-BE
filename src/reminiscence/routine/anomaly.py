"""
anomaly.py
----------
최근 며칠치 하루 지표 이력을 보고, 오늘이 평소와 얼마나 다른지 계산합니다.

계산 방식 (z-score 평균):
    1. 최근 N일치 각 지표의 평균/표준편차를 구함
    2. 오늘 값이 평균에서 몇 표준편차만큼 벗어났는지(z-score) 계산
    3. 모든 지표의 |z-score| 평균 = 종합 novelty score
    4. 임계값(threshold)을 넘으면 "패턴 이상"으로 판정

이 모듈은 "언제 계산을 돌릴지"는 전혀 몰라도 됩니다. 순수 계산 함수이므로
스케줄러(예: 매일 밤 23시)를 만드는 쪽에서 이 함수를 호출하기만 하면 됩니다.
"""

import statistics
from dataclasses import dataclass, field

from .daily_metrics import MetricVector

DEFAULT_THRESHOLD = 2.0

# 최소 이만큼의 이력이 있어야 평균/표준편차 계산을 신뢰할 수 있다고 봄
MIN_HISTORY_DAYS = 3

# 표준편차가 0(계속 똑같은 값이었음)일 때 나눗셈 오류를 막기 위한 값.
# 이 값을 아주 작게 둬야, "항상 0이었는데 오늘 갑자기 커진" 경우를 정확히 큰 이상치로 잡아낼 수 있음.
_ZERO_STDEV_EPSILON = 1e-6


@dataclass
class AnomalyResult:
    score: float
    threshold: float
    exceeded: bool
    insufficient_data: bool
    per_metric_z: dict[str, float] = field(default_factory=dict)


def compute_novelty_score(
    today_vector: MetricVector,
    history: list[dict[str, object]],
    threshold: float = DEFAULT_THRESHOLD,
    min_history_days: int = MIN_HISTORY_DAYS,
) -> AnomalyResult:
    """
    today_vector: daily_metrics.compute_daily_vector()가 반환한 오늘의 지표 dict
    history: daily_metrics.load_history()가 반환한 과거 기록 리스트
             (각 레코드는 "date" 필드 + 지표 필드들을 담은 dict)
    threshold: 이 값 이상이면 "패턴 이상"으로 판정
    min_history_days: 판단에 필요한 최소 이력 일수. 부족하면 insufficient_data=True 반환

    반환: AnomalyResult
        - insufficient_data=True면 아직 판단할 만큼 데이터가 안 쌓인 상태 (score/exceeded는 무시)
    """
    if len(history) < min_history_days:
        return AnomalyResult(score=0.0, threshold=threshold, exceeded=False, insufficient_data=True)

    metric_history: dict[str, list[float]] = {key: [] for key in today_vector}
    for record in history:
        for key in metric_history:
            value = record.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metric_history[key].append(float(value))

    per_metric_z: dict[str, float] = {}
    for key, values in metric_history.items():
        if len(values) < min_history_days:
            continue  # 이 지표는 이력이 부족해서 계산에서 제외 (스키마가 나중에 추가된 지표 등)

        mean = statistics.mean(values)
        stdev = statistics.pstdev(values)
        effective_stdev = stdev if stdev > _ZERO_STDEV_EPSILON else _ZERO_STDEV_EPSILON

        z = (float(today_vector[key]) - mean) / effective_stdev
        per_metric_z[key] = round(z, 2)

    if not per_metric_z:
        return AnomalyResult(score=0.0, threshold=threshold, exceeded=False, insufficient_data=True)

    score = round(statistics.mean(abs(z) for z in per_metric_z.values()), 2)
    return AnomalyResult(
        score=score,
        threshold=threshold,
        exceeded=score >= threshold,
        insufficient_data=False,
        per_metric_z=per_metric_z,
    )


def build_alert_payload(result: AnomalyResult, today: str) -> dict[str, object]:
    """
    exceeded=True일 때 보호자 알림 모듈로 넘길 표준 형식.
    daily_metrics의 deviation payload와 같은 스타일(type 필드로 구분)로 맞춤.
    """
    # 어떤 지표가 가장 크게 벗어났는지 함께 알려주면 알림 문구를 더 구체적으로 쓸 수 있음
    top_metric = max(result.per_metric_z.items(), key=lambda item: abs(item[1]), default=None)

    return {
        "type": "anomaly",
        "date": today,
        "novelty_score": result.score,
        "threshold": result.threshold,
        "exceeded": result.exceeded,
        "top_metric": top_metric[0] if top_metric else None,
        "top_metric_z": top_metric[1] if top_metric else None,
        "detail": result.per_metric_z,
    }
