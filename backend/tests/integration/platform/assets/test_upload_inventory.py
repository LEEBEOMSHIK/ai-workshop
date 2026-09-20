import asyncio
import hashlib
import json
from collections.abc import Iterator
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_workshop.infrastructure.object_store.originals import TrackedOriginalStore
from ai_workshop.platform.assets.domain import Document
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.assets.storage import StoredObject
from ai_workshop.platform.assets.upload_contracts import (
    OriginalFileObservation,
    OriginalStoreBinding,
    UploadClaim,
)
from ai_workshop.platform.assets.upload_inventory import OriginalUploadInventory
from ai_workshop.platform.assets.upload_models import OriginalResourceRecord, UploadAttemptRecord
from ai_workshop.platform.assets.upload_repository import UploadJournal
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.shared.errors import AppError
from alembic import command
from tests.integration.platform.assets.original_upload_support import (
    require_explicit_original_test_database,
)
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)


@pytest.fixture(autouse=True)
def ensure_legacy_document_processing_profile() -> None:
    pass


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[IsolatedPublishingDatabase]:
    require_explicit_original_test_database()
    with isolated_publishing_database(monkeypatch) as db:
        command.upgrade(db.config, "head")
        yield db


def test_inventory_reconciles_legacy_open_and_attached(
    database: IsolatedPublishingDatabase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        engine = create_async_engine(database.database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        user, workspace = uuid4(), uuid4()
        binding = OriginalStoreBinding("originals", uuid4())
        (tmp_path / ".ai-workshop-original-store.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "store_id": binding.store_id,
                    "binding_id": str(binding.binding_id),
                }
            ),
            encoding="utf-8",
        )
        store = TrackedOriginalStore(tmp_path, binding)
        inventory = OriginalUploadInventory(sessions, store)
        journal = UploadJournal(sessions)
        claim = UploadClaim(
            uuid4(), SourceIdentity(workspace, uuid4(), uuid4()), user, None, True, binding, ".txt"
        )
        try:
            async with sessions.begin() as session:
                session.add(
                    UserRecord(
                        id=user,
                        display_name="Synthetic",
                        role="member",
                        email=f"{user}@example.test",
                        normalized_email=f"{user}@example.test",
                        password_hash="synthetic",
                        is_active=True,
                    )
                )
                await session.flush()
                session.add(
                    WorkspaceRecord(id=workspace, name="Synthetic", kind="company", created_by=user)
                )
                await session.flush()
                session.add(
                    WorkspaceMembershipRecord(
                        id=uuid4(), user_id=user, workspace_id=workspace, role="owner"
                    )
                )
            await journal.reserve(claim)
            result = await inventory.collect(workspace, claim.source.document_id)
            assert not result.complete and "writer_unconfirmed" in result.blockers
            orphan = await inventory.list_unattached(user, workspace)
            assert orphan.exhausted and not orphan.complete
            assert [item.attempt_id for item in orphan.items] == [claim.attempt_id]
            serialized = json.dumps(asdict(orphan), default=str)
            for secret in ("canonical_key", "temporary_key", "sha256", "user_id", "filename"):
                assert secret not in serialized

            payload = b"synthetic original"
            canonical = tmp_path / claim.canonical_key
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(payload)
            stored = StoredObject(
                claim.canonical_key, len(payload), hashlib.sha256(payload).hexdigest()
            )
            await journal.published(claim, stored)
            assert (
                "unattached_upload"
                in (await inventory.collect(workspace, claim.source.document_id)).blockers
            )
            async with sessions.begin() as session:
                await journal.prepare_attachment(session, claim)
                doc = Document(claim.source.document_id, workspace, None, "synthetic.txt")
                doc.new_version(
                    object_key=stored.key,
                    sha256=stored.sha256,
                    media_type="text/plain",
                    size=stored.size,
                    version_id=claim.source.asset_version_id,
                )
                await SqlAlchemyAssetRepository(session).save(doc)
                await journal.attach(session, claim, stored)
            attached = await inventory.collect(workspace, claim.source.document_id)
            assert attached.complete and attached.exhausted and not attached.blockers
            assert len(attached.resources) == 1
            assert attached.resources[0].revision == 1
            assert (await inventory.list_unattached(user, workspace)).items == ()
            marker = tmp_path / ".ai-workshop-original-store.json"
            marker_payload = marker.read_text(encoding="utf-8")
            marker.write_text(marker_payload.replace("originals", "foreign"), encoding="utf-8")
            assert (
                "binding_mismatch"
                in (await inventory.collect(workspace, claim.source.document_id)).blockers
            )
            marker.write_text(marker_payload, encoding="utf-8")
            canonical = tmp_path / claim.canonical_key
            canonical.write_bytes(b"changed synthetic bytes")
            assert (
                "content_mismatch"
                in (await inventory.collect(workspace, claim.source.document_id)).blockers
            )
            canonical.write_bytes(b"synthetic original")
            temporary = tmp_path / claim.temporary_key
            temporary.write_bytes(b"unexpected temporary")
            assert (
                "temporary_present"
                in (await inventory.collect(workspace, claim.source.document_id)).blockers
            )
            temporary.unlink()
            observe = store.observe

            def failed_observation(_: UploadClaim) -> OriginalFileObservation:
                raise OSError("private path must never escape")

            monkeypatch.setattr(store, "observe", failed_observation)
            failed = await inventory.collect(workspace, claim.source.document_id)
            assert not failed.complete and "observation_failed" in failed.blockers
            assert "private" not in repr(failed)
            monkeypatch.setattr(store, "observe", observe)
            sync_url = database.database_url.replace("postgresql+psycopg://", "postgresql://")
            mutations = [
                (
                    "UPDATE documents SET lifecycle_generation = lifecycle_generation + 1 "
                    "WHERE id = %s",
                    (claim.source.document_id,),
                ),
                (
                    "UPDATE asset_source_relations SET resource_revision = 2 "
                    "WHERE resource_id = %s",
                    (claim.attempt_id,),
                ),
                (
                    "INSERT INTO asset_versions (id, document_id, number, object_key, sha256, "
                    "media_type, size, status) VALUES (%s,%s,2,%s,%s,'text/plain',1,'uploaded')",
                    (uuid4(), claim.source.document_id, "synthetic/another-version", "a" * 64),
                ),
            ]
            # Construct insert columns explicitly: column order is not a public contract.
            new_id = uuid4()
            mutations.append(
                (
                    "INSERT INTO original_upload_attempts (id, workspace_id, document_id, "
                    "asset_version_id, user_id, folder_id, new_document, store_id, binding_id, "
                    "suffix, generation, canonical_key, temporary_key, state, revision) "
                    "SELECT %s,workspace_id,document_id,%s,user_id,folder_id,false,store_id, "
                    "binding_id,suffix,2,workspace_id::text || '/' || document_id::text || '/' || "
                    "%s || suffix,workspace_id::text || '/' || document_id::text || '/.' || "
                    "%s || '.upload.tmp','open',1 FROM original_upload_attempts WHERE id=%s",
                    (new_id, uuid4(), new_id.hex, new_id.hex, claim.attempt_id),
                )
            )
            for sql, parameters in mutations:
                changed = False

                def mutate_during_observation(
                    value: UploadClaim,
                    sql: str = sql,
                    parameters: tuple[object, ...] = parameters,
                ) -> OriginalFileObservation:
                    nonlocal changed
                    result = observe(value)
                    if not changed:
                        changed = True
                        with psycopg.connect(sync_url) as connection:
                            connection.execute(sql, parameters)
                    return result

                monkeypatch.setattr(store, "observe", mutate_during_observation)
                changed_result = await inventory.collect(workspace, claim.source.document_id)
                assert not changed_result.complete
                assert "inventory_changed" in changed_result.blockers
            monkeypatch.setattr(store, "observe", observe)

            def revise_during_listing(value: UploadClaim) -> OriginalFileObservation:
                result = observe(value)
                with psycopg.connect(sync_url) as connection:
                    connection.execute(
                        "UPDATE original_upload_attempts SET state='abandoned', revision=2 "
                        "WHERE id=%s",
                        (new_id,),
                    )
                return result

            monkeypatch.setattr(store, "observe", revise_during_listing)
            revised = await inventory.list_unattached(user, workspace)
            assert not revised.complete and "inventory_changed" in revised.blockers
            monkeypatch.setattr(store, "observe", observe)

            abandoned = replace(
                claim, attempt_id=uuid4(), source=SourceIdentity(workspace, uuid4(), uuid4())
            )
            await journal.reserve(abandoned)
            await journal.abandoned(abandoned, expected_state="open")
            assert (await inventory.collect(workspace, abandoned.source.document_id)).complete
            abandoned_path = tmp_path / abandoned.canonical_key
            abandoned_path.parent.mkdir(parents=True)
            abandoned_path.write_bytes(payload)
            residual = await inventory.collect(workspace, abandoned.source.document_id)
            assert not residual.complete and "abandoned_files_present" in residual.blockers
            discarding = replace(
                claim,
                attempt_id=uuid4(),
                source=SourceIdentity(workspace, uuid4(), uuid4()),
            )
            await journal.reserve(discarding)
            discarding_path = tmp_path / discarding.canonical_key
            discarding_path.parent.mkdir(parents=True)
            discarding_path.write_bytes(payload)
            await journal.published(discarding, replace(stored, key=discarding.canonical_key))

            def fail_cleanup() -> None:
                raise OSError("synthetic cleanup failure")

            with pytest.raises(OSError):
                await journal.cleanup(
                    discarding,
                    expected_state="published",
                    discard=fail_cleanup,
                    observe=lambda: observe(discarding),
                )
            for exists in (True, False):
                if not exists:
                    discarding_path.unlink()
                fenced = await inventory.collect(workspace, discarding.source.document_id)
                assert not fenced.complete and "cleanup_unconfirmed" in fenced.blockers
            async with sessions.begin() as session:
                await session.execute(
                    update(UploadAttemptRecord)
                    .where(UploadAttemptRecord.id == discarding.attempt_id)
                    .values(state="abandoned", revision=4)
                )
            assert (await inventory.collect(workspace, discarding.source.document_id)).complete
            async with sessions.begin() as session:
                await session.execute(
                    delete(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.resource_id == claim.attempt_id
                    )
                )
            assert (
                "relation_mismatch"
                in (await inventory.collect(workspace, claim.source.document_id)).blockers
            )
            async with sessions.begin() as session:
                await session.execute(
                    delete(OriginalResourceRecord).where(
                        OriginalResourceRecord.id == claim.attempt_id
                    )
                )
            assert (
                "attachment_mismatch"
                in (await inventory.collect(workspace, claim.source.document_id)).blockers
            )
            legacy = Document(uuid4(), workspace, None, "legacy.txt")
            legacy.new_version(
                object_key="legacy/synthetic", sha256="a" * 64, media_type="text/plain", size=1
            )
            async with sessions.begin() as session:
                await SqlAlchemyAssetRepository(session).save(legacy)
            legacy_result = await inventory.collect(workspace, legacy.id)
            assert not legacy_result.complete
            assert "legacy_untracked" in legacy_result.blockers
            with pytest.raises(AppError) as error:
                await inventory.list_unattached(uuid4(), workspace)
            assert error.value.status_code == 404
            foreign = await inventory.collect(uuid4(), claim.source.document_id)
            assert not foreign.resources and not foreign.complete

            def revoke_during_observation(value: UploadClaim) -> OriginalFileObservation:
                result = observe(value)
                with psycopg.connect(sync_url) as connection:
                    connection.execute(
                        "DELETE FROM workspace_memberships WHERE user_id=%s", (user,)
                    )
                return result

            monkeypatch.setattr(store, "observe", revoke_during_observation)
            with pytest.raises(AppError) as revoked:
                await inventory.list_unattached(user, workspace)
            assert revoked.value.status_code == 404
        finally:
            await engine.dispose()

    asyncio.run(run())
