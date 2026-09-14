from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.platform.assets.models import (
    AssetVersionRecord,
    DocumentRecord,
    FolderRecord,
)
from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity
from ai_workshop.platform.assets.purge_contracts import CleanupReceipt
from ai_workshop.platform.assets.purge_inventory_contracts import (
    BoundCleanupReceipt,
    DocumentTarget,
    FolderTarget,
    ParticipantInventory,
    PurgeInventory,
    inventory_binding,
    retained_proof_binding,
)
from ai_workshop.platform.assets.purge_inventory_models import (
    AssetPurgeInventoryParticipantRecord,
    AssetPurgeInventoryRecord,
    AssetPurgeInventoryResourceRecord,
    AssetPurgeInventoryTargetRecord,
    AssetPurgeReceiptRecord,
)
from ai_workshop.platform.assets.purge_inventory_repository import (
    PurgeInventoryRepository,
)
from ai_workshop.platform.assets.purge_models import AssetPurgeJobRecord
from ai_workshop.platform.assets.purge_proof_models import (
    AssetPurgeProofParticipantRecord,
    AssetPurgeProofRecord,
    AssetPurgeProofTargetRecord,
)
from alembic import command
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)

FINISHED_AT = datetime(2026, 9, 14, 14, 0, tzinfo=UTC)
CHECKED_AT = datetime(2026, 9, 14, 13, 30, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class ProofSeed:
    actor_id: UUID
    workspace_id: UUID
    policy_version: int
    batch_id: UUID
    job_id: UUID
    folder_id: UUID
    document_id: UUID
    version_ids: tuple[UUID, UUID]


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


def _seed_proof_batch(connection: psycopg.Connection[Any]) -> ProofSeed:
    actor_id = uuid4()
    workspace_id, policy_id, batch_id, job_id = uuid4(), uuid4(), uuid4(), uuid4()
    folder_id, document_id = uuid4(), uuid4()
    version_ids = (uuid4(), uuid4())
    policy_version = 4
    email = f"purge-proof-{actor_id}@example.test"
    connection.execute(
        "INSERT INTO users(id,display_name,email,normalized_email,password_hash,role,"
        "is_active,created_at,updated_at) VALUES (%s,'Synthetic proof owner',%s,%s,"
        "'hash','member',true,now(),now())",
        (actor_id, email, email),
    )
    connection.execute(
        "INSERT INTO workspaces(id,name,kind,created_by,created_at,updated_at) "
        "VALUES (%s,'Synthetic proof','company',%s,now(),now())",
        (workspace_id, actor_id),
    )
    connection.execute(
        "INSERT INTO asset_retention_policies"
        "(id,workspace_id,version,days,created_by,created_at) "
        "VALUES (%s,%s,%s,30,%s,now())",
        (policy_id, workspace_id, policy_version, actor_id),
    )
    connection.execute(
        "INSERT INTO asset_trash_batches"
        "(id,workspace_id,actor_id,policy_version_id,trashed_at,purge_after,created_at) "
        "VALUES (%s,%s,%s,%s,now()-interval '31 days',now()-interval '1 day',now())",
        (batch_id, workspace_id, actor_id, policy_id),
    )
    connection.execute(
        "INSERT INTO folders"
        "(id,workspace_id,parent_id,name,metadata_revision,lifecycle,lifecycle_generation,"
        "trash_batch_id,trashed_at,purge_after,created_at,updated_at) "
        "VALUES (%s,%s,NULL,'proof-folder',1,'purging',6,%s,"
        "now()-interval '31 days',now()-interval '1 day',now(),now())",
        (folder_id, workspace_id, batch_id),
    )
    connection.execute(
        "INSERT INTO documents"
        "(id,workspace_id,folder_id,name,active_version_id,metadata_revision,lifecycle,"
        "lifecycle_generation,trash_batch_id,trashed_at,purge_after,created_at,updated_at) "
        "VALUES (%s,%s,%s,'proof.txt',%s,1,'purging',9,%s,"
        "now()-interval '31 days',now()-interval '1 day',now(),now())",
        (document_id, workspace_id, folder_id, version_ids[-1], batch_id),
    )
    for number, version_id in enumerate(version_ids, start=1):
        connection.execute(
            "INSERT INTO asset_versions"
            "(id,document_id,number,object_key,sha256,media_type,size,status,created_at,"
            "updated_at) VALUES (%s,%s,%s,%s,%s,'text/plain',1,'ready',now(),now())",
            (version_id, document_id, number, f"synthetic/{version_id}", f"{number:064x}"),
        )
    connection.execute(
        "INSERT INTO asset_purge_jobs"
        "(id,workspace_id,trash_batch_id,request_key,status,attempt_count,available_at,"
        "error_code,finished_at,created_at,updated_at) "
        "VALUES (%s,%s,%s,%s,'purging',1,now(),NULL,NULL,now(),now())",
        (job_id, workspace_id, batch_id, f"proof-{uuid4()}"),
    )
    return ProofSeed(
        actor_id,
        workspace_id,
        policy_version,
        batch_id,
        job_id,
        folder_id,
        document_id,
        version_ids,
    )


def _candidate(seed: ProofSeed) -> tuple[PurgeInventory, BoundCleanupReceipt]:
    inventory = PurgeInventory(
        workspace_id=seed.workspace_id,
        job_id=seed.job_id,
        version=1,
        documents=(DocumentTarget(seed.document_id, 9, seed.version_ids),),
        folders=(FolderTarget(seed.folder_id, 6),),
        participants=(
            ParticipantInventory(
                participant="rag",
                contract_version=2,
                resources=(ResourceIdentity("rag", "projection", uuid4(), 3),),
                exhausted=True,
                supported=True,
                legacy_resolved=True,
            ),
        ),
    )
    receipt = BoundCleanupReceipt(
        job_id=seed.job_id,
        inventory_version=1,
        inventory_binding=inventory_binding(inventory),
        participant_contract_version=2,
        attempt=1,
        checked_at=CHECKED_AT,
        receipt=CleanupReceipt("rag", 2, 0, 0, True),
    )
    return inventory, receipt


async def _persist_candidate(
    database: IsolatedPublishingDatabase,
    seed: ProofSeed,
    inventory: PurgeInventory,
    receipt: BoundCleanupReceipt,
) -> None:
    engine = create_async_engine(database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            repository = PurgeInventoryRepository(session)
            await repository.save_inventory(inventory)
            await repository.save_receipt(seed.workspace_id, receipt)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_store_proof_revalidates_persisted_candidate_batch_and_current_execution(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    with psycopg.connect(_psycopg_url(migrated_database.database_url)) as connection:
        seed = _seed_proof_batch(connection)
    inventory, receipt = _candidate(seed)
    await _persist_candidate(migrated_database, seed, inventory, receipt)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            repository = PurgeInventoryRepository(session)
            with pytest.raises(ValueError, match="actor"):
                await repository.store_proof(
                    inventory=inventory,
                    receipts=(receipt,),
                    required_participants=frozenset({"rag"}),
                    actor_id=uuid4(),
                    policy_version=seed.policy_version,
                    finished_at=FINISHED_AT,
                    writers_stopped=True,
                    references_cleared=True,
                )
            with pytest.raises(ValueError, match="policy"):
                await repository.store_proof(
                    inventory=inventory,
                    receipts=(receipt,),
                    required_participants=frozenset({"rag"}),
                    actor_id=seed.actor_id,
                    policy_version=seed.policy_version + 1,
                    finished_at=FINISHED_AT,
                    writers_stopped=True,
                    references_cleared=True,
                )
            with pytest.raises(ValueError, match="persisted receipt|attempt"):
                await repository.store_proof(
                    inventory=inventory,
                    receipts=(replace(receipt, attempt=2),),
                    required_participants=frozenset({"rag"}),
                    actor_id=seed.actor_id,
                    policy_version=seed.policy_version,
                    finished_at=FINISHED_AT,
                    writers_stopped=True,
                    references_cleared=True,
                )
            await session.rollback()

        for status in ("purge_pending", "retry_wait", "blocked", "purged"):
            async with sessions() as session:
                values: dict[str, object] = {"status": status}
                if status == "purged":
                    values["finished_at"] = FINISHED_AT
                await session.execute(
                    update(AssetPurgeJobRecord)
                    .where(AssetPurgeJobRecord.id == seed.job_id)
                    .values(**values)
                )
                with pytest.raises(ValueError, match="active purge execution"):
                    await PurgeInventoryRepository(session).store_proof(
                        inventory=inventory,
                        receipts=(receipt,),
                        required_participants=frozenset({"rag"}),
                        actor_id=seed.actor_id,
                        policy_version=seed.policy_version,
                        finished_at=FINISHED_AT,
                        writers_stopped=True,
                        references_cleared=True,
                    )
                await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_store_proof_rejects_unpersisted_or_unsuccessful_candidate_receipts(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    with psycopg.connect(_psycopg_url(migrated_database.database_url)) as connection:
        seed = _seed_proof_batch(connection)
    inventory, receipt = _candidate(seed)
    await _persist_candidate(migrated_database, seed, inventory, receipt)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        for changed in (
            replace(receipt, receipt=CleanupReceipt("rag", 3, 0, 0, True)),
            replace(receipt, receipt=CleanupReceipt("rag", 2, 0, 1, True)),
            replace(receipt, receipt=CleanupReceipt("rag", 2, 0, 0, False)),
        ):
            async with sessions() as session:
                with pytest.raises(ValueError, match="persisted receipt|complete"):
                    await PurgeInventoryRepository(session).store_proof(
                        inventory=inventory,
                        receipts=(changed,),
                        required_participants=frozenset({"rag"}),
                        actor_id=seed.actor_id,
                        policy_version=seed.policy_version,
                        finished_at=FINISHED_AT,
                        writers_stopped=True,
                        references_cleared=True,
                    )
                await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_store_proof_refreshes_cached_job_state_before_accepting_candidate(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_proof_batch(connection)
    inventory, receipt = _candidate(seed)
    await _persist_candidate(migrated_database, seed, inventory, receipt)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            cached = await session.get(AssetPurgeJobRecord, seed.job_id)
            assert cached is not None and cached.status == "purging"
            with psycopg.connect(url) as connection:
                connection.execute(
                    "UPDATE asset_purge_jobs SET status='retry_wait' WHERE id=%s",
                    (seed.job_id,),
                )
            with pytest.raises(ValueError, match="active purge execution"):
                await PurgeInventoryRepository(session).store_proof(
                    inventory=inventory,
                    receipts=(receipt,),
                    required_participants=frozenset({"rag"}),
                    actor_id=seed.actor_id,
                    policy_version=seed.policy_version,
                    finished_at=FINISHED_AT,
                    writers_stopped=True,
                    references_cleared=True,
                )
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_store_proof_refreshes_cached_inventory_targets_before_binding_check(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_proof_batch(connection)
    inventory, receipt = _candidate(seed)
    await _persist_candidate(migrated_database, seed, inventory, receipt)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            cached = (
                await session.scalars(
                select(AssetPurgeInventoryTargetRecord)
                    .where(
                    AssetPurgeInventoryTargetRecord.target_kind == "document",
                    AssetPurgeInventoryTargetRecord.target_id == seed.document_id,
                )
                )
            ).all()
            assert len(cached) == 2 and all(row.generation == 9 for row in cached)
            with psycopg.connect(url) as connection:
                connection.execute(
                    "UPDATE asset_purge_inventory_targets SET generation=10 "
                    "WHERE inventory_id IN "
                    "(SELECT id FROM asset_purge_inventories WHERE job_id=%s)",
                    (seed.job_id,),
                )
            with pytest.raises(ValueError, match="persisted latest inventory"):
                await PurgeInventoryRepository(session).store_proof(
                    inventory=inventory,
                    receipts=(receipt,),
                    required_participants=frozenset({"rag"}),
                    actor_id=seed.actor_id,
                    policy_version=seed.policy_version,
                    finished_at=FINISHED_AT,
                    writers_stopped=True,
                    references_cleared=True,
                )
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_store_proof_normalizes_persisted_receipt_timestamp_offset_to_utc(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    with psycopg.connect(_psycopg_url(migrated_database.database_url)) as connection:
        seed = _seed_proof_batch(connection)
    inventory, receipt = _candidate(seed)
    await _persist_candidate(migrated_database, seed, inventory, receipt)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            await session.execute(text("SET LOCAL TIME ZONE '+09:00'"))
            proof_id = await PurgeInventoryRepository(session).store_proof(
                inventory=inventory,
                receipts=(receipt,),
                required_participants=frozenset({"rag"}),
                actor_id=seed.actor_id,
                policy_version=seed.policy_version,
                finished_at=FINISHED_AT,
                writers_stopped=True,
                references_cleared=True,
            )
            assert isinstance(proof_id, UUID)
            job = await session.get(AssetPurgeJobRecord, seed.job_id)
            assert job is not None and job.status == "purging" and job.finished_at is None
            assert await session.scalar(
                select(func.count()).select_from(AssetPurgeInventoryRecord).where(
                    AssetPurgeInventoryRecord.job_id == seed.job_id
                )
            ) == 1
            with pytest.raises(ValueError, match="already exists"):
                await PurgeInventoryRepository(session).store_proof(
                    inventory=inventory,
                    receipts=(receipt,),
                    required_participants=frozenset({"rag"}),
                    actor_id=seed.actor_id,
                    policy_version=seed.policy_version,
                    finished_at=FINISHED_AT,
                    writers_stopped=True,
                    references_cleared=True,
                )
    finally:
        await engine.dispose()


async def _delete_details_and_sources(session: Any, seed: ProofSeed) -> None:
    inventory_ids = select(AssetPurgeInventoryRecord.id).where(
        AssetPurgeInventoryRecord.job_id == seed.job_id
    )
    await session.execute(
        delete(AssetPurgeReceiptRecord).where(
            AssetPurgeReceiptRecord.inventory_id.in_(inventory_ids)
        )
    )
    await session.execute(
        delete(AssetPurgeInventoryResourceRecord).where(
            AssetPurgeInventoryResourceRecord.inventory_id.in_(inventory_ids)
        )
    )
    await session.execute(
        delete(AssetPurgeInventoryParticipantRecord).where(
            AssetPurgeInventoryParticipantRecord.inventory_id.in_(inventory_ids)
        )
    )
    await session.execute(
        delete(AssetPurgeInventoryTargetRecord).where(
            AssetPurgeInventoryTargetRecord.inventory_id.in_(inventory_ids)
        )
    )
    await session.execute(
        delete(AssetPurgeInventoryRecord).where(
            AssetPurgeInventoryRecord.job_id == seed.job_id
        )
    )
    await session.execute(
        delete(AssetVersionRecord).where(AssetVersionRecord.document_id == seed.document_id)
    )
    await session.execute(
        delete(DocumentRecord).where(DocumentRecord.id == seed.document_id)
    )
    await session.execute(delete(FolderRecord).where(FolderRecord.id == seed.folder_id))


@pytest.mark.asyncio
async def test_proof_cleanup_and_job_completion_are_atomic_and_recomputable(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    with psycopg.connect(_psycopg_url(migrated_database.database_url)) as connection:
        seed = _seed_proof_batch(connection)
    inventory, receipt = _candidate(seed)
    await _persist_candidate(migrated_database, seed, inventory, receipt)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        with pytest.raises(RuntimeError, match="synthetic completion failure"):
            async with sessions.begin() as session:
                await PurgeInventoryRepository(session).store_proof(
                    inventory=inventory,
                    receipts=(receipt,),
                    required_participants=frozenset({"rag"}),
                    actor_id=seed.actor_id,
                    policy_version=seed.policy_version,
                    finished_at=FINISHED_AT,
                    writers_stopped=True,
                    references_cleared=True,
                )
                await _delete_details_and_sources(session, seed)
                await session.execute(
                    update(AssetPurgeJobRecord)
                    .where(AssetPurgeJobRecord.id == seed.job_id)
                    .values(status="purged", finished_at=FINISHED_AT)
                )
                raise RuntimeError("synthetic completion failure")

        async with sessions() as session:
            assert await session.scalar(
                select(func.count()).select_from(AssetPurgeProofRecord).where(
                    AssetPurgeProofRecord.job_id == seed.job_id
                )
            ) == 0
            assert await session.scalar(
                select(func.count()).select_from(AssetPurgeInventoryRecord).where(
                    AssetPurgeInventoryRecord.job_id == seed.job_id
                )
            ) == 1
            job = await session.get(AssetPurgeJobRecord, seed.job_id)
            assert job is not None and job.status == "purging" and job.finished_at is None

        async with sessions.begin() as session:
            proof_id = await PurgeInventoryRepository(session).store_proof(
                inventory=inventory,
                receipts=(receipt,),
                required_participants=frozenset({"rag"}),
                actor_id=seed.actor_id,
                policy_version=seed.policy_version,
                finished_at=FINISHED_AT,
                writers_stopped=True,
                references_cleared=True,
            )
            await _delete_details_and_sources(session, seed)
            await session.execute(
                update(AssetPurgeJobRecord)
                .where(AssetPurgeJobRecord.id == seed.job_id)
                .values(status="purged", finished_at=FINISHED_AT)
            )

        async with sessions() as session:
            proof = await session.get(AssetPurgeProofRecord, proof_id)
            assert proof is not None
            assert (proof.backup_state, proof.external_state) == ("pending", "unverified")
            assert await session.scalar(
                select(func.count()).select_from(AssetPurgeInventoryRecord).where(
                    AssetPurgeInventoryRecord.job_id == seed.job_id
                )
            ) == 0
            assert await session.get(DocumentRecord, seed.document_id) is None
            assert await session.get(FolderRecord, seed.folder_id) is None
            targets = (
                await session.scalars(
                    select(AssetPurgeProofTargetRecord).where(
                        AssetPurgeProofTargetRecord.proof_id == proof_id
                    )
                )
            ).all()
            participant_rows = (
                await session.scalars(
                    select(AssetPurgeProofParticipantRecord).where(
                        AssetPurgeProofParticipantRecord.proof_id == proof_id
                    )
                )
            ).all()
            document_generations: dict[UUID, set[int]] = {}
            document_versions: dict[UUID, set[UUID]] = {}
            for target in targets:
                if target.target_kind != "document":
                    continue
                assert target.asset_version_id is not None
                document_generations.setdefault(target.target_id, set()).add(
                    target.generation
                )
                document_versions.setdefault(target.target_id, set()).add(
                    target.asset_version_id
                )
            assert document_generations.keys() == document_versions.keys()
            assert all(
                len(generations) == 1
                for generations in document_generations.values()
            )
            documents = tuple(
                DocumentTarget(
                    target_id,
                    next(iter(document_generations[target_id])),
                    tuple(sorted(document_versions[target_id])),
                )
                for target_id in sorted(document_versions, key=str)
            )
            folders = tuple(
                FolderTarget(target.target_id, target.generation)
                for target in targets
                if target.target_kind == "folder"
            )
            retained_receipts = tuple(
                BoundCleanupReceipt(
                    job_id=proof.job_id,
                    inventory_version=proof.inventory_version,
                    inventory_binding=proof.inventory_binding,
                    participant_contract_version=row.contract_version,
                    attempt=row.attempt,
                    checked_at=row.checked_at.astimezone(UTC),
                    receipt=CleanupReceipt(
                        row.participant,
                        row.deleted,
                        row.retained_shared,
                        row.residual_owned,
                        row.verified,
                    ),
                )
                for row in participant_rows
            )
            assert retained_proof_binding(
                workspace_id=proof.workspace_id,
                job_id=proof.job_id,
                inventory_version=proof.inventory_version,
                inventory_binding=proof.inventory_binding,
                documents=documents,
                folders=folders,
                receipts=retained_receipts,
                required_participants=frozenset({"rag"}),
            ) == proof.binding
    finally:
        await engine.dispose()


def test_proof_schema_contains_no_source_body_locator_or_hash_and_rejects_failure_rows(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    url = _psycopg_url(migrated_database.database_url)
    with psycopg.connect(url) as connection:
        seed = _seed_proof_batch(connection)
        proof_id = uuid4()
        connection.execute(
            "INSERT INTO asset_purge_proofs"
            "(id,workspace_id,job_id,inventory_version,inventory_binding,binding,actor_id,"
            "policy_version,finished_at,backup_state,external_state) "
            "VALUES (%s,%s,%s,1,%s,%s,%s,%s,now(),'pending','unverified')",
            (
                proof_id,
                seed.workspace_id,
                seed.job_id,
                "a" * 64,
                "b" * 64,
                seed.actor_id,
                seed.policy_version,
            ),
        )
        columns = {
            name
            for (name,) in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=current_schema() AND table_name LIKE 'asset_purge_proof%'"
            ).fetchall()
        }
        assert columns.isdisjoint(
            {"body", "path", "filename", "object_key", "sha256", "query", "payload"}
        )
        for verified, residual_owned in ((False, 0), (True, 1)):
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(
                    "INSERT INTO asset_purge_proof_participants"
                    "(proof_id,participant,contract_version,attempt,checked_at,deleted,"
                    "retained_shared,residual_owned,verified) "
                    "VALUES (%s,%s,1,1,now(),0,0,%s,%s)",
                    (proof_id, f"participant_{int(verified)}", residual_owned, verified),
                )
