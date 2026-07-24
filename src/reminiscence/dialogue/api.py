"""회상 대화 HTTP API.

액자는 브라우저로 구현된다. 음성 인식(ASR)과 음성 합성(TTS)은 프론트엔드가
Web Speech API로 처리하고, 이 API는 그 사이에서 대화 흐름만 담당한다::

    브라우저 마이크 -> ASR -> POST /dialogue/sessions/{id}/turns
                                      |
                                 (문장 스트림)
                                      v
                        브라우저 speechSynthesis -> 스피커

응답은 NDJSON 스트림이다. 문장이 완성되는 즉시 한 줄씩 내보내므로,
프론트는 받는 대로 speechSynthesis에 넣으면 된다. 전체 응답을 기다리지
않으니 어르신이 체감하는 침묵이 짧아진다.

EventSource(SSE)를 쓰지 않은 이유는 두 가지다. EventSource는 GET만 되고,
발화를 쿼리 파라미터에 실으면 nginx 접근 로그에 어르신의 발화가 그대로
남는다. 치매 케어 기기에서 그건 받아들일 수 없다.
"""

import json
from collections.abc import Generator, Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from reminiscence.dialogue.context import SessionContext
from reminiscence.dialogue.manager import TurnResult
from reminiscence.dialogue.scenarios import LABELS, Scenario
from reminiscence.dialogue.store import Session, SessionNotFound, SessionStore

router = APIRouter(prefix="/dialogue", tags=["dialogue"])

_store = SessionStore()


def get_store() -> SessionStore:
    """저장소 의존성. 테스트에서 교체한다."""
    return _store


StoreDep = Annotated[SessionStore, Depends(get_store)]


# ---------------------------------------------------------------------------
# 스키마
# ---------------------------------------------------------------------------


class ContextFields(BaseModel):
    """액자가 지금 보여주고 있는 상태."""

    photo_meta: str | None = Field(
        default=None,
        description="표시 중인 사진 설명. 예: 1998년 제주도, 본인과 딸, 여름",
        max_length=500,
    )
    music_meta: str | None = Field(
        default=None, description="재생 중인 음악. 예: 동백아가씨 (1964)", max_length=200
    )
    routine_type: str | None = Field(
        default=None, description="루틴 종류. 예: 점심 복약", max_length=100
    )


class CreateSessionRequest(ContextFields):
    device_name: str = Field(default="하늘이", description="기기 호칭", max_length=20)


class UpdateSessionRequest(ContextFields):
    routine_pending: bool | None = Field(
        default=None, description="루틴 알림이 아직 미이행 상태인가"
    )


class SessionState(BaseModel):
    """세션 현재 상태."""

    session_id: str
    device_name: str
    photo_meta: str | None
    music_meta: str | None
    routine_type: str | None
    routine_pending: bool
    affect_state: str
    turn_count: int
    guardian_flag_count: int


class GuardianFlagOut(BaseModel):
    kind: str
    detail: str
    at: str


class SessionSummary(BaseModel):
    """설계서 5장 사용성 테스트 체크리스트에 대응하는 요약."""

    session_id: str
    turn_count: int
    violation_count: int
    scenario_breakdown: dict[str, int]
    guardian_flags: list[GuardianFlagOut]


class TurnRequest(BaseModel):
    """한 턴 요청.

    ``utterance``가 있으면 어르신이 말을 건 것이고, 없으면 액자가 먼저 말을
    거는 턴이다. 후자는 ``scenario``로 무엇 때문에 말을 거는지 알려줘야 한다.
    """

    utterance: str | None = Field(default=None, max_length=500)
    scenario: Scenario | None = Field(
        default=None, description="기기 주도 턴일 때의 시나리오. 예: S4"
    )


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.post(
    "/sessions",
    response_model=SessionState,
    status_code=status.HTTP_201_CREATED,
    summary="Start a dialogue session",
)
def create_session(request: CreateSessionRequest, store: StoreDep) -> SessionState:
    ctx = SessionContext(
        device_name=request.device_name,
        photo_meta=request.photo_meta,
        music_meta=request.music_meta,
        routine_type=request.routine_type,
        routine_pending=request.routine_type is not None,
    )
    return _state(store.create(ctx))


@router.get(
    "/sessions/{session_id}",
    response_model=SessionState,
    summary="Read the current session state",
)
def read_session(session_id: str, store: StoreDep) -> SessionState:
    return _state(_lookup(store, session_id))


@router.patch(
    "/sessions/{session_id}",
    response_model=SessionState,
    summary="Update what the frame is showing",
)
def update_session(
    session_id: str, request: UpdateSessionRequest, store: StoreDep
) -> SessionState:
    session = _lookup(store, session_id)
    changed = request.model_dump(exclude_unset=True)

    for name in ("photo_meta", "music_meta", "routine_type"):
        if name in changed:
            setattr(session.ctx, name, changed[name])

    if "routine_pending" in changed:
        session.ctx.routine_pending = bool(changed["routine_pending"])
    elif "routine_type" in changed:
        # 루틴을 새로 걸면 미이행 상태로 시작하는 것이 자연스럽다.
        session.ctx.routine_pending = changed["routine_type"] is not None

    return _state(session)


