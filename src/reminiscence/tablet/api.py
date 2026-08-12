"""Single polling surface for the tablet home priority flow."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from reminiscence.auth.dependencies import TabletSessionDependency
from reminiscence.conversation.api import (
    ConversationServiceDependency,
    ConversationSuggestionResponse,
    PhotoMemoryResponse,
    build_conversation_suggestion,
    load_configured_photos,
    photo_response,
)
from reminiscence.conversation.models import ConversationStatus
from reminiscence.conversation.storage import ConversationStorageError
from reminiscence.routine.api import (
    CurrentTimeDependency,
    RoutinePromptResponse,
    SchedulerDependency,
    build_current_routine_prompts,
)
from reminiscence.routine.storage import RoutineStorageError
from reminiscence.storage import JsonStorageError

router = APIRouter(prefix="/api/v1/tablet", tags=["tablet"])


class TabletStateResponse(BaseModel):
    """Everything needed to render the next tablet home state."""

    server_time: datetime
    active_routines: list[RoutinePromptResponse]
    conversation_suggestion: ConversationSuggestionResponse
    photos: list[PhotoMemoryResponse]
    active_conversation_session_id: str | None


@router.get(
    "/state",
    response_model=TabletStateResponse,
    summary="Get integrated tablet home state",
)
async def get_tablet_state(
    _: TabletSessionDependency,
    scheduler: SchedulerDependency,
    conversations: ConversationServiceDependency,
    now: CurrentTimeDependency,
) -> TabletStateResponse:
    """Advance due routines and return one coherent home payload."""

    try:
        sessions = conversations.list_sessions()
        active_session = next(
            (
                session
                for session in reversed(sessions)
                if session.status is ConversationStatus.ACTIVE
            ),
            None,
        )
        return TabletStateResponse(
            server_time=now,
            active_routines=build_current_routine_prompts(scheduler, now),
            conversation_suggestion=build_conversation_suggestion(
                conversations,
                now,
            ),
            photos=[photo_response(photo) for photo in load_configured_photos()],
            active_conversation_session_id=(
                active_session.session_id if active_session is not None else None
            ),
        )
    except (
        ConversationStorageError,
        RoutineStorageError,
        JsonStorageError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
