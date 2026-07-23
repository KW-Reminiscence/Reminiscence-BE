"""
tests/test_anomaly.py

실행: PYTHONPATH=src python -m pytest tests/test_anomaly.py -v
"""

from reminiscence.routine.anomaly import build_alert_payload, compute_novelty_score


def _history(*values: float, key: str = "약_평균지연") -> list[dict[str, object]]:
    return [{"date": f"2026-07-{i + 1:02d}", key: v} for i, v in enumerate(values)]


def test_insufficient_history_returns_flag():
    result = compute_novelty_score(
        today_vector={"약_평균지연": 10},
        history=_history(0, 10),  # 2일치뿐 (기본 최소 3일 미달)
    )
    assert result.insufficient_data is True
    assert result.exceeded is False


def test_normal_day_does_not_exceed_threshold():
    result = compute_novelty_score(
        today_vector={"약_평균지연": 12},
        history=_history(10, 0, 20, 10, 0),  # 평균 8, 오늘 12는 평범한 범위
    )
    assert result.insufficient_data is False
    assert result.exceeded is False


def test_anomalous_day_exceeds_threshold():
    result = compute_novelty_score(
        today_vector={"약_평균지연": 120},  # 평소보다 압도적으로 큰 값
        history=_history(0, 0, 10, 0, 0),
    )
    assert result.insufficient_data is False
    assert result.exceeded is True
    assert result.score >= result.threshold


def test_metric_missing_from_history_is_ignored_not_crashed():
    """오늘 벡터에만 있고 과거 이력엔 없던 새 지표는 조용히 무시되어야 함 (에러 X)"""
    history = _history(0, 0, 0)
    result = compute_novelty_score(
        today_vector={"약_평균지연": 0, "새로생긴지표": 999},
        history=history,
    )
    assert "새로생긴지표" not in result.per_metric_z
    assert "약_평균지연" in result.per_metric_z


def test_zero_variance_history_still_flags_sudden_change():
    """항상 0이었던 지표가 오늘 갑자기 커지면, 표준편차 0이어도 이상으로 잡혀야 함"""
    result = compute_novelty_score(
        today_vector={"대화_무응답횟수": 50},
        history=_history(0, 0, 0, 0, key="대화_무응답횟수"),
    )
    assert result.exceeded is True


def test_build_alert_payload_includes_top_metric():
    result = compute_novelty_score(
        today_vector={"약_평균지연": 100, "식사_평균지연": 15},
        history=[
            {"date": "2026-07-01", "약_평균지연": 0, "식사_평균지연": 10},
            {"date": "2026-07-02", "약_평균지연": 0, "식사_평균지연": 20},
            {"date": "2026-07-03", "약_평균지연": 0, "식사_평균지연": 10},
        ],
    )
    payload = build_alert_payload(result, today="2026-07-04")

    assert payload["type"] == "anomaly"
    assert payload["top_metric"] == "약_평균지연"  # 압도적으로 더 크게 벗어난 지표
    assert payload["exceeded"] is True


def test_build_alert_payload_handles_insufficient_data_without_crashing():
    """데이터가 부족해서 per_metric_z가 빈 상태여도 build_alert_payload가 안 터져야 함"""
    result = compute_novelty_score(today_vector={"약_평균지연": 10}, history=_history(0))
    payload = build_alert_payload(result, today="2026-07-04")

    assert payload["top_metric"] is None
    assert payload["top_metric_z"] is None


def test_metric_absent_from_older_records_is_skipped_gracefully():
    """나중에 추가된 지표라 옛날 기록엔 그 키 자체가 없는 경우에도 에러 없이 넘어가야 함"""
    history = [
        {"date": "2026-07-01", "약_평균지연": 0},  # 아직 이 지표가 없던 시절 기록
        {"date": "2026-07-02", "약_평균지연": 0, "대화_무응답횟수": 1},
        {"date": "2026-07-03", "약_평균지연": 0, "대화_무응답횟수": 2},
    ]
    result = compute_novelty_score(
        today_vector={"약_평균지연": 0, "대화_무응답횟수": 5},
        history=history,
    )
    # "대화_무응답횟수"는 이력이 2건뿐(최소 3일 미달)이라 계산에서 빠져야 함
    assert "대화_무응답횟수" not in result.per_metric_z
    assert "약_평균지연" in result.per_metric_z
