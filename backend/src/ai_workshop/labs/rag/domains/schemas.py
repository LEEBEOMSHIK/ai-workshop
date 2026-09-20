from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_workshop.labs.rag.configurations.schemas import (
    GenerationExecutionPreviewResponse,
)
from ai_workshop.labs.rag.domains.service import (
    AdminDomainConnectionVersion,
    Domain,
    DomainConnectionVersion,
    DomainLibraryContext,
    DomainSearchContext,
    DomainView,
    DomainWorkspaceOption,
)
from ai_workshop.labs.rag.generation.codex_admin_api import CodexInputApprovalRequest
from ai_workshop.labs.rag.retrieval.selection import reject_explicit_empty_document_ids
from ai_workshop.labs.rag.search.schemas import (
    ConversationTurnRequest,
    SearchResponse,
)
from ai_workshop.labs.rag.search.service import SearchResult
from ai_workshop.platform.workspaces.domain import WorkspaceKind


class DomainCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=1000)


class DomainUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=1000)


class DomainConnectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configuration_version_id: UUID
    workspace_ids: list[UUID] = Field(min_length=1)


class DomainSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_version_id: UUID
    query: str = Field(min_length=2, max_length=1000)
    workspace_ids: list[UUID] = Field(min_length=1)
    folder_ids: list[UUID] = Field(default_factory=list)
    document_ids: list[UUID] | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    include_diagnostics: bool = False
    history: list[ConversationTurnRequest] = Field(default_factory=list, max_length=20)
    codex_input_approval: CodexInputApprovalRequest | None = None

    _reject_empty_document_ids = field_validator("document_ids", mode="before")(
        reject_explicit_empty_document_ids
    )


class DomainConnectionIdentityResponse(BaseModel):
    id: UUID
    version: int


class DomainWorkspaceOptionResponse(BaseModel):
    id: UUID
    name: str
    kind: WorkspaceKind
    expires_at: datetime | None

    @classmethod
    def from_domain(cls, option: DomainWorkspaceOption) -> Self:
        return cls(
            id=option.id,
            name=option.name,
            kind=option.kind,
            expires_at=option.expires_at,
        )


class DomainLibraryResponse(BaseModel):
    domain_id: UUID
    display_name: str
    connection_version_id: UUID
    workspace_options: list[DomainWorkspaceOptionResponse]
    selection_limit: int

    @classmethod
    def from_domain(
        cls,
        context: DomainLibraryContext,
        *,
        selection_limit: int,
    ) -> Self:
        return cls(
            domain_id=context.domain.id,
            display_name=context.domain.display_name,
            connection_version_id=context.connection.id,
            workspace_options=[
                DomainWorkspaceOptionResponse.from_domain(option)
                for option in context.workspace_options
            ],
            selection_limit=selection_limit,
        )


class DomainReadinessResponse(BaseModel):
    search_ready: bool
    answer_ready: bool
    service_ready: bool
    reason_codes: list[str]


class DomainResponse(BaseModel):
    id: UUID
    slug: str
    display_name: str
    description: str
    active: bool
    ready: bool
    connection_version: DomainConnectionIdentityResponse | None
    readiness: DomainReadinessResponse
    workspace_options: list[DomainWorkspaceOptionResponse]
    generation_execution_preview: GenerationExecutionPreviewResponse | None

    @classmethod
    def from_domain(cls, view: DomainView) -> Self:
        connection = view.connection
        preview = view.generation_execution_preview
        return cls(
            id=view.domain.id,
            slug=view.domain.slug,
            display_name=view.domain.display_name,
            description=view.domain.description,
            active=view.active,
            ready=view.ready,
            connection_version=(
                DomainConnectionIdentityResponse(
                    id=connection.id,
                    version=connection.version,
                )
                if connection is not None
                else None
            ),
            readiness=DomainReadinessResponse(
                search_ready=view.search_ready,
                answer_ready=view.answer_ready,
                service_ready=view.ready,
                reason_codes=list(view.reason_codes),
            ),
            workspace_options=[
                DomainWorkspaceOptionResponse.from_domain(option)
                for option in view.workspace_options
            ],
            generation_execution_preview=(
                GenerationExecutionPreviewResponse.from_domain(preview)
                if preview is not None
                else None
            ),
        )


class DomainConnectionVersionResponse(BaseModel):
    id: UUID
    domain_id: UUID
    version: int
    configuration_version_id: UUID
    configuration_name: str
    configuration_version: int
    workspace_ids: list[UUID]
    created_by: UUID
    created_at: datetime | None

    @classmethod
    def from_domain(cls, item: AdminDomainConnectionVersion) -> Self:
        connection = item.connection
        return cls(
            id=connection.id,
            domain_id=connection.domain_id,
            version=connection.version,
            configuration_version_id=connection.configuration_version_id,
            configuration_name=item.configuration_name,
            configuration_version=item.configuration_version,
            workspace_ids=list(connection.workspace_ids),
            created_by=connection.created_by,
            created_at=connection.created_at,
        )


class DomainConnectionCreatedResponse(BaseModel):
    id: UUID
    domain_id: UUID
    version: int
    configuration_version_id: UUID
    workspace_ids: list[UUID]
    created_by: UUID
    created_at: datetime | None

    @classmethod
    def from_domain(cls, connection: DomainConnectionVersion) -> Self:
        return cls(
            id=connection.id,
            domain_id=connection.domain_id,
            version=connection.version,
            configuration_version_id=connection.configuration_version_id,
            workspace_ids=list(connection.workspace_ids),
            created_by=connection.created_by,
            created_at=connection.created_at,
        )


class AdminDomainResponse(BaseModel):
    id: UUID
    slug: str
    display_name: str
    description: str
    active_connection_version_id: UUID | None
    created_by: UUID
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def from_domain(cls, domain: Domain) -> Self:
        return cls(
            id=domain.id,
            slug=domain.slug,
            display_name=domain.display_name,
            description=domain.description,
            active_connection_version_id=domain.active_connection_version_id,
            created_by=domain.created_by,
            created_at=domain.created_at,
            updated_at=domain.updated_at,
        )


class DomainSearchContextResponse(BaseModel):
    domain_id: UUID
    connection_version_id: UUID
    workspace_ids: list[UUID]
    folder_ids: list[UUID]


class DomainSearchResponse(SearchResponse):
    domain_context: DomainSearchContextResponse

    @classmethod
    def from_result(
        cls,
        result: SearchResult,
        context: DomainSearchContext,
    ) -> Self:
        response = SearchResponse.from_domain(result)
        return cls(
            **response.model_dump(),
            domain_context=DomainSearchContextResponse(
                domain_id=context.domain_id,
                connection_version_id=context.connection_version_id,
                workspace_ids=list(context.workspace_ids),
                folder_ids=list(context.folder_ids),
            ),
        )
