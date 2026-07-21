"""대화 세션 저장소.

액자가 프론트엔드로 구현되므로 세션 상태를 서버가 들고 있어야 한다.
브라우저는 세션 ID만 기억하고, 사진·음악·루틴 상태와 대화 이력은 여기 남는다.

메모리에만 둔다. 액자는 한 어르신이 쓰는 기기이고 시연 규모가 작아서
데이터베이스를 붙일 이유가 없다. 프로세스가 재시작되면 세션은 사라진다.
"""

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from reminiscence.dialogue.context import SessionContext
from reminiscence.dialogue.llm_client import DialogueLLM, ReplyStreamer
from reminiscence.dialogue.manager import DialogueManager

#: 동시에 들고 있을 세션 수. 넘으면 가장 오래 쓰이지 않은 것부터 버린다.
MAX_SESSIONS: Final[int] = 32


class SessionNotFound(LookupError):
    """존재하지 않거나 이미 정리된 세션."""


@dataclass
class Session:
    """세션 하나와 그것을 다루는 데 필요한 것들."""

    id: str
    ctx: SessionContext
    manager: DialogueManager
    created_at: datetime = field(default_factory=datetime.now)
    last_used_at: datetime = field(default_factory=datetime.now)

    lock: threading.Lock = field(default_factory=threading.Lock)
    """한 세션에 턴이 겹쳐 들어오면 이력이 엉킨다. 턴 단위로 잠근다."""


class SessionStore:
    """세션을 만들고 찾아준다. 스레드 안전하다.

    LLM 클라이언트는 세션마다 만들지 않고 하나를 공유한다. 커넥션 풀을
    재사용하는 편이 빠르고, anthropic 클라이언트는 스레드 안전하다.
    """

    def __init__(self, llm: ReplyStreamer | None = None) -> None:
        self._llm: ReplyStreamer = llm if llm is not None else DialogueLLM()
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._guard = threading.Lock()

    def create(self, ctx: SessionContext) -> Session:
        session = Session(
            id=uuid.uuid4().hex,
            ctx=ctx,
            manager=DialogueManager(ctx, self._llm),
        )
        with self._guard:
            self._sessions[session.id] = session
            while len(self._sessions) > MAX_SESSIONS:
                self._sessions.popitem(last=False)
        return session

    def get(self, session_id: str) -> Session:
        with self._guard:
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFound(session_id)
            session.last_used_at = datetime.now()
            self._sessions.move_to_end(session_id)
            return session

    def drop(self, session_id: str) -> None:
        with self._guard:
            self._sessions.pop(session_id, None)

    def __len__(self) -> int:
        with self._guard:
            return len(self._sessions)
