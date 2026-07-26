"""Cold-start rules and separate Isolation Forest models."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite
from statistics import median

from sklearn.ensemble import IsolationForest  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from reminiscence.anomaly.models import (
    AnomalyMode,
    AnomalyStatus,
    ConversationMetric,
    DomainEvaluation,
    PersonalEvaluation,
    RoutineMetric,
)

ROUTINE_BASELINE_DAYS = 28
CONVERSATION_BASELINE_SESSIONS = 20
ROUTINE_FEATURE_NAMES = (
    "not_answered_ratio",
    "average_confirmation_delay_seconds",
)
CONVERSATION_FEATURE_NAMES = (
    "recent_7_day_user_turn_count",
    "total_utterance_chars",
    "average_utterance_chars",
    "average_turn_duration_seconds",
    "no_response_count",
)


@dataclass(frozen=True, slots=True)
class _DailyRoutineVector:
    target_date: date
    values: tuple[float, float]


class PersonalAnomalyDetector:
    """Evaluate current behavior against one user's own history."""

    def evaluate(
        self,
        routine_metrics: tuple[RoutineMetric, ...],
        conversation_metrics: tuple[ConversationMetric, ...],
        evaluated_at: datetime,
    ) -> PersonalEvaluation:
        """Evaluate routine and conversation domains independently."""

        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        routine = self.evaluate_routines(routine_metrics)
        conversation = self.evaluate_conversations(conversation_metrics)
        status = (
            AnomalyStatus.ANOMALOUS
            if AnomalyStatus.ANOMALOUS
            in {routine.status, conversation.status}
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
        metrics: tuple[RoutineMetric, ...],
    ) -> DomainEvaluation:
        """Apply three consecutive misses until 28 baseline days exist."""

        ordered = tuple(sorted(metrics, key=lambda metric: metric.scheduled_at))
        daily_vectors = self._daily_routine_vectors(ordered)
        if len(daily_vectors) <= ROUTINE_BASELINE_DAYS:
            missed_routine_id = self._three_consecutive_misses(ordered)
            reasons: tuple[str, ...] = (
                (f"{missed_routine_id} 루틴 3회 연속 미응답",)
                if missed_routine_id is not None
                else ()
            )
            return DomainEvaluation(
                status=(
                    AnomalyStatus.ANOMALOUS
                    if reasons
                    else AnomalyStatus.NORMAL
                ),
                mode=AnomalyMode.COLD_START,
                sample_count=len(daily_vectors),
                score=None,
                reasons=reasons,
                feature_names=ROUTINE_FEATURE_NAMES,
            )

        baseline = [list(vector.values) for vector in daily_vectors[:-1]]
        current = list(daily_vectors[-1].values)
        anomalous, score = self._is_anomalous(baseline, current)
        reasons = (
            self._routine_reasons(baseline, current) if anomalous else ()
        )
        return DomainEvaluation(
            status=(
                AnomalyStatus.ANOMALOUS
                if anomalous
                else AnomalyStatus.NORMAL
            ),
            mode=AnomalyMode.ISOLATION_FOREST,
            sample_count=len(daily_vectors),
            score=score,
            reasons=reasons,
            feature_names=ROUTINE_FEATURE_NAMES,
        )

    def evaluate_conversations(
        self,
        metrics: tuple[ConversationMetric, ...],
    ) -> DomainEvaluation:
        """Activate the conversation model after 20 completed baseline sessions."""

        ordered = tuple(sorted(metrics, key=lambda metric: metric.started_at))
        if len(ordered) <= CONVERSATION_BASELINE_SESSIONS:
            return DomainEvaluation(
                status=AnomalyStatus.NORMAL,
                mode=AnomalyMode.INSUFFICIENT_DATA,
                sample_count=len(ordered),
                score=None,
                reasons=(),
                feature_names=CONVERSATION_FEATURE_NAMES,
            )

        vectors = self._conversation_vectors(ordered)
        baseline = [list(vector) for vector in vectors[:-1]]
        current = list(vectors[-1])
        anomalous, score = self._is_anomalous(baseline, current)
        reasons = (
            self._conversation_reasons(baseline, current) if anomalous else ()
        )
        return DomainEvaluation(
            status=(
                AnomalyStatus.ANOMALOUS
                if anomalous
                else AnomalyStatus.NORMAL
            ),
            mode=AnomalyMode.ISOLATION_FOREST,
            sample_count=len(ordered),
            score=score,
            reasons=reasons,
            feature_names=CONVERSATION_FEATURE_NAMES,
        )

    @staticmethod
    def _three_consecutive_misses(
        metrics: tuple[RoutineMetric, ...],
    ) -> str | None:
        by_routine: dict[str, list[RoutineMetric]] = defaultdict(list)
        for metric in metrics:
            by_routine[metric.routine_id].append(metric)
        for routine_id, routine_metrics in sorted(by_routine.items()):
            if (
                len(routine_metrics) >= 3
                and all(
                    metric.state == "NOT_ANSWERED"
                    for metric in routine_metrics[-3:]
                )
            ):
                return routine_id
        return None

    @staticmethod
    def _daily_routine_vectors(
        metrics: tuple[RoutineMetric, ...],
    ) -> tuple[_DailyRoutineVector, ...]:
        grouped: dict[date, list[RoutineMetric]] = defaultdict(list)
        for metric in metrics:
            grouped[metric.scheduled_at.date()].append(metric)
        vectors: list[_DailyRoutineVector] = []
        for target_date, day_metrics in sorted(grouped.items()):
            not_answered_ratio = sum(
                metric.state == "NOT_ANSWERED" for metric in day_metrics
            ) / len(day_metrics)
            delays = [
                metric.confirmation_delay_seconds
                for metric in day_metrics
                if metric.confirmation_delay_seconds is not None
            ]
            average_delay = sum(delays) / len(delays) if delays else 0.0
            vectors.append(
                _DailyRoutineVector(
                    target_date=target_date,
                    values=(not_answered_ratio, average_delay),
                )
            )
        return tuple(vectors)

    @staticmethod
    def _conversation_vectors(
        metrics: tuple[ConversationMetric, ...],
    ) -> list[tuple[float, ...]]:
        vectors: list[tuple[float, ...]] = []
        for index, metric in enumerate(metrics):
            window_start = metric.started_at - timedelta(days=7)
            recent_turns = sum(
                candidate.user_turn_count
                for candidate in metrics[: index + 1]
                if candidate.started_at > window_start
            )
            values = (
                float(recent_turns),
                float(metric.total_utterance_chars),
                float(metric.average_utterance_chars or 0.0),
                float(metric.average_turn_duration_seconds or 0.0),
                float(metric.no_response_count),
            )
            if not all(isfinite(value) for value in values):
                raise ValueError("conversation metrics must be finite")
            vectors.append(values)
        return vectors

    @staticmethod
    def _is_anomalous(
        baseline: list[list[float]],
        current: list[float],
    ) -> tuple[bool, float]:
        constant_feature_shift = any(
            max(row[index] for row in baseline)
            == min(row[index] for row in baseline)
            != current[index]
            for index in range(len(current))
        )
        pipeline = make_pipeline(
            StandardScaler(),
            IsolationForest(
                n_estimators=100,
                contamination=0.1,
                random_state=42,
            ),
        )
        pipeline.fit(baseline)
        prediction = int(pipeline.predict([current])[0])
        score = float(pipeline.decision_function([current])[0])
        return prediction == -1 or constant_feature_shift, round(score, 6)

    @staticmethod
    def _routine_reasons(
        baseline: list[list[float]],
        current: list[float],
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if current[0] > median(row[0] for row in baseline):
            reasons.append("루틴 미응답 비율이 개인 기준선보다 증가")
        if current[1] > median(row[1] for row in baseline):
            reasons.append("루틴 확인 지연이 개인 기준선보다 증가")
        return tuple(reasons or ["루틴 패턴이 개인 기준선에서 이탈"])

    @staticmethod
    def _conversation_reasons(
        baseline: list[list[float]],
        current: list[float],
    ) -> tuple[str, ...]:
        medians = [median(row[index] for row in baseline) for index in range(5)]
        reasons: list[str] = []
        if current[0] < medians[0]:
            reasons.append("최근 7일 회상 대화 사용자 턴 수가 개인 기준선보다 감소")
        if current[1] < medians[1]:
            reasons.append("회상 대화 글자 수가 개인 기준선보다 감소")
        if current[4] > medians[4]:
            reasons.append("회상 대화 무응답 횟수가 개인 기준선보다 증가")
        if current[3] < medians[3]:
            reasons.append("회상 대화 턴 지속시간이 개인 기준선보다 감소")
        return tuple(reasons[:3] or ["회상 대화 패턴이 개인 기준선에서 이탈"])
