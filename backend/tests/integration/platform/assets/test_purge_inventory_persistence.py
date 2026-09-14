from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, func, inspect, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.platform.assets.models import DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity
from ai_workshop.platform.assets.purge_contracts import CleanupReceipt
from ai_workshop.platform.assets.purge_inventory_contracts import (
    BoundCleanupReceipt,
    DocumentTarget,
    FolderTarget,
    ParticipantInventory,
    PurgeInventory,
    inventory_binding,
)
from ai_workshop.platform.assets.purge_inventory_models import (
    AssetPurgeInventoryParticipantRecord,
    AssetPurgeInventoryRecord,
    AssetPurgeReceiptRecord,
)
from ai_workshop.platform.assets.purge_inventory_repository import (
    PurgeInventoryRepository,
)
from ai_workshop.platform.assets.purge_models import AssetPurgeJobRecord
from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@dataclass(frozen=True, slots=True)
class InventorySeed:
    actor_id: UUID
    workspace_ids: tuple[UUID, UUID]
    policy_versions: tuple[int, int]
    batch_ids: tuple[UUID, UUID]
    job_ids: tuple[UUID, UUID]
    folder_ids: tuple[UUID, UUID]
    document_ids: tuple[UUID, UUID]
    version_ids: tuple[tuple[UUID, ...], tuple[UUID, ...]]


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def _isolated_database_at(revision: str) -> Iterator[IsolatedPublishingDatabase]:
    monkeypatch = pytest.MonkeyPatch()
    try:
        with isolated_publishing_database(monkeypatch) as database:
            command.upgrade(database.config, revision)
            yield database
    finally:
        monkeypatch.undo()


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[IsolatedPublishingDatabase]:
    with _isolated_database_at("0039_asset_purge_inventory") as database:
        yield database


def _seed_inventory_batch(connection: psycopg.Connection[Any]) -> InventorySeed:
    actor_id = uuid4()
    email = f"purge-inventory-{actor_id}@example.test"
    connection.execute(
        "INSERT INTO users(id,display_name,email,normalized_email,password_hash,role,"
        "is_active,created_at,updated_at) VALUES (%s,'Synthetic inventory owner',%s,%s,"
        "'hash','member',true,now(),now())",
        (actor_id, email, email),
    )
    workspace_ids = (uuid4(), uuid4())
    policy_versions = (3, 5)
    batch_ids = (uuid4(), uuid4())
    job_ids = (uuid4(), uuid4())
    folder_ids = (uuid4(), uuid4())
    document_ids = (uuid4(), uuid4())
    version_ids = ((uuid4(), uuid4()), (uuid4(),))
    for index in range(2):
        workspace_id = workspace_ids[index]
        connection.execute(
            "INSERT INTO workspaces(id,name,kind,created_by,created_at,updated_at) "
            "VALUES (%s,%s,'company',%s,now(),now())",
            (workspace_id, f"Synthetic inventory {index}", actor_id),
        )
        policy_id = uuid4()
        connection.execute(
            "INSERT INTO asset_retention_policies"
            "(id,workspace_id,version,days,created_by,created_at) "
            "VALUES (%s,%s,%s,30,%s,now())",
            (policy_id, workspace_id, policy_versions[index], actor_id),
        )
        connection.execute(
            "INSERT INTO asset_trash_batches"
            "(id,workspace_id,actor_id,policy_version_id,trashed_at,purge_after,created_at) "
            "VALUES (%s,%s,%s,%s,now()-interval '31 days',now()-interval '1 day',now())",
            (batch_ids[index], workspace_id, actor_id, policy_id),
        )
        connection.execute(
            "INSERT INTO folders"
            "(id,workspace_id,parent_id,name,metadata_revision,lifecycle,"
            "lifecycle_generation,trash_batch_id,trashed_at,purge_after,created_at,updated_at) "
            "VALUES (%s,%s,NULL,%s,1,'purging',%s,%s,now()-interval '31 days',"
            "now()-interval '1 day',now(),now())",
            (folder_ids[index], workspace_id, f"folder-{index}", 7 + index, batch_ids[index]),
        )
        connection.execute(
            "INSERT INTO documents"
            "(id,workspace_id,folder_id,name,active_version_id,metadata_revision,lifecycle,"
            "lifecycle_generation,trash_batch_id,trashed_at,purge_after,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,%s,1,'purging',%s,%s,now()-interval '31 days',"
            "now()-interval '1 day',now(),now())",
            (
                document_ids[index],
                workspace_id,
                folder_ids[index],
                f"document-{index}.txt",
                version_ids[index][-1],
                11 + index,
                batch_ids[index],
            ),
        )
        for number, version_id in enumerate(version_ids[index], start=1):
            connection.execute(
                "INSERT INTO asset_versions"
                "(id,document_id,number,object_key,sha256,media_type,size,status,"
                "created_at,updated_at) VALUES (%s,%s,%s,%s,%s,'text/plain',1,'ready',"
                "now(),now())",
                (
                    version_id,
                    document_ids[index],
                    number,
                    f"synthetic/{version_id}",
                    f"{index + number:064x}",
                ),
            )
        connection.execute(
            "INSERT INTO asset_purge_jobs"
            "(id,workspace_id,trash_batch_id,request_key,status,attempt_count,available_at,"
            "error_code,finished_at,created_at,updated_at) "
            "VALUES (%s,%s,%s,%s,'purging',1,now(),NULL,NULL,now(),now())",
            (job_ids[index], workspace_id, batch_ids[index], f"inventory-{uuid4()}"),
        )
    return InventorySeed(
        actor_id,
        workspace_ids,
        policy_versions,
        batch_ids,
        job_ids,
        folder_ids,
        document_ids,
        version_ids,
    )


