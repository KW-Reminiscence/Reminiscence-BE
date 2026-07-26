"""Background runtime behavior and edge cases."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from reminiscence.runtime import BackgroundRuntime, build_background_runtime

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 7, 27, 9, 0, tzinfo=SEOUL)


class Recorder:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.calls: list[datetime] = []
        self.fail_once = fail_once

    def _record(self, now: datetime) -> None:
        self.calls.append(now)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("temporary failure")

    def tick(self, now: datetime) -> None:
        self._record(now)

    def evaluate_and_notify(self, evaluated_at: datetime) -> None:
        self._record(evaluated_at)


async def run_until(
    condition: Callable[[], bool],
    *,
    timeout_seconds: float = 1,
) -> None:
    async with asyncio.timeout(timeout_seconds):
        while not condition():
            await asyncio.sleep(0)


def test_runtime_runs_both_jobs_and_stops_cleanly() -> None:
    routine = Recorder()
    notification = Recorder()

    async def scenario() -> None:
        runtime = BackgroundRuntime(
            routine,
            notification,
            lambda: NOW,
            routine_interval_seconds=0.01,
            evaluation_interval_seconds=0.01,
        )
        runtime.start()
        await run_until(lambda: len(routine.calls) >= 2 and len(notification.calls) >= 2)
        await runtime.stop()
        counts_after_stop = (len(routine.calls), len(notification.calls))
        await asyncio.sleep(0.02)
        assert (len(routine.calls), len(notification.calls)) == counts_after_stop

    asyncio.run(scenario())


def test_one_job_failure_does_not_stop_other_iterations() -> None:
    routine = Recorder(fail_once=True)
    notification = Recorder()

    async def scenario() -> None:
        runtime = BackgroundRuntime(
            routine,
            notification,
            lambda: NOW,
            routine_interval_seconds=0.01,
            evaluation_interval_seconds=0.01,
        )
        runtime.start()
        await run_until(lambda: len(routine.calls) >= 2 and len(notification.calls) >= 2)
        await runtime.stop()

    asyncio.run(scenario())
    assert len(routine.calls) >= 2
    assert len(notification.calls) >= 2


def test_start_twice_is_rejected() -> None:
    async def scenario() -> None:
        recorder = Recorder()
        runtime = BackgroundRuntime(
            recorder,
            recorder,
            lambda: NOW,
            routine_interval_seconds=1,
            evaluation_interval_seconds=1,
        )
        runtime.start()
        with pytest.raises(RuntimeError, match="already started"):
            runtime.start()
        await runtime.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("environment_name", "value"),
    [
        ("REMINISCENCE_ROUTINE_TICK_SECONDS", "0"),
        ("REMINISCENCE_ROUTINE_TICK_SECONDS", "-1"),
        ("REMINISCENCE_EVALUATION_SECONDS", "not-a-number"),
    ],
)
def test_invalid_environment_intervals_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    value: str,
) -> None:
    monkeypatch.setenv(environment_name, value)
    recorder = Recorder()

    with pytest.raises(RuntimeError, match=environment_name):
        build_background_runtime(recorder, recorder, lambda: NOW)
