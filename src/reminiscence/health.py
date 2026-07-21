"""Health check endpoint for infrastructure probes."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """A successful health check response."""

    status: Literal["ok"] = "ok"


@router.get("/health", response_model=HealthResponse, summary="Check service health")
async def get_health() -> HealthResponse:
    """Return a lightweight readiness response without external dependencies."""

    return HealthResponse()
