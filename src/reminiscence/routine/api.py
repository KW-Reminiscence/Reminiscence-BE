"""Tablet-facing HTTP API for routine prompts and confirmations."""

from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from reminiscence.auth.dependencies import (
    GuardianSessionDependency,
    SameOriginDependency,
    TabletSessionDependency,
)
from reminiscence.routine.models import (
    RoutineCategory,
    RoutineDefinition,
    RoutineExecution,
    RoutineState,
)
from reminiscence.routine.scheduler import RoutineNotFoundError, RoutineScheduler
from reminiscence.routine.state_machine import RoutineStateError
from reminiscence.routine.storage import JsonRoutineStore, RoutineStorageError

router = APIRouter(prefix="/api/v1/routines", tags=["routines"])


class RoutinePromptResponse(BaseModel):
    """One active routine prompt rendered and spoken by the tablet."""

    execution_id: str
    routine_id: str
    name: str
    category: RoutineCategory
    state: RoutineState
    scheduled_at: datetime
    reminder_count: int
    display_text: str
    spoken_text: str
    confirm_label: str


class CurrentRoutinesResponse(BaseModel):
    """Active routine prompts at the server's current time."""

    server_time: datetime
    items: list[RoutinePromptResponse]


class RoutineExecutionResponse(BaseModel):
    """Persisted result for one routine occurrence."""

    execution_id: str
    routine_id: str
    state: RoutineState
    scheduled_at: datetime
    reminder_count: int
    confirmed_at: datetime | None
    confirmation_delay_seconds: int | None
    closed_at: datetime | None


def _data_directory() -> Path:
    return Path(os.environ.get("REMINISCENCE_DATA_DIR", "data"))


def _server_timezone() -> ZoneInfo:
    timezone_name = os.environ.get("REMINISCENCE_TIMEZONE", "Asia/Seoul")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"unknown REMINISCENCE_TIMEZONE: {timezone_name}") from exc


@lru_cache(maxsize=1)
def get_routine_scheduler() -> RoutineScheduler:
    """Build the process-wide scheduler over the configured data directory."""

    data_directory = _data_directory()
    return RoutineScheduler(
        JsonRoutineStore(
            data_directory / "configuration.json",
            data_directory / "activity_metrics.json",
        ),
        _server_timezone(),
    )


def get_current_time() -> datetime:
    """Return the current time in the configured server timezone."""

    return datetime.now(tz=_server_timezone())


def _prompt_text(name: str) -> str:
    return f"{name} 시간입니다. 마치신 뒤 기록 버튼을 눌러 주세요."


def _confirm_label(name: str, category: RoutineCategory) -> str:
    del category
    return f"{name} 기록하기"


def _prompt_response(
    definition: RoutineDefinition | None,
    execution: RoutineExecution,
) -> RoutinePromptResponse:
    name = execution.routine_name or (definition.name if definition else None)
    category = execution.category or (definition.category if definition else None)
    if name is None or category is None:
        raise ValueError("routine execution has no presentation snapshot")
    text = _prompt_text(name)
    return RoutinePromptResponse(
        execution_id=execution.execution_id,
        routine_id=execution.routine_id,
        name=name,
        category=category,
        state=execution.state,
        scheduled_at=execution.scheduled_at,
        reminder_count=execution.reminder_count,
        display_text=text,
        spoken_text=text,
        confirm_label=_confirm_label(name, category),
    )


def _execution_response(execution: RoutineExecution) -> RoutineExecutionResponse:
    return RoutineExecutionResponse(
        execution_id=execution.execution_id,
        routine_id=execution.routine_id,
        state=execution.state,
        scheduled_at=execution.scheduled_at,
        reminder_count=execution.reminder_count,
        confirmed_at=execution.confirmed_at,
        confirmation_delay_seconds=execution.confirmation_delay_seconds,
        closed_at=execution.closed_at,
    )


SchedulerDependency = Annotated[RoutineScheduler, Depends(get_routine_scheduler)]
CurrentTimeDependency = Annotated[datetime, Depends(get_current_time)]


@router.get(
    "/current",
    response_model=CurrentRoutinesResponse,
    summary="Get active tablet routine prompts",
)
async def get_current_routines(
    scheduler: SchedulerDependency,
    now: CurrentTimeDependency,
    _: TabletSessionDependency,
) -> CurrentRoutinesResponse:
    """Advance due transitions and return prompts the tablet should display."""

    try:
        scheduler.tick(now)
        definitions = {
            definition.routine_id: definition
            for definition in scheduler.list_definitions()
        }
        prompts = []
        for execution in scheduler.list_executions():
            if execution.state is not RoutineState.REMINDING:
                continue
            definition = definitions.get(execution.routine_id)
            if (
                definition is None
                and execution.routine_name is None
                and execution.category is None
            ):
                continue
            prompts.append(_prompt_response(definition, execution))
    except (RoutineStorageError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return CurrentRoutinesResponse(server_time=now, items=prompts)


@router.post(
    "/{execution_id}/confirm",
    response_model=RoutineExecutionResponse,
    summary="Confirm a completed routine",
)
async def confirm_routine(
    execution_id: str,
    scheduler: SchedulerDependency,
    now: CurrentTimeDependency,
    _: TabletSessionDependency,
    __: SameOriginDependency,
) -> RoutineExecutionResponse:
    """Record the tablet button press using the trusted server time."""

    try:
        execution = scheduler.confirm(execution_id, now)
    except RoutineNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except RoutineStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except RoutineStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return _execution_response(execution)


@router.get(
    "/history",
    response_model=list[RoutineExecutionResponse],
    summary="List persisted routine executions",
)
async def get_routine_history(
    scheduler: SchedulerDependency,
    now: CurrentTimeDependency,
    _: GuardianSessionDependency,
) -> list[RoutineExecutionResponse]:
    """Advance transitions and return routine history without prompt text."""

    try:
        scheduler.tick(now)
        return [
            _execution_response(execution)
            for execution in scheduler.list_executions()
        ]
    except RoutineStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
