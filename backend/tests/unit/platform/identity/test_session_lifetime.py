from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import Response
from pydantic import ValidationError

from ai_workshop.config import Settings
from ai_workshop.platform.identity.api import set_session_cookie
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.identity.service import JwtTokenService
from ai_workshop.shared.errors import AppError


@pytest.mark.parametrize("minutes", [30, 480, 1440])
def test_token_and_cookie_share_configured_lifetime(minutes: int) -> None:
    settings = Settings(_env_file=None, secret_key="x" * 32, session_lifetime_minutes=minutes)
    user = User.create_owner(
        display_name="Synthetic", email="test@example.com", password_hash="unused"
    )
    service = JwtTokenService(settings)
    token = service.create(user)
    claims = jwt.decode(token, "x" * 32, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == minutes * 60
    response = Response()
    set_session_cookie(response, token, settings)
    assert f"Max-Age={minutes * 60}" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert service.read_subject(token) == user.id


@pytest.mark.parametrize("minutes", [0, -1, 1441, 1.5])
def test_session_lifetime_rejects_invalid_values(minutes: float) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, secret_key="x" * 32, session_lifetime_minutes=minutes)


def test_longer_setting_does_not_accept_expired_tokens() -> None:
    settings = Settings(_env_file=None, secret_key="x" * 32, session_lifetime_minutes=480)
    token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "exp": datetime.now(UTC) - timedelta(seconds=1),
        },
        "x" * 32,
        algorithm="HS256",
    )
    with pytest.raises(AppError) as error:
        JwtTokenService(settings).read_subject(token)
    assert error.value.code == "not_authenticated"
