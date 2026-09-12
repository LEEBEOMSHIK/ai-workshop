from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn
from uuid import UUID

from ai_workshop.platform.identity.authorization import (
    Capability,
    TechnologyRegistry,
)
from ai_workshop.platform.identity.authorization_repository import (
    AuthorityAuditEntry,
    AuthorityUser,
    AuthorizationRepository,
)
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.shared.errors import AppError


@dataclass(frozen=True, slots=True)
class TechnologyAccess:
    key: str
    label: str
    capabilities: tuple[Capability, ...]
    delegation_enabled: bool = False


@dataclass(frozen=True, slots=True)
class AccessView:
    is_master: bool
    revision: int
    technologies: tuple[TechnologyAccess, ...]


@dataclass(frozen=True, slots=True)
class UserAuthorityView:
    id: UUID
    display_name: str
    email: str
    role: UserRole
    is_active: bool
    revision: int
    is_last_active_master: bool
    technologies: tuple[TechnologyAccess, ...]


@dataclass(frozen=True, slots=True)
class UserAuthorityPage:
    items: tuple[UserAuthorityView, ...]
    next_cursor: UUID | None


@dataclass(frozen=True, slots=True)
class AuditPage:
    items: tuple[AuthorityAuditEntry, ...]
    next_cursor: int | None


