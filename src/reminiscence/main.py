"""ASGI application entry point for the Reminiscence API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from reminiscence.anomaly.api import router as anomaly_router
from reminiscence.conversation.api import router as conversation_router
from reminiscence.health import router as health_router
from reminiscence.notification.api import (
    get_notification_coordinator,
)
from reminiscence.notification.api import (
    router as notification_router,
)
from reminiscence.routine.api import (
    get_current_time,
    get_routine_scheduler,
)
from reminiscence.routine.api import (
    router as routine_router,
)
from reminiscence.runtime import build_background_runtime


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Start and stop periodic appliance jobs with the API process."""

    runtime = build_background_runtime(
        get_routine_scheduler(),
        get_notification_coordinator(),
        get_current_time,
    )
    runtime.start()
    try:
        yield
    finally:
        await runtime.stop()


app = FastAPI(title="Reminiscence API", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
app.include_router(routine_router)
app.include_router(conversation_router)
app.include_router(anomaly_router)
app.include_router(notification_router)
