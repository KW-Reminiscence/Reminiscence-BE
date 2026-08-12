"""Tablet-facing API for Raspberry Pi Supertonic 3 audio."""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, StringConstraints
from starlette.concurrency import run_in_threadpool

from reminiscence.auth.dependencies import SameOriginDependency, TabletSessionDependency
from reminiscence.tts.models import (
    SpeechSynthesisUnavailableError,
    SpeechSynthesizer,
)
from reminiscence.tts.supertonic import (
    DEFAULT_MAX_TEXT_CHARS,
    SupertonicConfig,
    SupertonicSynthesizer,
)

router = APIRouter(prefix="/api/v1/tts", tags=["tts"])
logger = logging.getLogger(__name__)
_INITIALIZATION_LOCK = threading.Lock()

SpeechText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=DEFAULT_MAX_TEXT_CHARS,
    ),
]


class SpeechSynthesisRequest(BaseModel):
    """Visible spoken_text to synthesize with the configured local voice."""

    text: SpeechText


@lru_cache(maxsize=1)
def _build_speech_synthesizer() -> SpeechSynthesizer | None:
    try:
        return SupertonicSynthesizer(SupertonicConfig.from_environment())
    except (RuntimeError, ValueError, SpeechSynthesisUnavailableError) as exc:
        logger.error("failed to initialize Supertonic 3: %s", exc)
        return None


def get_speech_synthesizer() -> SpeechSynthesizer:
    """Load Supertonic once, including one cached failure per process."""

    with _INITIALIZATION_LOCK:
        synthesizer = _build_speech_synthesizer()
    if synthesizer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="speech synthesis is not configured",
        )
    return synthesizer


SynthesizerDependency = Annotated[
    SpeechSynthesizer,
    Depends(get_speech_synthesizer),
]


@router.post(
    "/speech",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "content": {"audio/wav": {}},
            "description": "Supertonic 3 PCM WAV audio",
        }
    },
    summary="Synthesize Korean speech with local Supertonic 3",
)
async def synthesize_speech(
    payload: SpeechSynthesisRequest,
    _: TabletSessionDependency,
    __: SameOriginDependency,
    synthesizer: SynthesizerDependency,
) -> Response:
    """Return a non-persisted WAV that the tablet can play immediately."""

    try:
        result = await run_in_threadpool(
            synthesizer.synthesize,
            payload.text,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except SpeechSynthesisUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="speech synthesis is temporarily unavailable",
        ) from exc
    return Response(
        content=result.audio,
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="speech.wav"',
            "X-Audio-Duration-Seconds": str(result.duration_seconds),
            "X-Audio-Sample-Rate": str(result.sample_rate),
            "X-TTS-Engine": result.engine,
        },
    )