def _assert_rejected(
    connection: psycopg.Connection[Any],
    statement: str,
    parameters: tuple[object, ...],
) -> None:
    with pytest.raises(psycopg.Error), connection.transaction():
        connection.execute(statement, parameters)


def _inventory(
    seed: InventorySeed,
    *,
    index: int = 0,
    version: int = 1,
    document_generation: int | None = None,
    folder_generation: int | None = None,
    asset_version_ids: tuple[UUID, ...] | None = None,
    resource_revision: int = 1,
) -> PurgeInventory:
    resource = ResourceIdentity("rag", "projection", uuid4(), resource_revision)
    return PurgeInventory(
        workspace_id=seed.workspace_ids[index],
        job_id=seed.job_ids[index],
        version=version,
        documents=(
            DocumentTarget(
                seed.document_ids[index],
                11 + index if document_generation is None else document_generation,
                tuple(sorted(seed.version_ids[index]))
                if asset_version_ids is None
                else asset_version_ids,
            ),
        ),
        folders=(
            FolderTarget(
                seed.folder_ids[index],
                7 + index if folder_generation is None else folder_generation,
            ),
        ),
        participants=(
            ParticipantInventory(
                participant="rag",
                contract_version=2,
                resources=(resource,),
                exhausted=True,
                supported=True,
                legacy_resolved=True,
            ),
        ),
    )


def _receipt(inventory: PurgeInventory, *, attempt: int = 1) -> BoundCleanupReceipt:
    return BoundCleanupReceipt(
        job_id=inventory.job_id,
        inventory_version=inventory.version,
        inventory_binding=inventory_binding(inventory),
        participant_contract_version=2,
        attempt=attempt,
        checked_at=datetime(2026, 9, 14, 12, 30, tzinfo=UTC),
        receipt=CleanupReceipt("rag", 2, 0, 0, True),
    )


