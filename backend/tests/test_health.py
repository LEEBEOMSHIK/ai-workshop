from fastapi.testclient import TestClient

from ai_workshop.main import app


def test_health_returns_ok() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
