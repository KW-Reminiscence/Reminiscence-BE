"""Request-body limits enforced before FastAPI materializes payloads."""

from __future__ import annotations

import json
import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_CONVERSATION_TURN_PATH = re.compile(
    r"^/api/v1/conversations/sessions/[^/]+/turns$"
)


class _RequestBodyTooLarge(Exception):
    """Abort body consumption as soon as the configured limit is crossed."""


class ConversationAudioLimitMiddleware:
    """Limit tablet audio uploads before endpoint body parsing allocates them."""

    def __init__(self, app: ASGIApp, *, max_audio_bytes: int) -> None:
        if max_audio_bytes <= 0:
            raise ValueError("max_audio_bytes must be positive")
        self._app = app
        self._max_audio_bytes = max_audio_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_audio_turn_request(scope):
            await self._app(scope, receive, send)
            return

        content_length = self._content_length(scope)
        if content_length is None:
            await self._run_with_stream_limit(scope, receive, send)
            return
        if content_length < 0:
            await self._send_error(send, 400, "invalid Content-Length")
            return
        if content_length > self._max_audio_bytes:
            await self._send_error(
                send,
                413,
                f"audio must not exceed {self._max_audio_bytes} bytes",
            )
            return
        await self._run_with_stream_limit(scope, receive, send)

    @staticmethod
    def _is_audio_turn_request(scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and _CONVERSATION_TURN_PATH.fullmatch(scope.get("path", "")) is not None
        )

    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        values = [
            value
            for name, value in scope.get("headers", [])
            if name.lower() == b"content-length"
        ]
        if not values:
            return None
        if len(set(values)) != 1:
            return -1
        try:
            length = int(values[0].decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            return -1
        return length if length >= 0 else -1

    async def _run_with_stream_limit(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self._max_audio_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise RuntimeError(
                    "request body limit crossed after response started"
                ) from None
            await self._send_error(
                send,
                413,
                f"audio must not exceed {self._max_audio_bytes} bytes",
            )

    @staticmethod
    async def _send_error(send: Send, status_code: int, detail: str) -> None:
        body = json.dumps(
            {"detail": detail},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
