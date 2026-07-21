from fastapi.testclient import TestClient

from reminiscence.main import app

client = TestClient(app)


def test_health_returns_a_stable_success_response() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_allows_only_get_requests() -> None:
    response = client.post("/health")

    assert response.status_code == 405


def test_health_is_included_in_the_openapi_document() -> None:
    openapi_document = app.openapi()

    assert "/health" in openapi_document["paths"]
