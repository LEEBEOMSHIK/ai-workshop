from uuid import uuid4

from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.identity.repository import _to_domain


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
