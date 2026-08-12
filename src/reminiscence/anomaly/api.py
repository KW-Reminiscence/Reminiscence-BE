"""HTTP API for evaluating and reading personal anomaly state."""

from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from reminiscence.anomaly.detector import PersonalAnomalyDetector
from reminiscence.anomaly.models import (
    AnomalyMode,
    AnomalyStatus,
    DomainEvaluation,
    PersonalEvaluation,
)
from reminiscence.anomaly.service import AnomalyService
from reminiscence.anomaly.storage import (
    ActivityObservationStore,
    AnomalyStorageError,
    BaselineStore,
    PersonalStateStore,
)
from reminiscence.storage import JsonStorageError, open_versioned_store

router = APIRouter(prefix="/api/v1/anomaly", tags=["anomaly"])


class DomainEvaluationResponse(BaseModel):
    """One detector's explainable current state."""

    status: AnomalyStatus
    mode: AnomalyMode
    sample_count: int
    score: float | None
    reasons: list[str]
    feature_names: list[str]
    rule_based_signal: bool
    isolation_forest_signal: bool
    persistence_signal: bool
    signal_count: int
    observation_key: str | None


class PersonalStateResponse(BaseModel):
    """Combined current state with separate domain details."""

    evaluated_at: datetime
    status: AnomalyStatus
    became_anomalous: bool
    consecutive_anomalous_evaluations: int
    routine: DomainEvaluationResponse
    conversation: DomainEvaluationResponse


def _data_directory() -> Path:
    return Path(os.environ.get("REMINISCENCE_DATA_DIR", "data"))


def _server_timezone() -> ZoneInfo:
    timezone_name = os.environ.get("REMINISCENCE_TIMEZONE", "Asia/Seoul")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"unknown REMINISCENCE_TIMEZONE: {timezone_name}") from exc


@lru_cache(maxsize=1)
def get_anomaly_service() -> AnomalyService:
    """Build the process-wide detector over local JSON files."""

    data_directory = _data_directory()
    return AnomalyService(
        ActivityObservationStore(
            open_versioned_store(
                data_directory / "activity_metrics.json",
                missing_default={},
            ),
            open_versioned_store(
                data_directory / "configuration.json",
                missing_default={},
                read_only=True,
            ),
        ),
        BaselineStore(
            open_versioned_store(
                data_directory / "anomaly_baseline.json",
                missing_default={},
            )
        ),
        PersonalStateStore(
            open_versioned_store(
                data_directory / "personal_state.json",
                missing_default={},
            )
        ),
        PersonalAnomalyDetector(),
    )


def get_current_time() -> datetime:
    """Return trusted server time."""

    return datetime.now(tz=_server_timezone())


def _domain_response(value: DomainEvaluation) -> DomainEvaluationResponse:
    return DomainEvaluationResponse(
        status=value.status,
        mode=value.mode,
        sample_count=value.sample_count,
        score=value.score,
        reasons=list(value.reasons),
        feature_names=list(value.feature_names),
        rule_based_signal=value.rule_based_signal,
        isolation_forest_signal=value.isolation_forest_signal,
        persistence_signal=value.persistence_signal,
        signal_count=value.signal_count,
        observation_key=value.observation_key,
    )


def _state_response(
    evaluation: PersonalEvaluation,
    *,
    became_anomalous: bool,
) -> PersonalStateResponse:
    return PersonalStateResponse(
        evaluated_at=evaluation.evaluated_at,
        status=evaluation.status,
        became_anomalous=became_anomalous,
        consecutive_anomalous_evaluations=(
            evaluation.consecutive_anomalous_evaluations
        ),
        routine=_domain_response(evaluation.routine),
        conversation=_domain_response(evaluation.conversation),
    )


AnomalyServiceDependency = Annotated[AnomalyService, Depends(get_anomaly_service)]
CurrentTimeDependency = Annotated[datetime, Depends(get_current_time)]


@router.post(
    "/evaluate",
    response_model=PersonalStateResponse,
    summary="Evaluate personal activity patterns",
)
async def evaluate_anomaly(
    service: AnomalyServiceDependency,
    now: CurrentTimeDependency,
) -> PersonalStateResponse:
    """Run both domain detectors and atomically store the current state."""

    try:
        outcome = service.evaluate(now)
    except (AnomalyStorageError, JsonStorageError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return _state_response(
        outcome.evaluation,
        became_anomalous=outcome.became_anomalous,
    )


@router.get(
    "/state",
    response_model=PersonalStateResponse,
    summary="Get the latest personal state",
)
async def get_anomaly_state(
    service: AnomalyServiceDependency,
) -> PersonalStateResponse:
    """Return the last evaluation without rerunning either model."""

    try:
        evaluation = service.current_state()
    except (AnomalyStorageError, JsonStorageError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="personal state has not been evaluated",
        )
    return _state_response(evaluation, became_anomalous=False)
