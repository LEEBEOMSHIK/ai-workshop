from datetime import UTC, datetime, timedelta
from typing import Annotated, Protocol
from uuid import UUID, uuid4

import jwt
from fastapi import Depends
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.platform.identity.domain import User, normalize_email
from ai_workshop.platform.identity.repository import SqlAlchemyUserRepository, UserRepository
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password: str, password_hash: str) -> bool: ...


class Argon2PasswordHasher:
    def __init__(self) -> None:
        self._password_hash = PasswordHash.recommended()

    def hash(self, password: str) -> str:
        return self._password_hash.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        return self._password_hash.verify(password, password_hash)


class JwtTokenService:
    algorithm = "HS256"

    def __init__(self, settings: Settings) -> None:
        self.secret = settings.secret_key.get_secret_value()

    def create(self, user: User) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": str(user.id),
                "iat": now,
                "exp": now + timedelta(minutes=30),
                "jti": str(uuid4()),
            },
            self.secret,
            algorithm=self.algorithm,
        )

    def read_subject(self, token: str) -> UUID:
        try:
            payload = jwt.decode(token, self.secret, algorithms=[self.algorithm])
            return UUID(payload["sub"])
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise AppError("not_authenticated", "Authentication is required.", 401) from exc


class AuthService:
    def __init__(
        self,
        repository: UserRepository,
        password_hasher: PasswordHasher,
        tokens: JwtTokenService,
    ) -> None:
        self.repository = repository
        self.password_hasher = password_hasher
        self.tokens = tokens

    async def authenticate(self, email: str, password: str) -> tuple[User, str]:
        user = await self.repository.find_by_normalized_email(normalize_email(email))
        if user is None or not user.is_active:
            raise AppError("invalid_credentials", "Email or password is incorrect.", 401)
        if not self.password_hasher.verify(password, user.password_hash):
            raise AppError("invalid_credentials", "Email or password is incorrect.", 401)
        return user, self.tokens.create(user)

    async def current_user(self, token: str | None) -> User:
        if token is None:
            raise AppError("not_authenticated", "Authentication is required.", 401)
        user = await self.repository.find_by_id(self.tokens.read_subject(token))
        if user is None or not user.is_active:
            raise AppError("not_authenticated", "Authentication is required.", 401)
        return user


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthService:
    return AuthService(
        SqlAlchemyUserRepository(session),
        Argon2PasswordHasher(),
        JwtTokenService(settings),
    )