class AuthorizationService:
    def __init__(
        self,
        repository: AuthorizationRepository,
        registry: TechnologyRegistry,
    ) -> None:
        self.repository = repository
        self.registry = registry

    async def require_capability(
        self,
        actor_id: UUID,
        technology: str,
        capability: Capability,
    ) -> None:
        if self.registry.get(technology) is None:
            self._deny_capability()
        actor = await self.repository.get_authority(actor_id)
        if actor is None or not actor.is_active:
            self._deny_capability()
        if actor.role is UserRole.OWNER:
            return
        if capability not in actor.grants.get(technology, frozenset()):
            self._deny_capability()

    async def get_access(self, actor_id: UUID) -> AccessView:
        actor = await self.repository.get_authority(actor_id)
        if actor is None:
            self._deny_capability()
        return AccessView(
            is_master=actor.is_active and actor.role is UserRole.OWNER,
            revision=actor.revision,
            technologies=self._effective_technology_views(actor),
        )

    async def list_technologies(self, actor_id: UUID) -> tuple[TechnologyAccess, ...]:
        await self._require_fresh_master(actor_id)
        return tuple(
            TechnologyAccess(key=item.key, label=item.label, capabilities=())
            for item in self.registry.technologies
        )

    async def list_users(
        self,
        actor_id: UUID,
        *,
        cursor: UUID | None,
        limit: int,
    ) -> UserAuthorityPage:
        await self._require_fresh_master(actor_id)
        users = await self.repository.list_authorities(cursor, limit + 1)
        has_more = len(users) > limit
        page_users = users[:limit]
        master_count = await self.repository.count_active_masters()
        items = tuple(self._user_view(user, master_count) for user in page_users)
        return UserAuthorityPage(
            items=items,
            next_cursor=page_users[-1].id if has_more and page_users else None,
        )

    async def get_user(self, actor_id: UUID, target_user_id: UUID) -> UserAuthorityView:
        await self._require_fresh_master(actor_id)
        target = await self.repository.get_authority(target_user_id)
        if target is None:
            self._missing_user()
        return self._user_view(target, await self.repository.count_active_masters())

    async def set_grant(
        self,
        actor_id: UUID,
        target_user_id: UUID,
        technology_key: str,
        capabilities: frozenset[Capability],
        *,
        expected_revision: int,
    ) -> UserAuthorityView:
        capabilities = self.registry.validate_capabilities(technology_key, capabilities)
        _, target = await self._lock_and_load(actor_id, target_user_id)
        self._check_revision(target, expected_revision)
        if target.role is UserRole.OWNER:
            raise AppError(
                "master_grants_not_editable",
                "A master's inherited capabilities cannot be edited.",
                409,
            )
        previous = target.grants.get(technology_key, frozenset())
        if previous == capabilities:
            return self._user_view(target, await self.repository.count_active_masters())

        before = self._audit_values(target)
        await self.repository.replace_grant(target.id, technology_key, capabilities)
        await self.repository.increment_revision(target.id)
        updated = await self._required_authority(target.id)
        await self.repository.append_audit(
            AuthorityAuditEntry(
                id=None,
                actor_id=actor_id,
                target_user_id=target.id,
                event_type="technology_grant_changed",
                technology_key=technology_key,
                before=before,
                after=self._audit_values(updated),
            )
        )
        return self._user_view(updated, await self.repository.count_active_masters())

    async def set_status(
        self,
        actor_id: UUID,
        target_user_id: UUID,
        is_active: bool,
        *,
        expected_revision: int,
    ) -> UserAuthorityView:
        _, target = await self._lock_and_load(actor_id, target_user_id)
        self._check_revision(target, expected_revision)
        if target.is_active == is_active:
            return self._user_view(target, await self.repository.count_active_masters())
        master_count = await self.repository.count_active_masters()
        if (
            target.role is UserRole.OWNER
            and target.is_active
            and not is_active
            and master_count == 1
        ):
            self._protect_last_master()

        before = self._audit_values(target)
        await self.repository.set_status(target.id, is_active)
        await self.repository.increment_revision(target.id)
        updated = await self._required_authority(target.id)
        await self.repository.append_audit(
            AuthorityAuditEntry(
                id=None,
                actor_id=actor_id,
                target_user_id=target.id,
                event_type="user_status_changed",
                technology_key=None,
                before=before,
                after=self._audit_values(updated),
            )
        )
        return self._user_view(updated, await self.repository.count_active_masters())

    async def set_role(
        self,
        actor_id: UUID,
        target_user_id: UUID,
        role: UserRole,
        *,
        expected_revision: int,
    ) -> UserAuthorityView:
        _, target = await self._lock_and_load(actor_id, target_user_id)
        self._check_revision(target, expected_revision)
        if target.role is role:
            return self._user_view(target, await self.repository.count_active_masters())
        master_count = await self.repository.count_active_masters()
        if (
            target.role is UserRole.OWNER
            and target.is_active
            and role is UserRole.MEMBER
            and master_count == 1
        ):
            self._protect_last_master()

        before = self._audit_values(target)
        await self.repository.clear_grants(target.id)
        await self.repository.set_role(target.id, role)
        await self.repository.increment_revision(target.id)
        updated = await self._required_authority(target.id)
        await self.repository.append_audit(
            AuthorityAuditEntry(
                id=None,
                actor_id=actor_id,
                target_user_id=target.id,
                event_type="user_role_changed",
                technology_key=None,
                before=before,
                after=self._audit_values(updated),
            )
        )
        return self._user_view(updated, await self.repository.count_active_masters())

    async def list_audit(
        self,
        actor_id: UUID,
        target_user_id: UUID,
        *,
        cursor: int | None,
        limit: int,
    ) -> AuditPage:
        await self._require_fresh_master(actor_id)
        if await self.repository.get_authority(target_user_id) is None:
            self._missing_user()
        entries = await self.repository.list_audit(target_user_id, cursor, limit + 1)
        has_more = len(entries) > limit
        page_entries = entries[:limit]
        return AuditPage(
            items=tuple(page_entries),
            next_cursor=(page_entries[-1].id if has_more and page_entries else None),
        )

    async def _lock_and_load(
        self, actor_id: UUID, target_user_id: UUID
    ) -> tuple[AuthorityUser, AuthorityUser]:
        await self.repository.lock_authorization_state()
        ordered_ids = tuple(sorted({actor_id, target_user_id}, key=lambda value: value.int))
        await self.repository.lock_users(ordered_ids)
        actor = await self.repository.get_authority(actor_id)
        if actor is None or not actor.is_active or actor.role is not UserRole.OWNER:
            self._deny_master()
        target = await self.repository.get_authority(target_user_id)
        if target is None:
            self._missing_user()
        return actor, target

    async def _require_fresh_master(self, actor_id: UUID) -> AuthorityUser:
        actor = await self.repository.get_authority(actor_id)
        if actor is None or not actor.is_active or actor.role is not UserRole.OWNER:
            self._deny_master()
        return actor

    async def _required_authority(self, user_id: UUID) -> AuthorityUser:
        user = await self.repository.get_authority(user_id)
        if user is None:
            raise RuntimeError("authority target disappeared inside transaction")
        return user

    def _effective_technology_views(
        self, user: AuthorityUser
    ) -> tuple[TechnologyAccess, ...]:
        is_master = user.is_active and user.role is UserRole.OWNER
        return tuple(
            TechnologyAccess(
                key=technology.key,
                label=technology.label,
                capabilities=(
                    tuple(Capability)
                    if is_master
                    else tuple(
                        capability
                        for capability in Capability
                        if user.is_active
                        and capability in user.grants.get(technology.key, frozenset())
                    )
                ),
            )
            for technology in self.registry.technologies
        )

    def _configured_technology_views(
        self, user: AuthorityUser
    ) -> tuple[TechnologyAccess, ...]:
        return tuple(
            TechnologyAccess(
                key=technology.key,
                label=technology.label,
                capabilities=(
                    tuple(Capability)
                    if user.role is UserRole.OWNER
                    else tuple(
                        capability
                        for capability in Capability
                        if capability in user.grants.get(technology.key, frozenset())
                    )
                ),
            )
            for technology in self.registry.technologies
        )

    def _user_view(self, user: AuthorityUser, master_count: int) -> UserAuthorityView:
        return UserAuthorityView(
            id=user.id,
            display_name=user.display_name,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
            revision=user.revision,
            is_last_active_master=(
                user.is_active and user.role is UserRole.OWNER and master_count == 1
            ),
            technologies=self._configured_technology_views(user),
        )

    def _audit_values(self, user: AuthorityUser) -> dict[str, object]:
        return {
            "role": user.role.value,
            "is_active": user.is_active,
            "revision": user.revision,
            "technologies": {
                technology.key: [
                    capability.value
                    for capability in Capability
                    if capability in user.grants.get(technology.key, frozenset())
                ]
                for technology in self.registry.technologies
            },
        }

    @staticmethod
    def _check_revision(target: AuthorityUser, expected_revision: int) -> None:
        if target.revision != expected_revision:
            raise AppError(
                "authority_revision_conflict",
                "The authority changed; reload it before saving.",
                409,
            )

    @staticmethod
    def _deny_capability() -> NoReturn:
        raise AppError(
            "technology_capability_required",
            "The requested technology capability is required.",
            403,
        )

    @staticmethod
    def _deny_master() -> NoReturn:
        raise AppError("owner_required", "Owner access is required.", 403)

    @staticmethod
    def _missing_user() -> NoReturn:
        raise AppError("user_not_found", "The requested user was not found.", 404)

    @staticmethod
    def _protect_last_master() -> NoReturn:
        raise AppError(
            "last_active_master_required",
            "At least one active master must remain.",
            409,
        )
