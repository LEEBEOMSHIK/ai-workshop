from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ai_workshop.infrastructure.object_store.tracked import (
    ArtifactStoreError,
    TrackedLocalArtifactStore,
)
from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.ingestion.artifact_contracts import (
    ArtifactBinding,
    ArtifactRole,
    VerifiedArtifact,
)
from ai_workshop.labs.rag.ingestion.artifact_models import (
    RagArtifactAttemptRecord,
    RagArtifactBundleRecord,
    RagArtifactSlotRecord,
)
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.purge_inventory_contracts import (
    DocumentTarget,
    ParticipantInventory,
)
from ai_workshop.platform.jobs.domain import JobType
from ai_workshop.platform.jobs.models import JobRecord

RAG_ARTIFACT_INVENTORY_CONTRACT_VERSION = 1

_PARTICIPANT = "rag_ingestion_artifacts"
_KIND = "artifact_bundle"
_RELATION_KIND = "derived_artifact"
_SOURCE_INVALID = "rag_artifact_source_invalid"
_INVENTORY_CHANGED = "rag_artifact_inventory_changed"
_INVENTORY_FAILED = "rag_artifact_inventory_failed"


class RagArtifactInventoryError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _Document:
    id: UUID
    workspace_id: UUID
    generation: int


@dataclass(frozen=True, slots=True)
class _Version:
    id: UUID
    document_id: UUID


@dataclass(frozen=True, slots=True)
class _Projection:
    id: UUID
    asset_version_id: UUID
    document_processing_profile_id: UUID
    indexing_profile_id: UUID
    status: str
    content_revision: int | None


@dataclass(frozen=True, slots=True)
class _Ingestion:
    job_id: UUID
    projection_id: UUID
    asset_version_id: UUID
    document_processing_profile_id: UUID
    indexing_profile_id: UUID
    parsed_object_key: str | None
    parsed_sha256: str | None
    chunk_object_key: str | None
    chunk_sha256: str | None
    embedding_object_key: str | None
    embedding_sha256: str | None
    index_build_id: UUID | None
    parsed_element_count: int | None
    chunk_count: int | None
    embedding_count: int | None
    indexed_document_count: int | None
    index_alias_verified: bool


@dataclass(frozen=True, slots=True)
class _Job:
    id: UUID
    user_id: UUID
    workspace_id: UUID
    asset_version_id: UUID
    type: str
    status: str
    stage: str
    attempt: int
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class _Bundle:
    id: UUID
    projection_id: UUID
    job_id: UUID
    workspace_id: UUID
    document_id: UUID
    asset_version_id: UUID
    revision: int


@dataclass(frozen=True, slots=True)
class _Slot:
    id: UUID
    bundle_id: UUID
    role: str
    store_id: str
    store_binding_id: UUID
    canonical_key: str
    state: str
    published_size: int | None
    published_sha256: str | None


@dataclass(frozen=True, slots=True)
class _Attempt:
    id: UUID
    slot_id: UUID
    store_id: str
    store_binding_id: UUID
    temporary_key: str
    proposed_size: int
    proposed_sha256: str
    state: str
    result_code: str | None
    created_at: datetime
    closed_at: datetime | None


@dataclass(frozen=True, slots=True)
class _Relation:
    id: UUID
    workspace_id: UUID
    document_id: UUID
    asset_version_id: UUID
    participant: str
    kind: str
    resource_id: UUID
    resource_revision: int
    relation_kind: str


@dataclass(frozen=True, slots=True)
class _Snapshot:
    documents: tuple[_Document, ...]
    versions: tuple[_Version, ...]
    projections: tuple[_Projection, ...]
    ingestions: tuple[_Ingestion, ...]
    jobs: tuple[_Job, ...]
    bundles: tuple[_Bundle, ...]
    slots: tuple[_Slot, ...]
    attempts: tuple[_Attempt, ...]
    relations: tuple[_Relation, ...]


