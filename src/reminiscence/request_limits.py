"""Request-body limits enforced before FastAPI materializes payloads."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_CONVERSATION_TURN_PATH = re.compile(
    r"^/api/v1/(?:demo/)?conversations/sessions/[^/]+/turns$"
)


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    """One fixed-window request budget for a path pattern."""

    pattern: re.Pattern[str]
    maximum_requests: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.maximum_requests <= 0 or self.window_seconds <= 0:
            raise ValueError("rate limit values must be positive")


DEFAULT_RATE_LIMIT_RULES = (
    RateLimitRule(
        re.compile(r"^/api/v1/auth/(guardian/login|tablet/pair)$"),
        10,
        60,
    ),
    RateLimitRule(_CONVERSATION_TURN_PATH, 30, 60),
    RateLimitRule(re.compile(r"^/api/v1/demo/conversations/sessions$"), 10, 60),
    RateLimitRule(
        re.compile(r"^/api/v1/demo/conversations/sessions/[^/]+/complete$"),
        30,
        60,
    ),
    RateLimitRule(re.compile(r"^/api/v1/tts/speech$"), 60, 60),
    RateLimitRule(re.compile(r"^/api/v1/tts/demo-speech$"), 20, 60),
)
DEFAULT_RATE_LIMIT_MAXIMUM_KEYS = 10_000


class RequestRateLimitMiddleware:
    """Bound abuse-prone POST routes per effective client address."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        rules: tuple[RateLimitRule, ...] = DEFAULT_RATE_LIMIT_RULES,
        clock: Callable[[], float] = time.monotonic,
        maximum_keys: int = DEFAULT_RATE_LIMIT_MAXIMUM_KEYS,
    ) -> None:
        if maximum_keys <= 0:
            raise ValueError("maximum_keys must be positive")
        self._app = app
        self._rules = rules
        self._clock = clock
        self._maximum_keys = maximum_keys
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], tuple[float, int]] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        rule = self._rule(scope)
        if rule is None:
            await self._app(scope, receive, send)
            return
        client = scope.get("client")
        address = client[0] if client else "unknown"
        now = self._clock()
        key = (address, rule.pattern.pattern)
        with self._lock:
            self._prune_expired(now)
            if key not in self._windows and len(self._windows) >= self._maximum_keys:
                oldest_key = min(
                    self._windows,
                    key=lambda item: self._windows[item][0],
                )
                del self._windows[oldest_key]
            started_at, count = self._windows.get(key, (now, 0))
            if now - started_at >= rule.window_seconds:
                started_at, count = now, 0
            if count >= rule.maximum_requests:
                retry_after = max(1, int(rule.window_seconds - (now - started_at)))
                limited = True
            else:
                self._windows[key] = (started_at, count + 1)
                retry_after = 0
                limited = False
        if limited:
            await self._send_limited(send, retry_after)
            return
        await self._app(scope, receive, send)

    def _prune_expired(self, now: float) -> None:
        longest_window = max(
            (rule.window_seconds for rule in self._rules),
            default=0,
        )
        expired = [
            key
            for key, (started_at, _) in self._windows.items()
            if now - started_at >= longest_window
        ]
        for key in expired:
            del self._windows[key]

    def _rule(self, scope: Scope) -> RateLimitRule | None:
        if scope["type"] != "http" or scope.get("method") != "POST":
            return None
        path = scope.get("path", "")
        return next(
            (rule for rule in self._rules if rule.pattern.fullmatch(path)),
            None,
        )

    @staticmethod
    async def _send_limited(send: Send, retry_after: int) -> None:
        body = b'{"detail":"request rate limit exceeded"}'
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"retry-after", str(retry_after).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


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
