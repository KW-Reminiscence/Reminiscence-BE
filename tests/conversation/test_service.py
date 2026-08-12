"""Conversation metrics and privacy retention tests."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from math import inf, nan
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from reminiscence.asr import RecognitionResult
from reminiscence.conversation import (
    ConversationNotFoundError,
    ConversationService,
    ConversationSource,
    ConversationStateError,
    JsonConversationStore,
)
from reminiscence.storage import JsonObjectStore

SEOUL = ZoneInfo("Asia/Seoul")


def now() -> datetime:
    return datetime(2026, 7, 27, 14, 0, tzinfo=SEOUL)


def recognition(transcript: str) -> RecognitionResult:
    return RecognitionResult(
        transcript=transcript,
        latency_seconds=0.25,
        attempts=1,
        http_status=200,
    )


def service_at(tmp_path: Path) -> tuple[ConversationService, Path]:
    path = tmp_path / "activity_metrics.json"
    identifiers = iter(["session-1", "turn-1", "turn-2", "turn-3"])
    return (
        ConversationService(
            JsonConversationStore(
                JsonObjectStore(path, missing_default={"conversation_sessions": []})
            ),
            id_factory=lambda: next(identifiers),
        ),
        path,
    )


def test_record_turn_persists_metrics_without_transcript(tmp_path: Path) -> None:
    service, path = service_at(tmp_path)
    session = service.start_session(
        ConversationSource.VOLUNTARY,
        "photo-1",
        now(),
    )

    metric = service.record_turn(
        session.session_id,
        recognition("비밀 가족 이야기"),
        4.0,
        now() + timedelta(seconds=5),
    )
    persisted = path.read_text(encoding="utf-8")

    assert metric.utterance_chars == 7
    assert metric.chars_per_second == 1.75
    assert "비밀 가족 이야기" not in persisted
    assert "transcript" not in persisted
    assert '"utterance_chars": 7' in persisted


def test_no_response_is_excluded_from_session_averages(tmp_path: Path) -> None:
    service, _ = service_at(tmp_path)
    session = service.start_session(ConversationSource.SCHEDULED, None, now())

    service.record_turn(
        session.session_id,
        recognition("   "),
        10.0,
        now() + timedelta(seconds=10),
    )
    service.record_turn(
        session.session_id,
        recognition("안녕 하세요"),
        2.0,
        now() + timedelta(seconds=20),
    )
    summary = service.get_session(session.session_id).summary

    assert summary.user_turn_count == 1
    assert summary.total_utterance_chars == 5
    assert summary.average_utterance_chars == 5.0
    assert summary.average_turn_duration_seconds == 2.0
    assert summary.no_response_count == 1


def test_zero_duration_has_no_chars_per_second(tmp_path: Path) -> None:
    service, _ = service_at(tmp_path)
    session = service.start_session(ConversationSource.VOLUNTARY, None, now())

    metric = service.record_turn(
        session.session_id,
        recognition("응답"),
        0,
        now(),
    )

    assert metric.utterance_chars == 2
    assert metric.chars_per_second is None


@pytest.mark.parametrize("duration", [-0.1, 300.1, nan, inf, -inf])
def test_invalid_duration_is_rejected(tmp_path: Path, duration: float) -> None:
    service, _ = service_at(tmp_path)
    session = service.start_session(ConversationSource.VOLUNTARY, None, now())

    with pytest.raises(ValueError, match="between 0 and 300"):
        service.record_turn(
            session.session_id,
            recognition("응답"),
            duration,
            now(),
        )


def test_turn_before_session_start_is_rejected(tmp_path: Path) -> None:
    service, _ = service_at(tmp_path)
    session = service.start_session(ConversationSource.VOLUNTARY, None, now())

    with pytest.raises(ValueError, match="before started_at"):
        service.record_turn(
            session.session_id,
            recognition("응답"),
            1,
            now() - timedelta(seconds=1),
        )


def test_concurrent_turns_are_both_persisted(tmp_path: Path) -> None:
    path = tmp_path / "activity_metrics.json"
    store = JsonObjectStore(
        path,
        missing_default={"conversation_sessions": []},
    )
    first_service = ConversationService(
        JsonConversationStore(store),
        id_factory=lambda: uuid4().hex,
    )
    second_service = ConversationService(
        JsonConversationStore(
            JsonObjectStore(
                path,
                missing_default={"conversation_sessions": []},
            )
        ),
        id_factory=lambda: uuid4().hex,
    )
    session = first_service.start_session(
        ConversationSource.VOLUNTARY,
        None,
        now(),
    )
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def record(service: ConversationService, transcript: str) -> None:
        try:
            barrier.wait()
            service.record_turn(
                session.session_id,
                recognition(transcript),
                1,
                now() + timedelta(seconds=1),
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [
        threading.Thread(target=record, args=(first_service, "첫 응답")),
        threading.Thread(target=record, args=(second_service, "둘째 응답")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    persisted = first_service.get_session(session.session_id)
    assert errors == []
    assert len(persisted.turns) == 2
    assert sum(turn.utterance_chars for turn in persisted.turns) == 7


def test_completed_session_rejects_more_turns(tmp_path: Path) -> None:
    service, _ = service_at(tmp_path)
    session = service.start_session(ConversationSource.VOLUNTARY, None, now())
    completed = service.complete_session(
        session.session_id,
        now() + timedelta(minutes=1),
    )

    with pytest.raises(ConversationStateError, match="COMPLETED"):
        service.record_turn(
            session.session_id,
            recognition("늦은 응답"),
            1,
            now() + timedelta(minutes=2),
        )

    assert completed.completed_at == now() + timedelta(minutes=1)


def test_complete_session_is_idempotent(tmp_path: Path) -> None:
    service, _ = service_at(tmp_path)
    session = service.start_session(ConversationSource.VOLUNTARY, None, now())
    first = service.complete_session(
        session.session_id,
        now() + timedelta(minutes=1),
    )

    repeated = service.complete_session(
        session.session_id,
        now() + timedelta(minutes=2),
    )

    assert repeated == first
    assert repeated.completed_at == now() + timedelta(minutes=1)


def test_duplicate_client_turn_id_returns_existing_metric(tmp_path: Path) -> None:
    service, _ = service_at(tmp_path)
    session = service.start_session(ConversationSource.VOLUNTARY, None, now())
    first = service.record_turn(
        session.session_id,
        recognition("첫 응답"),
        1,
        now() + timedelta(seconds=1),
        "client-turn-1",
    )

    repeated = service.record_turn(
        session.session_id,
        recognition("덮어쓰면 안 되는 응답"),
        5,
        now() + timedelta(seconds=2),
        "client-turn-1",
    )

    assert repeated == first
    assert service.get_session(session.session_id).turns == (first,)


def test_only_one_active_session_is_allowed(tmp_path: Path) -> None:
    service, _ = service_at(tmp_path)
    first = service.start_session(ConversationSource.VOLUNTARY, None, now())

    with pytest.raises(ConversationStateError, match="already exists"):
        service.start_session(
            ConversationSource.SCHEDULED,
            None,
            now() + timedelta(seconds=1),
        )

    assert service.list_sessions() == (first,)


def test_unknown_session_is_rejected(tmp_path: Path) -> None:
    service, _ = service_at(tmp_path)

    with pytest.raises(ConversationNotFoundError):
        service.get_session("missing")


def test_existing_routine_metrics_are_preserved(tmp_path: Path) -> None:
    service, path = service_at(tmp_path)
    path.write_text(
        json.dumps({"routine_executions": [{"execution_id": "kept"}]}),
        encoding="utf-8",
    )

    service.start_session(ConversationSource.VOLUNTARY, None, now())
    persisted = json.loads(path.read_text(encoding="utf-8"))

    assert persisted["routine_executions"] == [{"execution_id": "kept"}]
    assert len(persisted["conversation_sessions"]) == 1


def test_malformed_session_data_is_rejected(tmp_path: Path) -> None:
    service, path = service_at(tmp_path)
    path.write_text(
        json.dumps({"conversation_sessions": [{"session_id": "incomplete"}]}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="invalid conversation session"):
        service.list_sessions()


def test_semantically_invalid_completed_session_is_rejected(tmp_path: Path) -> None:
    service, path = service_at(tmp_path)
    path.write_text(
        json.dumps(
            {
                "conversation_sessions": [
                    {
                        "session_id": "session-1",
                        "source": "VOLUNTARY",
                        "photo_id": None,
                        "started_at": now().isoformat(),
                        "status": "COMPLETED",
                        "completed_at": None,
                        "turns": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="COMPLETED session requires completed_at"):
        service.list_sessions()


def test_nonfinite_persisted_metric_is_rejected(tmp_path: Path) -> None:
    service, path = service_at(tmp_path)
    path.write_text(
        json.dumps(
            {
                "conversation_sessions": [
                    {
                        "session_id": "session-1",
                        "source": "VOLUNTARY",
                        "photo_id": None,
                        "started_at": now().isoformat(),
                        "status": "ACTIVE",
                        "completed_at": None,
                        "turns": [
                            {
                                "turn_id": "turn-1",
                                "recorded_at": now().isoformat(),
                                "utterance_chars": 2,
                                "turn_duration_seconds": nan,
                                "chars_per_second": 2,
                                "no_response": False,
                                "asr_latency_seconds": 0.2,
                                "asr_attempts": 1,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="turn_duration_seconds must be finite"):
        service.list_sessions()
