from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_workshop.platform.identity.authorization import Capability
from ai_workshop.platform.identity.authorization_repository import AuthorityAuditEntry
from ai_workshop.platform.identity.authorization_service import (
    AccessView,
    TechnologyAccess,
    UserAuthorityPage,
    UserAuthorityView,
)
from ai_workshop.platform.identity.domain import UserRole

StrictRevision = Annotated[int, Field(strict=True, ge=0)]


class TechnologyAccessResponse(BaseModel):
    key: str
    label: str
    capabilities: list[Capability]
    delegation_enabled: bool

    @classmethod
    def from_domain(cls, value: TechnologyAccess) -> TechnologyAccessResponse:
        return cls(
            key=value.key,
            label=value.label,
            capabilities=list(value.capabilities),
            delegation_enabled=value.delegation_enabled,
        )


class TechnologyCatalogResponse(BaseModel):
    key: str
    label: str
    delegation_enabled: bool


class AccessResponse(BaseModel):
    is_master: bool
    revision: int
    technologies: list[TechnologyAccessResponse]

    @classmethod
    def from_domain(cls, value: AccessView) -> AccessResponse:
        return cls(
            is_master=value.is_master,
            revision=value.revision,
            technologies=[
                TechnologyAccessResponse.from_domain(item) for item in value.technologies
            ],
        )


class UserAuthorityResponse(BaseModel):
    id: UUID
    display_name: str
    email: str
    role: UserRole
    is_active: bool
    revision: int
    is_last_active_master: bool
    technologies: list[TechnologyAccessResponse]

    @classmethod
    def from_domain(cls, value: UserAuthorityView) -> UserAuthorityResponse:
        return cls(
            id=value.id,
            display_name=value.display_name,
            email=value.email,
            role=value.role,
            is_active=value.is_active,
            revision=value.revision,
            is_last_active_master=value.is_last_active_master,
            technologies=[
                TechnologyAccessResponse.from_domain(item) for item in value.technologies
            ],
        )


class UserAuthorityPageResponse(BaseModel):
    items: list[UserAuthorityResponse]
    next_cursor: UUID | None

    @classmethod
    def from_domain(cls, value: UserAuthorityPage) -> UserAuthorityPageResponse:
        return cls(
            items=[UserAuthorityResponse.from_domain(item) for item in value.items],
            next_cursor=value.next_cursor,
        )


class GrantUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictRevision
    capabilities: list[Capability]

    @field_validator("capabilities")
    @classmethod
    def require_unique_capabilities(cls, values: list[Capability]) -> list[Capability]:
        if len(values) != len(set(values)):
            raise ValueError("capabilities must be unique")
        return values


class StatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictRevision
    is_active: bool = Field(strict=True)


class RoleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictRevision
    role: UserRole


class AuthorityAuditResponse(BaseModel):
    id: int
    actor_id: UUID | None
    target_user_id: UUID
    event_type: str
    technology_key: str | None
    before: dict[str, Any]
    after: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_domain(cls, value: AuthorityAuditEntry) -> AuthorityAuditResponse:
        if value.id is None or value.created_at is None:
            raise ValueError("persisted audit identity and timestamp are required")
        return cls(
            id=value.id,
            actor_id=value.actor_id,
            target_user_id=value.target_user_id,
            event_type=value.event_type,
            technology_key=value.technology_key,
            before=dict(value.before),
            after=dict(value.after),
            created_at=value.created_at,
        )


class AuthorityAuditPageResponse(BaseModel):
    items: list[AuthorityAuditResponse]
    next_cursor: int | None
