from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from ai_workshop.infrastructure.object_store.tracked import TrackedLocalArtifactStore
from ai_workshop.labs.rag.ingestion.artifact_contracts import (
    ArtifactRole,
    VerifiedArtifact,
)
from ai_workshop.labs.rag.ingestion.artifact_inventory import (
    RagArtifactInventory,
    RagArtifactInventoryError,
)
from ai_workshop.labs.rag.ingestion.artifact_models import (
    RagArtifactAttemptRecord,
    RagArtifactBundleRecord,
    RagArtifactSlotRecord,
)
from ai_workshop.labs.rag.ingestion.artifact_repository import (
    SqlAlchemyRagArtifactRepository,
)
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.platform.assets.models import AssetVersionRecord
from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.purge_inventory_contracts import DocumentTarget
from tests.integration.labs.rag.ingestion.test_artifact_repository import (
    _BINDING,
    Seed,
    _isolated_database_at,
    _seed_official_ingestion,
)
from tests.integration.publishing_support import IsolatedPublishingDatabase


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[IsolatedPublishingDatabase]:
    with _isolated_database_at("head") as database:
        yield database


@pytest.fixture(autouse=True)
def ensure_legacy_document_processing_profile(
    migrated_database: IsolatedPublishingDatabase,
) -> None:
    """Never invoke the inherited seed before the owned UUID database exists."""
    assert migrated_database.name.startswith("ai_workshop_publishing_")


def _marker(root: Path) -> None:
    root.mkdir()
    (root / ".ai-workshop-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "store_id": _BINDING.store_id,
                "binding_id": str(_BINDING.binding_id),
            }
        ),
        encoding="utf-8",
    )


@dataclass(frozen=True, slots=True)
class InventorySeed:
    source: Seed
    bundle_id: UUID
    revision: int
    contents: dict[ArtifactRole, bytes]

    @property
    def target(self) -> DocumentTarget:
        return DocumentTarget(
            self.source.source.document_id,
            1,
            (self.source.source.asset_version_id,),
        )


async def _registered_seed(
    engine: AsyncEngine, *, label: str
) -> tuple[Seed, UUID]:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        seed = await _seed_official_ingestion(session, label=label)
        bundle_id = await SqlAlchemyRagArtifactRepository(session).register_bundle(
            seed.job_id, _BINDING
        )
    return seed, bundle_id


async def _verified_seed(
    engine: AsyncEngine,
    root: Path,
    *,
    label: str,
) -> InventorySeed:
    seed, bundle_id = await _registered_seed(engine, label=label)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = TrackedLocalArtifactStore(root, _BINDING)
    contents = {
        ArtifactRole.PARSED: b'{"parsed":true}',
        ArtifactRole.CHUNKS: b'{"chunks":true}',
        ArtifactRole.EMBEDDINGS: b'{"embeddings":true}',
    }
    reference_fields = {
        ArtifactRole.PARSED: ("parsed_object_key", "parsed_sha256"),
        ArtifactRole.CHUNKS: ("chunk_object_key", "chunk_sha256"),
        ArtifactRole.EMBEDDINGS: ("embedding_object_key", "embedding_sha256"),
    }
    for role in ArtifactRole:
        content = contents[role]
        digest = sha256(content).hexdigest()
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id,
                role,
                _BINDING,
                size=len(content),
                sha256=digest,
            )
        assert not isinstance(claim, VerifiedArtifact)
        publication, _ = await store.publish(claim, content)
        key_field, digest_field = reference_fields[role]
        async with sessions.begin() as session:
            await SqlAlchemyRagArtifactRepository(session).finalize(publication)
            await session.execute(
                update(RagIngestionJobRecord)
                .where(RagIngestionJobRecord.job_id == seed.job_id)
                .values(**{key_field: claim.canonical_key, digest_field: digest})
            )
    async with sessions() as session:
        revision = await session.scalar(
            select(RagArtifactBundleRecord.revision).where(
                RagArtifactBundleRecord.id == bundle_id
            )
        )
    assert revision is not None
    return InventorySeed(seed, bundle_id, revision, contents)


