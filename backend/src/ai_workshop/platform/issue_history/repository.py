from uuid import UUID

from sqlalchemy import String, cast, delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.issue_history.models import (
    Issue,
    IssueCategory,
    IssueCommand,
    IssueDocument,
    IssueDocumentLink,
    IssueDocumentVersion,
    IssueEvent,
)


class IssueRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def lock_command(self, actor: UUID, operation: str, request_id: UUID) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"issue:{actor}:{operation}:{request_id}"},
        )

    async def command(self, actor: UUID, operation: str, request_id: UUID) -> IssueCommand | None:
        return await self.session.get(IssueCommand, (actor, operation, request_id))

    async def categories(self) -> list[IssueCategory]:
        return list(
            (
                await self.session.scalars(
                    select(IssueCategory).order_by(IssueCategory.sort_order, IssueCategory.code)
                )
            ).all()
        )

    async def issues(
        self, q: str, status: str | None, category_id: UUID | None, offset: int, limit: int
    ) -> tuple[list[Issue], int, dict[str, int]]:
        filters = []
        if status:
            filters.append(Issue.status == status)
        if category_id:
            filters.append(Issue.category_id == category_id)
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            filters.append(
                or_(
                    *(
                        column.ilike(f"%{escaped}%", escape="\\")
                        for column in (
                            Issue.issue_key,
                            Issue.title,
                            Issue.symptom,
                            Issue.cause,
                            Issue.resolution,
                            cast(Issue.remaining, String),
                        )
                    )
                )
            )
        total = await self.session.scalar(select(func.count()).select_from(Issue).where(*filters))
        rows = list(
            (
                await self.session.scalars(
                    select(Issue)
                    .where(*filters)
                    .order_by(Issue.updated_at.desc(), Issue.id)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        counts = {"open": 0, "implemented": 0, "verified": 0}
        for state, count in (
            await self.session.execute(select(Issue.status, func.count()).group_by(Issue.status))
        ).all():
            counts[state] = count
        return rows, int(total or 0), counts

    async def events(self, issue_id: UUID) -> list[IssueEvent]:
        return list(
            (
                await self.session.scalars(
                    select(IssueEvent)
                    .where(IssueEvent.issue_id == issue_id)
                    .order_by(IssueEvent.event_date, IssueEvent.recorded_at, IssueEvent.id)
                )
            ).all()
        )

    async def links(
        self, issue_id: UUID
    ) -> list[tuple[IssueDocumentLink, IssueDocument, IssueDocumentVersion]]:
        result = await self.session.execute(
            select(IssueDocumentLink, IssueDocument, IssueDocumentVersion)
            .join(IssueDocument, IssueDocument.id == IssueDocumentLink.document_id)
            .join(
                IssueDocumentVersion,
                (IssueDocumentVersion.document_id == IssueDocumentLink.document_id)
                & (IssueDocumentVersion.version == IssueDocumentLink.version),
            )
            .where(IssueDocumentLink.issue_id == issue_id)
            .order_by(IssueDocumentLink.sort_order)
        )
        return [(link, document, version) for link, document, version in result.all()]

    async def documents(self) -> list[IssueDocument]:
        return list(
            (
                await self.session.scalars(
                    select(IssueDocument).order_by(
                        IssueDocument.updated_at.desc(), IssueDocument.id
                    )
                )
            ).all()
        )

    async def remove_links(self, issue_id: UUID) -> None:
        await self.session.execute(
            delete(IssueDocumentLink).where(IssueDocumentLink.issue_id == issue_id)
        )
