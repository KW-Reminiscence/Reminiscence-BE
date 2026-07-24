"""회상 대화 HTTP API 검증.

LLM 스텁을 넣은 저장소로 의존성을 갈아끼워 API 키 없이 돈다.
"""

import json
from collections.abc import Generator, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from reminiscence.dialogue.api import get_store
from reminiscence.dialogue.messages import ChatMessage
from reminiscence.dialogue.store import SessionStore
from reminiscence.main import app


class StubLLM:
    """'|'로 구분한 문장을 순서대로 흘려보내는 가짜 LLM."""

    def __init__(self, reply: str) -> None:
        self.reply = reply

    def stream_reply(
        self, system: str, messages: list[ChatMessage]
    ) -> Generator[str, None, str]:
        for sentence in self.reply.split("|"):
            yield sentence.strip()
        return self.reply.replace("|", " ").strip()


@pytest.fixture
def client() -> Iterator[TestClient]:
    store = SessionStore(StubLLM("바다 앞에서 활짝 웃고 계시네요.|그때 기분이 어떠셨어요?"))
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def _lines(response: httpx.Response) -> list[dict[str, object]]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_creating_a_session_returns_its_state(client: TestClient) -> None:
    response = client.post(
        "/dialogue/sessions", json={"photo_meta": "1998년 제주도, 본인과 딸"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["session_id"]
    assert body["photo_meta"] == "1998년 제주도, 본인과 딸"
    assert body["turn_count"] == 0


def test_a_turn_streams_sentences_then_a_result(client: TestClient) -> None:
    session_id = client.post(
        "/dialogue/sessions", json={"photo_meta": "1998년 제주도, 본인과 딸"}
    ).json()["session_id"]

    response = client.post(
        f"/dialogue/sessions/{session_id}/turns", json={"utterance": "이거 뭐야"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")

    lines = _lines(response)
    assert [line["type"] for line in lines[:-1]] == ["sentence", "sentence"]
    assert lines[0]["text"] == "바다 앞에서 활짝 웃고 계시네요."

    result = lines[-1]
    assert result["type"] == "result"
    assert result["scenario"] == "S1"
    assert result["scenario_label"] == "개인 사진 회상"
    assert result["degraded"] is False


def test_the_frame_can_speak_first_without_an_utterance(client: TestClient) -> None:
    session_id = client.post(
        "/dialogue/sessions", json={"routine_type": "점심 복약"}
    ).json()["session_id"]

    response = client.post(
        f"/dialogue/sessions/{session_id}/turns", json={"scenario": "S4"}
    )

    assert response.status_code == 200
    assert _lines(response)[-1]["scenario"] == "S4"


def test_a_turn_needs_an_utterance_or_a_scenario(client: TestClient) -> None:
    session_id = client.post("/dialogue/sessions", json={}).json()["session_id"]

    response = client.post(f"/dialogue/sessions/{session_id}/turns", json={})

    assert response.status_code == 422


def test_updating_context_switches_the_scenario(client: TestClient) -> None:
    session_id = client.post(
        "/dialogue/sessions", json={"photo_meta": "가족사진"}
    ).json()["session_id"]

    patched = client.patch(
        f"/dialogue/sessions/{session_id}",
        json={"photo_meta": "1970년대 시대자료사진, 남대문 시장"},
    )

    assert patched.status_code == 200
    assert patched.json()["photo_meta"] == "1970년대 시대자료사진, 남대문 시장"

    response = client.post(
        f"/dialogue/sessions/{session_id}/turns", json={"utterance": "저런 데 자주 갔지"}
    )
    assert _lines(response)[-1]["scenario"] == "S2"


def test_a_sensitive_utterance_is_reported_to_the_caller(client: TestClient) -> None:
    session_id = client.post(
        "/dialogue/sessions", json={"photo_meta": "가족사진"}
    ).json()["session_id"]

    response = client.post(
        f"/dialogue/sessions/{session_id}/turns", json={"utterance": "우리 남편은 언제 와?"}
    )

    result = _lines(response)[-1]
    assert result["scenario"] == "S6"
    assert result["guardian_flagged"] is True


def test_the_summary_reports_usability_metrics(client: TestClient) -> None:
    session_id = client.post(
        "/dialogue/sessions", json={"photo_meta": "가족사진"}
    ).json()["session_id"]
    client.post(f"/dialogue/sessions/{session_id}/turns", json={"utterance": "이거 뭐야"})

    summary = client.get(f"/dialogue/sessions/{session_id}/summary").json()

    assert summary["turn_count"] == 1
    assert summary["scenario_breakdown"] == {"S1": 1}
    assert summary["violation_count"] == 0


def test_an_unknown_session_returns_404(client: TestClient) -> None:
    assert client.get("/dialogue/sessions/nope").status_code == 404
    assert (
        client.post("/dialogue/sessions/nope/turns", json={"utterance": "안녕"}).status_code
        == 404
    )


def test_ending_a_session_removes_it(client: TestClient) -> None:
    session_id = client.post("/dialogue/sessions", json={}).json()["session_id"]

    assert client.delete(f"/dialogue/sessions/{session_id}").status_code == 204
    assert client.get(f"/dialogue/sessions/{session_id}").status_code == 404
