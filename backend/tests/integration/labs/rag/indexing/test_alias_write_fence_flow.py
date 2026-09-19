# ruff: noqa: F811
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.labs.rag.indexing.alias_journal import AliasJournal
from ai_workshop.labs.rag.indexing.alias_models import AliasOperationRecord
from ai_workshop.labs.rag.indexing.recovery import SqlAlchemyRagAliasParityReconciler
from ai_workshop.labs.rag.indexing.resource_inventory import RagIndexInventory
from ai_workshop.labs.rag.indexing.tracking_contracts import IndexTrackingError
from ai_workshop.labs.rag.indexing.write_fence import block_index_writes
from ai_workshop.labs.rag.ingestion.domain import RagIngestionError
from ai_workshop.labs.rag.ingestion.locking import lock_ingestion_source
from ai_workshop.labs.rag.ingestion.stages import ProductionReadinessVerifier
from ai_workshop.platform.assets.purge_inventory_contracts import DocumentTarget
from tests.integration.labs.rag.indexing.test_alias_parity_recovery import (
    _seed_alias_parity_fixture,
)
from tests.integration.labs.rag.indexing.test_tracked_activation import (
    Alias,
    adapters,
    cluster_probe,
    prepared_resource,
    settings,
)
from tests.integration.labs.rag.ingestion.test_artifact_repository import (
    ensure_legacy_document_processing_profile,  # noqa: F401
    migrated_database,  # noqa: F401
)