@dataclass(frozen=True, slots=True)
class _InspectionPlan:
    resources: tuple[ResourceIdentity, ...]
    verified: tuple[VerifiedArtifact, ...]
    reserved_keys: tuple[str, ...]
    attempt_keys: tuple[str, ...]
    exhausted: bool
    supported: bool
    legacy_resolved: bool


class RagArtifactInventory:
    def __init__(
        self, engine: AsyncEngine, store: TrackedLocalArtifactStore
    ) -> None:
        if not isinstance(engine, AsyncEngine):
            raise TypeError("engine must be an AsyncEngine")
        if not isinstance(store, TrackedLocalArtifactStore):
            raise TypeError("store must be a TrackedLocalArtifactStore")
        self._engine = engine
        self._store = store

    async def collect(
        self,
        workspace_id: UUID,
        documents: tuple[DocumentTarget, ...],
    ) -> ParticipantInventory:
        self._validate_input(workspace_id, documents)
        first = await self._read_snapshot(workspace_id, documents)
        plan = self._plan(first, self._store.binding)
        exhausted, legacy_resolved = await self._inspect_files(plan)
        try:
            final = await self._read_snapshot(workspace_id, documents)
        except RagArtifactInventoryError as error:
            if error.code == _SOURCE_INVALID:
                raise RagArtifactInventoryError(_INVENTORY_CHANGED) from None
            raise
        if final != first:
            raise RagArtifactInventoryError(_INVENTORY_CHANGED)
        return ParticipantInventory(
            participant=_PARTICIPANT,
            contract_version=RAG_ARTIFACT_INVENTORY_CONTRACT_VERSION,
            resources=plan.resources,
            exhausted=exhausted,
            supported=plan.supported,
            legacy_resolved=legacy_resolved,
        )

    @staticmethod
    def _validate_input(
        workspace_id: UUID, documents: tuple[DocumentTarget, ...]
    ) -> None:
        if not isinstance(workspace_id, UUID):
            raise TypeError("workspace_id must be a UUID")
        if type(documents) is not tuple or any(
            not isinstance(document, DocumentTarget) for document in documents
        ):
            raise TypeError("documents must be a tuple of DocumentTarget values")
        if len({document.document_id for document in documents}) != len(documents):
            raise RagArtifactInventoryError(_SOURCE_INVALID)

    async def _read_snapshot(
        self,
        workspace_id: UUID,
        documents: tuple[DocumentTarget, ...],
    ) -> _Snapshot:
        try:
            async with self._engine.connect() as connection, connection.begin():
                await connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
                async with AsyncSession(bind=connection) as session:
                    return await self._snapshot(session, workspace_id, documents)
        except RagArtifactInventoryError:
            raise
        except Exception:
            raise RagArtifactInventoryError(_INVENTORY_FAILED) from None

    async def _snapshot(
        self,
        session: AsyncSession,
        workspace_id: UUID,
        documents: tuple[DocumentTarget, ...],
    ) -> _Snapshot:
        targets = {target.document_id: target for target in documents}
        document_ids = tuple(targets)
        document_records = tuple(
            await session.scalars(
                select(DocumentRecord).where(DocumentRecord.id.in_(document_ids))
            )
        )
        document_rows = tuple(
            sorted(
                (
                    _Document(
                        record.id,
                        record.workspace_id,
                        record.lifecycle_generation,
                    )
                    for record in document_records
                ),
                key=lambda item: str(item.id),
            )
        )
        if len(document_rows) != len(targets) or any(
            row.workspace_id != workspace_id
            or row.generation != targets[row.id].generation
            for row in document_rows
        ):
            raise RagArtifactInventoryError(_SOURCE_INVALID)

        version_records = tuple(
            await session.scalars(
                select(AssetVersionRecord).where(
                    AssetVersionRecord.document_id.in_(document_ids)
                )
            )
        )
        version_rows = tuple(
            sorted(
                (_Version(record.id, record.document_id) for record in version_records),
                key=lambda item: str(item.id),
            )
        )
        actual_versions: dict[UUID, set[UUID]] = defaultdict(set)
        for row in version_rows:
            actual_versions[row.document_id].add(row.id)
        if any(
            actual_versions[target.document_id] != set(target.asset_version_ids)
            for target in documents
        ):
            raise RagArtifactInventoryError(_SOURCE_INVALID)
        version_ids = tuple(row.id for row in version_rows)

        projection_records = tuple(
            await session.scalars(
                select(RagProjectionRecord).where(
                    RagProjectionRecord.asset_version_id.in_(version_ids)
                )
            )
        )
        projection_rows = tuple(
            sorted(
                (
                    _Projection(
                        record.id,
                        record.asset_version_id,
                        record.document_processing_profile_id,
                        record.indexing_profile_id,
                        str(record.status),
                        record.content_revision,
                    )
                    for record in projection_records
                ),
                key=lambda item: str(item.id),
            )
        )
        projection_ids = tuple(row.id for row in projection_rows)

        ingestion_records = tuple(
            await session.scalars(
                select(RagIngestionJobRecord).where(
                    or_(
                        RagIngestionJobRecord.asset_version_id.in_(version_ids),
                        RagIngestionJobRecord.projection_id.in_(projection_ids),
                    )
                )
            )
        )
        ingestion_rows = tuple(
            sorted(
                (
                    _Ingestion(
                        record.job_id,
                        record.projection_id,
                        record.asset_version_id,
                        record.document_processing_profile_id,
                        record.indexing_profile_id,
                        record.parsed_object_key,
                        record.parsed_sha256,
                        record.chunk_object_key,
                        record.chunk_sha256,
                        record.embedding_object_key,
                        record.embedding_sha256,
                        record.index_build_id,
                        record.parsed_element_count,
                        record.chunk_count,
                        record.embedding_count,
                        record.indexed_document_count,
                        record.index_alias_verified,
                    )
                    for record in ingestion_records
                ),
                key=lambda item: str(item.job_id),
            )
        )
        ingestion_job_ids = tuple(row.job_id for row in ingestion_rows)

        job_records = tuple(
            await session.scalars(
                select(JobRecord).where(
                    or_(
                        JobRecord.id.in_(ingestion_job_ids),
                        (
                            JobRecord.asset_version_id.in_(version_ids)
                            & (JobRecord.type == JobType.RAG_INGESTION)
                        ),
                    )
                )
            )
        )
        job_rows = tuple(
            sorted(
                (
                    _Job(
                        record.id,
                        record.user_id,
                        record.workspace_id,
                        record.asset_version_id,
                        str(record.type),
                        str(record.status),
                        record.stage,
                        record.attempt,
                        record.error_code,
                        record.started_at,
                        record.finished_at,
                    )
                    for record in job_records
                ),
                key=lambda item: str(item.id),
            )
        )
        job_ids = tuple(row.id for row in job_rows)

        bundle_records = tuple(
            await session.scalars(
                select(RagArtifactBundleRecord).where(
                    or_(
                        RagArtifactBundleRecord.asset_version_id.in_(version_ids),
                        RagArtifactBundleRecord.projection_id.in_(projection_ids),
                        RagArtifactBundleRecord.job_id.in_(job_ids),
                    )
                )
            )
        )
        bundle_rows = tuple(
            sorted(
                (
                    _Bundle(
                        record.id,
                        record.projection_id,
                        record.job_id,
                        record.workspace_id,
                        record.document_id,
                        record.asset_version_id,
                        record.revision,
                    )
                    for record in bundle_records
                ),
                key=lambda item: str(item.id),
            )
        )
        bundle_ids = tuple(row.id for row in bundle_rows)

        slot_records = tuple(
            await session.scalars(
                select(RagArtifactSlotRecord).where(
                    RagArtifactSlotRecord.bundle_id.in_(bundle_ids)
                )
            )
        )
        slot_rows = tuple(
            sorted(
                (
                    _Slot(
                        record.id,
                        record.bundle_id,
                        record.role,
                        record.store_id,
                        record.store_binding_id,
                        record.canonical_key,
                        record.state,
                        record.published_size,
                        record.published_sha256,
                    )
                    for record in slot_records
                ),
                key=lambda item: str(item.id),
            )
        )
        slot_ids = tuple(row.id for row in slot_rows)

        attempt_records = tuple(
            await session.scalars(
                select(RagArtifactAttemptRecord).where(
                    RagArtifactAttemptRecord.slot_id.in_(slot_ids)
                )
            )
        )
        attempt_rows = tuple(
            sorted(
                (
                    _Attempt(
                        record.id,
                        record.slot_id,
                        record.store_id,
                        record.store_binding_id,
                        record.temporary_key,
                        record.proposed_size,
                        record.proposed_sha256,
                        record.state,
                        record.result_code,
                        record.created_at,
                        record.closed_at,
                    )
                    for record in attempt_records
                ),
                key=lambda item: str(item.id),
            )
        )

        relation_records: tuple[AssetSourceRelationRecord, ...] = ()
        relation_scope = []
        if version_ids:
            relation_scope.append(
                AssetSourceRelationRecord.asset_version_id.in_(version_ids)
            )
        if bundle_ids:
            relation_scope.append(
                AssetSourceRelationRecord.resource_id.in_(bundle_ids)
            )
        if relation_scope:
            relation_records = tuple(
                await session.scalars(
                    select(AssetSourceRelationRecord).where(
                        AssetSourceRelationRecord.participant == _PARTICIPANT,
                        or_(*relation_scope),
                    )
                )
            )
        relation_rows = tuple(
            sorted(
                (
                    _Relation(
                        record.id,
                        record.workspace_id,
                        record.document_id,
                        record.asset_version_id,
                        record.participant,
                        record.kind,
                        record.resource_id,
                        record.resource_revision,
                        record.relation_kind,
                    )
                    for record in relation_records
                ),
                key=lambda item: str(item.id),
            )
        )
        return _Snapshot(
            document_rows,
            version_rows,
            projection_rows,
            ingestion_rows,
            job_rows,
            bundle_rows,
            slot_rows,
            attempt_rows,
            relation_rows,
        )

    @staticmethod
    def _plan(snapshot: _Snapshot, binding: ArtifactBinding) -> _InspectionPlan:
        projections = {row.id: row for row in snapshot.projections}
        ingestions_by_projection: dict[UUID, list[_Ingestion]] = defaultdict(list)
        for ingestion_row in snapshot.ingestions:
            ingestions_by_projection[ingestion_row.projection_id].append(ingestion_row)
        jobs = {row.id: row for row in snapshot.jobs}
        bundles_by_projection: dict[UUID, list[_Bundle]] = defaultdict(list)
        for bundle_row in snapshot.bundles:
            bundles_by_projection[bundle_row.projection_id].append(bundle_row)
        versions = {row.id: row for row in snapshot.versions}
        documents = {row.id: row for row in snapshot.documents}
        resources = {
            ResourceIdentity(_PARTICIPANT, _KIND, bundle.id, bundle.revision)
            for bundle in snapshot.bundles
        }
        resources.update(
            ResourceIdentity(
                relation.participant,
                relation.kind,
                relation.resource_id,
                relation.resource_revision,
            )
            for relation in snapshot.relations
        )
        supported = all(relation.kind == _KIND for relation in snapshot.relations)
        legacy_resolved = True

        expected_relation_values = set()
        for projection in snapshot.projections:
            ingestions = ingestions_by_projection[projection.id]
            bundles = bundles_by_projection[projection.id]
            if len(ingestions) != 1:
                legacy_resolved = False
                continue
            ingestion = ingestions[0]
            job = jobs.get(ingestion.job_id)
            version = versions.get(projection.asset_version_id)
            document = documents.get(version.document_id) if version is not None else None
            if job is None or version is None or document is None:
                legacy_resolved = False
                continue
            if (
                ingestion.asset_version_id != projection.asset_version_id
                or ingestion.document_processing_profile_id
                != projection.document_processing_profile_id
                or ingestion.indexing_profile_id != projection.indexing_profile_id
                or job.type != JobType.RAG_INGESTION.value
                or job.workspace_id != document.workspace_id
                or job.asset_version_id != version.id
            ):
                legacy_resolved = False
                continue
            if len(bundles) != 1:
                legacy_resolved = False
                continue
            bundle = bundles[0]
            if (
                bundle.job_id != ingestion.job_id
                or bundle.workspace_id != document.workspace_id
                or bundle.document_id != document.id
                or bundle.asset_version_id != version.id
            ):
                legacy_resolved = False
                continue
            expected_relation_values.add(
                (
                    bundle.workspace_id,
                    bundle.document_id,
                    bundle.asset_version_id,
                    _KIND,
                    bundle.id,
                    bundle.revision,
                    _RELATION_KIND,
                )
            )

        if (
            set(ingestions_by_projection) != set(projections)
            or {row.job_id for row in snapshot.ingestions} != set(jobs)
            or set(bundles_by_projection) - set(projections)
        ):
            legacy_resolved = False
        actual_relation_values = {
            (
                relation.workspace_id,
                relation.document_id,
                relation.asset_version_id,
                relation.kind,
                relation.resource_id,
                relation.resource_revision,
                relation.relation_kind,
            )
            for relation in snapshot.relations
        }
        if actual_relation_values != expected_relation_values:
            legacy_resolved = False

        slots_by_bundle: dict[UUID, list[_Slot]] = defaultdict(list)
        for slot in snapshot.slots:
            slots_by_bundle[slot.bundle_id].append(slot)
        attempts_by_slot: dict[UUID, list[_Attempt]] = defaultdict(list)
        for attempt in snapshot.attempts:
            attempts_by_slot[attempt.slot_id].append(attempt)
        ingestion_by_job = {row.job_id: row for row in snapshot.ingestions}
        verified: list[VerifiedArtifact] = []
        reserved_keys: list[str] = []
        attempt_keys: list[str] = []
        exhausted = True

        for bundle in snapshot.bundles:
            slots = slots_by_bundle[bundle.id]
            role_slots: dict[ArtifactRole, _Slot] = {}
            for slot in slots:
                try:
                    role = ArtifactRole(slot.role)
                except ValueError:
                    exhausted = False
                    supported = False
                    legacy_resolved = False
                    continue
                if role in role_slots:
                    exhausted = False
                    legacy_resolved = False
                role_slots[role] = slot
            if set(role_slots) != set(ArtifactRole):
                exhausted = False
                legacy_resolved = False
            bundle_ingestion = ingestion_by_job.get(bundle.job_id)
            if bundle_ingestion is None or bundle.projection_id not in projections:
                legacy_resolved = False
                continue
            for role, slot in role_slots.items():
                expected_key = f"rag/{role.value}/{bundle.projection_id}.json"
                known_store = (
                    slot.store_id == binding.store_id
                    and slot.store_binding_id == binding.binding_id
                )
                if not known_store:
                    supported = False
                    legacy_resolved = False
                if slot.canonical_key != expected_key:
                    exhausted = False
                    legacy_resolved = False
                reference_key, reference_digest = _ingestion_reference(
                    bundle_ingestion, role
                )
                attempts = attempts_by_slot[slot.id]
                verified_attempts = [
                    attempt
                    for attempt in attempts
                    if attempt.state == "closed" and attempt.result_code == "verified"
                ]
                for attempt in attempts:
                    expected_temp = (
                        f"rag/{role.value}/.{bundle.projection_id}.json."
                        f"{attempt.id.hex}.tmp"
                    )
                    attempt_known = (
                        attempt.store_id == slot.store_id
                        and attempt.store_binding_id == slot.store_binding_id
                        and attempt.temporary_key == expected_temp
                    )
                    if not attempt_known:
                        exhausted = False
                        legacy_resolved = False
                    if attempt.store_id != binding.store_id or (
                        attempt.store_binding_id != binding.binding_id
                    ):
                        supported = False
                    if attempt.state == "open":
                        exhausted = False
                        if attempt.result_code is not None or attempt.closed_at is not None:
                            exhausted = False
                            legacy_resolved = False
                    elif attempt.state == "closed":
                        if attempt.result_code is None or attempt.closed_at is None:
                            exhausted = False
                            legacy_resolved = False
                    else:
                        exhausted = False
                        supported = False
                        legacy_resolved = False
                    if attempt_known and known_store:
                        attempt_keys.append(attempt.temporary_key)
                if slot.state == "verified":
                    verified_shape = (
                        slot.published_size is not None
                        and slot.published_sha256 is not None
                        and reference_key == slot.canonical_key
                        and reference_digest == slot.published_sha256
                        and len(verified_attempts) == 1
                        and verified_attempts[0].proposed_size == slot.published_size
                        and verified_attempts[0].proposed_sha256
                        == slot.published_sha256
                        and not any(attempt.state == "open" for attempt in attempts)
                    )
                    if not verified_shape:
                        exhausted = False
                        legacy_resolved = False
                    elif known_store and slot.canonical_key == expected_key:
                        assert slot.published_size is not None
                        assert slot.published_sha256 is not None
                        verified.append(
                            VerifiedArtifact(
                                bundle.id,
                                slot.id,
                                bundle.job_id,
                                bundle.projection_id,
                                role,
                                binding,
                                slot.canonical_key,
                                slot.published_size,
                                slot.published_sha256,
                            )
                        )
                elif slot.state == "reserved":
                    if (
                        slot.published_size is not None
                        or slot.published_sha256 is not None
                        or reference_key is not None
                        or reference_digest is not None
                        or verified_attempts
                    ):
                        exhausted = False
                        legacy_resolved = False
                    if known_store and slot.canonical_key == expected_key:
                        reserved_keys.append(slot.canonical_key)
                else:
                    exhausted = False
                    supported = False
                    legacy_resolved = False

        if set(slots_by_bundle) - {bundle.id for bundle in snapshot.bundles}:
            legacy_resolved = False
        return _InspectionPlan(
            tuple(
                sorted(
                    resources,
                    key=lambda item: (
                        item.kind,
                        str(item.resource_id),
                        item.revision,
                    ),
                )
            ),
            tuple(verified),
            tuple(reserved_keys),
            tuple(attempt_keys),
            exhausted,
            supported,
            legacy_resolved,
        )

    async def _inspect_files(self, plan: _InspectionPlan) -> tuple[bool, bool]:
        exhausted = plan.exhausted
        legacy_resolved = plan.legacy_resolved
        try:
            self._store.verify_binding()
            for artifact in plan.verified:
                try:
                    await self._store.read_verified(artifact)
                except ArtifactStoreError as error:
                    if error.code in {"artifact_missing", "artifact_integrity_mismatch"}:
                        legacy_resolved = False
                        continue
                    raise
            for key in plan.reserved_keys:
                if await self._store.inspect_key(key) is not None:
                    legacy_resolved = False
            for key in plan.attempt_keys:
                if await self._store.inspect_key(key) is not None:
                    exhausted = False
        except ArtifactStoreError:
            raise RagArtifactInventoryError(_INVENTORY_FAILED) from None
        return exhausted, legacy_resolved


def _ingestion_reference(
    ingestion: _Ingestion, role: ArtifactRole
) -> tuple[str | None, str | None]:
    if role is ArtifactRole.PARSED:
        return ingestion.parsed_object_key, ingestion.parsed_sha256
    if role is ArtifactRole.CHUNKS:
        return ingestion.chunk_object_key, ingestion.chunk_sha256
    return ingestion.embedding_object_key, ingestion.embedding_sha256
