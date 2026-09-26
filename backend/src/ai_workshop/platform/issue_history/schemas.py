from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Title = Annotated[str, Field(min_length=1, max_length=200)]
LongText = Annotated[str, Field(max_length=20000)]
TextItem = Annotated[str, Field(max_length=2000)]
TextList = Annotated[list[TextItem], Field(max_length=100)]
Status = Literal["open", "implemented", "verified"]


class DTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class Command(DTO):
    request_id: UUID


class Update(Command):
    expected_revision: int = Field(ge=1)


class CategoryCreate(Command):
    parent_id: UUID | None = None
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    name: Title
    sort_order: int = 0
    is_active: bool = True


class CategoryUpdate(Update):
    parent_id: UUID | None = None
    name: Title
    sort_order: int = 0
    is_active: bool = True


class IssueCategoryView(DTO):
    parent_id: UUID | None = None
    id: UUID
    code: str
    name: str
    sort_order: int
    is_active: bool
    revision: int


class IssueCategoryList(DTO):
    items: list[IssueCategoryView]


class IssueFields(DTO):
    category_id: UUID
    title: Title
    status: Status = "open"
    symptom: LongText = ""
    cause: LongText = ""
    resolution: LongText = ""
    verification: TextList = Field(default_factory=list)
    remaining: TextList = Field(default_factory=list)
    commits: TextList = Field(default_factory=list)


class IssueCreate(IssueFields, Command):
    pass


class IssueUpdate(IssueFields, Update):
    pass


class IssueView(IssueFields):
    id: UUID
    issue_key: str
    legacy_keys: list[str] = Field(default_factory=list)
    revision: int
    created_at: datetime
    updated_at: datetime


class IssueEventView(DTO):
    id: UUID
    event_date: date
    recorded_at: datetime
    actor_id: UUID | None
    kind: str
    description: str
    before_revision: int | None
    after_revision: int
    snapshot: dict[str, object]


class IssueDocumentLinkView(DTO):
    document_id: UUID
    version: int
    title: str
    current_version: int
    source_path: str | None
    sort_order: int


class IssueDetail(IssueView):
    events: list[IssueEventView]
    documents: list[IssueDocumentLinkView]


class IssueList(DTO):
    items: list[IssueView]
    total: int
    status_counts: dict[str, int]


class EventCreate(Update):
    event_date: date
    description: Annotated[str, Field(min_length=1, max_length=20000)]


class DocumentLink(DTO):
    document_id: UUID
    version: int = Field(ge=1)


class LinksUpdate(Update):
    links: list[DocumentLink] = Field(max_length=100)


class DocumentContent(DTO):
    content: str
    source_path: str | None = Field(default=None, max_length=2000)
    source_commit: str | None = Field(default=None, max_length=200)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 512 * 1024:
            raise ValueError("Document exceeds 512 KiB.")
        return value


class DocumentCreate(DocumentContent, Command):
    title: Title


class DocumentUpdate(Update):
    title: Title


class DocumentVersionCreate(DocumentContent, Update):
    pass


class IssueDocumentView(DTO):
    id: UUID
    title: str
    current_version: int
    revision: int
    import_source_key: str | None
    created_at: datetime
    updated_at: datetime


class IssueDocumentList(DTO):
    items: list[IssueDocumentView]


class IssueDocumentVersionView(DTO):
    document_id: UUID
    version: int
    title: str
    current_version: int
    content: str
    sha256: str
    source_path: str | None
    source_commit: str | None
    created_at: datetime
