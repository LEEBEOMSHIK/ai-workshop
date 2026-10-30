"""Read/import observations without touching inference, executions or acceptance gates."""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from ai_workshop.labs.rag.comparisons.schemas import (
    ComparisonDetail,
    ComparisonImport,
    ComparisonList,
    ComparisonSummary,
)
from ai_workshop.shared.errors import AppError


def unavailable() -> AppError:
    return AppError("not_found", "The comparison is unavailable.", 404)


@dataclass(frozen=True)
class StoredComparison:
    id: UUID
    owner_id: UUID
    source_key: str
    source_result_sha256: str
    content_sha256: str
    payload: dict[str, object]
    completed_at: datetime
    created_at: datetime


class ComparisonStore(Protocol):
    async def find(self, actor_id: UUID, record_id: UUID) -> StoredComparison | None: ...
    async def by_key(self, actor_id: UUID, key: str) -> StoredComparison | None: ...
    async def list(self, actor_id: UUID) -> list[StoredComparison]: ...
    async def insert(self, actor_id: UUID, report: ComparisonImport) -> StoredComparison: ...


class ComparisonAccess(Protocol):
    async def accessible(self, actor_id: UUID, report: ComparisonImport) -> bool: ...


class ComparisonService:
    def __init__(self, store: ComparisonStore, access: ComparisonAccess) -> None:
        self.store, self.access = store, access

    async def _report(self, actor_id: UUID, row: StoredComparison) -> ComparisonImport | None:
        if row.owner_id != actor_id:
            return None
        try:
            report = ComparisonImport.model_validate(row.payload)
        except (ValidationError, ValueError, TypeError):
            return None
        if (
            row.source_key != report.source_key
            or row.source_result_sha256 != report.source_result_sha256
            or row.completed_at != report.completed_at
            or row.content_sha256 != hashlib.sha256(report.canonical_bytes()).hexdigest()
            or not await self.access.accessible(actor_id, report)
        ):
            return None
        return report

    @staticmethod
    def _detail(row: StoredComparison, report: ComparisonImport) -> ComparisonDetail:
        return ComparisonDetail(
            id=row.id,
            created_at=row.created_at,
            content_sha256=row.content_sha256,
            report=report,
        )

    async def import_report(self, actor_id: UUID, report: ComparisonImport) -> ComparisonDetail:
        # Do not expose an existing import before fresh source authorization succeeds.
        if not await self.access.accessible(actor_id, report):
            raise unavailable()
        row = await self.store.by_key(actor_id, report.source_key)
        if row is None:
            row = await self.store.insert(actor_id, report)
        if row.content_sha256 != hashlib.sha256(report.canonical_bytes()).hexdigest():
            raise AppError(
                "comparison_import_conflict",
                "Use a new source key for changed observations.",
                409,
            )
        fresh = await self._report(actor_id, row)
        if fresh is None:
            raise unavailable()
        return self._detail(row, fresh)

    async def list(self, actor_id: UUID) -> ComparisonList:
        result: list[ComparisonSummary] = []
        for row in await self.store.list(actor_id):
            report = await self._report(actor_id, row)
            if report is None:
                continue
            result.append(
                ComparisonSummary(
                    id=row.id,
                    source_key=row.source_key,
                    title=report.title,
                    question=report.question,
                    completed_at=report.completed_at,
                    created_at=row.created_at,
                    request_count=len(report.requests),
                    models=list(dict.fromkeys(item.model for item in report.requests)),
                    estimated_total_usd=report.estimated_total_usd,
                    billing_status=report.billing_status,
                )
            )
        return ComparisonList(items=result)

    async def detail(self, actor_id: UUID, record_id: UUID) -> ComparisonDetail:
        row = await self.store.find(actor_id, record_id)
        if row is None:
            raise unavailable()
        report = await self._report(actor_id, row)
        if report is None:
            raise unavailable()
        return self._detail(row, report)
