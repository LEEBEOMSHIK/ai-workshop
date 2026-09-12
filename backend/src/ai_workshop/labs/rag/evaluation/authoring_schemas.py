"""Closed, bounded authoring inputs and sanitized read models."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

MAX_WORKSPACES = 100
MAX_DOCUMENTS = 100
MAX_EVIDENCE = 10_000
MAX_CASES = 500
MAX_QUERY_CHARS = 4_000
MAX_NAME_CHARS = 180
MAX_HIGHLIGHTS = 32
MAX_RESPONSE_BYTES = 16_777_216

type Position = Annotated[int, Field(strict=True, ge=0)]
type Coordinate = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
type Span = tuple[Position, Position]
type Box = tuple[Coordinate, Coordinate, Coordinate, Coordinate]
type Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthoringSelection(ClosedModel):
    configuration_version_id: UUID
    workspace_ids: tuple[UUID, ...] = Field(min_length=1, max_length=MAX_WORKSPACES)

    @field_validator("workspace_ids")
    @classmethod
    def unique_workspaces(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("Workspace IDs must be unique.")
        return tuple(sorted(values))


class AuthoringDocumentsRequest(AuthoringSelection):
    cursor: UUID | None = None
    limit: StrictInt = Field(default=50, ge=1, le=100)


class AuthoringScope(AuthoringSelection):
    asset_version_ids: tuple[UUID, ...] = Field(min_length=1, max_length=MAX_DOCUMENTS)

    @field_validator("asset_version_ids")
    @classmethod
    def unique_versions(cls, values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("Asset Version IDs must be unique.")
        return tuple(sorted(values))


class AuthoringHighlight(ClosedModel):
    kind: Literal["keyword", "semantic"]
    surface: Literal["answer", "conflict"] = "answer"
    document_id: UUID
    asset_version_id: UUID
    evidence_unit_id: UUID
    page: Position | None = None
    spans: tuple[Span, ...] = Field(default=(), max_length=MAX_HIGHLIGHTS)
    bboxes: tuple[Box, ...] = Field(default=(), max_length=MAX_HIGHLIGHTS)


class AuthoringCase(ClosedModel):
    id: UUID
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    expected_answer_status: Literal["supported", "insufficient_evidence"]
    expected_evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=MAX_EVIDENCE)
    expected_highlight: AuthoringHighlight | None = None

    @model_validator(mode="after")
    def validate_manual_answer(self) -> Self:
        if not self.query.strip() or len(self.expected_evidence_ids) != len(
            set(self.expected_evidence_ids)
        ):
            raise ValueError("A nonempty query and unique expected evidence are required.")
        if self.expected_answer_status == "supported":
            if not self.expected_evidence_ids or self.expected_highlight is None:
                raise ValueError("Supported cases require expected evidence and a highlight.")
        elif self.expected_evidence_ids or self.expected_highlight is not None:
            raise ValueError("Insufficient cases cannot claim evidence or highlights.")
        return self


class AuthoringRunRequest(AuthoringScope):
    scope_sha256: Digest
    draft_id: UUID
    dataset_name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    cases: tuple[AuthoringCase, ...] = Field(min_length=1, max_length=MAX_CASES)
    retrieval_k: StrictInt = Field(ge=1, le=50)
    repetition_count: StrictInt = Field(default=2, ge=2, le=5)
    retention_confirmed: StrictBool

    @model_validator(mode="after")
    def require_confirmation(self) -> Self:
        if self.retention_confirmed is not True or not self.dataset_name.strip():
            raise ValueError("Explicit retention confirmation and dataset name are required.")
        if len(self.cases) != len({case.id for case in self.cases}):
            raise ValueError("Case IDs must be unique.")
        return self

    def scope(self) -> AuthoringScope:
        return AuthoringScope(
            configuration_version_id=self.configuration_version_id,
            workspace_ids=self.workspace_ids,
            asset_version_ids=self.asset_version_ids,
        )


class AuthoringDocumentMetadata(ClosedModel):
    document_id: UUID
    workspace_id: UUID
    asset_version_id: UUID
    title: str
    number: int
    ready: bool


class AuthoringDocumentsResponse(ClosedModel):
    documents: tuple[AuthoringDocumentMetadata, ...]
    next_cursor: UUID | None


class AuthoringDocument(ClosedModel):
    document_id: UUID
    workspace_id: UUID
    asset_version_id: UUID
    title: str
    number: int
    sha256: Digest


class AuthoringEvidence(ClosedModel):
    id: UUID
    document_id: UUID
    asset_version_id: UUID
    projection_id: UUID
    index_build_id: UUID
    text: str
    element_id: UUID
    page: Position | None = None
    start_char: Position
    end_char: Position
    bounding_boxes: tuple[Box, ...] = ()


class AuthoringPreview(ClosedModel):
    scope: AuthoringScope
    baseline_configuration_version_id: UUID
    document_processing_profile_id: UUID
    indexing_profile_id: UUID
    documents: tuple[AuthoringDocument, ...]
    evidence: tuple[AuthoringEvidence, ...]
    document_count: int
    evidence_count: int
    complete: Literal[True] = True
    scope_sha256: Digest
