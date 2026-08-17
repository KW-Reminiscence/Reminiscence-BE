"""Tablet-facing API for reminiscence conversations, ASR, and TTS text."""

from __future__ import annotations

from datetime import datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from reminiscence.asr import (
    CodexLbRecognizer,
    CodexLbRecognizerConfig,
    RecognitionUnavailableError,
    SpeechRecognizer,
)
from reminiscence.auth.dependencies import (
    GuardianSessionDependency,
    SameOriginDependency,
    TabletSessionDependency,
)
from reminiscence.auth.secrets import load_auth_secrets
from reminiscence.conversation.context import TransientConversationContextStore
from reminiscence.conversation.llm_questions import (
    CodexLbFollowUpQuestionProvider,
    CodexLbQuestionConfig,
    QuestionGenerationUnavailableError,
)
from reminiscence.conversation.models import (
    ConversationCompletionReason,
    ConversationSession,
    ConversationSource,
    ConversationStatus,
    ConversationSummary,
    ConversationTurnMetric,
)
from reminiscence.conversation.photos import (
    PhotoConfigurationError,
    PhotoMemory,
    parse_photos,
)
from reminiscence.conversation.questions import (
    QuestionProvider,
    SpeechText,
    TemplateOpeningQuestionProvider,
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
from reminiscence.runtime_config import (
    data_directory as runtime_data_directory,
)
from reminiscence.runtime_config import load_runtime_settings, server_timezone
from reminiscence.storage import JsonStorageError, open_versioned_store

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


class PhotoMemoryResponse(BaseModel):
    """Photo and family-provided context rendered by the tablet."""

    id: str
    image_base64: str
    image_media_type: str
    location: str
    people: list[str]
    event: str
    description: str


class StartConversationResponse(BaseModel):
    """Session context and the first safe question."""

    session_id: str
    status: ConversationStatus
    photo: PhotoMemoryResponse
    question: SpeechTextResponse


class TurnMetricResponse(BaseModel):
    """Non-sensitive metrics produced from one audio turn."""

    turn_id: str
    utterance_chars: int
    turn_duration_seconds: float
    chars_per_second: float | None
    no_response: bool
    speech_detected: bool | None
    next_question: SpeechTextResponse


class ConversationSummaryResponse(BaseModel):
    """Persisted session aggregate without conversation text."""

    session_id: str
    status: ConversationStatus
    started_at: datetime
    completed_at: datetime | None
    completion_reason: ConversationCompletionReason | None
    user_turn_count: int
    total_utterance_chars: int
    average_utterance_chars: float | None
    average_turn_duration_seconds: float | None
    no_response_count: int


class CompleteConversationRequest(BaseModel):
    """Tablet-observed reason for finalizing a conversation."""

    reason: ConversationCompletionReason = ConversationCompletionReason.USER_FINISHED


def _data_directory() -> Path:
    return runtime_data_directory()


def _server_timezone() -> ZoneInfo:
    return server_timezone()


@lru_cache(maxsize=1)
def get_conversation_service() -> ConversationService:
    """Build the process-wide conversation service."""

    return ConversationService(
        JsonConversationStore(
            open_versioned_store(
                _data_directory() / "activity_metrics.json",
                missing_default={"conversation_sessions": []},
            )
        )
    )


@lru_cache(maxsize=1)
def get_conversation_context_store() -> TransientConversationContextStore:
    """Build process-local session context that is never written to storage."""

    return TransientConversationContextStore()


@lru_cache(maxsize=1)
def get_speech_recognizer() -> SpeechRecognizer:
    """Build the configured ASR provider without persisting its credential."""

    try:
        runtime = load_runtime_settings().codex_lb
        return CodexLbRecognizer(
            CodexLbRecognizerConfig(
                api_key=load_auth_secrets().codex_lb_api_key,
                base_url=runtime.base_url,
                connect_timeout_seconds=runtime.connect_timeout_seconds,
                read_timeout_seconds=runtime.transcription_read_timeout_seconds,
            )
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="speech recognition is not configured",
        ) from exc


@lru_cache(maxsize=1)
def get_question_provider() -> QuestionProvider:
    """Build a fixed opening with photo-aware codex-lb follow-up questions."""

    try:
        runtime = load_runtime_settings().codex_lb
        return TemplateOpeningQuestionProvider(
            CodexLbFollowUpQuestionProvider(
                CodexLbQuestionConfig(
                    api_key=load_auth_secrets().codex_lb_api_key,
                    base_url=runtime.base_url,
                    model=runtime.response_model,
                    connect_timeout_seconds=runtime.connect_timeout_seconds,
                    read_timeout_seconds=runtime.response_read_timeout_seconds,
                )
            )
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="question generation is not configured",
        ) from exc


def get_current_time() -> datetime:
    """Return trusted server time."""

    return datetime.now(tz=_server_timezone())


def _load_photo(photo_id: str | None) -> PhotoMemory:
    photos = load_configured_photos()
    if photo_id is None:
        return photos[0]
    selected = next(
        (photo for photo in photos if photo.photo_id == photo_id),
        None,
    )
    if selected is None:
        raise ConversationNotFoundError(f"photo not found: {photo_id}")
    return selected


def load_configured_photos() -> tuple[PhotoMemory, ...]:
    """Load the strictly parsed family photo configuration."""

    root = open_versioned_store(
        _data_directory() / "configuration.json",
        missing_default={"photos": []},
        read_only=True,
    ).read()
    try:
        photos = parse_photos(root.get("photos", []))
    except PhotoConfigurationError as exc:
        raise ConversationStorageError(str(exc)) from exc
    if not photos:
        raise ConversationStorageError("at least one photo must be configured")
    return photos


def _load_conversation_suggestion_time() -> time:
    root = open_versioned_store(
        _data_directory() / "configuration.json",
        missing_default={},
        read_only=True,
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


def photo_response(photo: PhotoMemory) -> PhotoMemoryResponse:
    return PhotoMemoryResponse(
        id=photo.photo_id,
        image_base64=photo.image_base64,
        image_media_type=photo.image_media_type,
        location=photo.location,
        people=list(photo.people),
        event=photo.event,
        description=photo.description,
    )


def _summary_response(session: ConversationSession) -> ConversationSummaryResponse:
    summary: ConversationSummary = session.summary
    return ConversationSummaryResponse(
        session_id=session.session_id,
        status=session.status,
        started_at=session.started_at,
        completed_at=session.completed_at,
        completion_reason=session.completion_reason,
        user_turn_count=summary.user_turn_count,
        total_utterance_chars=summary.total_utterance_chars,
        average_utterance_chars=summary.average_utterance_chars,
        average_turn_duration_seconds=summary.average_turn_duration_seconds,
        no_response_count=summary.no_response_count,
    )


def build_conversation_suggestion(
    service: ConversationService,
    now: datetime,
) -> ConversationSuggestionResponse:
    """Build the shared daily suggestion response for tablet surfaces."""

    outcome = ConversationSuggestionPolicy(
        _load_conversation_suggestion_time()
    ).evaluate(now, service.list_sessions())
    text = "오늘 사진을 보며 이야기 나눠 보실래요?"
    return ConversationSuggestionResponse(
        suggested=outcome.suggested,
        scheduled_time=outcome.scheduled_time,
        display_text=text if outcome.suggested else None,
        spoken_text=text if outcome.suggested else None,
        start_label="이야기 시작하기" if outcome.suggested else None,
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
ConversationContextDependency = Annotated[
    TransientConversationContextStore,
    Depends(get_conversation_context_store),
]
CurrentTimeDependency = Annotated[datetime, Depends(get_current_time)]
AudioBody = Annotated[bytes, Body(media_type="audio/wav")]
TurnDuration = Annotated[float, Query(ge=0, le=300)]
HasSpeech = Annotated[bool, Query()]
ClientTurnId = Annotated[
    str,
    Header(
        alias="X-Turn-ID",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    ),
]


@router.get(
    "/suggestion",
    response_model=ConversationSuggestionResponse,
    summary="Get today's scheduled conversation suggestion",
)
async def get_conversation_suggestion(
    _: TabletSessionDependency,
    service: ConversationServiceDependency,
    now: CurrentTimeDependency,
) -> ConversationSuggestionResponse:
    """Offer a daily session without treating a dismissed offer as an anomaly."""

    try:
        return build_conversation_suggestion(service, now)
    except (ConversationStorageError, JsonStorageError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post(
    "/sessions",
    response_model=StartConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a reminiscence conversation",
)
async def start_conversation(
    payload: StartConversationRequest,
    _: TabletSessionDependency,
    __: SameOriginDependency,
    service: ConversationServiceDependency,
    questions: QuestionProviderDependency,
    now: CurrentTimeDependency,
) -> StartConversationResponse:
    """Start a scheduled or voluntary session with a synthesizable question."""

    try:
        photo = _load_photo(payload.photo_id)
        question = await run_in_threadpool(questions.initial_question, photo)
        session = service.start_session(payload.source, photo.photo_id, now)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConversationStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except QuestionGenerationUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="question generation is temporarily unavailable",
        ) from exc
    except (ConversationStorageError, JsonStorageError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return StartConversationResponse(
        session_id=session.session_id,
        status=session.status,
        photo=photo_response(photo),
        question=_speech_response(question),
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
    has_speech: HasSpeech,
    turn_id: ClientTurnId,
    _: TabletSessionDependency,
    __: SameOriginDependency,
    service: ConversationServiceDependency,
    recognizer: RecognizerDependency,
    questions: QuestionProviderDependency,
    context: ConversationContextDependency,
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
        existing = service.get_turn(session_id, turn_id)
        if existing is not None:
            return TurnMetricResponse(
                turn_id=existing.turn_id,
                utterance_chars=existing.utterance_chars,
                turn_duration_seconds=existing.turn_duration_seconds,
                chars_per_second=existing.chars_per_second,
                no_response=existing.no_response,
                speech_detected=existing.speech_detected,
                next_question=SpeechTextResponse(
                    display_text="이어서 이야기해 주세요.",
                    spoken_text="이어서 이야기해 주세요.",
                ),
            )
        active_session = service.require_active_session(session_id)
        photo = _load_photo(active_session.photo_id)
        recognition = await run_in_threadpool(
            recognizer.recognize,
            audio,
            content_type,
        )
        transcript = recognition.transcript if has_speech else ""
        next_question = await run_in_threadpool(
            questions.follow_up_question,
            photo,
            transcript,
            active_session.summary.user_turn_count + 1,
            context.history(session_id),
        )
        metric: ConversationTurnMetric = service.record_turn(
            session_id,
            recognition,
            turn_duration_seconds,
            now,
            turn_id,
            has_speech,
        )
        context.remember(session_id, transcript)
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
    except QuestionGenerationUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="question generation is temporarily unavailable",
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
        speech_detected=metric.speech_detected,
        next_question=_speech_response(next_question),
    )


@router.post(
    "/sessions/{session_id}/complete",
    response_model=ConversationSummaryResponse,
    summary="Complete a conversation session",
)
async def complete_conversation(
    session_id: str,
    _: TabletSessionDependency,
    __: SameOriginDependency,
    service: ConversationServiceDependency,
    context: ConversationContextDependency,
    now: CurrentTimeDependency,
    payload: CompleteConversationRequest | None = None,
) -> ConversationSummaryResponse:
    """Finalize a session and return its metrics-only summary."""

    try:
        reason = (
            payload.reason
            if payload is not None
            else ConversationCompletionReason.USER_FINISHED
        )
        summary = service.complete_session(session_id, now, reason)
        context.clear(session_id)
        return _summary_response(summary)
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
    _: GuardianSessionDependency,
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
