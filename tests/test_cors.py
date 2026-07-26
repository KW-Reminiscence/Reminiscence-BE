"""Tablet web origin allowlist tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reminiscence.main import create_app, parse_cors_origins


def test_configured_vercel_origin_receives_cors_header() -> None:
    client = TestClient(create_app(("https://tablet.example.vercel.app",)))

    response = client.get(
        "/health",
        headers={"Origin": "https://tablet.example.vercel.app"},
    )

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "https://tablet.example.vercel.app"
    )


def test_unconfigured_origin_does_not_receive_cors_header() -> None:
    client = TestClient(create_app(("https://tablet.example.vercel.app",)))

    response = client.get(
        "/health",
        headers={"Origin": "https://attacker.example"},
    )

    assert "access-control-allow-origin" not in response.headers


def test_local_file_origin_must_be_explicitly_allowed() -> None:
    client = TestClient(create_app(("null",)))

    response = client.get("/health", headers={"Origin": "null"})

    assert response.headers["access-control-allow-origin"] == "null"


def test_origins_are_trimmed_normalized_and_deduplicated() -> None:
    assert parse_cors_origins(
        " https://tablet.example/ ,http://192.168.0.10:3000,"
        "https://tablet.example "
    ) == (
        "https://tablet.example",
        "http://192.168.0.10:3000",
    )


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "ftp://tablet.example",
        "https://tablet.example/path",
        "https://user:password@tablet.example",
        "https://tablet.example:invalid",
    ],
)
def test_unsafe_or_malformed_origins_are_rejected(value: str) -> None:
    with pytest.raises(RuntimeError, match="REMINISCENCE_CORS_ORIGINS"):
        parse_cors_origins(value)
