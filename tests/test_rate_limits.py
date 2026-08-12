"""Application rate limits for credential, ASR and TTS routes."""

from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from reminiscence.request_limits import RateLimitRule, RequestRateLimitMiddleware


def test_post_budget_is_enforced_per_client_and_resets_after_window() -> None:
    now = [100.0]
    app = FastAPI()

    @app.post("/limited")
    async def limited() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(
        RequestRateLimitMiddleware,
        rules=(RateLimitRule(re.compile(r"^/limited$"), 2, 60),),
        clock=lambda: now[0],
    )
    client = TestClient(app)

    assert client.post("/limited").status_code == 200
    assert client.post("/limited").status_code == 200
    blocked = client.post("/limited")
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "60"
    assert blocked.headers["cache-control"] == "no-store"

    now[0] += 60
    assert client.post("/limited").status_code == 200


def test_get_and_unmatched_post_do_not_consume_budget() -> None:
    app = FastAPI()

    @app.api_route("/limited", methods=["GET", "POST"])
    async def limited() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(
        RequestRateLimitMiddleware,
        rules=(RateLimitRule(re.compile(r"^/other$"), 1, 60),),
    )
    client = TestClient(app)

    assert client.get("/limited").status_code == 200
    assert client.post("/limited").status_code == 200
    assert client.post("/limited").status_code == 200
