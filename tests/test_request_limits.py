"""Streaming request-size enforcement tests."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
from starlette.types import Message, Receive, Scope, Send

from reminiscence.request_limits import ConversationAudioLimitMiddleware


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/conversations/sessions/session-1/turns",
        "/api/v1/demo/conversations/sessions/session-1/turns",
    ],
)
def test_chunked_audio_stops_at_limit_before_reaching_endpoint(path: str) -> None:
    endpoint_reached = False
    incoming: asyncio.Queue[Message] = asyncio.Queue()
    outgoing: list[Message] = []
    incoming.put_nowait(
        {
            "type": "http.request",
            "body": b"1234",
            "more_body": True,
        }
    )
    incoming.put_nowait(
        {
            "type": "http.request",
            "body": b"56",
            "more_body": False,
        }
    )

    async def endpoint(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope, send
        nonlocal endpoint_reached
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break
        endpoint_reached = True

    async def receive() -> Message:
        return await incoming.get()

    async def send(message: Message) -> None:
        outgoing.append(message)

    scope = cast(
        Scope,
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"transfer-encoding", b"chunked")],
        },
    )
    middleware = ConversationAudioLimitMiddleware(endpoint, max_audio_bytes=5)

    asyncio.run(middleware(scope, receive, send))

    assert endpoint_reached is False
    assert outgoing[0]["type"] == "http.response.start"
    assert outgoing[0]["status"] == 413


def test_non_audio_route_is_not_limited() -> None:
    endpoint_reached = False

    async def endpoint(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope, receive, send
        nonlocal endpoint_reached
        endpoint_reached = True

    async def receive() -> Message:
        return {"type": "http.request", "body": b"123456", "more_body": False}

    async def send(message: Message) -> None:
        del message

    scope = cast(
        Scope,
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/tts/synthesize",
            "headers": [(b"content-length", b"6")],
        },
    )
    middleware = ConversationAudioLimitMiddleware(endpoint, max_audio_bytes=5)

    asyncio.run(middleware(scope, receive, send))

    assert endpoint_reached is True
