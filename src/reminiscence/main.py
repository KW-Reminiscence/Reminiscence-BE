"""ASGI application entry point for the Reminiscence API."""

from fastapi import FastAPI

from reminiscence.anomaly.api import router as anomaly_router
from reminiscence.conversation.api import router as conversation_router
from reminiscence.health import router as health_router

app = FastAPI(
    title="Reminiscence API",
    version="0.1.0",
)
app.include_router(health_router)
app.include_router(conversation_router)
app.include_router(anomaly_router)
