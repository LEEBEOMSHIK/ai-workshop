from fastapi.testclient import TestClient

from ai_workshop.main import create_app


def test_not_found_uses_public_error_contract() -> None:
    response = TestClient(create_app()).get("/api/v1/does-not-exist")

    assert response.status_code == 404
    correlation_id = response.headers["x-correlation-id"]
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "The requested resource was not found.",
            "correlation_id": correlation_id,
        }
    }
