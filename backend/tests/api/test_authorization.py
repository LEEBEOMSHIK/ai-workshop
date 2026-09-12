from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ai_workshop.authorization_composition import get_authorization_service
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.authorization import (
    Capability,
    TechnologyDefinition,
    TechnologyRegistry,
)
from ai_workshop.platform.identity.authorization_repository import (
    AuthorityAuditEntry,
    AuthorityUser,
)
from ai_workshop.platform.identity.authorization_service import AuthorizationService
from ai_workshop.platform.identity.domain import User, UserRole


class ApiAuthorizationRepository:
    def __init__(self, users: list[AuthorityUser]) -> None:
        self.users = {user.id: user for user in users}
        self.audits = [
            AuthorityAuditEntry(
                id=7,
                actor_id=users[0].id,
                target_user_id=users[-1].id,
                event_type="technology_grant_changed",
                technology_key="rag",
                before={"revision": 0},
                after={"revision": 1},
                created_at=datetime(2026, 9, 9, tzinfo=UTC),
            )
        ]

    async def get_authority(self, user_id: UUID) -> AuthorityUser | None:
        return deepcopy(self.users.get(user_id))

    async def list_authorities(self, cursor: UUID | None, limit: int) -> list[AuthorityUser]:
        users = sorted(self.users.values(), key=lambda user: user.id.int)
        if cursor is not None:
            users = [user for user in users if user.id.int > cursor.int]
        return deepcopy(users[:limit])

    async def lock_authorization_state(self) -> None:
        return None

    async def lock_users(self, user_ids: tuple[UUID, ...]) -> None:
        return None

    async def count_active_masters(self) -> int:
        return sum(user.role is UserRole.OWNER and user.is_active for user in self.users.values())

    async def replace_grant(
        self, user_id: UUID, technology_key: str, capabilities: frozenset[Capability]
    ) -> None:
        target = self.users[user_id]
        grants = dict(target.grants)
        if capabilities:
            grants[technology_key] = capabilities
        else:
            grants.pop(technology_key, None)
        self.users[user_id] = replace(target, grants=grants)

    async def clear_grants(self, user_id: UUID) -> None:
        self.users[user_id] = replace(self.users[user_id], grants={})

    async def set_status(self, user_id: UUID, is_active: bool) -> None:
        self.users[user_id] = replace(self.users[user_id], is_active=is_active)

    async def set_role(self, user_id: UUID, role: UserRole) -> None:
        self.users[user_id] = replace(self.users[user_id], role=role)

    async def increment_revision(self, user_id: UUID) -> int:
        revision = self.users[user_id].revision + 1
        self.users[user_id] = replace(self.users[user_id], revision=revision)
        return revision

    async def append_audit(self, entry: AuthorityAuditEntry) -> None:
        self.audits.append(replace(entry, id=len(self.audits) + 8, created_at=datetime.now(UTC)))

    async def list_audit(
        self, target_user_id: UUID, cursor: int | None, limit: int
    ) -> list[AuthorityAuditEntry]:
        items = [item for item in self.audits if item.target_user_id == target_user_id]
        if cursor is not None:
            items = [item for item in items if item.id is not None and item.id < cursor]
        return sorted(items, key=lambda item: item.id or 0, reverse=True)[:limit]


def make_user(
    role: UserRole,
    *,
    is_active: bool = True,
    grants: dict[str, frozenset[Capability]] | None = None,
) -> tuple[User, AuthorityUser]:
    identifier = uuid4()
    domain = User(
        id=identifier,
        display_name=role.value.title(),
        email=f"{role.value}-{identifier.hex[:6]}@example.test",
        normalized_email=f"{role.value}-{identifier.hex[:6]}@example.test",
        password_hash="hash",
        role=role,
        is_active=is_active,
    )
    authority = AuthorityUser(
        id=identifier,
        display_name=domain.display_name,
        email=domain.email,
        role=role,
        is_active=is_active,
        revision=0,
        grants=grants or {},
    )
    return domain, authority


