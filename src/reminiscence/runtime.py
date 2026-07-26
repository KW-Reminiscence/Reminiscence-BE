"""Periodic backend jobs that keep the appliance useful without tablet polling."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

logger = logging.getLogger(__name__)


class RoutineTicker(Protocol):
    """Routine scheduler operation used by the background runtime."""

    def tick(self, now: datetime) -> object:
        """Advance due routine state transitions."""

        ...


class NotificationEvaluator(Protocol):
    """Notification operation used by the background runtime."""

    def evaluate_and_notify(self, evaluated_at: datetime) -> object:
        """Evaluate personal patterns and notify when required."""

        ...


def _positive_interval(environment_name: str, default: float) -> float:
    raw_value = os.environ.get(environment_name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{environment_name} must be a number") from exc
    if value <= 0:
        raise RuntimeError(f"{environment_name} must be positive")
    return value


class BackgroundRuntime:
    """Run routine and anomaly jobs independently until application shutdown."""

    def __init__(
        self,
        routine_scheduler: RoutineTicker,
        notification_coordinator: NotificationEvaluator,
        clock: Callable[[], datetime],
        *,
        routine_interval_seconds: float,
        evaluation_interval_seconds: float,
    ) -> None:
        if routine_interval_seconds <= 0 or evaluation_interval_seconds <= 0:
            raise ValueError("background intervals must be positive")
        self._routine_scheduler = routine_scheduler
        self._notification_coordinator = notification_coordinator
        self._clock = clock
        self._routine_interval_seconds = routine_interval_seconds
        self._evaluation_interval_seconds = evaluation_interval_seconds
        self._stop_event = asyncio.Event()
        self._tasks: tuple[asyncio.Task[None], ...] = ()

    def start(self) -> None:
        """Start both periodic jobs once."""

        if self._tasks:
            raise RuntimeError("background runtime is already started")
        self._tasks = (
            asyncio.create_task(
                self._run_periodically(
                    "routine tick",
                    self._routine_scheduler.tick,
                    self._routine_interval_seconds,
                )
            ),
            asyncio.create_task(
                self._run_periodically(
                    "anomaly notification evaluation",
                    self._notification_coordinator.evaluate_and_notify,
                    self._evaluation_interval_seconds,
                )
            ),
        )

    async def stop(self) -> None:
        """Stop both jobs and wait for clean task completion."""

        self._stop_event.set()
        if self._tasks:
            await asyncio.gather(*self._tasks)
        self._tasks = ()

    async def _run_periodically(
        self,
        job_name: str,
        job: Callable[[datetime], object],
        interval_seconds: float,
    ) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(job, self._clock())
            except Exception:
                logger.exception("background %s failed", job_name)
            await self._wait_or_stop(interval_seconds)

    async def _wait_or_stop(self, interval_seconds: float) -> None:
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=interval_seconds,
            )
        except TimeoutError:
            pass


def build_background_runtime(
    routine_scheduler: RoutineTicker,
    notification_coordinator: NotificationEvaluator,
    clock: Callable[[], datetime],
) -> BackgroundRuntime:
    """Build the runtime from validated environment intervals."""

    return BackgroundRuntime(
        routine_scheduler,
        notification_coordinator,
        clock,
        routine_interval_seconds=_positive_interval(
            "REMINISCENCE_ROUTINE_TICK_SECONDS",
            5.0,
        ),
        evaluation_interval_seconds=_positive_interval(
            "REMINISCENCE_EVALUATION_SECONDS",
            60.0,
        ),
    )