@pytest.mark.asyncio
async def test_repository_round_trips_sequential_versions_and_isolates_attempts(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    with psycopg.connect(_psycopg_url(migrated_database.database_url)) as connection:
        seed = _seed_inventory_batch(connection)
    first = _inventory(seed)
    second = _inventory(seed, version=2, resource_revision=2)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            repository = PurgeInventoryRepository(session)
            await repository.save_inventory(first)
            assert await repository.load_inventory(
                first.workspace_id, first.job_id, first.version
            ) == first
            with pytest.raises(ValueError, match="version"):
                await repository.save_inventory(first)
            with pytest.raises(ValueError, match="version"):
                await repository.save_inventory(replace(second, version=3))
            await repository.save_inventory(second)
            assert await repository.load_inventory(
                second.workspace_id, second.job_id, second.version
            ) == second
            with pytest.raises(ValueError, match="latest inventory"):
                await repository.save_receipt(first.workspace_id, _receipt(first))
            await repository.save_receipt(second.workspace_id, _receipt(second))
            with pytest.raises(ValueError, match="duplicate"):
                await repository.save_receipt(second.workspace_id, _receipt(second))
            await session.execute(
                update(AssetPurgeJobRecord)
                .where(AssetPurgeJobRecord.id == second.job_id)
                .values(attempt_count=2)
            )
            with pytest.raises(ValueError, match="attempt"):
                await repository.save_receipt(second.workspace_id, _receipt(second))
            await repository.save_receipt(
                second.workspace_id, _receipt(second, attempt=2)
            )
            assert await session.scalar(
                select(func.count())
                .select_from(AssetPurgeReceiptRecord)
                .join(
                    AssetPurgeInventoryRecord,
                    AssetPurgeInventoryRecord.id
                    == AssetPurgeReceiptRecord.inventory_id,
                )
                .where(AssetPurgeInventoryRecord.job_id == second.job_id)
            ) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    (
        "mixed_workspace_job",
        "missing_version",
        "document_generation",
        "folder_generation",
        "wrong_batch",
    ),
)
async def test_save_inventory_rejects_targets_not_exactly_in_the_locked_batch(
    migrated_database: IsolatedPublishingDatabase,
    mutation: str,
) -> None:
    with psycopg.connect(_psycopg_url(migrated_database.database_url)) as connection:
        seed = _seed_inventory_batch(connection)
    inventory = _inventory(seed)
    if mutation == "mixed_workspace_job":
        inventory = replace(inventory, workspace_id=seed.workspace_ids[1])
    elif mutation == "missing_version":
        inventory = replace(
            inventory,
            documents=(
                replace(
                    inventory.documents[0],
                    asset_version_ids=(seed.version_ids[0][0],),
                ),
            ),
        )
    elif mutation == "document_generation":
        inventory = replace(
            inventory,
            documents=(replace(inventory.documents[0], generation=12),),
        )
    elif mutation == "folder_generation":
        inventory = replace(
            inventory,
            folders=(replace(inventory.folders[0], generation=8),),
        )
    else:
        inventory = replace(
            inventory,
            documents=(
                DocumentTarget(seed.document_ids[1], 12, seed.version_ids[1]),
            ),
        )

    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            with pytest.raises(ValueError, match="job|batch|target|version|generation"):
                await PurgeInventoryRepository(session).save_inventory(inventory)
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repository_flushes_without_committing(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    with psycopg.connect(_psycopg_url(migrated_database.database_url)) as connection:
        seed = _seed_inventory_batch(connection)
    inventory = _inventory(seed)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            await PurgeInventoryRepository(session).save_inventory(inventory)
            assert await session.scalar(
                select(func.count()).select_from(AssetPurgeInventoryRecord).where(
                    AssetPurgeInventoryRecord.job_id == inventory.job_id
                )
            ) == 1
            await session.rollback()
        async with sessions() as session:
            assert await session.scalar(
                select(func.count()).select_from(AssetPurgeInventoryRecord).where(
                    AssetPurgeInventoryRecord.job_id == inventory.job_id
                )
            ) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_save_inventory_rechecks_generation_despite_a_stale_identity_map(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_inventory_batch(connection)
    inventory = _inventory(seed)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            cached = await session.get(DocumentRecord, seed.document_ids[0])
            assert cached is not None and cached.lifecycle_generation == 11
            with psycopg.connect(url) as connection:
                connection.execute(
                    "UPDATE documents SET lifecycle_generation=12 WHERE id=%s",
                    (seed.document_ids[0],),
                )
            with pytest.raises(ValueError, match="generation"):
                await PurgeInventoryRepository(session).save_inventory(inventory)
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_save_inventory_locks_batch_against_new_member_until_rollback(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_inventory_batch(connection)
    inventory = _inventory(seed)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            await PurgeInventoryRepository(session).save_inventory(inventory)
            with psycopg.connect(url) as contender:
                contender.execute("SET lock_timeout = '250ms'")
                contender.commit()
                try:
                    with pytest.raises(
                        psycopg.errors.LockNotAvailable, match="lock timeout"
                    ):
                        contender.execute(
                            "INSERT INTO folders"
                            "(id,workspace_id,parent_id,name,metadata_revision,lifecycle,"
                            "lifecycle_generation,trash_batch_id,trashed_at,purge_after,"
                            "created_at,updated_at) VALUES (%s,%s,NULL,%s,1,'purging',1,%s,"
                            "now()-interval '31 days',now()-interval '1 day',now(),now())",
                            (
                                uuid4(),
                                inventory.workspace_id,
                                f"late-member-{uuid4()}",
                                seed.batch_ids[0],
                            ),
                        )
                finally:
                    contender.rollback()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_save_inventory_locks_existing_versions_against_deletion_until_rollback(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_inventory_batch(connection)
    inventory = _inventory(seed)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            await PurgeInventoryRepository(session).save_inventory(inventory)
            with psycopg.connect(url) as contender:
                contender.execute("SET lock_timeout = '250ms'")
                contender.commit()
                try:
                    with pytest.raises(
                        psycopg.errors.LockNotAvailable, match="lock timeout"
                    ):
                        contender.execute(
                            "DELETE FROM asset_versions WHERE id=%s",
                            (seed.version_ids[0][0],),
                        )
                finally:
                    contender.rollback()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_load_inventory_refreshes_a_stale_cached_header(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_inventory_batch(connection)
    inventory = _inventory(seed)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await PurgeInventoryRepository(session).save_inventory(inventory)
        async with sessions() as session:
            cached = await session.scalar(
                select(AssetPurgeInventoryRecord).where(
                    AssetPurgeInventoryRecord.job_id == inventory.job_id
                )
            )
            assert cached is not None and cached.binding == inventory_binding(inventory)
            with psycopg.connect(url) as connection:
                connection.execute(
                    "UPDATE asset_purge_inventories SET binding=%s WHERE id=%s",
                    ("f" * 64, cached.id),
                )
            with pytest.raises(ValueError, match="binding"):
                await PurgeInventoryRepository(session).load_inventory(
                    inventory.workspace_id,
                    inventory.job_id,
                    inventory.version,
                )
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_field", ("inventory_binding", "participant_contract"))
async def test_save_receipt_refreshes_stale_cached_contract_rows(
    migrated_database: IsolatedPublishingDatabase,
    stale_field: str,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_inventory_batch(connection)
    inventory = _inventory(seed)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await PurgeInventoryRepository(session).save_inventory(inventory)
        async with sessions() as session:
            cached_inventory = await session.scalar(
                select(AssetPurgeInventoryRecord).where(
                    AssetPurgeInventoryRecord.job_id == inventory.job_id
                )
            )
            assert cached_inventory is not None
            cached_participant = await session.scalar(
                select(AssetPurgeInventoryParticipantRecord).where(
                    AssetPurgeInventoryParticipantRecord.inventory_id
                    == cached_inventory.id
                )
            )
            assert cached_participant is not None
            with psycopg.connect(url) as connection:
                if stale_field == "inventory_binding":
                    connection.execute(
                        "UPDATE asset_purge_inventories SET binding=%s WHERE id=%s",
                        ("f" * 64, cached_inventory.id),
                    )
                    expected_error = "latest inventory"
                else:
                    connection.execute(
                        "UPDATE asset_purge_inventory_participants "
                        "SET contract_version=3 WHERE inventory_id=%s",
                        (cached_inventory.id,),
                    )
                    expected_error = "participant contract"
            with pytest.raises(ValueError, match=expected_error):
                await PurgeInventoryRepository(session).save_receipt(
                    inventory.workspace_id,
                    _receipt(inventory),
                )
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_load_inventory_rejects_details_that_do_not_match_stored_binding(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_inventory_batch(connection)
    inventory = _inventory(seed)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await PurgeInventoryRepository(session).save_inventory(inventory)
        with psycopg.connect(url) as connection:
            connection.execute(
                "UPDATE asset_purge_inventory_targets SET generation=12 "
                "WHERE inventory_id IN "
                "(SELECT id FROM asset_purge_inventories WHERE job_id=%s)",
                (seed.job_ids[0],),
            )
        async with sessions() as session:
            with pytest.raises(ValueError, match="binding"):
                await PurgeInventoryRepository(session).load_inventory(
                    inventory.workspace_id,
                    inventory.job_id,
                    inventory.version,
                )
    finally:
        await engine.dispose()


def test_database_enforces_inventory_receipt_shape_and_restricts_detail_loss(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    with psycopg.connect(_psycopg_url(migrated_database.database_url)) as connection:
        seed = _seed_inventory_batch(connection)
        inventory_id = uuid4()
        connection.execute(
            "INSERT INTO asset_purge_inventories"
            "(id,workspace_id,job_id,version,binding,created_at) "
            "VALUES (%s,%s,%s,1,%s,now())",
            (inventory_id, seed.workspace_ids[0], seed.job_ids[0], "a" * 64),
        )
        _assert_rejected(
            connection,
            "INSERT INTO asset_purge_inventories"
            "(id,workspace_id,job_id,version,binding,created_at) "
            "VALUES (%s,%s,%s,1,%s,now())",
            (uuid4(), seed.workspace_ids[1], seed.job_ids[0], "a" * 64),
        )
        _assert_rejected(
            connection,
            "INSERT INTO asset_purge_inventory_targets"
            "(id,workspace_id,inventory_id,target_kind,target_id,generation,asset_version_id) "
            "VALUES (%s,%s,%s,'folder',%s,7,%s)",
            (
                uuid4(),
                seed.workspace_ids[0],
                inventory_id,
                seed.folder_ids[0],
                seed.version_ids[0][0],
            ),
        )
        connection.execute(
            "INSERT INTO asset_purge_inventory_targets"
            "(id,workspace_id,inventory_id,target_kind,target_id,generation,asset_version_id) "
            "VALUES (%s,%s,%s,'folder',%s,7,NULL)",
            (uuid4(), seed.workspace_ids[0], inventory_id, seed.folder_ids[0]),
        )
        _assert_rejected(
            connection,
            "INSERT INTO asset_purge_inventory_targets"
            "(id,workspace_id,inventory_id,target_kind,target_id,generation,asset_version_id) "
            "VALUES (%s,%s,%s,'folder',%s,7,NULL)",
            (uuid4(), seed.workspace_ids[0], inventory_id, seed.folder_ids[0]),
        )
        _assert_rejected(
            connection,
            "INSERT INTO asset_purge_inventory_participants"
            "(workspace_id,inventory_id,participant,contract_version,exhausted,supported,"
            "legacy_resolved) VALUES (%s,%s,'Rag',1,true,true,true)",
            (seed.workspace_ids[0], inventory_id),
        )
        connection.execute(
            "INSERT INTO asset_purge_inventory_participants"
            "(workspace_id,inventory_id,participant,contract_version,exhausted,supported,"
            "legacy_resolved) VALUES (%s,%s,'rag',2,true,true,true)",
            (seed.workspace_ids[0], inventory_id),
        )
        _assert_rejected(
            connection,
            "INSERT INTO asset_purge_inventory_resources"
            "(workspace_id,inventory_id,participant,kind,resource_id,resource_revision) "
            "VALUES (%s,%s,'rag','projection',%s,0)",
            (seed.workspace_ids[0], inventory_id, uuid4()),
        )
        _assert_rejected(
            connection,
            "INSERT INTO asset_purge_receipts"
            "(workspace_id,inventory_id,participant,attempt,checked_at,binding,"
            "contract_version,deleted,retained_shared,residual_owned,verified) "
            "VALUES (%s,%s,'rag',1,now(),%s,2,-1,0,0,true)",
            (seed.workspace_ids[0], inventory_id, "a" * 64),
        )
        _assert_rejected(
            connection,
            "DELETE FROM asset_purge_inventories WHERE id=%s",
            (inventory_id,),
        )
        digest_types = {
            (table_name, column_name): data_type
            for table_name, column_name, data_type in connection.execute(
                "SELECT table_name,column_name,data_type FROM information_schema.columns "
                "WHERE table_schema=current_schema() AND "
                "((table_name='asset_purge_inventories' AND column_name='binding') OR "
                "(table_name='asset_purge_receipts' AND column_name='binding') OR "
                "(table_name='asset_purge_proofs' AND "
                "column_name IN ('inventory_binding','binding')))"
            ).fetchall()
        }
        assert digest_types == {
            ("asset_purge_inventories", "binding"): "character",
            ("asset_purge_receipts", "binding"): "character",
            ("asset_purge_proofs", "inventory_binding"): "character",
            ("asset_purge_proofs", "binding"): "character",
        }


def test_0038_to_0039_preserves_existing_provenance_and_empty_downgrade() -> None:
    with _isolated_database_at("0038_asset_provenance") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            actor_id, workspace_id, document_id, version_id = (
                uuid4(),
                uuid4(),
                uuid4(),
                uuid4(),
            )
            email = f"migration-{actor_id}@example.test"
            connection.execute(
                "INSERT INTO users(id,display_name,email,normalized_email,password_hash,"
                "role,is_active,created_at,updated_at) VALUES (%s,'Migration owner',%s,%s,"
                "'hash','member',true,now(),now())",
                (actor_id, email, email),
            )
            connection.execute(
                "INSERT INTO workspaces(id,name,kind,created_by,created_at,updated_at) "
                "VALUES (%s,'Migration workspace','company',%s,now(),now())",
                (workspace_id, actor_id),
            )
            connection.execute(
                "INSERT INTO documents(id,workspace_id,folder_id,name,active_version_id,"
                "metadata_revision,created_at,updated_at) "
                "VALUES (%s,%s,NULL,'migration.txt',%s,1,now(),now())",
                (document_id, workspace_id, version_id),
            )
            connection.execute(
                "INSERT INTO asset_versions(id,document_id,number,object_key,sha256,"
                "media_type,size,status,created_at,updated_at) "
                "VALUES (%s,%s,1,%s,%s,'text/plain',1,'ready',now(),now())",
                (version_id, document_id, f"migration/{version_id}", "c" * 64),
            )
            relation_id = uuid4()
            connection.execute(
                "INSERT INTO asset_source_relations"
                "(id,workspace_id,document_id,asset_version_id,participant,kind,resource_id,"
                "resource_revision,relation_kind,created_at) "
                "VALUES (%s,%s,%s,%s,'rag','projection',%s,1,'derived_artifact',now())",
                (relation_id, workspace_id, document_id, version_id, uuid4()),
            )

        command.upgrade(database.config, "0039_asset_purge_inventory")
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT id FROM asset_source_relations WHERE id=%s", (relation_id,)
            ).fetchone() == (relation_id,)
        command.downgrade(database.config, "0038_asset_provenance")
        engine = create_engine(database.database_url)
        try:
            assert not inspect(engine).has_table("asset_purge_inventories")
            assert inspect(engine).has_table("asset_source_relations")
        finally:
            engine.dispose()
        with psycopg.connect(url) as connection:
            assert connection.execute(
                "SELECT id FROM asset_source_relations WHERE id=%s", (relation_id,)
            ).fetchone() == (relation_id,)


@pytest.mark.parametrize("retained_table", ("inventory", "proof"))
def test_nonempty_0039_downgrade_is_rejected_without_data_loss(
    retained_table: str,
) -> None:
    with _isolated_database_at("0039_asset_purge_inventory") as database:
        url = _psycopg_url(database.database_url)
        with psycopg.connect(url) as connection:
            seed = _seed_inventory_batch(connection)
            retained_id = uuid4()
            if retained_table == "inventory":
                connection.execute(
                    "INSERT INTO asset_purge_inventories"
                    "(id,workspace_id,job_id,version,binding,created_at) "
                    "VALUES (%s,%s,%s,1,%s,now())",
                    (retained_id, seed.workspace_ids[0], seed.job_ids[0], "d" * 64),
                )
            else:
                connection.execute(
                    "INSERT INTO asset_purge_proofs"
                    "(id,workspace_id,job_id,inventory_version,inventory_binding,binding,"
                    "actor_id,policy_version,finished_at,backup_state,external_state) "
                    "VALUES (%s,%s,%s,1,%s,%s,%s,%s,now(),'pending','unverified')",
                    (
                        retained_id,
                        seed.workspace_ids[0],
                        seed.job_ids[0],
                        "d" * 64,
                        "e" * 64,
                        seed.actor_id,
                        seed.policy_versions[0],
                    ),
                )

        with pytest.raises(RuntimeError, match="asset_purge_inventory_downgrade_unsafe"):
            command.downgrade(database.config, "0038_asset_provenance")
        with psycopg.connect(url) as connection:
            table_name = (
                "asset_purge_inventories"
                if retained_table == "inventory"
                else "asset_purge_proofs"
            )
            assert connection.execute(
                f"SELECT id FROM {table_name} WHERE id=%s", (retained_id,)
            ).fetchone() == (retained_id,)
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0039_asset_purge_inventory",)


def test_model_registry_resolves_all_0039_foreign_keys_in_a_fresh_process() -> None:
    backend_root = Path(__file__).resolve().parents[4]
    script = """
from ai_workshop.shared.model_registry import load_models
from ai_workshop.shared.models import Base
load_models()
tables = (
    'asset_purge_inventories',
    'asset_purge_inventory_targets',
    'asset_purge_inventory_participants',
    'asset_purge_inventory_resources',
    'asset_purge_receipts',
    'asset_purge_proofs',
    'asset_purge_proof_targets',
    'asset_purge_proof_participants',
)
for table_name in tables:
    table = Base.metadata.tables[table_name]
    for foreign_key in table.foreign_keys:
        foreign_key.column
proof_columns = set(Base.metadata.tables['asset_purge_proofs'].columns.keys())
assert proof_columns.isdisjoint(
    {'body', 'path', 'filename', 'object_key', 'sha256', 'query', 'payload'}
)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=backend_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
