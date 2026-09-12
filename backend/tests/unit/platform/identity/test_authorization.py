from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

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
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.shared.errors import AppError


class MemoryAuthorizationRepository:
    def __init__(self, users: Iterable[AuthorityUser], *, initialized: bool = True) -> None:
        self.users = {user.id: deepcopy(user) for user in users}
        self.initialized = initialized
        self.audits: list[AuthorityAuditEntry] = []
        self.lock_calls: list[tuple[str, ...]] = []

    async def get_authority(self, user_id: UUID) -> AuthorityUser | None:
        user = self.users.get(user_id)
        return deepcopy(user) if user is not None else None

    async def list_authorities(self, cursor: UUID | None, limit: int) -> list[AuthorityUser]:
        users = sorted(self.users.values(), key=lambda item: item.id.int)
        if cursor is not None:
            users = [item for item in users if item.id.int > cursor.int]
        return deepcopy(users[:limit])

    async def lock_authorization_state(self) -> None:
        self.lock_calls.append(("state",))
        if not self.initialized:
            raise AppError("authorization_not_initialized", "Authorization is unavailable.", 409)

    async def lock_users(self, user_ids: tuple[UUID, ...]) -> None:
        ordered = tuple(str(item) for item in user_ids)
        self.lock_calls.append(ordered)

    async def count_active_masters(self) -> int:
        return sum(user.role is UserRole.OWNER and user.is_active for user in self.users.values())

    async def replace_grant(
        self, user_id: UUID, technology_key: str, capabilities: frozenset[Capability]
    ) -> None:
        user = self.users[user_id]
        grants = dict(user.grants)
        if capabilities:
            grants[technology_key] = capabilities
        else:
            grants.pop(technology_key, None)
        self.users[user_id] = replace(user, grants=grants)

    async def clear_grants(self, user_id: UUID) -> None:
        self.users[user_id] = replace(self.users[user_id], grants={})

    async def set_status(self, user_id: UUID, is_active: bool) -> None:
        self.users[user_id] = replace(self.users[user_id], is_active=is_active)

    async def set_role(self, user_id: UUID, role: UserRole) -> None:
        self.users[user_id] = replace(self.users[user_id], role=role)

    async def increment_revision(self, user_id: UUID) -> int:
        next_revision = self.users[user_id].revision + 1
        self.users[user_id] = replace(self.users[user_id], revision=next_revision)
        return next_revision

    async def append_audit(self, entry: AuthorityAuditEntry) -> None:
        self.audits.append(deepcopy(entry))

    async def list_audit(
        self, target_user_id: UUID, cursor: int | None, limit: int
    ) -> list[AuthorityAuditEntry]:
        items = [item for item in self.audits if item.target_user_id == target_user_id]
        items.sort(key=lambda item: item.id or 0, reverse=True)
        if cursor is not None:
            items = [item for item in items if (item.id or 0) < cursor]
        return deepcopy(items[:limit])


def authority_user(
    *,
    role: UserRole = UserRole.MEMBER,
    is_active: bool = True,
    revision: int = 0,
    grants: dict[str, frozenset[Capability]] | None = None,
) -> AuthorityUser:
    identifier = uuid4()
    return AuthorityUser(
        id=identifier,
        display_name=f"User {identifier.hex[:6]}",
        email=f"{identifier.hex[:8]}@example.test",
        role=role,
        is_active=is_active,
        revision=revision,
        grants=grants or {},
    )


def service_for(
    *users: AuthorityUser,
) -> tuple[AuthorizationService, MemoryAuthorizationRepository]:
    repository = MemoryAuthorizationRepository(users)
    registry = TechnologyRegistry((TechnologyDefinition(key="rag", label="RAG"),))
    return AuthorizationService(repository, registry), repository


@pytest.mark.asyncio
async def test_member_without_a_grant_is_denied_configure() -> None:
    member = authority_user()
    service, _ = service_for(member)

    with pytest.raises(AppError) as exc:
        await service.require_capability(member.id, "rag", Capability.CONFIGURE)

    assert exc.value.status_code == 403


