"""Fixed-baseline anomaly policy from the confirmed product specification."""

from __future__ import annotations

from statistics import median

from sklearn.ensemble import IsolationForest  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from reminiscence.anomaly.models import (
    AnomalyMode,
    AnomalyObservations,
    AnomalyStatus,
    BaselineState,
    ConversationQualityObservation,
    DomainEvaluation,
    PersonalEvaluation,
    RoutineObservation,
)

ROUTINE_BASELINE_DAYS = 28
CONVERSATION_BASELINE_SESSIONS = 20
PARTICIPATION_BASELINE_DAYS = 28
MODEL_RANDOM_STATE = 42
MODEL_ESTIMATORS = 100
MODEL_CONTAMINATION = 0.1
ROUTINE_FEATURE_NAMES = (
    "meal_not_answered_ratio",
    "medication_not_answered_ratio",
    "meal_average_confirmation_delay_seconds",
    "medication_average_confirmation_delay_seconds",
    "completion_ratio",
    "maximum_consecutive_not_answered",
)
CONVERSATION_FEATURE_NAMES = (
    "user_turn_count",
    "total_utterance_chars",
    "average_utterance_chars",
    "average_turn_duration_seconds",
    "no_response_count",
)


class PersonalAnomalyDetector:
    """Evaluate immutable observations against fixed JSON baselines."""

    def evaluate(
        self,
        observations: AnomalyObservations,
        baseline: BaselineState,
        evaluated_at: object,
    ) -> PersonalEvaluation:
        """Apply independent routine and conversation three-signal policies."""

        from datetime import datetime

        if not isinstance(evaluated_at, datetime):
            raise TypeError("evaluated_at must be a datetime")
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        routine = self.evaluate_routines(observations.routine_days, baseline)
        conversation = self.evaluate_conversations(observations, baseline)
        status = (
            AnomalyStatus.ANOMALOUS
            if AnomalyStatus.ANOMALOUS in {routine.status, conversation.status}
            else AnomalyStatus.NORMAL
        )
        return PersonalEvaluation(
            evaluated_at=evaluated_at,
            status=status,
            routine=routine,
            conversation=conversation,
        )

    def evaluate_routines(
        self,
        observations: tuple[RoutineObservation, ...],
        baseline: BaselineState,
    ) -> DomainEvaluation:
        """Evaluate cold-start misses or post-baseline daily IF candidates."""

        ordered = tuple(sorted(observations, key=lambda item: item.target_date))
        latest = ordered[-1] if ordered else None
        rule_signal = bool(latest and latest.values[5] >= 3)
        reasons: list[str] = []
        if rule_signal:
            reasons.append("동일 루틴에서 3회 연속 미응답")

        if not baseline.routine_vectors:
            persistence_signal = rule_signal
            status = self._consensus(rule_signal, False, persistence_signal)
            return DomainEvaluation(
                status=status,
                mode=(
                    AnomalyMode.COLD_START
                    if ordered
                    else AnomalyMode.INSUFFICIENT_DATA
                ),
                sample_count=len(ordered),
                score=None,
                reasons=tuple(reasons),
                feature_names=ROUTINE_FEATURE_NAMES,
                rule_based_signal=rule_signal,
                persistence_signal=persistence_signal,
                observation_key=latest.key if latest else None,
            )

        candidates = ordered[ROUTINE_BASELINE_DAYS:]
        model_results = tuple(
            self._is_anomalous(baseline.routine_vectors, item.values)
            for item in candidates
        )
        model_signal, score = model_results[-1] if model_results else (False, None)
        persistence_signal = (
            len(model_results) >= 2
            and model_results[-1][0]
            and model_results[-2][0]
        )
        if model_signal and latest is not None:
            reasons.extend(self._routine_reasons(baseline.routine_vectors, latest.values))
        if persistence_signal:
            reasons.append("루틴 모델 이탈이 완성된 2개 관측일 연속 발생")
        return DomainEvaluation(
            status=self._consensus(rule_signal, model_signal, persistence_signal),
            mode=AnomalyMode.ISOLATION_FOREST,
            sample_count=len(ordered),
            score=score,
            reasons=tuple(dict.fromkeys(reasons)),
            feature_names=ROUTINE_FEATURE_NAMES,
            rule_based_signal=rule_signal,
            isolation_forest_signal=model_signal,
            persistence_signal=persistence_signal,
            observation_key=latest.key if latest else None,
        )

    def evaluate_conversations(
        self,
        observations: AnomalyObservations,
        baseline: BaselineState,
    ) -> DomainEvaluation:
        """Combine participation rule, session IF and their persistence."""

        quality = tuple(
            sorted(observations.conversation_quality, key=lambda item: item.completed_at)
        )
        participation = tuple(
            sorted(observations.participation_days, key=lambda item: item.target_date)
        )
        model_results: tuple[tuple[bool, float], ...] = ()
        if baseline.conversation_quality_vectors:
            model_results = tuple(
                self._is_anomalous(
                    baseline.conversation_quality_vectors,
                    item.values,
                )
                for item in quality[CONVERSATION_BASELINE_SESSIONS:]
            )
        model_signal, score = model_results[-1] if model_results else (False, None)
        quality_persistence = (
            len(model_results) >= 2
            and sum(result[0] for result in model_results[-3:]) >= 2
        )

        participation_candidates = participation[PARTICIPATION_BASELINE_DAYS:]
        decrease_candidates = tuple(
            self._participation_decreased(
                baseline.participation_weekly_turn_mean,
                item.recent_7_day_user_turn_count,
            )
            for item in participation_candidates
        )
        rule_signal = decrease_candidates[-1] if decrease_candidates else False
        participation_persistence = (
            len(decrease_candidates) >= 2
            and decrease_candidates[-1]
            and decrease_candidates[-2]
        )
        persistence_signal = quality_persistence or participation_persistence
        latest_quality = quality[-1] if quality else None
        latest_participation = participation[-1] if participation else None
        reasons: list[str] = []
        if rule_signal and latest_participation is not None:
            baseline_mean = baseline.participation_weekly_turn_mean or 0.0
            decrease = baseline_mean - latest_participation.recent_7_day_user_turn_count
            reasons.append(
                "최근 7일 사용자 턴 수가 기준보다 "
                f"{decrease:.1f}턴 감소"
            )
        if model_signal and latest_quality is not None:
            reasons.extend(
                self._conversation_reasons(
                    baseline.conversation_quality_vectors,
                    latest_quality,
                )
            )
        if quality_persistence:
            reasons.append("최근 3개 완료 세션 중 2개 이상이 모델 이상 후보")
        if participation_persistence:
            reasons.append("대화 참여량 감소가 2개 관측일 연속 유지")

        mode = (
            AnomalyMode.ISOLATION_FOREST
            if baseline.conversation_quality_vectors
            else AnomalyMode.INSUFFICIENT_DATA
        )
        observation_key = (
            latest_quality.key
            if latest_quality is not None
            else (latest_participation.key if latest_participation else None)
        )
        return DomainEvaluation(
            status=self._consensus(rule_signal, model_signal, persistence_signal),
            mode=mode,
            sample_count=len(quality),
            score=score,
            reasons=tuple(dict.fromkeys(reasons)),
            feature_names=CONVERSATION_FEATURE_NAMES,
            rule_based_signal=rule_signal,
            isolation_forest_signal=model_signal,
            persistence_signal=persistence_signal,
            observation_key=observation_key,
        )

    @staticmethod
    def _consensus(rule: bool, model: bool, persistence: bool) -> AnomalyStatus:
        return (
            AnomalyStatus.ANOMALOUS
            if sum((rule, model, persistence)) >= 2
            else AnomalyStatus.NORMAL
        )

    @staticmethod
    def _participation_decreased(
        baseline: float | None,
        current: int,
    ) -> bool:
        if baseline is None or baseline <= 0:
            return False
        decrease = baseline - current
        return decrease >= 10 and current <= baseline * 0.5

    @staticmethod
    def _is_anomalous(
        baseline: tuple[tuple[float, ...], ...],
        current: tuple[float, ...],
    ) -> tuple[bool, float]:
        if not baseline:
            raise ValueError("Isolation Forest baseline must not be empty")
        constant_feature_shift = any(
            max(row[index] for row in baseline)
            == min(row[index] for row in baseline)
            != current[index]
            for index in range(len(current))
        )
        pipeline = make_pipeline(
            StandardScaler(),
            IsolationForest(
                n_estimators=MODEL_ESTIMATORS,
                contamination=MODEL_CONTAMINATION,
                random_state=MODEL_RANDOM_STATE,
            ),
        )
        pipeline.fit([list(row) for row in baseline])
        prediction = int(pipeline.predict([list(current)])[0])
        score = float(pipeline.decision_function([list(current)])[0])
        return prediction == -1 or constant_feature_shift, round(score, 6)

    @staticmethod
    def _routine_reasons(
        baseline: tuple[tuple[float, ...], ...],
        current: tuple[float, ...],
    ) -> tuple[str, ...]:
        labels = (
            "식사 미응답률 증가",
            "복약 미응답률 증가",
            "식사 확인 지연 증가",
            "복약 확인 지연 증가",
            "전체 완료율 변화",
            "동일 루틴 연속 미응답 증가",
        )
        reasons = [
            labels[index]
            for index in range(len(current))
            if (
                current[index] > median(row[index] for row in baseline)
                if index != 4
                else current[index] < median(row[index] for row in baseline)
            )
        ]
        return tuple(reasons[:3] or ["루틴 패턴이 개인 기준선에서 이탈"])

    @staticmethod
    def _conversation_reasons(
        baseline: tuple[tuple[float, ...], ...],
        current: ConversationQualityObservation,
    ) -> tuple[str, ...]:
        values = current.values
        medians = tuple(
            median(row[index] for row in baseline) for index in range(len(values))
        )
        reasons: list[str] = []
        if values[0] < medians[0]:
            reasons.append("회상 대화 사용자 턴 수 감소")
        if values[1] < medians[1]:
            reasons.append("회상 대화 총 글자 수 감소")
        if values[3] < medians[3]:
            reasons.append("회상 대화 평균 턴 입력 시간 감소")
        if values[4] > medians[4]:
            reasons.append("회상 대화 무응답 횟수 증가")
        return tuple(reasons[:3] or ["회상 대화 품질이 개인 기준선에서 이탈"])
