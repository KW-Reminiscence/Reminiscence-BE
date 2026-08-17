"""ASGI application entry point for the Reminiscence API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from reminiscence.anomaly.api import router as anomaly_router
from reminiscence.asr.models import MAX_AUDIO_BYTES
from reminiscence.auth.api import router as auth_router
from reminiscence.conversation.api import demo_router as demo_conversation_router
from reminiscence.conversation.api import router as conversation_router
from reminiscence.health import router as health_router
from reminiscence.notification.api import (
    get_notification_coordinator,
)
from reminiscence.notification.api import (
    router as notification_router,
)
from reminiscence.request_limits import (
    ConversationAudioLimitMiddleware,
    RequestRateLimitMiddleware,
)
from reminiscence.routine.api import (
    get_current_time,
    get_routine_scheduler,
)
from reminiscence.routine.api import (
    router as routine_router,
)
from reminiscence.runtime import build_background_runtime
from reminiscence.runtime_config import data_directory, load_runtime_settings
from reminiscence.storage.instance_lock import SingleInstanceLock
from reminiscence.storage.migration import validate_data_directory
from reminiscence.tablet.api import router as tablet_router
from reminiscence.tts.api import router as tts_router


def parse_cors_origins(value: str | None) -> tuple[str, ...]:
    """Validate exact tablet web origins without enabling credential wildcards."""

    if value is None or not value.strip():
        return ()
    origins: list[str] = []
    for raw_origin in value.split(","):
        origin = raw_origin.strip()
        if not origin:
            continue
        if origin == "*":
            raise RuntimeError("REMINISCENCE_CORS_ORIGINS must not contain *")
        if origin == "null":
            normalized = origin
        else:
            parsed = urlsplit(origin)
            try:
                port = parsed.port
            except ValueError as exc:
                raise RuntimeError(
                    f"invalid REMINISCENCE_CORS_ORIGINS origin: {origin}"
                ) from exc
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or (port is not None and port == 0)
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise RuntimeError(
                    f"invalid REMINISCENCE_CORS_ORIGINS origin: {origin}"
                )
            normalized = f"{parsed.scheme}://{parsed.netloc}"
        if normalized not in origins:
            origins.append(normalized)
    return tuple(origins)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Start and stop periodic appliance jobs with the API process."""

    configured_data_directory = data_directory()
    with SingleInstanceLock(configured_data_directory) as instance_lock:
        validate_data_directory(configured_data_directory)
        runtime = build_background_runtime(
            get_routine_scheduler(),
            get_notification_coordinator(),
            get_current_time,
        )
        runtime.start()
        application.state.instance_lock = instance_lock
        application.state.background_runtime = runtime
        try:
            yield
        finally:
            await runtime.stop()
            del application.state.background_runtime
            del application.state.instance_lock


def create_app(cors_origins: tuple[str, ...] | None = None) -> FastAPI:
    """Build the API with an explicit tablet-origin allowlist."""

    application = FastAPI(
        title="Reminiscence API",
        version="0.1.0",
        lifespan=lifespan,
    )
    configured_origins = (
        load_runtime_settings().cors_origins
        if cors_origins is None
        else cors_origins
    )
    if configured_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(configured_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )
    application.add_middleware(
        ConversationAudioLimitMiddleware,
        max_audio_bytes=MAX_AUDIO_BYTES,
    )
    application.add_middleware(RequestRateLimitMiddleware)
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(tablet_router)
    application.include_router(routine_router)
    application.include_router(conversation_router)
    application.include_router(demo_conversation_router)
    application.include_router(anomaly_router)
    application.include_router(notification_router)
    application.include_router(tts_router)
    return application


app = create_app()
