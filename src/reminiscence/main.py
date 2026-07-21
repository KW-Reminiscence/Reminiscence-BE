"""ASGI application entry point for the Reminiscence API."""

from fastapi import FastAPI

app = FastAPI(
    title="Reminiscence API",
    version="0.1.0",
)
