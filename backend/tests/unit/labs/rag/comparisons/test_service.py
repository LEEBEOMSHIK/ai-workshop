import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.comparisons.schemas import ComparisonImport
from ai_workshop.labs.rag.comparisons.service import ComparisonService, StoredComparison
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.comparisons.support import payload

ACTOR = UUID("20000000-0000-0000-0000-000000000001")
OTHER = UUID("20000000-0000-0000-0000-000000000002")


class MemoryStore:
    def __init__(self) -> None:
        self.rows: list[StoredComparison] = []
        self.allowed = True
        self.access_calls = 0

    async def find(self, actor_id: UUID, record_id: UUID) -> StoredComparison | None:
        return next((r for r in self.rows if r.id == record_id and r.owner_id == actor_id), None)

    async def by_key(self, actor_id: UUID, key: str) -> StoredComparison | None:
        return next((r for r in self.rows if r.source_key == key and r.owner_id == actor_id), None)

    async def list(self, actor_id: UUID) -> list[StoredComparison]:
        return [r for r in self.rows if r.owner_id == actor_id]

    async def insert(self, actor_id: UUID, report: ComparisonImport) -> StoredComparison:
        row = StoredComparison(
            id=uuid4(),
            owner_id=actor_id,
            source_key=report.source_key,
            source_result_sha256=report.source_result_sha256,
            completed_at=report.completed_at,
            created_at=datetime.now(UTC),
            content_sha256=hashlib.sha256(report.canonical_bytes()).hexdigest(),
            payload=report.model_dump(mode="json"),
        )
        self.rows.append(row)
        return row

    async def accessible(self, actor_id: UUID, report: ComparisonImport) -> bool:
        self.access_calls += 1
        return self.allowed


async def test_import_is_idempotent_and_conflicting_body_rejected() -> None:
    store = MemoryStore()
    service = ComparisonService(store, store)
    report = ComparisonImport.model_validate(payload())
    first = await service.import_report(ACTOR, report)
    second = await service.import_report(ACTOR, report)
    assert first.id == second.id and len(store.rows) == 1
    changed = report.model_copy(update={"title": "다른 제목"})
    with pytest.raises(AppError) as caught:
        await service.import_report(ACTOR, changed)
    assert caught.value.status_code == 409


async def test_owner_and_current_source_access_revalidated_on_each_read() -> None:
    store = MemoryStore()
    service = ComparisonService(store, store)
    detail = await service.import_report(ACTOR, ComparisonImport.model_validate(payload()))
    assert len((await service.list(ACTOR)).items) == 1
    assert (await service.detail(ACTOR, detail.id)).id == detail.id
    assert (await service.list(OTHER)).items == []
    with pytest.raises(AppError) as caught:
        await service.detail(OTHER, detail.id)
    assert caught.value.status_code == 404
    store.allowed = False
    assert (await service.list(ACTOR)).items == []
    with pytest.raises(AppError) as caught:
        await service.detail(ACTOR, detail.id)
    assert caught.value.status_code == 404
    with pytest.raises(AppError):
        await service.import_report(ACTOR, ComparisonImport.model_validate(payload()))
    assert len(store.rows) == 1


async def test_corrupt_stored_body_fails_closed_and_does_not_break_other_reports() -> None:
    store = MemoryStore()
    service = ComparisonService(store, store)
    report = ComparisonImport.model_validate(payload())
    detail = await service.import_report(ACTOR, report)
    store.rows[0] = replace(store.rows[0], payload={**store.rows[0].payload, "title": "변조"})
    assert (await service.list(ACTOR)).items == []
    with pytest.raises(AppError):
        await service.detail(ACTOR, detail.id)


async def test_summary_uses_recorded_completion_and_never_claims_execution() -> None:
    store = MemoryStore()
    service = ComparisonService(store, store)
    await service.import_report(ACTOR, ComparisonImport.model_validate(payload()))
    summary = (await service.list(ACTOR)).items[0]
    assert summary.record_kind == "imported_comparison"
    assert summary.request_count == 2
    assert summary.unique_question_count == 1
    assert summary.models == ["synthetic-model"]
    assert summary.estimated_total_usd is None
