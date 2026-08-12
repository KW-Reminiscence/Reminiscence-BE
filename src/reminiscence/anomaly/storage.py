"""Immutable anomaly observations, fixed baselines and current JSON state."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from math import isfinite
from statistics import mean
from typing import Any

from reminiscence.anomaly.detector import (
    CONVERSATION_BASELINE_SESSIONS,
    MODEL_CONTAMINATION,
    MODEL_ESTIMATORS,
    MODEL_RANDOM_STATE,
    PARTICIPATION_BASELINE_DAYS,
    ROUTINE_BASELINE_DAYS,
)
from reminiscence.anomaly.models import (
    AnomalyMode,
    AnomalyObservations,
    AnomalyStatus,
    BaselineState,
    ConversationMetric,
    ConversationQualityObservation,
    DomainEvaluation,
    ParticipationObservation,
    PersonalEvaluation,
    RoutineMetric,
    RoutineObservation,
)
from reminiscence.storage import JsonObjectStore, JsonStorageError


class AnomalyStorageError(JsonStorageError):
    """Raised when anomaly inputs or persisted state are malformed."""


KNOWN_ROUTINE_STATES = frozenset({"REMINDING", "CONFIRMED", "NOT_ANSWERED"})
KNOWN_ROUTINE_CATEGORIES = frozenset({"MEAL", "MEDICATION"})


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AnomalyStorageError(f"{field_name} must be a non-empty string")
    return value


def _required_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise AnomalyStorageError(f"{field_name} must be an integer")
    return value


def _number(value: Any, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AnomalyStorageError(f"{field_name} must be a number")
    result = float(value)
    if not isfinite(result):
        raise AnomalyStorageError(f"{field_name} must be finite")
    return result


def _optional_number(value: Any, field_name: str) -> float | None:
    return None if value is None else _number(value, field_name)


def _aware_datetime(value: Any, field_name: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(_required_string(value, field_name))
    except ValueError as exc:
        raise AnomalyStorageError(f"{field_name} must be a valid datetime") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise AnomalyStorageError(f"{field_name} must be timezone-aware")
    return timestamp


def _local_date(value: Any, field_name: str) -> date:
    try:
        return date.fromisoformat(_required_string(value, field_name))
    except ValueError as exc:
        raise AnomalyStorageError(f"{field_name} must be a valid date") from exc


def _parse_routine_metric(value: Any) -> RoutineMetric:
    if not isinstance(value, dict):
        raise AnomalyStorageError("each routine execution must be an object")
    try:
        state = _required_string(value["state"], "state")
        if state not in KNOWN_ROUTINE_STATES:
            raise AnomalyStorageError(f"unknown routine state: {state}")
        delay_value = value.get("confirmation_delay_seconds")
        delay = None if delay_value is None else _required_int(
            delay_value,
            "confirmation_delay_seconds",
        )
        if delay is not None and delay < 0:
            raise AnomalyStorageError(
                "confirmation_delay_seconds must not be negative"
            )
        if state == "CONFIRMED" and delay is None:
            raise AnomalyStorageError(
                "CONFIRMED routine requires confirmation_delay_seconds"
            )
        if state != "CONFIRMED" and delay is not None:
            raise AnomalyStorageError(
                f"{state} routine must not have confirmation_delay_seconds"
            )
        category_value = value.get("category")
        category = None
        if category_value is not None:
            category = _required_string(category_value, "category")
            if category not in KNOWN_ROUTINE_CATEGORIES:
                raise AnomalyStorageError(f"unknown routine category: {category}")
        return RoutineMetric(
            routine_id=_required_string(value["routine_id"], "routine_id"),
            scheduled_at=_aware_datetime(value["scheduled_at"], "scheduled_at"),
            state=state,
            confirmation_delay_seconds=delay,
            category=category,
        )
    except KeyError as exc:
        raise AnomalyStorageError(f"invalid routine execution: {exc}") from exc


def _parse_conversation_metric(value: Any) -> ConversationMetric | None:
    if not isinstance(value, dict):
        raise AnomalyStorageError("each conversation session must be an object")
    if value.get("status") != "COMPLETED":
        return None
    try:
        summary = value["summary"]
        if not isinstance(summary, dict):
            raise AnomalyStorageError("conversation summary must be an object")
        counts = (
            _required_int(summary["user_turn_count"], "user_turn_count"),
            _required_int(summary["total_utterance_chars"], "total_utterance_chars"),
            _required_int(summary["no_response_count"], "no_response_count"),
        )
        if min(counts) < 0:
            raise AnomalyStorageError("conversation summary counts must not be negative")
        completed_at = _aware_datetime(value["completed_at"], "completed_at")
        return ConversationMetric(
            session_id=_required_string(value["session_id"], "session_id"),
            started_at=_aware_datetime(value["started_at"], "started_at"),
            completed_at=completed_at,
            user_turn_count=counts[0],
            total_utterance_chars=counts[1],
            average_utterance_chars=_optional_number(
                summary.get("average_utterance_chars"), "average_utterance_chars"
            ),
            average_turn_duration_seconds=_optional_number(
                summary.get("average_turn_duration_seconds"),
                "average_turn_duration_seconds",
            ),
            no_response_count=counts[2],
        )
    except KeyError as exc:
        raise AnomalyStorageError(f"invalid conversation session: {exc}") from exc


def _parse_routine_observation(value: Any) -> RoutineObservation:
    if not isinstance(value, dict):
        raise AnomalyStorageError("each routine observation must be an object")
    values = value.get("values")
    if not isinstance(values, list) or len(values) != 6:
        raise AnomalyStorageError("routine observation values must have 6 numbers")
    parsed = tuple(_number(item, "routine observation value") for item in values)
    if any(parsed[index] < 0 or parsed[index] > 1 for index in (0, 1, 4)):
        raise AnomalyStorageError("routine observation ratios must be between 0 and 1")
    if parsed[2] < 0 or parsed[3] < 0:
        raise AnomalyStorageError("routine observation delays must not be negative")
    if parsed[5] < 0 or not parsed[5].is_integer():
        raise AnomalyStorageError(
            "maximum consecutive misses must be a non-negative integer"
        )
    return RoutineObservation(
        target_date=_local_date(value.get("target_date"), "target_date"),
        values=parsed,  # type: ignore[arg-type]
    )


def _parse_quality_observation(value: Any) -> ConversationQualityObservation:
    if not isinstance(value, dict):
        raise AnomalyStorageError("each quality observation must be an object")
    values = value.get("values")
    if not isinstance(values, list) or len(values) != 5:
        raise AnomalyStorageError("quality observation values must have 5 numbers")
    parsed = tuple(_number(item, "quality observation value") for item in values)
    if any(item < 0 for item in parsed):
        raise AnomalyStorageError("quality observation values must not be negative")
    if any(not parsed[index].is_integer() for index in (0, 1, 4)):
        raise AnomalyStorageError("quality observation counts must be integers")
    return ConversationQualityObservation(
        session_id=_required_string(value.get("session_id"), "session_id"),
        completed_at=_aware_datetime(value.get("completed_at"), "completed_at"),
        values=parsed,  # type: ignore[arg-type]
    )


def _parse_participation_observation(value: Any) -> ParticipationObservation:
    if not isinstance(value, dict):
        raise AnomalyStorageError("each participation observation must be an object")
    count = _required_int(
        value.get("recent_7_day_user_turn_count"),
        "recent_7_day_user_turn_count",
    )
    if count < 0:
        raise AnomalyStorageError("recent_7_day_user_turn_count must not be negative")
    return ParticipationObservation(
        target_date=_local_date(value.get("target_date"), "target_date"),
        recent_7_day_user_turn_count=count,
    )


class ActivityObservationStore:
    """Materialize immutable observation keys inside activity_metrics.json."""

    def __init__(
        self,
        activity_store: JsonObjectStore,
        configuration_store: JsonObjectStore | None = None,
    ) -> None:
        self._activity_store = activity_store
        self._configuration_store = configuration_store

    def materialize(self, evaluated_at: datetime) -> AnomalyObservations:
        """Append every newly completed date and session exactly once."""

        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        category_by_id, scheduled_weekdays = self._routine_configuration()
        result: AnomalyObservations | None = None

        def mutate(root: dict[str, Any]) -> None:
            nonlocal result
            routines_raw = root.get("routine_executions", [])
            conversations_raw = root.get("conversation_sessions", [])
            if not isinstance(routines_raw, list):
                raise AnomalyStorageError("routine_executions must be an array")
            if not isinstance(conversations_raw, list):
                raise AnomalyStorageError("conversation_sessions must be an array")
            routines = tuple(_parse_routine_metric(value) for value in routines_raw)
            conversations = tuple(
                metric
                for metric in (
                    _parse_conversation_metric(value) for value in conversations_raw
                )
                if metric is not None and metric.started_at <= evaluated_at
            )
            stored_routines = self._stored_routines(root)
            stored_quality = self._stored_quality(root)
            stored_participation = self._stored_participation(root)
            observation_started_on = self._observation_started_on(
                root,
                routines,
                conversations,
                evaluated_at,
            )
            self._reject_date_reversal(
                evaluated_at.date(), stored_routines, stored_participation
            )

            computed_routines = self._routine_observations(
                routines,
                category_by_id,
                scheduled_weekdays,
                evaluated_at,
            )
            computed_quality = tuple(
                ConversationQualityObservation(
                    session_id=metric.session_id,
                    completed_at=metric.completed_at,
                    values=(
                        float(metric.user_turn_count),
                        float(metric.total_utterance_chars),
                        float(metric.average_utterance_chars or 0.0),
                        float(metric.average_turn_duration_seconds or 0.0),
                        float(metric.no_response_count),
                    ),
                )
                for metric in conversations
                if metric.completed_at <= evaluated_at
            )
            computed_participation = self._participation_observations(
                routines,
                conversations,
                evaluated_at,
                observation_started_on,
            )
            merged_routines = tuple(
                sorted(
                    self._merge_immutable(stored_routines, computed_routines),
                    key=lambda item: item.target_date,
                )
            )
            merged_quality = tuple(
                sorted(
                    self._merge_immutable(stored_quality, computed_quality),
                    key=lambda item: (item.completed_at, item.session_id),
                )
            )
            merged_participation = self._merge_immutable(
                stored_participation, computed_participation
            )
            merged_participation = tuple(
                sorted(merged_participation, key=lambda item: item.target_date)
            )
            root["routine_observations"] = [
                {"target_date": item.key, "values": list(item.values)}
                for item in merged_routines
            ]
            root["conversation_quality_observations"] = [
                {
                    "session_id": item.session_id,
                    "completed_at": item.completed_at.isoformat(),
                    "values": list(item.values),
                }
                for item in merged_quality
            ]
            root["participation_observations"] = [
                {
                    "target_date": item.key,
                    "recent_7_day_user_turn_count": (
                        item.recent_7_day_user_turn_count
                    ),
                }
                for item in merged_participation
            ]
            result = AnomalyObservations(
                routine_days=merged_routines,
                conversation_quality=merged_quality,
                participation_days=merged_participation,
            )

        self._activity_store.update(mutate)
        if result is None:  # pragma: no cover - update invariant
            raise AnomalyStorageError("observation update produced no result")
        return result

    def _routine_configuration(
        self,
    ) -> tuple[dict[str, str], dict[str, frozenset[int]]]:
        if self._configuration_store is None:
            return {}, {}
        root = self._configuration_store.read()
        routines = root.get("routines", [])
        if not isinstance(routines, list):
            raise AnomalyStorageError("routines must be an array")
        categories: dict[str, str] = {}
        scheduled_weekdays: dict[str, frozenset[int]] = {}
        for value in routines:
            if not isinstance(value, dict):
                raise AnomalyStorageError("each routine must be an object")
            routine_id = _required_string(value.get("id"), "routine id")
            category = _required_string(value.get("category"), "routine category")
            if category not in KNOWN_ROUTINE_CATEGORIES:
                raise AnomalyStorageError(f"unknown routine category: {category}")
            categories[routine_id] = category
            active = value.get("active", True)
            if not isinstance(active, bool):
                raise AnomalyStorageError("routine active must be a boolean")
            weekdays = value.get("weekdays")
            if not isinstance(weekdays, list) or not all(
                isinstance(day, int)
                and not isinstance(day, bool)
                and 0 <= day <= 6
                for day in weekdays
            ):
                raise AnomalyStorageError("routine weekdays must contain 0 through 6")
            if active:
                scheduled_weekdays[routine_id] = frozenset(weekdays)
        return categories, scheduled_weekdays

    @staticmethod
    def _observation_started_on(
        root: dict[str, Any],
        routines: tuple[RoutineMetric, ...],
        conversations: tuple[ConversationMetric, ...],
        evaluated_at: datetime,
    ) -> date:
        stored = root.get("anomaly_observation_started_on")
        if stored is not None:
            return _local_date(stored, "anomaly_observation_started_on")
        historical_dates = [
            item.scheduled_at.astimezone(evaluated_at.tzinfo).date()
            for item in routines
            if item.scheduled_at <= evaluated_at
        ]
        historical_dates.extend(
            item.started_at.astimezone(evaluated_at.tzinfo).date()
            for item in conversations
        )
        started_on = min(historical_dates, default=evaluated_at.date())
        root["anomaly_observation_started_on"] = started_on.isoformat()
        return started_on

    @staticmethod
    def _stored_routines(root: dict[str, Any]) -> tuple[RoutineObservation, ...]:
        value = root.get("routine_observations", [])
        if not isinstance(value, list):
            raise AnomalyStorageError("routine_observations must be an array")
        return tuple(_parse_routine_observation(item) for item in value)

    @staticmethod
    def _stored_quality(
        root: dict[str, Any],
    ) -> tuple[ConversationQualityObservation, ...]:
        value = root.get("conversation_quality_observations", [])
        if not isinstance(value, list):
            raise AnomalyStorageError(
                "conversation_quality_observations must be an array"
            )
        return tuple(_parse_quality_observation(item) for item in value)

    @staticmethod
    def _stored_participation(
        root: dict[str, Any],
    ) -> tuple[ParticipationObservation, ...]:
        value = root.get("participation_observations", [])
        if not isinstance(value, list):
            raise AnomalyStorageError("participation_observations must be an array")
        return tuple(_parse_participation_observation(item) for item in value)

    @staticmethod
    def _merge_immutable(current: tuple[Any, ...], computed: tuple[Any, ...]) -> tuple[Any, ...]:
        by_key = {item.key: item for item in current}
        if len(by_key) != len(current):
            raise AnomalyStorageError("observation keys must be unique")
        for item in computed:
            existing = by_key.get(item.key)
            if existing is not None and existing != item:
                raise AnomalyStorageError(
                    f"immutable observation changed for key: {item.key}"
                )
            by_key[item.key] = item
        return tuple(sorted(by_key.values(), key=lambda item: item.key))

    @staticmethod
    def _reject_date_reversal(
        target: date,
        routines: tuple[RoutineObservation, ...],
        participation: tuple[ParticipationObservation, ...],
    ) -> None:
        dates = [item.target_date for item in routines]
        dates.extend(item.target_date for item in participation)
        latest = max(dates, default=None)
        if latest is not None and target < latest:
            raise AnomalyStorageError("evaluation date must not move backwards")

    @staticmethod
    def _routine_observations(
        metrics: tuple[RoutineMetric, ...],
        category_by_id: dict[str, str],
        scheduled_weekdays: dict[str, frozenset[int]],
        evaluated_at: datetime,
    ) -> tuple[RoutineObservation, ...]:
        grouped: dict[date, list[RoutineMetric]] = defaultdict(list)
        for metric in metrics:
            if metric.scheduled_at <= evaluated_at:
                grouped[
                    metric.scheduled_at.astimezone(evaluated_at.tzinfo).date()
                ].append(metric)
        ordered = tuple(sorted(metrics, key=lambda item: item.scheduled_at))
        observations: list[RoutineObservation] = []
        for target_date, day_metrics in sorted(grouped.items()):
            if target_date >= evaluated_at.date() or any(
                metric.state == "REMINDING" for metric in day_metrics
            ):
                continue
            expected_ids = {
                routine_id
                for routine_id, weekdays in scheduled_weekdays.items()
                if target_date.weekday() in weekdays
            }
            actual_ids = {metric.routine_id for metric in day_metrics}
            if expected_ids and not expected_ids.issubset(actual_ids):
                continue
            categories = {
                metric.routine_id: metric.category or category_by_id.get(metric.routine_id)
                for metric in day_metrics
            }
            if any(value not in KNOWN_ROUTINE_CATEGORIES for value in categories.values()):
                raise AnomalyStorageError(
                    "terminal routine requires a MEAL or MEDICATION category"
                )
            meals = [item for item in day_metrics if categories[item.routine_id] == "MEAL"]
            medications = [
                item for item in day_metrics if categories[item.routine_id] == "MEDICATION"
            ]
            terminal = [item for item in day_metrics if item.state != "REMINDING"]
            values = (
                ActivityObservationStore._miss_ratio(meals),
                ActivityObservationStore._miss_ratio(medications),
                ActivityObservationStore._average_delay(meals),
                ActivityObservationStore._average_delay(medications),
                sum(item.state == "CONFIRMED" for item in terminal) / len(terminal),
                float(
                    ActivityObservationStore._maximum_miss_streak(
                        ordered,
                        target_date,
                        evaluated_at,
                    )
                ),
            )
            observations.append(RoutineObservation(target_date, values))
        return tuple(observations)

    @staticmethod
    def _miss_ratio(metrics: list[RoutineMetric]) -> float:
        return (
            sum(item.state == "NOT_ANSWERED" for item in metrics) / len(metrics)
            if metrics
            else 0.0
        )

    @staticmethod
    def _average_delay(metrics: list[RoutineMetric]) -> float:
        delays = [
            item.confirmation_delay_seconds
            for item in metrics
            if item.confirmation_delay_seconds is not None
        ]
        return float(mean(delays)) if delays else 0.0

    @staticmethod
    def _maximum_miss_streak(
        metrics: tuple[RoutineMetric, ...],
        target: date,
        evaluated_at: datetime,
    ) -> int:
        streaks: dict[str, int] = defaultdict(int)
        for metric in metrics:
            local_date = metric.scheduled_at.astimezone(evaluated_at.tzinfo).date()
            if local_date > target or metric.state == "REMINDING":
                continue
            if metric.state == "CONFIRMED":
                streaks[metric.routine_id] = 0
            else:
                streaks[metric.routine_id] += 1
        return max(streaks.values(), default=0)

    @staticmethod
    def _participation_observations(
        routines: tuple[RoutineMetric, ...],
        conversations: tuple[ConversationMetric, ...],
        evaluated_at: datetime,
        observation_started_on: date,
    ) -> tuple[ParticipationObservation, ...]:
        del routines
        start = observation_started_on
        end = evaluated_at.date() - timedelta(days=1)
        if end < start:
            return ()
        observations: list[ParticipationObservation] = []
        current = start
        while current <= end:
            window_start = current - timedelta(days=6)
            turns = sum(
                item.user_turn_count
                for item in conversations
                if window_start
                <= item.completed_at.astimezone(evaluated_at.tzinfo).date()
                <= current
            )
            observations.append(ParticipationObservation(current, turns))
            current += timedelta(days=1)
        return tuple(observations)


class BaselineStore:
    """Persist fixed first-window baselines and deterministic model settings."""

    def __init__(self, store: JsonObjectStore) -> None:
        self._store = store

    def load_or_initialize(self, observations: AnomalyObservations) -> BaselineState:
        """Write each baseline only once when its sample boundary is reached."""

        result: BaselineState | None = None

        def mutate(root: dict[str, Any]) -> None:
            nonlocal result
            routine = self._vectors(root.get("routine_vectors"), 6, "routine_vectors")
            quality = self._vectors(
                root.get("conversation_quality_vectors"),
                5,
                "conversation_quality_vectors",
            )
            participation_value = root.get("participation_weekly_turn_mean")
            participation = (
                None
                if participation_value is None
                else _number(participation_value, "participation_weekly_turn_mean")
            )
            if not routine and len(observations.routine_days) >= ROUTINE_BASELINE_DAYS:
                routine = tuple(
                    item.values for item in observations.routine_days[:ROUTINE_BASELINE_DAYS]
                )
                root["routine_vectors"] = [list(vector) for vector in routine]
            if (
                not quality
                and len(observations.conversation_quality)
                >= CONVERSATION_BASELINE_SESSIONS
            ):
                quality = tuple(
                    item.values
                    for item in observations.conversation_quality[
                        :CONVERSATION_BASELINE_SESSIONS
                    ]
                )
                root["conversation_quality_vectors"] = [
                    list(vector) for vector in quality
                ]
            if (
                participation is None
                and len(observations.participation_days) >= PARTICIPATION_BASELINE_DAYS
            ):
                first = observations.participation_days[:PARTICIPATION_BASELINE_DAYS]
                weekly_totals = [
                    first[index].recent_7_day_user_turn_count
                    for index in (6, 13, 20, 27)
                ]
                participation = float(mean(weekly_totals))
                root["participation_weekly_turn_mean"] = participation
            root["model"] = {
                "algorithm": "IsolationForest",
                "random_state": MODEL_RANDOM_STATE,
                "n_estimators": MODEL_ESTIMATORS,
                "contamination": MODEL_CONTAMINATION,
            }
            result = BaselineState(routine, quality, participation)

        self._store.update(mutate)
        if result is None:  # pragma: no cover - update invariant
            raise AnomalyStorageError("baseline update produced no result")
        return result

    @staticmethod
    def _vectors(value: Any, width: int, field_name: str) -> tuple[tuple[float, ...], ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise AnomalyStorageError(f"{field_name} must be an array")
        vectors: list[tuple[float, ...]] = []
        for row in value:
            if not isinstance(row, list) or len(row) != width:
                raise AnomalyStorageError(f"{field_name} rows must have {width} numbers")
            vectors.append(tuple(_number(item, field_name) for item in row))
        return tuple(vectors)


def _serialize_domain(evaluation: DomainEvaluation) -> dict[str, Any]:
    return {
        "status": evaluation.status.value,
        "mode": evaluation.mode.value,
        "sample_count": evaluation.sample_count,
        "score": evaluation.score,
        "reasons": list(evaluation.reasons),
        "feature_names": list(evaluation.feature_names),
        "rule_based_signal": evaluation.rule_based_signal,
        "isolation_forest_signal": evaluation.isolation_forest_signal,
        "persistence_signal": evaluation.persistence_signal,
        "observation_key": evaluation.observation_key,
    }


def _parse_domain(value: Any) -> DomainEvaluation:
    if not isinstance(value, dict):
        raise AnomalyStorageError("domain state must be an object")
    try:
        reasons = value["reasons"]
        feature_names = value["feature_names"]
        if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
            raise AnomalyStorageError("reasons must be an array of strings")
        if not isinstance(feature_names, list) or not all(
            isinstance(item, str) for item in feature_names
        ):
            raise AnomalyStorageError("feature_names must be an array of strings")
        signals = tuple(
            value.get(name, False)
            for name in (
                "rule_based_signal",
                "isolation_forest_signal",
                "persistence_signal",
            )
        )
        if not all(isinstance(item, bool) for item in signals):
            raise AnomalyStorageError("domain signals must be booleans")
        observation_key = value.get("observation_key")
        if observation_key is not None and not isinstance(observation_key, str):
            raise AnomalyStorageError("observation_key must be a string or null")
        return DomainEvaluation(
            status=AnomalyStatus(_required_string(value["status"], "domain status")),
            mode=AnomalyMode(_required_string(value["mode"], "mode")),
            sample_count=_required_int(value["sample_count"], "sample_count"),
            score=_optional_number(value.get("score"), "score"),
            reasons=tuple(reasons),
            feature_names=tuple(feature_names),
            rule_based_signal=signals[0],
            isolation_forest_signal=signals[1],
            persistence_signal=signals[2],
            observation_key=observation_key,
        )
    except (KeyError, ValueError) as exc:
        raise AnomalyStorageError(f"invalid domain state: {exc}") from exc


class PersonalStateStore:
    """Persist only the latest explainable personal state."""

    def __init__(self, store: JsonObjectStore) -> None:
        self._store = store

    def load(self) -> PersonalEvaluation | None:
        root = self._store.read()
        if not root or set(root) <= {"schema_version"}:
            return None
        try:
            return PersonalEvaluation(
                evaluated_at=_aware_datetime(root["evaluated_at"], "evaluated_at"),
                status=AnomalyStatus(_required_string(root["status"], "status")),
                routine=_parse_domain(root["routine"]),
                conversation=_parse_domain(root["conversation"]),
                consecutive_anomalous_evaluations=_required_int(
                    root.get("consecutive_anomalous_evaluations", 0),
                    "consecutive_anomalous_evaluations",
                ),
            )
        except (KeyError, ValueError) as exc:
            raise AnomalyStorageError(f"invalid personal state: {exc}") from exc

    def save(self, evaluation: PersonalEvaluation) -> None:
        def mutate(root: dict[str, Any]) -> None:
            root.clear()
            root.update(
                {
                    "status": evaluation.status.value,
                    "evaluated_at": evaluation.evaluated_at.isoformat(),
                    "consecutive_anomalous_evaluations": (
                        evaluation.consecutive_anomalous_evaluations
                    ),
                    "routine": _serialize_domain(evaluation.routine),
                    "conversation": _serialize_domain(evaluation.conversation),
                    "model_metadata": {
                        "algorithm": "IsolationForest",
                        "random_state": MODEL_RANDOM_STATE,
                        "routine_baseline_days": ROUTINE_BASELINE_DAYS,
                        "conversation_baseline_sessions": (
                            CONVERSATION_BASELINE_SESSIONS
                        ),
                        "participation_baseline_days": PARTICIPATION_BASELINE_DAYS,
                        "consensus_required_signals": 2,
                    },
                }
            )

        self._store.update(mutate)