@pytest.mark.asyncio
async def test_ready_shortcut_cannot_hide_open_alias_request(migrated_database, monkeypatch):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await prepared_resource(session)

        async def resolve(*args, **kwargs):
            return SimpleNamespace(config=SimpleNamespace(dimension=3))

        monkeypatch.setattr("ai_workshop.labs.rag.ingestion.stages._resolve_embedding", resolve)
        alias = Alias()
        aliases, tracked = adapters(alias)
        verifier = ProductionReadinessVerifier(
            settings(migrated_database),
            search_index_session=aliases,
            tracked_search_session=tracked,
            alias_cluster_probe=cluster_probe,
        )
        args = dict(
            projection_id=resource.projection_id, indexing_profile_id=resource.indexing_profile_id
        )
        assert (await verifier.verify(**args)).is_complete
        await AliasJournal(sessions).reserve(
            resource.binding,
            resource.alias,
            resource.indexing_profile_id,
            resource.document_processing_profile_id,
            (resource.index_name,),
        )
        with pytest.raises(IndexTrackingError, match="attempt_busy"):
            await verifier.verify(**args)
        assert alias.calls == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fence_waits_for_real_activation_critical_section(migrated_database, monkeypatch):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    entered, release = asyncio.Event(), asyncio.Event()
    tasks = []
    try:
        async with sessions.begin() as session:
            resource = await prepared_resource(session)

        async def resolve(*args, **kwargs):
            return SimpleNamespace(config=SimpleNamespace(dimension=3))

        monkeypatch.setattr("ai_workshop.labs.rag.ingestion.stages._resolve_embedding", resolve)

        class PausedAlias(Alias):
            async def replace_active_targets(self, alias, targets):
                entered.set()
                await release.wait()
                return await super().replace_active_targets(alias, targets)

        aliases, tracked = adapters(PausedAlias())
        verifier = ProductionReadinessVerifier(
            settings(migrated_database),
            search_index_session=aliases,
            tracked_search_session=tracked,
            alias_cluster_probe=cluster_probe,
        )
        args = dict(
            projection_id=resource.projection_id, indexing_profile_id=resource.indexing_profile_id
        )
        activation = asyncio.create_task(verifier.verify(**args))
        tasks.append(activation)
        await asyncio.wait_for(entered.wait(), 5)
        fence = asyncio.create_task(
            block_index_writes(
                sessions,
                resource.workspace_id,
                resource.document_id,
                1,
            )
        )
        tasks.append(fence)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(fence), 0.15)
        release.set()
        assert (await asyncio.wait_for(activation, 5)).is_complete
        await asyncio.wait_for(fence, 5)
        with pytest.raises(RagIngestionError, match="blocked"):
            await verifier.verify(**args)
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "journal_commit"])
async def test_alias_request_survives_business_rollback_and_cannot_replay(
    migrated_database,
    monkeypatch,
    failure,
):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await prepared_resource(session)

        async def resolve(*args, **kwargs):
            return SimpleNamespace(config=SimpleNamespace(dimension=3))

        monkeypatch.setattr("ai_workshop.labs.rag.ingestion.stages._resolve_embedding", resolve)

        class AmbiguousAlias(Alias):
            async def replace_active_targets(self, alias, targets):
                await super().replace_active_targets(alias, targets)
                if failure == "timeout":
                    raise TimeoutError("synthetic private response")
                return True

        if failure == "journal_commit":

            async def failed_finish(self, operation_id):
                raise RuntimeError("synthetic private database error")

            monkeypatch.setattr(AliasJournal, "finish", failed_finish)
        alias = AmbiguousAlias()
        aliases, tracked = adapters(alias)
        verifier = ProductionReadinessVerifier(
            settings(migrated_database),
            search_index_session=aliases,
            tracked_search_session=tracked,
            alias_cluster_probe=cluster_probe,
        )
        args = dict(
            projection_id=resource.projection_id, indexing_profile_id=resource.indexing_profile_id
        )
        with pytest.raises(IndexTrackingError, match="writer_unconfirmed") as error:
            await verifier.verify(**args)
        assert "synthetic" not in str(error.value)
        async with sessions() as session:
            operation = await session.scalar(
                select(AliasOperationRecord).where(
                    AliasOperationRecord.indexing_profile_id == resource.indexing_profile_id,
                )
            )
            assert operation.state == "open"
        with pytest.raises(IndexTrackingError, match="attempt_busy"):
            await verifier.verify(**args)
        assert alias.calls == 1 and alias.targets == (resource.index_name,)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_parity_removes_fenced_document_and_preserves_other_document(migrated_database):
    configured = settings(migrated_database)
    fixture = await _seed_alias_parity_fixture(configured)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    alias = Alias()
    alias.targets = tuple(sorted(fixture.index_names))
    aliases, tracked = adapters(alias)
    try:
        await block_index_writes(sessions, fixture.workspace_id, fixture.document_ids[0], 1)
        reconciler = SqlAlchemyRagAliasParityReconciler(
            configured,
            search_index_session=aliases,
            tracked_search_session=tracked,
            alias_cluster_probe=cluster_probe,
        )
        result = await reconciler.run_once(profile_id=fixture.profile_id)
        assert result.failed == 0
        assert alias.targets == (fixture.index_names[1],)
        async with sessions() as session:
            rows = tuple(
                await session.scalars(
                    select(AliasOperationRecord).where(
                        AliasOperationRecord.indexing_profile_id == fixture.profile_id,
                    )
                )
            )
            assert len(rows) == 1 and rows[0].state == "closed"
        again = await reconciler.run_once(profile_id=fixture.profile_id)
        assert again.failed == 0 and alias.targets == (fixture.index_names[1],)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_inventory_open_alias_and_changes_are_not_complete(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await prepared_resource(session)
        _, tracked = adapters(Alias())
        args = (
            resource.workspace_id,
            (DocumentTarget(resource.document_id, 1, (resource.asset_version_id,)),),
        )
        async with tracked() as inspector:
            inventory = RagIndexInventory(engine, inspector)
            assert (await inventory.collect(*args)).exhausted
            operation_id = await AliasJournal(sessions).reserve(
                resource.binding,
                resource.alias,
                resource.indexing_profile_id,
                resource.document_processing_profile_id,
                (resource.index_name,),
            )
            assert not (await inventory.collect(*args)).exhausted

            class ChangedInspector:
                async def observe(self, item, ids):
                    await AliasJournal(sessions).finish(operation_id)
                    return await inspector.observe(item, ids)

            with pytest.raises(IndexTrackingError, match="inventory_changed"):
                await RagIndexInventory(engine, ChangedInspector()).collect(*args)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fence_blocks_both_source_modes_and_survives_worker_restart(migrated_database):
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            resource = await prepared_resource(session)
        await block_index_writes(
            sessions,
            resource.workspace_id,
            resource.document_id,
            1,
        )
        for require_active in (True, False):
            async with sessions.begin() as session:
                with pytest.raises(RagIngestionError, match="blocked"):
                    await lock_ingestion_source(
                        session,
                        resource.asset_version_id,
                        require_active=require_active,
                    )
    finally:
        await engine.dispose()
