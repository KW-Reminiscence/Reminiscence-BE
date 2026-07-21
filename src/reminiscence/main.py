"""ASGI application entry point for the Reminiscence API."""

from fastapi import FastAPI

from reminiscence.health import router as health_router

app = FastAPI(
    title="Reminiscence API",
    version="0.1.0",
)
app.include_router(health_router)
