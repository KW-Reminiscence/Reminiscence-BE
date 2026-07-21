from fastapi.testclient import TestClient

from reminiscence.main import app


def test_openapi_document_describes_the_application() -> None:
    response = TestClient(app).get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Reminiscence API"