@pytest.mark.asyncio
async def test_collect_returns_only_opaque_registered_bundles_for_valid_sources(
    migrated_database: IsolatedPublishingDatabase, tmp_path: Path
) -> None:
    root = tmp_path / "valid-store"
    _marker(root)
    engine = create_async_engine(migrated_database.database_url)
    try:
        seed = await _verified_seed(engine, root, label="inventory-valid")

        result = await RagArtifactInventory(
            engine, TrackedLocalArtifactStore(root, _BINDING)
        ).collect(seed.source.source.workspace_id, (seed.target,))

        assert result.resources == (
            ResourceIdentity(
                "rag_ingestion_artifacts",
                "artifact_bundle",
                seed.bundle_id,
                seed.revision,
            ),
        )
        assert result.participant == "rag_ingestion_artifacts"
        assert result.contract_version == 1
        assert result.exhausted is True
        assert result.supported is True
        assert result.legacy_resolved is True
        assert set(asdict(result)) == {
            "participant",
            "contract_version",
            "resources",
            "exhausted",
            "supported",
            "legacy_resolved",
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_collect_rejects_nonexistent_wrong_workspace_generation_or_versions(
    migrated_database: IsolatedPublishingDatabase, tmp_path: Path
) -> None:
    root = tmp_path / "source-store"
    _marker(root)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            seed = await _seed_official_ingestion(session, label="inventory-source")
            second_version_id = uuid4()
            session.add(
                AssetVersionRecord(
                    id=second_version_id,
                    document_id=seed.source.document_id,
                    number=2,
                    object_key=f"synthetic/artifact/{second_version_id}.txt",
                    sha256="b" * 64,
                    media_type="text/plain",
                    size=2,
                    status="stored",
                )
            )
        inventory = RagArtifactInventory(
            engine, TrackedLocalArtifactStore(root, _BINDING)
        )
        invalid_cases = (
            (
                seed.source.workspace_id,
                (DocumentTarget(uuid4(), 1, (uuid4(),)),),
            ),
            (
                uuid4(),
                (
                    DocumentTarget(
                        seed.source.document_id,
                        1,
                        (seed.source.asset_version_id, second_version_id),
                    ),
                ),
            ),
            (
                seed.source.workspace_id,
                (
                    DocumentTarget(
                        seed.source.document_id,
                        2,
                        (seed.source.asset_version_id, second_version_id),
                    ),
                ),
            ),
            (
                seed.source.workspace_id,
                (
                    DocumentTarget(
                        seed.source.document_id,
                        1,
                        (seed.source.asset_version_id,),
                    ),
                ),
            ),
        )
        for workspace_id, targets in invalid_cases:
            with pytest.raises(RagArtifactInventoryError) as error:
                await inventory.collect(workspace_id, targets)
            assert error.value.code == "rag_artifact_source_invalid"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_projection_and_verified_file_failures_remain_incomplete(
    migrated_database: IsolatedPublishingDatabase, tmp_path: Path
) -> None:
    root = tmp_path / "incomplete-store"
    _marker(root)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions.begin() as session:
            legacy = await _seed_official_ingestion(session, label="inventory-legacy")
        inventory = RagArtifactInventory(
            engine, TrackedLocalArtifactStore(root, _BINDING)
        )
        legacy_result = await inventory.collect(
            legacy.source.workspace_id,
            (
                DocumentTarget(
                    legacy.source.document_id, 1, (legacy.source.asset_version_id,)
                ),
            ),
        )
        assert legacy_result.resources == ()
        assert legacy_result.exhausted is True
        assert legacy_result.supported is True
        assert legacy_result.legacy_resolved is False

        verified = await _verified_seed(engine, root, label="inventory-file")
        parsed = root / f"rag/parsed/{verified.source.projection_id}.json"
        parsed.unlink()
        absent = await inventory.collect(
            verified.source.source.workspace_id, (verified.target,)
        )
        assert absent.legacy_resolved is False
        assert absent.exhausted is True

        parsed.write_bytes(b"corrupt")
        corrupt = await inventory.collect(
            verified.source.source.workspace_id, (verified.target,)
        )
        assert corrupt.legacy_resolved is False
        assert corrupt.exhausted is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_open_or_closed_residual_temp_keeps_inventory_unexhausted(
    migrated_database: IsolatedPublishingDatabase, tmp_path: Path
) -> None:
    root = tmp_path / "attempt-store"
    _marker(root)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        seed, _ = await _registered_seed(engine, label="inventory-attempt")
        content = b"open"
        async with sessions.begin() as session:
            claim = await SqlAlchemyRagArtifactRepository(session).reserve_attempt(
                seed.job_id,
                ArtifactRole.PARSED,
                _BINDING,
                size=len(content),
                sha256=sha256(content).hexdigest(),
            )
        assert not isinstance(claim, VerifiedArtifact)
        temporary = root / claim.temporary_key
        temporary.parent.mkdir(parents=True)
        temporary.write_bytes(content)
        inventory = RagArtifactInventory(
            engine, TrackedLocalArtifactStore(root, _BINDING)
        )
        target = DocumentTarget(seed.source.document_id, 1, (seed.source.asset_version_id,))

        opened = await inventory.collect(seed.source.workspace_id, (target,))
        assert opened.exhausted is False

        async with sessions.begin() as session:
            await SqlAlchemyRagArtifactRepository(session).close_failed_attempt(
                claim, code="synthetic_failure"
            )
        closed_with_residual = await inventory.collect(
            seed.source.workspace_id, (target,)
        )
        assert closed_with_residual.exhausted is False

        temporary.unlink()
        async with sessions.begin() as session:
            await session.execute(
                update(RagArtifactAttemptRecord)
                .where(RagArtifactAttemptRecord.id == claim.attempt_id)
                .values(
                    temporary_key=(
                        f"rag/parsed/.{seed.projection_id}.json.{uuid4().hex}.tmp"
                    )
                )
            )
        invalid_registration = await inventory.collect(
            seed.source.workspace_id, (target,)
        )
        assert invalid_registration.exhausted is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reserved_canonical_missing_slot_or_registry_relation_is_incomplete(
    migrated_database: IsolatedPublishingDatabase, tmp_path: Path
) -> None:
    root = tmp_path / "registry-store"
    _marker(root)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        seed, bundle_id = await _registered_seed(engine, label="inventory-registry")
        canonical = root / f"rag/parsed/{seed.projection_id}.json"
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(b"unexplained")
        target = DocumentTarget(seed.source.document_id, 1, (seed.source.asset_version_id,))
        inventory = RagArtifactInventory(
            engine, TrackedLocalArtifactStore(root, _BINDING)
        )

        unexplained = await inventory.collect(seed.source.workspace_id, (target,))
        assert unexplained.legacy_resolved is False

        canonical.unlink()
        async with sessions.begin() as session:
            slot_id = await session.scalar(
                select(RagArtifactSlotRecord.id).where(
                    RagArtifactSlotRecord.bundle_id == bundle_id,
                    RagArtifactSlotRecord.role == ArtifactRole.CHUNKS.value,
                )
            )
            assert slot_id is not None
            await session.execute(
                delete(RagArtifactSlotRecord).where(RagArtifactSlotRecord.id == slot_id)
            )
            session.add(
                AssetSourceRelationRecord(
                    id=uuid4(),
                    workspace_id=seed.source.workspace_id,
                    document_id=seed.source.document_id,
                    asset_version_id=seed.source.asset_version_id,
                    participant="rag_ingestion_artifacts",
                    kind="artifact_bundle",
                    resource_id=uuid4(),
                    resource_revision=1,
                    relation_kind="derived_artifact",
                )
            )
        mismatched = await inventory.collect(seed.source.workspace_id, (target,))
        assert mismatched.legacy_resolved is False
        assert mismatched.exhausted is False
        assert len(mismatched.resources) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_store_or_relation_kind_is_reported_unsupported(
    migrated_database: IsolatedPublishingDatabase, tmp_path: Path
) -> None:
    root = tmp_path / "unsupported-store"
    _marker(root)
    engine = create_async_engine(migrated_database.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        seed, bundle_id = await _registered_seed(engine, label="inventory-unsupported")
        async with sessions.begin() as session:
            await session.execute(
                update(RagArtifactSlotRecord)
                .where(
                    RagArtifactSlotRecord.bundle_id == bundle_id,
                    RagArtifactSlotRecord.role == ArtifactRole.PARSED.value,
                )
                .values(store_id="unknown_store")
            )
            await session.execute(
                update(AssetSourceRelationRecord)
                .where(
                    AssetSourceRelationRecord.participant
                    == "rag_ingestion_artifacts",
                    AssetSourceRelationRecord.resource_id == bundle_id,
                )
                .values(kind="unknown_bundle")
            )
        target = DocumentTarget(seed.source.document_id, 1, (seed.source.asset_version_id,))

        result = await RagArtifactInventory(
            engine, TrackedLocalArtifactStore(root, _BINDING)
        ).collect(seed.source.workspace_id, (target,))

        assert result.supported is False
        assert result.legacy_resolved is False
    finally:
        await engine.dispose()


class _MutatingStore(TrackedLocalArtifactStore):
    def __init__(
        self, root: Path, engine: AsyncEngine, bundle_id: UUID
    ) -> None:
        super().__init__(root, _BINDING)
        self._engine = engine
        self._bundle_id = bundle_id
        self._mutated = False

    async def read_verified(self, artifact: VerifiedArtifact) -> bytes:
        content = await super().read_verified(artifact)
        if not self._mutated:
            self._mutated = True
            async with self._engine.begin() as connection:
                await connection.execute(
                    update(RagArtifactBundleRecord)
                    .where(RagArtifactBundleRecord.id == self._bundle_id)
                    .values(revision=RagArtifactBundleRecord.revision + 1)
                )
                await connection.execute(
                    update(AssetSourceRelationRecord)
                    .where(
                        AssetSourceRelationRecord.participant
                        == "rag_ingestion_artifacts",
                        AssetSourceRelationRecord.resource_id == self._bundle_id,
                    )
                    .values(
                        resource_revision=
                        AssetSourceRelationRecord.resource_revision + 1
                    )
                )
        return content


@pytest.mark.asyncio
async def test_full_second_snapshot_rejects_changes_during_file_inspection(
    migrated_database: IsolatedPublishingDatabase, tmp_path: Path
) -> None:
    root = tmp_path / "mutation-store"
    _marker(root)
    engine = create_async_engine(migrated_database.database_url)
    try:
        seed = await _verified_seed(engine, root, label="inventory-mutation")
        inventory = RagArtifactInventory(
            engine, _MutatingStore(root, engine, seed.bundle_id)
        )

        with pytest.raises(RagArtifactInventoryError) as error:
            await inventory.collect(seed.source.source.workspace_id, (seed.target,))

        assert error.value.code == "rag_artifact_inventory_changed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_database_and_store_failures_return_only_safe_errors(
    migrated_database: IsolatedPublishingDatabase,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "missing-marker"
    root.mkdir()
    engine = create_async_engine(migrated_database.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False).begin() as session:
            seed = await _seed_official_ingestion(session, label="inventory-errors")
        target = DocumentTarget(seed.source.document_id, 1, (seed.source.asset_version_id,))
        capsys.readouterr()

        with pytest.raises(RagArtifactInventoryError) as store_error:
            await RagArtifactInventory(
                engine, TrackedLocalArtifactStore(root, _BINDING)
            ).collect(seed.source.workspace_id, (target,))
        assert store_error.value.code == "rag_artifact_inventory_failed"
        assert str(store_error.value) == "rag_artifact_inventory_failed"

        def fail_connect(_engine: AsyncEngine) -> None:
            raise RuntimeError("synthetic private database detail")

        monkeypatch.setattr(AsyncEngine, "connect", fail_connect)
        with pytest.raises(RagArtifactInventoryError) as database_error:
            await RagArtifactInventory(
                engine, TrackedLocalArtifactStore(root, _BINDING)
            ).collect(seed.source.workspace_id, (target,))
        assert database_error.value.code == "rag_artifact_inventory_failed"
        assert str(database_error.value) == "rag_artifact_inventory_failed"
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
    finally:
        await engine.dispose()
