"""Tablet-facing API for reminiscence conversations, ASR, and TTS text."""

from __future__ import annotations

import os
from datetime import datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from reminiscence.asr import (
    EtriRecognizer,
    EtriRecognizerConfig,
    RecognitionUnavailableError,
    SpeechRecognizer,
)
from reminiscence.conversation.models import (
    ConversationSession,
    ConversationSource,
    ConversationStatus,
    ConversationSummary,
    ConversationTurnMetric,
)
from reminiscence.conversation.questions import (
    QuestionProvider,
    SafeTemplateQuestionProvider,
    SpeechText,
)
from reminiscence.conversation.service import (
    ConversationNotFoundError,
    ConversationService,
    ConversationStateError,
)
from reminiscence.conversation.storage import (
    ConversationStorageError,
    JsonConversationStore,
)
from reminiscence.conversation.suggestion import ConversationSuggestionPolicy
from reminiscence.storage import JsonObjectStore, JsonStorageError

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


class StartConversationRequest(BaseModel):
    """How the tablet starts a session."""

    source: ConversationSource
    photo_id: str | None = None


class ConversationSuggestionResponse(BaseModel):
    """Daily suggestion state consumed by the tablet home screen."""

    suggested: bool
    scheduled_time: time
    display_text: str | None
    spoken_text: str | None
    start_label: str | None


class SpeechTextResponse(BaseModel):
    """Supertonic 3 input contract coupled to visible text."""

    display_text: str
    spoken_text: str


class StartConversationResponse(BaseModel):
    """Session context and the first safe question."""

    session_id: str
    status: ConversationStatus
    photo_id: str | None
    image_url: str | None
    question: SpeechTextResponse


class TurnMetricResponse(BaseModel):
    """Non-sensitive metrics produced from one audio turn."""

    turn_id: str
    utterance_chars: int
    turn_duration_seconds: float
    chars_per_second: float | None
    no_response: bool
    next_question: SpeechTextResponse


class ConversationSummaryResponse(BaseModel):
    """Persisted session aggregate without conversation text."""

    session_id: str
    status: ConversationStatus
    started_at: datetime
    completed_at: datetime | None
    user_turn_count: int
    total_utterance_chars: int
    average_utterance_chars: float | None
    average_turn_duration_seconds: float | None
    no_response_count: int


def _data_directory() -> Path:
    return Path(os.environ.get("REMINISCENCE_DATA_DIR", "data"))


def _server_timezone() -> ZoneInfo:
    timezone_name = os.environ.get("REMINISCENCE_TIMEZONE", "Asia/Seoul")
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"unknown REMINISCENCE_TIMEZONE: {timezone_name}") from exc


@lru_cache(maxsize=1)
def get_conversation_service() -> ConversationService:
    """Build the process-wide conversation service."""

    return ConversationService(
        JsonConversationStore(
            JsonObjectStore(
                _data_directory() / "activity_metrics.json",
                missing_default={"conversation_sessions": []},
            )
        )
    )


@lru_cache(maxsize=1)
def get_speech_recognizer() -> SpeechRecognizer:
    """Build the configured ASR provider without persisting its credential."""

    try:
        return EtriRecognizer(EtriRecognizerConfig.from_environment())
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="speech recognition is not configured",
        ) from exc


@lru_cache(maxsize=1)
def get_question_provider() -> QuestionProvider:
    """Return the safe MVP question provider."""

    return SafeTemplateQuestionProvider()


def get_current_time() -> datetime:
    """Return trusted server time."""

    return datetime.now(tz=_server_timezone())


def _load_photo(photo_id: str | None) -> tuple[str | None, str | None]:
    root = JsonObjectStore(
        _data_directory() / "configuration.json",
        missing_default={"photos": []},
    ).read()
    photos_value = root.get("photos", [])
    if not isinstance(photos_value, list):
        raise ConversationStorageError("photos must be an array")
    photos = [photo for photo in photos_value if isinstance(photo, dict)]
    selected: dict[str, Any] | None = None
    if photo_id is None:
        selected = photos[0] if photos else None
    else:
        selected = next(
            (photo for photo in photos if photo.get("id") == photo_id),
            None,
        )
        if selected is None:
            raise ConversationNotFoundError(f"photo not found: {photo_id}")
    if selected is None:
        return None, None
    selected_id = selected.get("id")
    image_url = selected.get("image_url")
    if not isinstance(selected_id, str) or not selected_id:
        raise ConversationStorageError("photo id must be a non-empty string")
    if not isinstance(image_url, str) or not image_url:
        raise ConversationStorageError("photo image_url must be a non-empty string")
    return selected_id, image_url


def _load_conversation_suggestion_time() -> time:
    root = JsonObjectStore(
        _data_directory() / "configuration.json",
        missing_default={},
    ).read()
    conversation_value = root.get("conversation", {})
    if not isinstance(conversation_value, dict):
        raise ConversationStorageError("conversation must be an object")
    scheduled_time_value = conversation_value.get("suggestion_time", "14:00")
    if not isinstance(scheduled_time_value, str):
        raise ConversationStorageError("conversation.suggestion_time must be a string")
    try:
        scheduled_time = time.fromisoformat(scheduled_time_value)
    except ValueError as exc:
        raise ConversationStorageError(
            "conversation.suggestion_time must be a valid local time"
        ) from exc
    if scheduled_time.tzinfo is not None:
        raise ConversationStorageError(
            "conversation.suggestion_time must not include a timezone"
        )
    return scheduled_time