def authorization_client(
    *,
    as_member: bool = False,
    inactive_member_with_grant: bool = False,
) -> tuple[TestClient, AuthorityUser]:
    owner, owner_authority = make_user(UserRole.OWNER)
    member, member_authority = make_user(
        UserRole.MEMBER,
        is_active=not inactive_member_with_grant,
        grants=(
            {"rag": frozenset({Capability.VIEW, Capability.EXECUTE})}
            if inactive_member_with_grant
            else None
        ),
    )
    repository = ApiAuthorizationRepository([owner_authority, member_authority])
    service = AuthorizationService(
        repository,
        TechnologyRegistry((TechnologyDefinition(key="rag", label="RAG"),)),
    )
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: member if as_member else owner
    app.dependency_overrides[get_authorization_service] = lambda: service
    return TestClient(app), member_authority


def test_access_returns_effective_permissions_with_private_no_store() -> None:
    client, _ = authorization_client()

    with client:
        response = client.get("/api/v1/auth/access")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "is_master": True,
        "revision": 0,
        "technologies": [
            {
                "key": "rag",
                "label": "RAG",
                "capabilities": ["view", "configure", "execute"],
                "delegation_enabled": False,
            }
        ],
    }


def test_master_directory_and_audit_contracts_are_bounded() -> None:
    client, member = authorization_client()

    with client:
        technologies = client.get("/api/v1/admin/access/technologies")
        users = client.get("/api/v1/admin/access/users", params={"limit": 1})
        detail = client.get(f"/api/v1/admin/access/users/{member.id}")
        audit = client.get(f"/api/v1/admin/access/users/{member.id}/audit")

    assert technologies.status_code == 200
    assert technologies.json() == [{"key": "rag", "label": "RAG", "delegation_enabled": False}]
    assert users.status_code == 200
    assert len(users.json()["items"]) == 1
    assert users.json()["next_cursor"] is not None
    assert detail.status_code == 200
    assert detail.json()["id"] == str(member.id)
    assert detail.json()["email"] == member.email
    assert audit.status_code == 200
    assert audit.json()["items"][0]["id"] == 7


def test_non_master_cannot_use_master_directory() -> None:
    client, _ = authorization_client(as_member=True)

    with client:
        response = client.get("/api/v1/admin/access/users")

    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"


def test_master_detail_exposes_inactive_members_configured_grants() -> None:
    client, member = authorization_client(inactive_member_with_grant=True)

    with client:
        response = client.get(f"/api/v1/admin/access/users/{member.id}")

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert response.json()["technologies"][0]["capabilities"] == ["view", "execute"]


@pytest.mark.parametrize("expected_revision", [True, "0", 0.0, -1, None])
def test_mutations_reject_coercive_or_invalid_revisions(expected_revision: object) -> None:
    client, member = authorization_client()
    body: dict[str, object] = {
        "expected_revision": expected_revision,
        "capabilities": ["view"],
    }

    with client:
        response = client.put(
            f"/api/v1/admin/access/users/{member.id}/technologies/rag",
            json=body,
        )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"expected_revision": 0, "capabilities": ["configure"]},
        {"expected_revision": 0, "capabilities": ["view", "view"]},
        {"expected_revision": 0, "capabilities": ["view"], "unexpected": True},
        {"capabilities": ["view"]},
    ],
)
def test_grant_body_rejects_dependency_duplicates_and_extra_fields(
    body: dict[str, object],
) -> None:
    client, member = authorization_client()

    with client:
        response = client.put(
            f"/api/v1/admin/access/users/{member.id}/technologies/rag",
            json=body,
        )

    assert response.status_code == 422


def test_valid_grant_status_and_role_mutations_return_updated_authority() -> None:
    client, member = authorization_client()

    with client:
        grant = client.put(
            f"/api/v1/admin/access/users/{member.id}/technologies/rag",
            json={"expected_revision": 0, "capabilities": ["view", "execute"]},
        )
        status = client.patch(
            f"/api/v1/admin/access/users/{member.id}/status",
            json={"expected_revision": 1, "is_active": False},
        )
        role = client.patch(
            f"/api/v1/admin/access/users/{member.id}/role",
            json={"expected_revision": 2, "role": "owner"},
        )

    assert grant.status_code == 200
    assert grant.json()["revision"] == 1
    assert grant.json()["technologies"][0]["capabilities"] == ["view", "execute"]
    assert status.status_code == 200
    assert status.json()["revision"] == 2
    assert status.json()["is_active"] is False
    assert role.status_code == 200
    assert role.json()["revision"] == 3
    assert role.json()["role"] == "owner"
