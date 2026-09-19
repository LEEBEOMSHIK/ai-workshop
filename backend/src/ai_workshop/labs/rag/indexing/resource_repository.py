"""Transactional index tracking. The caller owns commit and lifecycle mutations."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import event, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RagProjectionRecord
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.indexing.resource_models import (
    RagIndexAttemptRecord,
    RagIndexResourceRecord,
)
from ai_workshop.labs.rag.indexing.tracking_contracts import (
    INDEX_RESULT_CODES,
    IndexBinding,
    IndexClaim,
    IndexResource,
    IndexTrackingError,
)
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import (
    ResourceIdentity,
    SourceIdentity,
    SourceRelation,
)
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.provenance_repository import ProvenanceRepository
from ai_workshop.platform.jobs.domain import JobType
from ai_workshop.platform.jobs.models import JobRecord

_STATE = "rag_index_revision_transaction_state"


@dataclass
class _Advance:
    transaction: SessionTransaction
    revision: int


@dataclass
class _State:
    transaction: SessionTransaction
    advances: dict[UUID, _Advance]


def _rollback(session: Session, rolled_back: SessionTransaction) -> None:
    state = session.info.get(_STATE)
    if not isinstance(state, _State):
        return
    if state.transaction is rolled_back:
        session.info.pop(_STATE, None)
        return
    for build_id, advance in tuple(state.advances.items()):
        origin: SessionTransaction | None = advance.transaction
        while origin is not None:
            if origin is rolled_back:
                del state.advances[build_id]
                break
            origin = origin.parent


class SqlAlchemyRagIndexRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, build_id: UUID) -> IndexResource | None:
        row = await self.session.scalar(
            select(RagIndexResourceRecord)
            .where(RagIndexResourceRecord.build_id == build_id)
            .execution_options(populate_existing=True)
        )
        return self._dto(row) if row is not None else None

    async def register(
        self,
        build_id: UUID,
        binding: IndexBinding,
        descriptor: IndexDescriptor,
        index_name: str,
        alias: str,
    ) -> IndexResource:
        build = await self.session.get(RagIndexBuildRecord, build_id)
        if build is None:
            raise IndexTrackingError("rag_index_identity_conflict")
        projection = await self.session.get(RagProjectionRecord, build.projection_id)
        ingestion = await self.session.scalar(
            select(RagIngestionJobRecord).where(
                RagIngestionJobRecord.projection_id == build.projection_id
            )
        )
        if projection is None or ingestion is None:
            raise IndexTrackingError("rag_index_identity_conflict")
        version = await self.session.get(AssetVersionRecord, projection.asset_version_id)
        job = await self.session.get(JobRecord, ingestion.job_id)
        document = await self.session.get(DocumentRecord, version.document_id) if version else None
        if (
            version is None
            or document is None
            or job is None
            or job.type != JobType.RAG_INGESTION
            or job.workspace_id != document.workspace_id
            or job.asset_version_id != version.id
            or ingestion.asset_version_id != version.id
            or ingestion.index_build_id != build_id
        ):
            raise IndexTrackingError("rag_index_identity_conflict")
        if any(
            getattr(build, p) != getattr(projection, p)
            or getattr(ingestion, p) != getattr(projection, p)
            for p in ("document_processing_profile_id", "indexing_profile_id")
        ):
            raise IndexTrackingError("rag_index_identity_conflict")
        if (
            (descriptor.index_name is not None and descriptor.index_name != index_name)
            or (descriptor.index_build_id is not None and descriptor.index_build_id != build_id)
            or (descriptor.projection_id is not None and descriptor.projection_id != projection.id)
            or (
                descriptor.indexing_profile_id is not None
                and descriptor.indexing_profile_id != projection.indexing_profile_id
            )
            or (build.index_name is not None and build.index_name != index_name)
        ):
            raise IndexTrackingError("rag_index_identity_conflict")
        candidate = IndexResource(
            build_id,
            projection.id,
            job.id,
            document.workspace_id,
            document.id,
            version.id,
            projection.document_processing_profile_id,
            projection.indexing_profile_id,
            1,
            binding,
            index_name,
            alias,
            descriptor.mapping_version,
            descriptor.vector_dimension,
            descriptor.similarity,
            None,
            None,
        )
        values = {
            field.name: getattr(candidate, field.name)
            for field in fields(candidate)
            if field.name != "binding"
        }
        values.update(
            store_id=binding.store_id, cluster_uuid=binding.cluster_uuid, name_contract_version=1
        )
        inserted = await self.session.scalar(
            insert(RagIndexResourceRecord)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["build_id"])
            .returning(RagIndexResourceRecord.build_id)
        )
        row = await self._lock(build_id)
        actual = self._dto(row)
        expected = replace(
            candidate,
            revision=actual.revision,
            index_uuid=actual.index_uuid,
            input_fingerprint=actual.input_fingerprint,
            chunk_ids_sha256=actual.chunk_ids_sha256,
        )
        if actual != expected:
            raise IndexTrackingError("rag_index_identity_conflict")
        if inserted is not None:
            await ProvenanceRepository(self.session).register(self._relation(row))
        await self._lock_relation(row)
        return actual

    async def reserve(
        self, build_id: UUID, input_fingerprint: str, *, chunk_ids_sha256: str
    ) -> IndexClaim:
        row = await self._lock(build_id)
        attempts = tuple(
            await self.session.scalars(
                select(RagIndexAttemptRecord)
                .where(
                    RagIndexAttemptRecord.build_id == build_id,
                    RagIndexAttemptRecord.state == "open",
                )
                .with_for_update()
            )
        )
        if attempts:
            raise IndexTrackingError("rag_index_attempt_busy")
        if any(
            re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (input_fingerprint, chunk_ids_sha256)
        ):
            raise IndexTrackingError("rag_index_input_conflict")
        if row.input_fingerprint is not None and (
            row.input_fingerprint != input_fingerprint or row.chunk_ids_sha256 != chunk_ids_sha256
        ):
            raise IndexTrackingError("rag_index_input_conflict")
        relation = await self._lock_relation(row)
        row.input_fingerprint = input_fingerprint
        row.chunk_ids_sha256 = chunk_ids_sha256
        attempt_id = uuid4()
        self.session.add(
            RagIndexAttemptRecord(
                id=attempt_id, build_id=build_id, operation="prepare", state="open"
            )
        )
        self._advance(row, relation)
        await self.session.flush()
        return IndexClaim(self._dto(row), attempt_id)

    async def observe_uuid(self, claim: IndexClaim, index_uuid: str) -> IndexClaim:
        if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", index_uuid) is None:
            raise IndexTrackingError("rag_index_identity_conflict")
        row, attempt = await self._claim(claim)
        relation = await self._lock_relation(row)
        if row.index_uuid is not None and row.index_uuid != index_uuid:
            raise IndexTrackingError("rag_index_identity_conflict")
        if row.index_uuid is None:
            if attempt.state != "open":
                raise IndexTrackingError("rag_index_identity_conflict")
            row.index_uuid = index_uuid
            self._advance(row, relation)
            await self.session.flush()
        return IndexClaim(self._dto(row), claim.attempt_id)

    async def finish(self, claim: IndexClaim, result_code: str) -> IndexResource:
        if result_code not in INDEX_RESULT_CODES:
            raise IndexTrackingError("rag_index_identity_conflict")
        row, attempt = await self._claim(claim)
        relation = await self._lock_relation(row)
        if attempt.state == "closed":
            if attempt.result_code != result_code:
                raise IndexTrackingError("rag_index_identity_conflict")
            return self._dto(row)
        if result_code == "prepared" and row.index_uuid is None:
            raise IndexTrackingError("rag_index_identity_conflict")
        attempt.state = "closed"
        attempt.result_code = result_code
        attempt.closed_at = datetime.now(UTC)
        self._advance(row, relation)
        await self.session.flush()
        return self._dto(row)

    async def advance(self, build_ids: Sequence[UUID]) -> None:
        rows = tuple(
            await self.session.scalars(
                select(RagIndexResourceRecord)
                .where(RagIndexResourceRecord.build_id.in_(set(build_ids)))
                .order_by(RagIndexResourceRecord.build_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        for row in rows:
            relation = await self._lock_relation(row)
            self._advance(row, relation)
        await self.session.flush()

    async def _lock(self, build_id: UUID) -> RagIndexResourceRecord:
        row = await self.session.scalar(
            select(RagIndexResourceRecord)
            .where(RagIndexResourceRecord.build_id == build_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise IndexTrackingError("rag_index_inventory_incomplete")
        return row

    async def _claim(
        self, claim: IndexClaim
    ) -> tuple[RagIndexResourceRecord, RagIndexAttemptRecord]:
        row = await self._lock(claim.resource.build_id)
        actual = self._dto(row)
        # UUID may have been learned by this exact writer; all immutable input must agree.
        if (
            replace(actual, revision=claim.resource.revision, index_uuid=claim.resource.index_uuid)
            != claim.resource
            or actual.revision < claim.resource.revision
            or (
                claim.resource.index_uuid is not None
                and actual.index_uuid != claim.resource.index_uuid
            )
        ):
            raise IndexTrackingError("rag_index_identity_conflict")
        attempt = await self.session.scalar(
            select(RagIndexAttemptRecord)
            .where(RagIndexAttemptRecord.id == claim.attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if attempt is None or attempt.build_id != row.build_id or attempt.operation != "prepare":
            raise IndexTrackingError("rag_index_identity_conflict")
        if attempt.state == "open" and actual.revision != claim.resource.revision:
            state = self.session.info.get(_STATE)
            current_transaction = self.session.sync_session.get_transaction()
            advance = state.advances.get(row.build_id) if isinstance(state, _State) else None
            if (
                not isinstance(state, _State)
                or state.transaction is not current_transaction
                or advance is None
                or advance.revision != actual.revision
                or actual.revision != claim.resource.revision + 1
            ):
                raise IndexTrackingError("rag_index_inventory_changed")
        return row, attempt

    async def _lock_relation(self, row: RagIndexResourceRecord) -> AssetSourceRelationRecord:
        relations = tuple(
            await self.session.scalars(
                select(AssetSourceRelationRecord)
                .where(
                    AssetSourceRelationRecord.participant == "rag_index_resources",
                    AssetSourceRelationRecord.kind == "index_build",
                    AssetSourceRelationRecord.resource_id == row.build_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if len(relations) != 1:
            raise IndexTrackingError("rag_index_inventory_incomplete")
        relation = relations[0]
        if (
            relation.workspace_id,
            relation.document_id,
            relation.asset_version_id,
            relation.resource_revision,
            relation.relation_kind,
        ) != (
            row.workspace_id,
            row.document_id,
            row.asset_version_id,
            row.revision,
            "derived_artifact",
        ):
            raise IndexTrackingError("rag_index_inventory_incomplete")
        return relation

    @staticmethod
    def _relation(row: RagIndexResourceRecord) -> SourceRelation:
        return SourceRelation(
            SourceIdentity(row.workspace_id, row.document_id, row.asset_version_id),
            ResourceIdentity("rag_index_resources", "index_build", row.build_id, row.revision),
            "derived_artifact",
        )

    @staticmethod
    def _dto(row: RagIndexResourceRecord) -> IndexResource:
        return IndexResource(
            **{
                field.name: getattr(row, field.name)
                for field in fields(IndexResource)
                if field.name != "binding"
            },
            binding=IndexBinding(row.store_id, row.cluster_uuid),
        )

    def _advance(self, row: RagIndexResourceRecord, relation: AssetSourceRelationRecord) -> None:
        sync = self.session.sync_session
        transaction = sync.get_transaction()
        if transaction is None:
            raise IndexTrackingError("rag_index_identity_conflict")
        if not event.contains(sync, "after_soft_rollback", _rollback):
            event.listen(sync, "after_soft_rollback", _rollback)
        state = self.session.info.get(_STATE)
        if not isinstance(state, _State) or state.transaction is not transaction:
            state = _State(transaction, {})
            self.session.info[_STATE] = state
        advance = state.advances.get(row.build_id)
        if advance is None:
            row.revision += 1
            relation.resource_revision = row.revision
            state.advances[row.build_id] = _Advance(
                sync.get_nested_transaction() or transaction, row.revision
            )
        elif advance.revision != row.revision:
            raise IndexTrackingError("rag_index_inventory_changed")
