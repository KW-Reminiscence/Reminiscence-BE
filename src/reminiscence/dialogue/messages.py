"""대화 메시지 타입.

특정 LLM 제공자에 묶이지 않도록 자체 타입을 둔다. OpenAI든 다른 제공자든
role/content 두 필드로 표현되므로, 엔진은 이 타입만 알면 된다. 제공자별
변환은 llm_client.py 안에서만 일어난다.
"""

from typing import Literal, TypedDict


class ChatMessage(TypedDict):
    """대화 이력 한 줄. system 프롬프트는 여기 넣지 않고 별도로 전달한다."""

    role: Literal["user", "assistant"]
    content: str