@router.get(
    "/sessions/{session_id}/summary",
    response_model=SessionSummary,
    summary="Read usability-test metrics for the session",
)
def read_summary(session_id: str, store: StoreDep) -> SessionSummary:
    session = _lookup(store, session_id)
    replies = [t for t in session.ctx.history if t.role == "assistant"]

    breakdown: dict[str, int] = {}
    for turn in replies:
        if turn.scenario is not None:
            breakdown[turn.scenario] = breakdown.get(turn.scenario, 0) + 1

    return SessionSummary(
        session_id=session.id,
        turn_count=len(replies),
        violation_count=sum(len(t.violations) for t in replies),
        scenario_breakdown=breakdown,
        guardian_flags=[
            GuardianFlagOut(kind=f.kind, detail=f.detail, at=f.at.isoformat())
            for f in session.ctx.guardian_flags
        ],
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End a dialogue session",
)
def end_session(session_id: str, store: StoreDep) -> None:
    _lookup(store, session_id)
    store.drop(session_id)


@router.post(
    "/sessions/{session_id}/turns",
    summary="Run one dialogue turn and stream the reply",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"application/x-ndjson": {}},
            "description": (
                "문장이 완성되는 대로 한 줄씩 내보낸다. "
                '{"type":"sentence","text":...} 이후 마지막에 '
                '{"type":"result",...} 한 줄이 온다.'
            ),
        }
    },
)
def run_turn(
    session_id: str, request: TurnRequest, store: StoreDep
) -> StreamingResponse:
    session = _lookup(store, session_id)

    utterance = (request.utterance or "").strip()
    if not utterance and request.scenario is None:
        # starlette 버전에 따라 상수 이름이 갈려서 숫자를 그대로 쓴다.
        raise HTTPException(
            status_code=422,
            detail="utterance 또는 scenario 중 하나는 있어야 합니다.",
        )

    return StreamingResponse(
        _stream_turn(session, utterance, request.scenario),
        media_type="application/x-ndjson",
        # 프록시가 스트림을 모아서 한 번에 보내면 문장 단위 전송이 무의미해진다.
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# 내부
# ---------------------------------------------------------------------------


def _stream_turn(
    session: Session, utterance: str, scenario: Scenario | None
) -> Iterator[str]:
    """한 턴을 돌리며 NDJSON 줄을 내보낸다."""
    # 한 세션에 턴이 겹치면 대화 이력이 엉킨다. 턴 단위로 잠근다.
    with session.lock:
        if utterance:
            stream = session.manager.stream_turn(utterance)
        else:
            assert scenario is not None  # 호출 측에서 이미 검증했다
            stream = session.manager.stream_initiate(scenario)

        yield from _pump(stream)


def _pump(stream: Generator[str, None, TurnResult]) -> Iterator[str]:
    while True:
        try:
            sentence = next(stream)
        except StopIteration as stop:
            result: TurnResult = stop.value
            yield _line(_result_payload(result))
            return
        except Exception as error:  # noqa: BLE001 - 프론트를 매달아두지 않는다
            # 여기까지 온 예외는 버그다. 스트림을 조용히 끊으면 프론트가
            # 응답을 기다리며 멈추므로, 오류를 알리고 정상 종료한다.
            stream.close()
            yield _line({"type": "error", "detail": type(error).__name__})
            return
        yield _line({"type": "sentence", "text": sentence})


def _result_payload(result: TurnResult) -> dict[str, object]:
    return {
        "type": "result",
        "scenario": result.scenario.value,
        "scenario_label": LABELS[result.scenario],
        "phase": result.phase,
        "reply": result.reply,
        "violations": result.violations,
        "guardian_flagged": result.guardian_flagged,
        "degraded": result.degraded,
    }


def _line(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _lookup(store: SessionStore, session_id: str) -> Session:
    try:
        return store.get(session_id)
    except SessionNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="세션을 찾을 수 없습니다. 새로 시작해 주세요.",
        ) from None


def _state(session: Session) -> SessionState:
    ctx = session.ctx
    return SessionState(
        session_id=session.id,
        device_name=ctx.device_name,
        photo_meta=ctx.photo_meta,
        music_meta=ctx.music_meta,
        routine_type=ctx.routine_type,
        routine_pending=ctx.routine_pending,
        affect_state=ctx.affect_state,
        turn_count=len([t for t in ctx.history if t.role == "assistant"]),
        guardian_flag_count=len(ctx.guardian_flags),
    )