def test_configure_without_view_is_rejected_before_persistence() -> None:
    registry = TechnologyRegistry((TechnologyDefinition(key="rag", label="RAG"),))

    with pytest.raises(AppError) as exc:
        registry.validate_capabilities("rag", frozenset({Capability.CONFIGURE}))

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_unknown_technology_is_denied_even_for_a_legacy_owner() -> None:
    owner = authority_user(role=UserRole.OWNER)
    service, _ = service_for(owner)

    with pytest.raises(AppError) as exc:
        await service.require_capability(owner.id, "unregistered", Capability.VIEW)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_active_legacy_owner_inherits_all_known_capabilities() -> None:
    owner = authority_user(role=UserRole.OWNER)
    service, _ = service_for(owner)

    for capability in Capability:
        await service.require_capability(owner.id, "rag", capability)

    access = await service.get_access(owner.id)
    assert access.is_master is True
    assert access.revision == 0
    assert access.technologies[0].capabilities == tuple(Capability)


@pytest.mark.asyncio
async def test_inactive_owner_has_no_effective_permissions() -> None:
    owner = authority_user(role=UserRole.OWNER, is_active=False)
    service, _ = service_for(owner)

    with pytest.raises(AppError) as exc:
        await service.require_capability(owner.id, "rag", Capability.VIEW)

    assert exc.value.status_code == 403
    access = await service.get_access(owner.id)
    assert access.technologies[0].capabilities == ()


@pytest.mark.asyncio
async def test_admin_view_preserves_inactive_member_configured_grants() -> None:
    owner = authority_user(role=UserRole.OWNER)
    member = authority_user(
        is_active=False,
        grants={"rag": frozenset({Capability.VIEW, Capability.EXECUTE})},
    )
    service, _ = service_for(owner, member)

    detail = await service.get_user(owner.id, member.id)
    effective = await service.get_access(member.id)

    assert detail.technologies[0].capabilities == (
        Capability.VIEW,
        Capability.EXECUTE,
    )
    assert effective.technologies[0].capabilities == ()


@pytest.mark.asyncio
async def test_noop_grant_save_keeps_revision_and_creates_no_audit() -> None:
    owner = authority_user(role=UserRole.OWNER)
    member = authority_user(
        revision=4,
        grants={"rag": frozenset({Capability.VIEW, Capability.CONFIGURE})},
    )
    service, repository = service_for(owner, member)

    result = await service.set_grant(
        owner.id,
        member.id,
        "rag",
        frozenset({Capability.CONFIGURE, Capability.VIEW}),
        expected_revision=4,
    )

    assert result.revision == 4
    assert repository.audits == []


@pytest.mark.asyncio
async def test_grant_mutation_locks_state_then_sorted_users_and_rereads_actor() -> None:
    owner = authority_user(role=UserRole.OWNER)
    member = authority_user()
    service, repository = service_for(owner, member)

    await service.set_grant(
        owner.id,
        member.id,
        "rag",
        frozenset({Capability.VIEW}),
        expected_revision=0,
    )

    assert repository.lock_calls == [
        ("state",),
        tuple(str(item) for item in sorted((owner.id, member.id), key=lambda value: value.int)),
    ]
    assert repository.users[member.id].revision == 1
    assert len(repository.audits) == 1


@pytest.mark.asyncio
async def test_stale_revision_is_rejected_without_mutation() -> None:
    owner = authority_user(role=UserRole.OWNER)
    member = authority_user(revision=2)
    service, repository = service_for(owner, member)

    with pytest.raises(AppError) as exc:
        await service.set_status(owner.id, member.id, False, expected_revision=1)

    assert exc.value.status_code == 409
    assert repository.users[member.id].is_active is True
    assert repository.audits == []


