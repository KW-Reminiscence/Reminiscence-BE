"""ASGI application entry point for the Reminiscence API."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from reminiscence.dialogue.api import router as dialogue_router
from reminiscence.health import router as health_router

app = FastAPI(
    title="Reminiscence API",
    version="0.1.0",
)

# 액자를 브라우저로 구현하므로 프론트엔드는 다른 오리진에서 뜬다.
# 아직 인증이 없어 기본값은 전체 허용이고, 배포할 때 DIALOGUE_CORS_ORIGINS에
# 실제 오리진을 넣어 좁힌다.
_cors_origins = [
    origin.strip()
    for origin in os.getenv("DIALOGUE_CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(dialogue_router)
