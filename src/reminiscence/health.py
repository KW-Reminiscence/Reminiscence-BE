"""Infrastructure liveness and appliance dependency readiness checks."""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from reminiscence.runtime_config import data_directory
from reminiscence.storage.migration import validate_data_directory
from reminiscence.tts.api import get_speech_synthesizer

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """A successful process liveness response."""

    status: Literal["ok"] = "ok"


class ReadinessResponse(HealthResponse):
    """Successful checks for every local runtime dependency."""

    checks: dict[str, Literal["ok"]]


class ReadinessError(RuntimeError):
    """Named readiness checks that are not currently usable."""

    def __init__(self, failed_checks: tuple[str, ...]) -> None:
        super().__init__("appliance is not ready")
        self.failed_checks = failed_checks


class AtomicWriteProbe:
    """Periodically verify a durable replace without wearing storage per request."""

    def __init__(self, *, cache_seconds: float = 30.0) -> None:
        if cache_seconds < 0:
            raise ValueError("cache_seconds must not be negative")
        self._cache_seconds = cache_seconds
        self._last_success: dict[Path, float] = {}
        self._lock = threading.Lock()

    def check(self, data_directory: Path) -> None:
        """Write, replace, sync, and remove a hidden probe file."""

        resolved_directory = data_directory.resolve()
        with self._lock:
            checked_at = monotonic()
            last_success = self._last_success.get(resolved_directory)
            if (
                last_success is not None
                and checked_at - last_success < self._cache_seconds
            ):
                return
            descriptor, temporary_name = tempfile.mkstemp(
                dir=resolved_directory,
                prefix=".readiness.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            target_path = resolved_directory / ".readiness-probe"
            try:
                with os.fdopen(descriptor, "wb") as temporary_file:
                    temporary_file.write(b'{"status":"ok"}\n')
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
                os.replace(temporary_path, target_path)
                self._fsync_directory(resolved_directory)
                target_path.unlink()
                self._fsync_directory(resolved_directory)
            finally:
                temporary_path.unlink(missing_ok=True)
                target_path.unlink(missing_ok=True)
            self._last_success[resolved_directory] = checked_at

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class ReadinessChecker:
    """Validate durable data, model initialization, and live process owners."""

    def __init__(
        self,
        data_directory: Path,
        *,
        atomic_write_probe: AtomicWriteProbe,
        tts_probe: Callable[[], object],
    ) -> None:
        self._data_directory = data_directory
        self._atomic_write_probe = atomic_write_probe
        self._tts_probe = tts_probe

    def check(self, application: object) -> dict[str, Literal["ok"]]:
        """Return named successes or fail closed with non-sensitive names."""

        state = getattr(application, "state", None)
        instance_lock = getattr(state, "instance_lock", None)
        background_runtime = getattr(state, "background_runtime", None)
        failed = []
        if instance_lock is None or not instance_lock.acquired:
            failed.append("instance_lock")
        if background_runtime is None or not background_runtime.is_running:
            failed.append("background_runtime")
        if failed:
            raise ReadinessError(tuple(failed))

        checks: dict[str, Literal["ok"]] = {
            "instance_lock": "ok",
            "background_runtime": "ok",
        }
        for name, probe in (
            ("json_documents", lambda: validate_data_directory(self._data_directory)),
            ("atomic_write", lambda: self._atomic_write_probe.check(self._data_directory)),
            ("tts_model", self._tts_probe),
        ):
            try:
                probe()
            except Exception:
                failed.append(name)
            else:
                checks[name] = "ok"
        if failed:
            raise ReadinessError(tuple(failed))
        return checks


_ATOMIC_WRITE_PROBE = AtomicWriteProbe()


def get_readiness_checker() -> ReadinessChecker:
    """Build a checker for the current process configuration."""

    return ReadinessChecker(
        data_directory(),
        atomic_write_probe=_ATOMIC_WRITE_PROBE,
        tts_probe=get_speech_synthesizer,
    )


ReadinessCheckerDependency = Annotated[
    ReadinessChecker,
    Depends(get_readiness_checker),
]


@router.get(
    "/api/health/live",
    response_model=HealthResponse,
    summary="Check process liveness",
)
async def get_liveness() -> HealthResponse:
    """Return without touching models, JSON, or background jobs."""

    return HealthResponse()


@router.get(
    "/api/health/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Not ready"}},
    summary="Check appliance readiness",
)
async def get_readiness(
    request: Request,
    checker: ReadinessCheckerDependency,
) -> ReadinessResponse:
    """Check all local dependencies used to serve tablet traffic."""

    try:
        checks = await run_in_threadpool(checker.check, request.app)
    except ReadinessError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "not_ready",
                "failed_checks": list(exc.failed_checks),
            },
        ) from exc
    return ReadinessResponse(checks=checks)


@router.get(
    "/health",
    response_model=HealthResponse,
    deprecated=True,
    summary="Check process liveness (legacy)",
)
async def get_legacy_health() -> HealthResponse:
    """Keep the original probe path compatible during rollout."""

    return HealthResponse()
