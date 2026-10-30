"""Opt-in rollback only: use existing public source/account, create no environment or account."""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import ai_workshop.main  # noqa: F401 -- register shared metadata
from ai_workshop.labs.rag.comparisons.models import ComparisonReportRecord
from ai_workshop.labs.rag.comparisons.repository import SqlComparisonRepository
from ai_workshop.labs.rag.comparisons.schemas import ComparisonImport
from ai_workshop.labs.rag.comparisons.service import ComparisonService
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.shared.db import create_engine
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.comparisons.support import payload

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_VERIFY_COMPARISON_DB") != "1",
        reason="Explicit existing database rollback verification is required.",
    ),
]


async def test_existing_public_source_import_is_immutable_idempotent_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_"):
            monkeypatch.delenv(key)
    root = Path(__file__).resolve().parents[6]
    settings = load_original_settings(root)
    fixture_path = root / "backend/tests/fixtures/rag/stored_payment_table.json"
    fixture = json.loads(fixture_path.read_bytes())
    unit = next(item for item in fixture["evidence_units"] if item["ordinal"] == 19)
    data = payload()
    data["source_key"] = f"rollback-comparison-{uuid4()}"
    data["evidence"] = [
        {
            "ref": "e1",
            "evidence_id": unit["id"],
            "document_id": fixture["document_id"],
            "asset_version_id": fixture["asset_version_id"],
            "projection_id": fixture["projection_id"],
            "index_build_id": fixture["index_build_id"],
            "retrieval_chunk_id": fixture["chunk_id"],
            "element_id": unit["element_id"],
            "title": fixture["title"],
            "text": unit["text"],
            "ordinal": unit["ordinal"],
            "page": unit["page"],
            "char_start": unit["char_start"],
            "char_end": unit["char_end"],
            "bbox": unit["bbox"],
            "source_kind": "pdf_page",
        }
    ]
    report = ComparisonImport.model_validate(data)
    engine = create_engine(settings)

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(_connection: Connection) -> None:
        raise AssertionError("Comparison verification must never commit.")

    imported_id: UUID | None = None
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                    "0067_stored_model_comparisons"
                ), "Apply the reviewed additive migration separately before this test."
                owner = await connection.scalar(
                    text(
                        "SELECT id FROM users WHERE role='owner' AND is_active "
                        "ORDER BY created_at LIMIT 1"
                    )
                )
                assert isinstance(owner, UUID), "The original active owner must exist."
                async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                    repository = SqlComparisonRepository(session)
                    service = ComparisonService(repository, repository)
                    assert await repository.accessible(owner, report)
                    first = await service.import_report(owner, report)
                    imported_id = first.id
                    duplicate = await service.import_report(owner, report)
                    assert duplicate.id == first.id
                    assert (await service.detail(owner, first.id)).report == report
                    assert first.id in [item.id for item in (await service.list(owner)).items]
                    with pytest.raises(AppError) as caught:
                        await service.import_report(
                            owner, report.model_copy(update={"title": "changed"})
                        )
                    assert caught.value.status_code == 409
                    with pytest.raises(AppError) as caught:
                        await service.detail(uuid4(), first.id)
                    assert caught.value.status_code == 404
                    wrong = report.model_copy(
                        update={
                            "evidence": [
                                report.evidence[0].model_copy(
                                    update={"text": "변조된 합성 본문"},
                                )
                            ]
                        }
                    )
                    assert not await repository.accessible(owner, wrong)
                    wrong = report.model_copy(
                        update={
                            "evidence": [
                                report.evidence[0].model_copy(
                                    update={"asset_version_id": uuid4()},
                                )
                            ]
                        }
                    )
                    assert not await repository.accessible(owner, wrong)
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.execute(
                                update(ComparisonReportRecord)
                                .where(
                                    ComparisonReportRecord.id == first.id,
                                )
                                .values(source_key="must-not-change")
                            )
                    assert (await service.detail(owner, first.id)).report == report
            finally:
                if transaction.is_active:
                    await transaction.rollback()
            assert imported_id is not None
            assert (
                await connection.scalar(
                    select(ComparisonReportRecord.id).where(
                        ComparisonReportRecord.id == imported_id,
                    )
                )
                is None
            )
    finally:
        await engine.dispose()