def _speech_response(value: SpeechText) -> SpeechTextResponse:
    return SpeechTextResponse(
        display_text=value.display_text,
        spoken_text=value.spoken_text,
    )


def _summary_response(session: ConversationSession) -> ConversationSummaryResponse:
    summary: ConversationSummary = session.summary
    return ConversationSummaryResponse(
        session_id=session.session_id,
        status=session.status,
        started_at=session.started_at,
        completed_at=session.completed_at,
        user_turn_count=summary.user_turn_count,
        total_utterance_chars=summary.total_utterance_chars,
        average_utterance_chars=summary.average_utterance_chars,
        average_turn_duration_seconds=summary.average_turn_duration_seconds,
        no_response_count=summary.no_response_count,
    )


ConversationServiceDependency = Annotated[
    ConversationService,
    Depends(get_conversation_service),
]
RecognizerDependency = Annotated[SpeechRecognizer, Depends(get_speech_recognizer)]
QuestionProviderDependency = Annotated[
    QuestionProvider,
    Depends(get_question_provider),
]
CurrentTimeDependency = Annotated[datetime, Depends(get_current_time)]
AudioBody = Annotated[bytes, Body(media_type="audio/wav")]
TurnDuration = Annotated[float, Query(ge=0, le=300)]


@router.get(
    "/suggestion",
    response_model=ConversationSuggestionResponse,
    summary="Get today's scheduled conversation suggestion",
)
async def get_conversation_suggestion(
    service: ConversationServiceDependency,
    now: CurrentTimeDependency,
) -> ConversationSuggestionResponse:
    """Offer a daily session without treating a dismissed offer as an anomaly."""

    try:
        outcome = ConversationSuggestionPolicy(
            _load_conversation_suggestion_time()
        ).evaluate(now, service.list_sessions())
    except (ConversationStorageError, JsonStorageError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    text = "오늘 사진을 보며 이야기 나눠 보실래요?"
    return ConversationSuggestionResponse(
        suggested=outcome.suggested,
        scheduled_time=outcome.scheduled_time,
        display_text=text if outcome.suggested else None,
        spoken_text=text if outcome.suggested else None,
        start_label="이야기 시작하기" if outcome.suggested else None,
    )


@router.post(
    "/sessions",
    response_model=StartConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a reminiscence conversation",
)
async def start_conversation(
    payload: StartConversationRequest,
    service: ConversationServiceDependency,
    questions: QuestionProviderDependency,
    now: CurrentTimeDependency,
) -> StartConversationResponse:
    """Start a scheduled or voluntary session with a synthesizable question."""

    try:
        photo_id, image_url = _load_photo(payload.photo_id)
        session = service.start_session(payload.source, photo_id, now)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ConversationStorageError, JsonStorageError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return StartConversationResponse(
        session_id=session.session_id,
        status=session.status,
        photo_id=session.photo_id,
        image_url=image_url,
        question=_speech_response(questions.initial_question()),
    )


@router.post(
    "/sessions/{session_id}/turns",
    response_model=TurnMetricResponse,
    summary="Recognize and reduce one user turn",
)
async def record_conversation_turn(
    session_id: str,
    request: Request,
    audio: AudioBody,
    turn_duration_seconds: TurnDuration,
    service: ConversationServiceDependency,
    recognizer: RecognizerDependency,
    questions: QuestionProviderDependency,
    now: CurrentTimeDependency,
) -> TurnMetricResponse:
    """Use ASR transiently, then persist metrics without text or audio."""

    content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0]
    if content_type not in {"audio/wav", "audio/x-wav"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="only WAV audio is supported",
        )
    if not audio:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="audio must not be empty",
        )
    try:
        recognition = await run_in_threadpool(
            recognizer.recognize,
            audio,
            content_type,
        )
        metric: ConversationTurnMetric = service.record_turn(
            session_id,
            recognition,
            turn_duration_seconds,
            now,
        )
        session = service.get_session(session_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConversationStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except RecognitionUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="speech recognition is temporarily unavailable",
        ) from exc
    except (ConversationStorageError, JsonStorageError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return TurnMetricResponse(
        turn_id=metric.turn_id,
        utterance_chars=metric.utterance_chars,
        turn_duration_seconds=metric.turn_duration_seconds,
        chars_per_second=metric.chars_per_second,
        no_response=metric.no_response,
        next_question=_speech_response(
            questions.follow_up_question(session.summary.user_turn_count)
        ),
    )


@router.post(
    "/sessions/{session_id}/complete",
    response_model=ConversationSummaryResponse,
    summary="Complete a conversation session",
)
async def complete_conversation(
    session_id: str,
    service: ConversationServiceDependency,
    now: CurrentTimeDependency,
) -> ConversationSummaryResponse:
    """Finalize a session and return its metrics-only summary."""

    try:
        return _summary_response(service.complete_session(session_id, now))
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConversationStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (ConversationStorageError, JsonStorageError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.get(
    "/sessions",
    response_model=list[ConversationSummaryResponse],
    summary="List conversation session summaries",
)
async def list_conversations(
    service: ConversationServiceDependency,
) -> list[ConversationSummaryResponse]:
    """Return metrics-only session history."""

    try:
        return [_summary_response(session) for session in service.list_sessions()]
    except (ConversationStorageError, JsonStorageError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
