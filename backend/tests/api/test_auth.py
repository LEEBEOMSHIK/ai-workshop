from dataclasses import replace
from uuid import UUID

from fastapi.testclient import TestClient

from ai_workshop.config import Settings, get_settings
from ai_workshop.main import create_app
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.identity.repository import UserRepository
from ai_workshop.platform.identity.service import (
    Argon2PasswordHasher,
    AuthService,
    JwtTokenService,
    get_auth_service,
)


class MemoryUserRepository(UserRepository):
    def __init__(self, user: User) -> None:
        self.user = user

    async def find_by_normalized_email(self, normalized_email: str) -> User | None:
        return self.user if self.user.normalized_email == normalized_email else None

    async def find_by_id(self, user_id: UUID) -> User | None:
        return self.user if self.user.id == user_id else None

    async def owner_exists(self) -> bool:
        return True

    async def add(self, user: User) -> User:
        self.user = replace(user)
        return self.user


def auth_client() -> TestClient:
    hasher = Argon2PasswordHasher()
    user = User.create_owner(
        display_name="LEE BEOMSHIK",
        email="bumcity135@naver.com",
        password_hash=hasher.hash("correct-password"),
    )
    settings = Settings(
        _env_file=None,
        environment="test",
        secret_key="x" * 32,
    )
    repository = MemoryUserRepository(user)
    service = AuthService(repository, hasher, JwtTokenService(settings))
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_auth_service] = lambda: service
    return TestClient(app)


def test_login_sets_http_only_cookie_and_me_returns_owner() -> None:
    with auth_client() as client:
        assert client.get("/api/v1/auth/me").status_code == 401

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "BUMCITY135@NAVER.COM", "password": "correct-password"},
        )

        assert response.status_code == 200
        assert response.json()["display_name"] == "LEE BEOMSHIK"
        assert response.json()["role"] == "owner"
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert client.get("/api/v1/auth/me").status_code == 200


def test_logout_clears_session_cookie() -> None:
    with auth_client() as client:
        client.post(
            "/api/v1/auth/login",
            json={"email": "bumcity135@naver.com", "password": "correct-password"},
        )

        response = client.post("/api/v1/auth/logout")

        assert response.status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
