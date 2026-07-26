"""Integration coverage for concurrent activity metric writers."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Barrier
from zoneinfo import ZoneInfo

from reminiscence.conversation import JsonConversationStore
from reminiscence.conversation.models import (
    ConversationSession,
    ConversationSource,
    ConversationStatus,
)
from reminiscence.routine import RoutineState
from reminiscence.routine.models import RoutineExecution
from reminiscence.routine.storage import JsonRoutineStore
from reminiscence.storage import JsonObjectStore

SEOUL = ZoneInfo("Asia/Seoul")


def test_routine_and_conversation_writes_do_not_lose_each_other(
    tmp_path: Path,
) -> None:
    activity_path = tmp_path / "activity_metrics.json"
    routine_store = JsonRoutineStore(
        tmp_path / "configuration.json",
        activity_path,
    )
    conversation_store = JsonConversationStore(
        JsonObjectStore(activity_path, missing_default={})
    )
    barrier = Barrier(2)
    count = 30

    def write_routines() -> None:
        barrier.wait()
        for index in range(count):
            timestamp = datetime(2026, 7, 27, 9, index, tzinfo=SEOUL)
            routine_store.save_execution(
                RoutineExecution(
                    execution_id=f"routine-{index}",
                    routine_id="morning-medication",
                    scheduled_at=timestamp,
                    state=RoutineState.REMINDING,
                    reminder_count=0,
                    last_prompted_at=timestamp,
                )
            )

    def write_conversations() -> None:
        barrier.wait()
        for index in range(count):
            conversation_store.save_session(
                ConversationSession(
                    session_id=f"session-{index}",
                    source=ConversationSource.VOLUNTARY,
                    photo_id=None,
                    started_at=datetime(2026, 7, 27, 14, index, tzinfo=SEOUL),
                    status=ConversationStatus.ACTIVE,
                    turns=(),
                )
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(write_routines),
            executor.submit(write_conversations),
        ]
        for future in futures:
            future.result()

    persisted = json.loads(activity_path.read_text(encoding="utf-8"))
    assert len(persisted["routine_executions"]) == count
    assert len(persisted["conversation_sessions"]) == count
    assert list(tmp_path.glob("*.tmp")) == []
