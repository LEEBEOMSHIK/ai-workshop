from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.identity.api import require_owner
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.issue_history import schemas as s
from ai_workshop.platform.issue_history.service import IssueHistoryService
from ai_workshop.platform.publishing.api import require_publishing_mutation
from ai_workshop.shared.db import get_session

router = APIRouter(
    prefix="/api/v1/admin/issue-history",
    tags=["issue-history"],
    dependencies=[Depends(require_owner)],
)


def get_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[User, Depends(require_owner)],
) -> IssueHistoryService:
    return IssueHistoryService(session, actor)


Service = Annotated[IssueHistoryService, Depends(get_service)]
mutation = [Depends(require_publishing_mutation)]


@router.get("/categories", response_model=s.IssueCategoryList)
async def categories(service: Service) -> s.IssueCategoryList:
    return await service.categories()


@router.post("/categories", response_model=s.IssueCategoryView, dependencies=mutation)
async def create_category(request: s.CategoryCreate, service: Service) -> s.IssueCategoryView:
    return await service.create_category(request)


@router.put("/categories/{identity}", response_model=s.IssueCategoryView, dependencies=mutation)
async def update_category(
    identity: UUID, request: s.CategoryUpdate, service: Service
) -> s.IssueCategoryView:
    return await service.update_category(identity, request)


@router.get("/issues", response_model=s.IssueList)
async def issues(
    service: Service,
    q: str = Query(default="", max_length=200),
    status: s.Status | None = None,
    category_id: UUID | None = None,
    parent_category_id: UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> s.IssueList:
    return await service.list_issues(q, status, category_id, offset, limit, parent_category_id)


@router.post("/issues", response_model=s.IssueDetail, dependencies=mutation)
async def create_issue(request: s.IssueCreate, service: Service) -> s.IssueDetail:
    return await service.create_issue(request)


@router.get("/issues/{identity}", response_model=s.IssueDetail)
async def issue(identity: str, service: Service) -> s.IssueDetail:
    return await service.detail(identity)


@router.put("/issues/{identity}", response_model=s.IssueDetail, dependencies=mutation)
async def update_issue(identity: UUID, request: s.IssueUpdate, service: Service) -> s.IssueDetail:
    return await service.update_issue(identity, request)


@router.post("/issues/{identity}/events", response_model=s.IssueDetail, dependencies=mutation)
async def add_event(identity: UUID, request: s.EventCreate, service: Service) -> s.IssueDetail:
    return await service.add_event(identity, request)


@router.put("/issues/{identity}/links", response_model=s.IssueDetail, dependencies=mutation)
async def replace_links(identity: UUID, request: s.LinksUpdate, service: Service) -> s.IssueDetail:
    return await service.replace_links(identity, request)


@router.get("/documents", response_model=s.IssueDocumentList)
async def documents(service: Service) -> s.IssueDocumentList:
    return await service.documents()


@router.post("/documents", response_model=s.IssueDocumentVersionView, dependencies=mutation)
async def create_document(
    request: s.DocumentCreate, service: Service
) -> s.IssueDocumentVersionView:
    return await service.create_document(request)


@router.put("/documents/{identity}", response_model=s.IssueDocumentView, dependencies=mutation)
async def update_document(
    identity: UUID, request: s.DocumentUpdate, service: Service
) -> s.IssueDocumentView:
    return await service.update_document(identity, request)


@router.post(
    "/documents/{identity}/versions",
    response_model=s.IssueDocumentVersionView,
    dependencies=mutation,
)
async def add_version(
    identity: UUID, request: s.DocumentVersionCreate, service: Service
) -> s.IssueDocumentVersionView:
    return await service.add_version(identity, request)


@router.get("/documents/{identity}/versions/{version}", response_model=s.IssueDocumentVersionView)
async def document_version(
    identity: UUID, version: Annotated[int, Path(ge=1)], service: Service
) -> s.IssueDocumentVersionView:
    return await service.document_version(identity, version)


@router.get(
    "/issues/{issue_id}/documents/{identity}/versions/{version}",
    response_model=s.IssueDocumentVersionView,
)
async def linked_document(
    issue_id: UUID, identity: UUID, version: Annotated[int, Path(ge=1)], service: Service
) -> s.IssueDocumentVersionView:
    return await service.document_version(identity, version, issue_id)