@pytest.mark.asyncio
async def test_last_active_master_cannot_be_demoted_or_deactivated() -> None:
    owner = authority_user(role=UserRole.OWNER)
    service, repository = service_for(owner)

    with pytest.raises(AppError) as demotion:
        await service.set_role(owner.id, owner.id, UserRole.MEMBER, expected_revision=0)
    with pytest.raises(AppError) as deactivation:
        await service.set_status(owner.id, owner.id, False, expected_revision=0)

    assert demotion.value.status_code == 409
    assert deactivation.value.status_code == 409
    assert repository.users[owner.id].role is UserRole.OWNER
    assert repository.users[owner.id].is_active is True


@pytest.mark.asyncio
async def test_promotion_clears_explicit_grants_and_demotion_starts_empty() -> None:
    owner = authority_user(role=UserRole.OWNER)
    member = authority_user(grants={"rag": frozenset({Capability.VIEW})})
    service, repository = service_for(owner, member)

    promoted = await service.set_role(owner.id, member.id, UserRole.OWNER, expected_revision=0)
    demoted = await service.set_role(owner.id, member.id, UserRole.MEMBER, expected_revision=1)

    assert promoted.role is UserRole.OWNER
    assert demoted.role is UserRole.MEMBER
    assert demoted.technologies[0].capabilities == ()
    assert repository.users[member.id].grants == {}
    assert len(repository.audits) == 2


@pytest.mark.asyncio
async def test_grants_on_a_master_are_rejected_even_when_the_values_are_empty() -> None:
    actor = authority_user(role=UserRole.OWNER)
    target = authority_user(role=UserRole.OWNER)
    service, repository = service_for(actor, target)

    with pytest.raises(AppError) as exc:
        await service.set_grant(actor.id, target.id, "rag", frozenset(), expected_revision=0)

    assert exc.value.status_code == 409
    assert repository.audits == []


@pytest.mark.asyncio
async def test_inactive_grant_audit_records_assignment_replacement_and_revocation() -> None:
    owner = authority_user(role=UserRole.OWNER)
    member = authority_user(is_active=False)
    service, repository = service_for(owner, member)

    assigned = await service.set_grant(
        owner.id,
        member.id,
        "rag",
        frozenset({Capability.VIEW}),
        expected_revision=0,
    )
    replaced = await service.set_grant(
        owner.id,
        member.id,
        "rag",
        frozenset({Capability.VIEW, Capability.EXECUTE}),
        expected_revision=1,
    )
    revoked = await service.set_grant(
        owner.id,
        member.id,
        "rag",
        frozenset(),
        expected_revision=2,
    )

    assert assigned.technologies[0].capabilities == (Capability.VIEW,)
    assert replaced.technologies[0].capabilities == (
        Capability.VIEW,
        Capability.EXECUTE,
    )
    assert revoked.technologies[0].capabilities == ()
    assert [audit.before["technologies"] for audit in repository.audits] == [
        {"rag": []},
        {"rag": ["view"]},
        {"rag": ["view", "execute"]},
    ]
    assert [audit.after["technologies"] for audit in repository.audits] == [
        {"rag": ["view"]},
        {"rag": ["view", "execute"]},
        {"rag": []},
    ]


@pytest.mark.asyncio
async def test_inactive_promotion_audit_records_cleared_stored_grants() -> None:
    owner = authority_user(role=UserRole.OWNER)
    member = authority_user(
        is_active=False,
        grants={"rag": frozenset({Capability.VIEW, Capability.CONFIGURE})},
    )
    service, repository = service_for(owner, member)

    promoted = await service.set_role(
        owner.id,
        member.id,
        UserRole.OWNER,
        expected_revision=0,
    )

    assert promoted.technologies[0].capabilities == tuple(Capability)
    assert (await service.get_access(member.id)).technologies[0].capabilities == ()
    audit = repository.audits[0]
    assert audit.before["technologies"] == {"rag": ["view", "configure"]}
    assert audit.after["technologies"] == {"rag": []}
