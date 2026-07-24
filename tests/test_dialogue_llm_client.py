"""문장 분리 검증.

TTS로 넘어가는 단위를 정하는 부분이라, 여기가 틀리면 액자가 한 문장을
여러 번에 나눠 읽는다. OpenAI 클라이언트를 스텁으로 갈아끼워 API 호출 없이
스트리밍 처리만 돌린다.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from reminiscence.dialogue.llm_client import DialogueLLM
from reminiscence.dialogue.messages import ChatMessage


@dataclass
class _Delta:
    content: str | None


@dataclass
class _Choice:
    delta: _Delta


@dataclass
class _Chunk:
    choices: list[_Choice]


class _FakeCompletions:
    def __init__(self, deltas: list[str]) -> None:
        self._deltas = deltas

    def create(self, **kwargs: object) -> Iterator[_Chunk]:
        return iter(_Chunk([_Choice(_Delta(d))]) for d in self._deltas)


class _FakeChat:
    def __init__(self, deltas: list[str]) -> None:
        self.completions = _FakeCompletions(deltas)


class _FakeClient:
    """OpenAI 클라이언트에서 chat.completions.create만 흉내낸다."""

    def __init__(self, deltas: list[str]) -> None:
        self.chat = _FakeChat(deltas)


def _pump(deltas: list[str]) -> tuple[list[str], str]:
    """토큰 조각들을 흘려보내고 (문장 목록, 전체 텍스트)를 돌려준다."""
    llm = DialogueLLM(client=_FakeClient(deltas))  # type: ignore[arg-type]
    messages: list[ChatMessage] = [{"role": "user", "content": "이거 뭐야"}]
    stream = llm.stream_reply("시스템 프롬프트", messages)

    sentences: list[str] = []
    while True:
        try:
            sentences.append(next(stream))
        except StopIteration as stop:
            full: str = stop.value
            return sentences, full


def test_a_sentence_is_emitted_once_complete() -> None:
    sentences, full = _pump(["바다 앞에서 ", "활짝 웃고 ", "계시네요. ", "좋으셨겠어요."])

    assert sentences == ["바다 앞에서 활짝 웃고 계시네요.", "좋으셨겠어요."]
    assert full == "바다 앞에서 활짝 웃고 계시네요. 좋으셨겠어요."


def test_a_noun_ending_in_a_verb_ending_is_not_a_boundary() -> None:
    # "바다", "생각", "저요" 같이 종결어미와 같은 글자로 끝나는 말이 흔하다
    sentences, _ = _pump(["바다 앞에서 웃고 계시네요."])

    assert sentences == ["바다 앞에서 웃고 계시네요."]


def test_a_question_ends_a_sentence() -> None:
    sentences, _ = _pump(["그때 기분이 어떠셨어요?", " 참 좋았겠어요."])

    assert sentences == ["그때 기분이 어떠셨어요?", "참 좋았겠어요."]


def test_a_trailing_fragment_without_punctuation_is_still_emitted() -> None:
    sentences, full = _pump(["좋네요. ", "그때가 생각나시나 봐요"])

    assert sentences == ["좋네요.", "그때가 생각나시나 봐요"]
    assert full == "좋네요. 그때가 생각나시나 봐요"


def test_empty_deltas_are_skipped() -> None:
    # OpenAI 스트림은 role만 담긴 빈 델타로 시작하곤 한다
    sentences, full = _pump(["", "좋네요.", ""])

    assert sentences == ["좋네요."]
    assert full == "좋네요."
