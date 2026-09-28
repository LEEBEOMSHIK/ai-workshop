"""Original database snapshot access; permission mutations always roll back."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401
from ai_workshop.config import get_settings
from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits
from ai_workshop.labs.rag.evaluation.authoring_repository import SqlAlchemyAuthoringRepository
from ai_workshop.labs.rag.evaluation.models import EvaluationDatasetRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.trash_models import (
    AssetRetentionPolicyRecord,
    AssetTrashBatchRecord,
)
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord
from ai_workshop.shared.db import create_engine


@pytest.mark.asyncio
async def test_saved_original_snapshot_owner_and_revoked_source_access():
    engine = create_engine(get_settings())
    try:
        async with async_sessionmaker(engine)() as session:
            records = (
                await session.scalars(
                    select(EvaluationDatasetRecord).order_by(
                        EvaluationDatasetRecord.created_at.desc()
                    )
                )
            ).all()
            record = next(
                item
                for item in records
                if json.loads(item.fixture_bytes).get("authoring_scope_sha256")
            )
            repository = SqlAlchemyAuthoringRepository(
                session, inspector=None, limits=AuthoringLimits()
            )
            dataset = await repository.load_snapshot(record.owner_id, record.id)
            assert dataset is not None
            assert dataset.fixture_bytes == record.fixture_bytes
            assert await repository.load_snapshot(uuid4(), record.id) is None
            source = dataset.document_snapshot[0]
            asset_id = UUID(str(source["asset_version_id"]))
            document_id = UUID(str(source["document_id"]))
            now = datetime.now(UTC)
            batch = uuid4()
            workspace = dataset.cases[0].permission_scenario.workspace_ids[0]
            for index, (statement, visible) in enumerate(
                [
                    (
                        update(AssetVersionRecord)
                        .where(AssetVersionRecord.id == asset_id)
                        .values(sha256="0" * 64),
                        False,
                    ),
                    (
                        update(AssetVersionRecord)
                        .where(AssetVersionRecord.id == asset_id)
                        .values(status="failed"),
                        False,
                    ),
                    (
                        update(DocumentRecord)
                        .where(DocumentRecord.id == document_id)
                        .values(
                            lifecycle="trashed",
                            trash_batch_id=batch,
                            trashed_at=now,
                            purge_after=now + timedelta(days=1),
                        ),
                        False,
                    ),
                    (
                        update(DocumentRecord)
                        .where(DocumentRecord.id == document_id)
                        .values(active_version_id=None),
                        True,
                    ),
                ]
            ):
                savepoint = await session.begin_nested()
                try:
                    if index == 2:
                        policy = await session.scalar(
                            select(AssetRetentionPolicyRecord)
                            .where(AssetRetentionPolicyRecord.workspace_id == workspace)
                            .limit(1)
                        )
                        if policy is None:
                            policy = AssetRetentionPolicyRecord(
                                id=uuid4(),
                                workspace_id=workspace,
                                version=1,
                                days=1,
                                created_by=record.owner_id,
                            )
                            session.add(policy)
                            await session.flush()
                        session.add(
                            AssetTrashBatchRecord(
                                id=batch,
                                workspace_id=workspace,
                                actor_id=record.owner_id,
                                policy_version_id=policy.id,
                                trashed_at=now,
                                purge_after=now + timedelta(days=1),
                            )
                        )
                        await session.flush()
                    await session.execute(statement)
                    assert (
                        await repository.load_snapshot(record.owner_id, record.id) is not None
                    ) == visible
                finally:
                    await savepoint.rollback()
                assert await repository.load_snapshot(record.owner_id, record.id) is not None
            workspace = dataset.cases[0].permission_scenario.workspace_ids[0]
            savepoint = await session.begin_nested()
            try:
                await session.execute(
                    delete(WorkspaceMembershipRecord).where(
                        WorkspaceMembershipRecord.workspace_id == workspace,
                        WorkspaceMembershipRecord.user_id == record.owner_id,
                    )
                )
                assert await repository.load_snapshot(record.owner_id, record.id) is None
            finally:
                await savepoint.rollback()
            assert await repository.load_snapshot(record.owner_id, record.id) is not None
    finally:
        await engine.dispose()
