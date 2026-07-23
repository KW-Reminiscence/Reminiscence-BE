"""ASGI application entry point for the Reminiscence API."""

from fastapi import FastAPI

from reminiscence.health import router as health_router
from reminiscence.notification.api import router as guardian_alert_router

app = FastAPI(
    title="Reminiscence API",
    version="0.1.0",
)
app.include_router(health_router)
app.include_router(guardian_alert_router)
