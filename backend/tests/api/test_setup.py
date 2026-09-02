from fastapi.testclient import TestClient

from ai_workshop.config import Settings, get_settings
from ai_workshop.main import create_app
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.setup.service import get_system_setup_service


class StubSetupService:
    def __init__(self, *, required: bool = True) -> None:
        self.required = required
        self.received: dict[str, str] | None = None

    async def setup_required(self) -> bool:
        return self.required

    async def create_owner(self, **values: str) -> tuple[User, str]:
        self.received = values
        return (
            User.create_owner(
                display_name=values["display_name"],
                email=values["email"],
                password_hash="hash",
            ),
            "setup-session-token",
        )


def setup_client(service: StubSetupService) -> TestClient:
    settings = Settings(_env_file=None, environment="local", secret_key="x" * 32)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_system_setup_service] = lambda: service
    return TestClient(app)


def test_setup_status_is_public() -> None:
    with setup_client(StubSetupService(required=True)) as client:
        response = client.get("/api/v1/setup/status")

    assert response.status_code == 200
    assert response.json() == {"setup_required": True}


def test_owner_setup_creates_session_and_returns_owner() -> None:
    service = StubSetupService()
    with setup_client(service) as client:
        response = client.post(
            "/api/v1/setup/owner",
            json={
                "display_name": "Workshop Owner",
                "email": "owner@example.com",
                "password": "correct-password",
                "password_confirmation": "correct-password",
            },
        )

    assert response.status_code == 201
    assert response.json()["display_name"] == "Workshop Owner"
    assert response.json()["role"] == "owner"
    assert service.received == {
        "display_name": "Workshop Owner",
        "email": "owner@example.com",
        "password": "correct-password",
        "password_confirmation": "correct-password",
    }
    cookie = response.headers["set-cookie"]
    assert "ai_workshop_session=setup-session-token" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie


def test_owner_setup_validates_password_length() -> None:
    with setup_client(StubSetupService()) as client:
        response = client.post(
            "/api/v1/setup/owner",
            json={
                "display_name": "Workshop Owner",
                "email": "owner@example.com",
                "password": "short",
                "password_confirmation": "short",
            },
        )

    assert response.status_code == 422
