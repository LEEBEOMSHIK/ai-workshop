from ai_workshop.platform.identity.domain import UserRole


def test_user_roles_include_non_administrator_members() -> None:
    assert [role.value for role in UserRole] == ["owner", "member"]
