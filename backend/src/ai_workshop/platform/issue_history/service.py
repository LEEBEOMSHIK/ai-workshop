import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.issue_history import schemas as s
from ai_workshop.platform.issue_history.models import (
    Issue,
    IssueCategory,
    IssueCommand,
    IssueDocument,
    IssueDocumentLink,
    IssueDocumentVersion,
    IssueEvent,
)
from ai_workshop.platform.issue_history.repository import IssueRepository
from ai_workshop.shared.errors import AppError

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R", Issue, IssueCategory, IssueDocument)


def conflict() -> AppError:
    return AppError(
        "issue_history_conflict",
        "The record changed or the request conflicts. Refresh and retry.",
        409,
    )


class IssueHistoryService:
    def __init__(self, session: AsyncSession, actor: User):
        if actor.role != UserRole.OWNER or not actor.is_active:
            raise AppError("owner_required", "Owner access is required.", 403)
        self.session = session
        self.actor = actor
        self.repository = IssueRepository(session)

    async def _get(self, model: type[R], identity: UUID, lock: bool = False) -> R:
        row = await self.session.get(model, identity, with_for_update=lock, populate_existing=lock)
        if row is None:
            raise AppError("issue_history_not_found", "Record not found.", 404)
        return row

    @staticmethod
    def _revision(row: Issue | IssueCategory | IssueDocument, expected: int) -> None:
        if row.revision != expected:
            raise conflict()

    async def _command(
        self,
        operation: str,
        request: s.Command,
        result_type: type[T],
        action: Callable[[], Awaitable[T]],
    ) -> T:
        payload_hash = sha256(
            json.dumps(
                request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        try:
            async with self.session.begin_nested():
                await self.repository.lock_command(self.actor.id, operation, request.request_id)
                saved = await self.repository.command(self.actor.id, operation, request.request_id)
                if saved:
                    if saved.payload_hash != payload_hash:
                        raise conflict()
                    return result_type.model_validate(saved.result)
                result = await action()
                self.session.add(
                    IssueCommand(
                        actor_id=self.actor.id,
                        operation=operation,
                        request_id=request.request_id,
                        payload_hash=payload_hash,
                        result=result.model_dump(mode="json"),
                    )
                )
                await self.session.flush()
                return result
        except IntegrityError as error:
            raise conflict() from error

    async def categories(self) -> s.IssueCategoryList:
        return s.IssueCategoryList(
            items=[
                s.IssueCategoryView.model_validate(x) for x in await self.repository.categories()
            ]
        )

    async def create_category(self, request: s.CategoryCreate) -> s.IssueCategoryView:
        async def action() -> s.IssueCategoryView:
            row = IssueCategory(**request.model_dump(exclude={"request_id"}))
            self.session.add(row)
            await self.session.flush()
            return s.IssueCategoryView.model_validate(row)

        return await self._command("category.create", request, s.IssueCategoryView, action)

    async def update_category(
        self, identity: UUID, request: s.CategoryUpdate
    ) -> s.IssueCategoryView:
        async def action() -> s.IssueCategoryView:
            row = await self._get(IssueCategory, identity, True)
            self._revision(row, request.expected_revision)
            for key, value in request.model_dump(
                exclude={"request_id", "expected_revision"}
            ).items():
                setattr(row, key, value)
            row.revision += 1
            await self.session.flush()
            return s.IssueCategoryView.model_validate(row)

        return await self._command(
            f"category.update:{identity}", request, s.IssueCategoryView, action
        )

    async def list_issues(
        self,
        q: str = "",
        status: str | None = None,
        category_id: UUID | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> s.IssueList:
        rows, total, counts = await self.repository.issues(q, status, category_id, offset, limit)
        return s.IssueList(
            items=[s.IssueView.model_validate(x) for x in rows], total=total, status_counts=counts
        )

    async def detail(self, identity: UUID) -> s.IssueDetail:
        row = await self._get(Issue, identity)
        links = await self.repository.links(identity)
        return s.IssueDetail(
            **s.IssueView.model_validate(row).model_dump(),
            events=[
                s.IssueEventView.model_validate(x) for x in await self.repository.events(identity)
            ],
            documents=[
                s.IssueDocumentLinkView(
                    document_id=link.document_id,
                    version=link.version,
                    title=document.title,
                    current_version=document.current_version,
                    source_path=version.source_path,
                    sort_order=link.sort_order,
                )
                for link, document, version in links
            ],
        )

    async def _category(self, identity: UUID, previous: UUID | None = None) -> None:
        category = await self._get(IssueCategory, identity, True)
        if not category.is_active and identity != previous:
            raise AppError(
                "issue_category_inactive", "Inactive categories cannot be assigned.", 409
            )

    def _event(
        self,
        row: Issue,
        kind: str,
        description: str,
        before: dict[str, object] | None,
        event_date: object = None,
    ) -> None:
        self.session.add(
            IssueEvent(
                issue_id=row.id,
                event_date=event_date or datetime.now(UTC).date(),
                actor_id=self.actor.id,
                kind=kind,
                description=description,
                before_revision=before["revision"] if before else None,
                after_revision=row.revision,
                snapshot={
                    "before": before,
                    "after": s.IssueView.model_validate(row).model_dump(mode="json"),
                },
            )
        )

    async def create_issue(self, request: s.IssueCreate) -> s.IssueDetail:
        async def action() -> s.IssueDetail:
            await self._category(request.category_id)
            row = Issue(**request.model_dump(exclude={"request_id"}))
            self.session.add(row)
            await self.session.flush()
            self._event(row, "created", "Issue registered.", None)
            await self.session.flush()
            return await self.detail(row.id)

        return await self._command("issue.create", request, s.IssueDetail, action)

    async def update_issue(self, identity: UUID, request: s.IssueUpdate) -> s.IssueDetail:
        async def action() -> s.IssueDetail:
            row = await self._get(Issue, identity, True)
            self._revision(row, request.expected_revision)
            await self._category(request.category_id, row.category_id)
            before = s.IssueView.model_validate(row).model_dump(mode="json")
            for key, value in request.model_dump(
                exclude={"request_id", "expected_revision"}
            ).items():
                setattr(row, key, value)
            row.revision += 1
            row.updated_at = datetime.now(UTC)
            self._event(row, "updated", "Issue updated.", before)
            await self.session.flush()
            return await self.detail(identity)

        return await self._command(f"issue.update:{identity}", request, s.IssueDetail, action)

    async def add_event(self, identity: UUID, request: s.EventCreate) -> s.IssueDetail:
        async def action() -> s.IssueDetail:
            row = await self._get(Issue, identity, True)
            self._revision(row, request.expected_revision)
            before = s.IssueView.model_validate(row).model_dump(mode="json")
            row.revision += 1
            row.updated_at = datetime.now(UTC)
            self._event(row, "progress", request.description, before, request.event_date)
            await self.session.flush()
            return await self.detail(identity)

        return await self._command(f"issue.event:{identity}", request, s.IssueDetail, action)

    async def replace_links(self, identity: UUID, request: s.LinksUpdate) -> s.IssueDetail:
        async def action() -> s.IssueDetail:
            row = await self._get(Issue, identity, True)
            self._revision(row, request.expected_revision)
            keys = [(link.document_id, link.version) for link in request.links]
            if len(set(keys)) != len(keys):
                raise conflict()
            for document_id, version in keys:
                await self.document_version(document_id, version)
            before = (await self.detail(identity)).model_dump(mode="json", exclude={"events"})
            await self.repository.remove_links(identity)
            for order, link in enumerate(request.links):
                self.session.add(
                    IssueDocumentLink(
                        issue_id=identity,
                        document_id=link.document_id,
                        version=link.version,
                        sort_order=order,
                    )
                )
            row.revision += 1
            row.updated_at = datetime.now(UTC)
            await self.session.flush()
            after = (await self.detail(identity)).model_dump(mode="json", exclude={"events"})
            self.session.add(
                IssueEvent(
                    issue_id=identity,
                    event_date=datetime.now(UTC).date(),
                    actor_id=self.actor.id,
                    kind="links_updated",
                    description="Document links updated.",
                    before_revision=request.expected_revision,
                    after_revision=row.revision,
                    snapshot={"before": before, "after": after},
                )
            )
            await self.session.flush()
            return await self.detail(identity)

        return await self._command(f"issue.links:{identity}", request, s.IssueDetail, action)

    async def documents(self) -> s.IssueDocumentList:
        return s.IssueDocumentList(
            items=[s.IssueDocumentView.model_validate(x) for x in await self.repository.documents()]
        )

    async def document_version(
        self, identity: UUID, version: int, issue_id: UUID | None = None
    ) -> s.IssueDocumentVersionView:
        if (
            issue_id is not None
            and await self.session.get(IssueDocumentLink, (issue_id, identity, version)) is None
        ):
            raise AppError("issue_history_not_found", "Linked document not found.", 404)
        document = await self._get(IssueDocument, identity)
        row = await self.session.get(IssueDocumentVersion, (identity, version))
        if row is None:
            raise AppError("issue_history_not_found", "Document version not found.", 404)
        return s.IssueDocumentVersionView(
            document_id=identity,
            version=row.version,
            title=document.title,
            current_version=document.current_version,
            content=row.content,
            sha256=row.sha256,
            source_path=row.source_path,
            source_commit=row.source_commit,
            created_at=row.created_at,
        )

    async def create_document(self, request: s.DocumentCreate) -> s.IssueDocumentVersionView:
        async def action() -> s.IssueDocumentVersionView:
            document = IssueDocument(id=uuid4(), title=request.title, current_version=1, revision=1)
            self.session.add(document)
            await self.session.flush()
            self.session.add(
                IssueDocumentVersion(
                    document_id=document.id,
                    version=1,
                    content=request.content,
                    sha256=sha256(request.content.encode()).hexdigest(),
                    source_path=request.source_path,
                    source_commit=request.source_commit,
                    actor_id=self.actor.id,
                )
            )
            await self.session.flush()
            return await self.document_version(document.id, 1)

        return await self._command("document.create", request, s.IssueDocumentVersionView, action)

    async def update_document(
        self, identity: UUID, request: s.DocumentUpdate
    ) -> s.IssueDocumentView:
        async def action() -> s.IssueDocumentView:
            row = await self._get(IssueDocument, identity, True)
            self._revision(row, request.expected_revision)
            row.title = request.title
            row.revision += 1
            row.updated_at = datetime.now(UTC)
            await self.session.flush()
            return s.IssueDocumentView.model_validate(row)

        return await self._command(
            f"document.update:{identity}", request, s.IssueDocumentView, action
        )

    async def add_version(
        self, identity: UUID, request: s.DocumentVersionCreate
    ) -> s.IssueDocumentVersionView:
        async def action() -> s.IssueDocumentVersionView:
            document = await self._get(IssueDocument, identity, True)
            self._revision(document, request.expected_revision)
            digest = sha256(request.content.encode()).hexdigest()
            existing = await self.session.scalar(
                select(IssueDocumentVersion).where(
                    IssueDocumentVersion.document_id == identity,
                    IssueDocumentVersion.sha256 == digest,
                )
            )
            if existing:
                return await self.document_version(identity, existing.version)
            version = document.current_version + 1
            self.session.add(
                IssueDocumentVersion(
                    document_id=identity,
                    version=version,
                    content=request.content,
                    sha256=digest,
                    source_path=request.source_path,
                    source_commit=request.source_commit,
                    actor_id=self.actor.id,
                )
            )
            document.current_version = version
            document.revision += 1
            document.updated_at = datetime.now(UTC)
            await self.session.flush()
            return await self.document_version(identity, version)

        return await self._command(
            f"document.version:{identity}", request, s.IssueDocumentVersionView, action
        )
