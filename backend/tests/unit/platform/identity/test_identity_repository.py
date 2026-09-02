from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.identity.repository import SqlAlchemyUserRepository, _to_domain


def test_database_role_string_is_normalized_to_user_role() -> None:
    record = UserRecord(
        id=uuid4(),
        display_name="Owner",
        email="owner@example.com",
        normalized_email="owner@example.com",
        password_hash="hash",
        role="owner",
        is_active=True,
    )

    user = _to_domain(record)

    assert user.role is UserRole.OWNER


@pytest.mark.asyncio
async def test_owner_setup_lock_serializes_the_users_table() -> None:
    session = AsyncMock()
    repository = SqlAlchemyUserRepository(session)

    await repository.lock_owner_setup()

    statement = session.execute.await_args.args[0]
    assert str(statement) == "LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"
