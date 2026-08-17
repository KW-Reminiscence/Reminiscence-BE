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
from reminiscence.runtime_config import load_runtime_settings
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

DEMO_SPEECH_TEXTS = frozenset(
    {
        "가족사진을 보니 어떤 날이 떠오르세요?",
        "그날 가장 기억에 남는 이야기를 들려주세요.",
        "어르신~ 아침 드실 시간이예요~, 아침 꼭 챙겨드시고 여기 버튼 눌러주세요",
        "어르신~ 이따가 아침약 드실 시간에 다시 알려드릴게요~",
        "어르신~ 아침약 드실 시간이예요~, 귀찮으시더라도 꼭 챙겨 드시고 버튼을 눌러주세요!",
        "어르신~ 이따가 점심 드실 시간에 다시 알려드릴게요~",
        "어르신~ 점심 드실 시간이예요~, 점심 꼭 챙겨드시고 여기 버튼 눌러주세요",
        "어르신~ 이따가 점심약 드실 시간에 다시 알려드릴게요~",
        "어르신~ 점심약 드실 시간이예요~, 귀찮으시더라도 꼭 챙겨 드시고 버튼을 눌러주세요!",
        "어르신~ 이따가 저녁 드실 시간에 다시 알려드릴게요~",
    }
)


class SpeechSynthesisRequest(BaseModel):
    """Visible spoken_text to synthesize with the configured local voice."""

    text: SpeechText


@lru_cache(maxsize=1)
def _build_speech_synthesizer() -> SpeechSynthesizer | None:
    try:
        settings = load_runtime_settings().supertonic
        return SupertonicSynthesizer(
            SupertonicConfig(
                model_dir=settings.model_dir,
                auto_download=settings.auto_download,
                voice=settings.voice,
                language=settings.language,
                total_steps=settings.total_steps,
                speed=settings.speed,
                max_text_chars=settings.max_text_chars,
                intra_op_num_threads=settings.intra_op_num_threads,
                inter_op_num_threads=settings.inter_op_num_threads,
            )
        )
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


async def _synthesize_response(
    payload: SpeechSynthesisRequest,
    synthesizer: SpeechSynthesizer,
) -> Response:
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

    return await _synthesize_response(payload, synthesizer)


@router.post(
    "/demo-speech",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "content": {"audio/wav": {}},
            "description": "Supertonic 3 PCM WAV audio for an allowlisted demo prompt",
        }
    },
    summary="Synthesize an allowlisted public demo prompt",
)
async def synthesize_demo_speech(
    payload: SpeechSynthesisRequest,
    _: SameOriginDependency,
    synthesizer: SynthesizerDependency,
) -> Response:
    """Use the production voice engine without exposing arbitrary public TTS."""

    if payload.text not in DEMO_SPEECH_TEXTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="speech text is not available in the public demo",
        )
    return await _synthesize_response(payload, synthesizer)
