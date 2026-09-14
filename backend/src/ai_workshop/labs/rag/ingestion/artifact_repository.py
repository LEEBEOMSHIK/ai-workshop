from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import event, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from ai_workshop.labs.rag.documents.models import RagProjectionRecord
from ai_workshop.labs.rag.ingestion.artifact_contracts import (
    ArtifactBinding,
    ArtifactClaim,
    ArtifactPublication,
    ArtifactRole,
    ArtifactTrackingError,
    VerifiedArtifact,
)
from ai_workshop.labs.rag.ingestion.artifact_models import (
    RagArtifactAttemptRecord,
    RagArtifactBundleRecord,
    RagArtifactSlotRecord,
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

_PARTICIPANT = "rag_ingestion_artifacts"
_KIND = "artifact_bundle"
_RELATION_KIND = "derived_artifact"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{0,79}")
_REVISION_STATE_KEY = "rag_artifact_revision_transaction_state"


@dataclass(frozen=True, slots=True)
class _OfficialSource:
    job_id: UUID
    projection_id: UUID
    source: SourceIdentity


@dataclass(slots=True)
class _RevisionAdvance:
    transaction: SessionTransaction
    revision: int


@dataclass(slots=True)
class _RevisionTransactionState:
    transaction: SessionTransaction
    advances: dict[UUID, _RevisionAdvance]


def _discard_rolled_back_revisions(
    session: Session, rolled_back: SessionTransaction,
) -> None:
    state = session.info.get(_REVISION_STATE_KEY)
    if not isinstance(state, _RevisionTransactionState):
        return
    if state.transaction is rolled_back:
        session.info.pop(_REVISION_STATE_KEY, None)
        return
    for bundle_id, advance in tuple(state.advances.items()):
        origin: SessionTransaction | None = advance.transaction
        # A released inner savepoint still belongs to an outer rollback scope.
        while origin is not None:
            if origin is rolled_back:
                del state.advances[bundle_id]
                break
            origin = origin.parent


class SqlAlchemyRagArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register_bundle(self, job_id: UUID, binding: ArtifactBinding) -> UUID:
        source = await self._load_official_source(job_id)
        candidate_id = uuid4()
        result = await self.session.execute(
            insert(RagArtifactBundleRecord)
            .values(
                id=candidate_id,
                projection_id=source.projection_id,
                job_id=source.job_id,
                workspace_id=source.source.workspace_id,
                document_id=source.source.document_id,
                asset_version_id=source.source.asset_version_id,
                revision=1,
            )
            .on_conflict_do_nothing(index_elements=[RagArtifactBundleRecord.projection_id])
            .returning(RagArtifactBundleRecord.id)
        )
        inserted_id = result.scalar_one_or_none()
        bundle = await self._lock_bundle(source)
        if bundle is None:
            raise ArtifactTrackingError("artifact_bundle_conflict")
        self._require_bundle_source(bundle, source)
        if inserted_id is not None:
            for role in ArtifactRole:
                self.session.add(
                    RagArtifactSlotRecord(
                        bundle_id=bundle.id,
                        role=role.value,
                        store_id=binding.store_id,
                        store_binding_id=binding.binding_id,
                        canonical_key=self._canonical_key(source.projection_id, role),
                        state="reserved",
                        published_size=None,
                        published_sha256=None,
                    )
                )
            await self.session.flush()
            await ProvenanceRepository(self.session).register(
                self._expected_relation(bundle, source.source)
            )
        slots = await self._lock_slots(bundle.id)
        self._require_exact_slots(slots, source.projection_id, binding)
        await self._lock_current_relation(bundle, source.source)
        return bundle.id

    async def reserve_attempt(
        self,
        job_id: UUID,
        role: ArtifactRole,
        binding: ArtifactBinding,
        *,
        size: int,
        sha256: str,
    ) -> ArtifactClaim | VerifiedArtifact:
        self._require_size(size)
        self._require_sha256(sha256)
        if not isinstance(role, ArtifactRole):
            raise ArtifactTrackingError("artifact_role_invalid")
        source = await self._load_official_source(job_id)
        bundle = await self._lock_bundle(source)
        if bundle is None:
            raise ArtifactTrackingError("artifact_bundle_missing")
        self._require_bundle_source(bundle, source)
        slot = await self._lock_slot(bundle.id, role)
        self._require_slot(slot, source.projection_id, role, binding)
        attempts = await self._lock_attempts(slot.id)
        relation = await self._lock_current_relation(bundle, source.source)
        if slot.state == "verified":
            if any(attempt.state == "open" for attempt in attempts):
                raise ArtifactTrackingError("artifact_slot_state_conflict")
            if slot.published_size != size or slot.published_sha256 != sha256:
                raise ArtifactTrackingError("artifact_verified_conflict")
            return self._verified(bundle, slot, source, role, binding)
        if any(attempt.state == "open" for attempt in attempts):
            raise ArtifactTrackingError("artifact_attempt_busy")

        attempt_id = uuid4()
        claim = ArtifactClaim(
            bundle_id=bundle.id,
            slot_id=slot.id,
            attempt_id=attempt_id,
            job_id=source.job_id,
            projection_id=source.projection_id,
            role=role,
            binding=binding,
            canonical_key=slot.canonical_key,
            temporary_key=self._temporary_key(slot.canonical_key, attempt_id),
            proposed_size=size,
            proposed_sha256=sha256,
        )
        self.session.add(
            RagArtifactAttemptRecord(
                id=attempt_id,
                slot_id=slot.id,
                store_id=binding.store_id,
                store_binding_id=binding.binding_id,
                temporary_key=claim.temporary_key,
                proposed_size=size,
                proposed_sha256=sha256,
                state="open",
                result_code=None,
                closed_at=None,
            )
        )
        self._advance(bundle, relation)
        await self.session.flush()
        return claim

    async def finalize(self, publication: ArtifactPublication) -> VerifiedArtifact:
        claim = publication.claim
        if (
            publication.size != claim.proposed_size
            or publication.sha256 != claim.proposed_sha256
        ):
            raise ArtifactTrackingError("artifact_publication_mismatch")
        self._require_size(publication.size)
        self._require_sha256(publication.sha256)
        source = await self._load_official_source(claim.job_id)
        if source.projection_id != claim.projection_id:
            raise ArtifactTrackingError("artifact_claim_source_mismatch")
        bundle = await self._lock_bundle_by_id(claim.bundle_id)
        self._require_claim_bundle(bundle, source, claim)
        slot = await self._lock_slot_by_id(claim.slot_id)
        self._require_claim_slot(slot, bundle, claim)
        attempt = await self._lock_attempt(claim.attempt_id)
        self._require_claim_attempt(attempt, claim)
        relation = await self._lock_current_relation(bundle, source.source)

        if attempt.state == "closed":
            if (
                attempt.result_code != "verified"
                or slot.state != "verified"
                or slot.published_size != publication.size
                or slot.published_sha256 != publication.sha256
            ):
                raise ArtifactTrackingError("artifact_attempt_closed")
            return self._verified(bundle, slot, source, claim.role, claim.binding)
        if slot.state != "reserved":
            raise ArtifactTrackingError("artifact_slot_state_conflict")

        slot.state = "verified"
        slot.published_size = publication.size
        slot.published_sha256 = publication.sha256
        attempt.state = "closed"
        attempt.result_code = "verified"
        attempt.closed_at = datetime.now(UTC)
        self._advance(bundle, relation)
        await self.session.flush()
        return self._verified(bundle, slot, source, claim.role, claim.binding)

    async def close_failed_attempt(self, claim: ArtifactClaim, *, code: str) -> None:
        if type(code) is not str or _SAFE_CODE.fullmatch(code) is None or code == "verified":
            raise ArtifactTrackingError("artifact_failure_code_invalid")
        source = await self._load_official_source(claim.job_id)
        if source.projection_id != claim.projection_id:
            raise ArtifactTrackingError("artifact_claim_source_mismatch")
        bundle = await self._lock_bundle_by_id(claim.bundle_id)
        self._require_claim_bundle(bundle, source, claim)
        slot = await self._lock_slot_by_id(claim.slot_id)
        self._require_claim_slot(slot, bundle, claim)
        attempt = await self._lock_attempt(claim.attempt_id)
        self._require_claim_attempt(attempt, claim)
        relation = await self._lock_current_relation(bundle, source.source)

        if attempt.state == "closed":
            if attempt.result_code != code or slot.state != "reserved":
                raise ArtifactTrackingError("artifact_attempt_closed")
            return
        if slot.state != "reserved":
            raise ArtifactTrackingError("artifact_slot_state_conflict")
        attempt.state = "closed"
        attempt.result_code = code
        attempt.closed_at = datetime.now(UTC)
        self._advance(bundle, relation)
        await self.session.flush()

    async def _load_official_source(self, job_id: UUID) -> _OfficialSource:
        row = (
            await self.session.execute(
                select(
                    JobRecord.id,
                    JobRecord.type,
                    JobRecord.workspace_id,
                    JobRecord.asset_version_id,
                    RagIngestionJobRecord.projection_id,
                    RagIngestionJobRecord.asset_version_id,
                    RagProjectionRecord.asset_version_id,
                    AssetVersionRecord.document_id,
                    DocumentRecord.workspace_id,
                )
                .select_from(JobRecord)
                .join(RagIngestionJobRecord, RagIngestionJobRecord.job_id == JobRecord.id)
                .join(
                    RagProjectionRecord,
                    RagProjectionRecord.id == RagIngestionJobRecord.projection_id,
                )
                .join(
                    AssetVersionRecord,
                    AssetVersionRecord.id == RagIngestionJobRecord.asset_version_id,
                )
                .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
                .where(JobRecord.id == job_id)
            )
        ).one_or_none()
        if row is None:
            raise ArtifactTrackingError("artifact_source_invalid")
        (
            stored_job_id,
            job_type,
            job_workspace_id,
            job_asset_version_id,
            projection_id,
            ingestion_asset_version_id,
            projection_asset_version_id,
            document_id,
            document_workspace_id,
        ) = row
        if (
            job_type != JobType.RAG_INGESTION
            or job_workspace_id != document_workspace_id
            or job_asset_version_id != ingestion_asset_version_id
            or ingestion_asset_version_id != projection_asset_version_id
        ):
            raise ArtifactTrackingError("artifact_source_invalid")
        return _OfficialSource(
            job_id=stored_job_id,
            projection_id=projection_id,
            source=SourceIdentity(
                workspace_id=document_workspace_id,
                document_id=document_id,
                asset_version_id=ingestion_asset_version_id,
            ),
        )

    async def _lock_bundle(
        self, source: _OfficialSource
    ) -> RagArtifactBundleRecord | None:
        return cast(
            RagArtifactBundleRecord | None,
            await self.session.scalar(
                select(RagArtifactBundleRecord)
                .where(RagArtifactBundleRecord.projection_id == source.projection_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )

    async def _lock_bundle_by_id(self, bundle_id: UUID) -> RagArtifactBundleRecord:
        bundle = await self.session.scalar(
            select(RagArtifactBundleRecord)
            .where(RagArtifactBundleRecord.id == bundle_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if bundle is None:
            raise ArtifactTrackingError("artifact_attempt_invalid")
        return bundle

    async def _lock_slots(self, bundle_id: UUID) -> tuple[RagArtifactSlotRecord, ...]:
        return tuple(
            await self.session.scalars(
                select(RagArtifactSlotRecord)
                .where(RagArtifactSlotRecord.bundle_id == bundle_id)
                .order_by(RagArtifactSlotRecord.role)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    async def _lock_slot(
        self, bundle_id: UUID, role: ArtifactRole
    ) -> RagArtifactSlotRecord:
        slot = await self.session.scalar(
            select(RagArtifactSlotRecord)
            .where(
                RagArtifactSlotRecord.bundle_id == bundle_id,
                RagArtifactSlotRecord.role == role.value,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if slot is None:
            raise ArtifactTrackingError("artifact_slot_invalid")
        return slot

    async def _lock_slot_by_id(self, slot_id: UUID) -> RagArtifactSlotRecord:
        slot = await self.session.scalar(
            select(RagArtifactSlotRecord)
            .where(RagArtifactSlotRecord.id == slot_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if slot is None:
            raise ArtifactTrackingError("artifact_attempt_invalid")
        return slot

    async def _lock_attempts(self, slot_id: UUID) -> tuple[RagArtifactAttemptRecord, ...]:
        return tuple(
            await self.session.scalars(
                select(RagArtifactAttemptRecord)
                .where(RagArtifactAttemptRecord.slot_id == slot_id)
                .order_by(RagArtifactAttemptRecord.created_at, RagArtifactAttemptRecord.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    async def _lock_attempt(self, attempt_id: UUID) -> RagArtifactAttemptRecord:
        attempt = await self.session.scalar(
            select(RagArtifactAttemptRecord)
            .where(RagArtifactAttemptRecord.id == attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if attempt is None:
            raise ArtifactTrackingError("artifact_attempt_invalid")
        return attempt

    async def _lock_current_relation(
        self,
        bundle: RagArtifactBundleRecord,
        source: SourceIdentity,
    ) -> AssetSourceRelationRecord:
        records = tuple(
            await self.session.scalars(
                select(AssetSourceRelationRecord)
                .where(
                    AssetSourceRelationRecord.participant == _PARTICIPANT,
                    AssetSourceRelationRecord.kind == _KIND,
                    AssetSourceRelationRecord.resource_id == bundle.id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        expected = self._expected_relation(bundle, source)
        if len(records) != 1:
            raise ArtifactTrackingError("artifact_current_relation_conflict")
        record = records[0]
        actual = SourceRelation(
            source=SourceIdentity(
                record.workspace_id, record.document_id, record.asset_version_id
            ),
            resource=ResourceIdentity(
                record.participant,
                record.kind,
                record.resource_id,
                record.resource_revision,
            ),
            relation_kind=record.relation_kind,
        )
        if actual != expected:
            raise ArtifactTrackingError("artifact_current_relation_conflict")
        return record

    @staticmethod
    def _require_bundle_source(
        bundle: RagArtifactBundleRecord, source: _OfficialSource
    ) -> None:
        if (
            bundle.job_id != source.job_id
            or bundle.projection_id != source.projection_id
            or bundle.workspace_id != source.source.workspace_id
            or bundle.document_id != source.source.document_id
            or bundle.asset_version_id != source.source.asset_version_id
        ):
            raise ArtifactTrackingError("artifact_bundle_source_conflict")

    @classmethod
    def _require_claim_bundle(
        cls,
        bundle: RagArtifactBundleRecord,
        source: _OfficialSource,
        claim: ArtifactClaim,
    ) -> None:
        cls._require_bundle_source(bundle, source)
        if bundle.id != claim.bundle_id or bundle.job_id != claim.job_id:
            raise ArtifactTrackingError("artifact_attempt_invalid")

    @classmethod
    def _require_slot(
        cls,
        slot: RagArtifactSlotRecord,
        projection_id: UUID,
        role: ArtifactRole,
        binding: ArtifactBinding,
    ) -> None:
        if (
            slot.role != role.value
            or slot.canonical_key != cls._canonical_key(projection_id, role)
        ):
            raise ArtifactTrackingError("artifact_slot_invalid")
        if slot.store_id != binding.store_id or slot.store_binding_id != binding.binding_id:
            raise ArtifactTrackingError("artifact_binding_mismatch")

    @classmethod
    def _require_claim_slot(
        cls,
        slot: RagArtifactSlotRecord,
        bundle: RagArtifactBundleRecord,
        claim: ArtifactClaim,
    ) -> None:
        if slot.id != claim.slot_id or slot.bundle_id != bundle.id:
            raise ArtifactTrackingError("artifact_attempt_invalid")
        cls._require_slot(slot, claim.projection_id, claim.role, claim.binding)
        if slot.canonical_key != claim.canonical_key:
            raise ArtifactTrackingError("artifact_attempt_invalid")

    @staticmethod
    def _require_claim_attempt(
        attempt: RagArtifactAttemptRecord, claim: ArtifactClaim
    ) -> None:
        if (
            attempt.id != claim.attempt_id
            or attempt.slot_id != claim.slot_id
            or attempt.store_id != claim.binding.store_id
            or attempt.store_binding_id != claim.binding.binding_id
            or attempt.temporary_key != claim.temporary_key
            or attempt.proposed_size != claim.proposed_size
            or attempt.proposed_sha256 != claim.proposed_sha256
        ):
            raise ArtifactTrackingError("artifact_attempt_invalid")

    @classmethod
    def _require_exact_slots(
        cls,
        slots: tuple[RagArtifactSlotRecord, ...],
        projection_id: UUID,
        binding: ArtifactBinding,
    ) -> None:
        if len(slots) != len(ArtifactRole):
            raise ArtifactTrackingError("artifact_slot_invalid")
        roles = sorted(ArtifactRole, key=lambda item: item.value)
        for slot, role in zip(slots, roles, strict=True):
            cls._require_slot(slot, projection_id, role, binding)

    @staticmethod
    def _require_size(size: int) -> None:
        if type(size) is not int or size < 0:
            raise ArtifactTrackingError("artifact_size_invalid")

    @staticmethod
    def _require_sha256(value: str) -> None:
        if type(value) is not str or _SHA256.fullmatch(value) is None:
            raise ArtifactTrackingError("artifact_sha256_invalid")

    @staticmethod
    def _canonical_key(projection_id: UUID, role: ArtifactRole) -> str:
        return f"rag/{role.value}/{projection_id}.json"

    @staticmethod
    def _temporary_key(canonical_key: str, attempt_id: UUID) -> str:
        parent, filename = canonical_key.rsplit("/", 1)
        return f"{parent}/.{filename}.{attempt_id.hex}.tmp"

    @staticmethod
    def _expected_relation(
        bundle: RagArtifactBundleRecord, source: SourceIdentity
    ) -> SourceRelation:
        return SourceRelation(
            source=source,
            resource=ResourceIdentity(
                _PARTICIPANT,
                _KIND,
                bundle.id,
                bundle.revision,
            ),
            relation_kind=_RELATION_KIND,
        )

    def _advance(
        self,
        bundle: RagArtifactBundleRecord,
        relation: AssetSourceRelationRecord,
    ) -> None:
        sync_session = self.session.sync_session
        transaction = sync_session.get_transaction()
        if transaction is None:
            raise ArtifactTrackingError("artifact_transaction_required")
        if not event.contains(sync_session, "after_soft_rollback", _discard_rolled_back_revisions):
            event.listen(sync_session, "after_soft_rollback", _discard_rolled_back_revisions)
        state = self.session.info.get(_REVISION_STATE_KEY)
        if not isinstance(state, _RevisionTransactionState) or state.transaction is not transaction:
            state = _RevisionTransactionState(transaction=transaction, advances={})
            self.session.info[_REVISION_STATE_KEY] = state
        advance = state.advances.get(bundle.id)
        if advance is None:
            bundle.revision += 1
            relation.resource_revision = bundle.revision
            # Record where this increment originated, not just its numeric value.
            # Row locks can be released by rollback of that savepoint alone.
            state.advances[bundle.id] = _RevisionAdvance(
                transaction=sync_session.get_nested_transaction() or transaction,
                revision=bundle.revision,
            )
            return
        if bundle.revision != advance.revision:
            raise ArtifactTrackingError("artifact_revision_conflict")

    @staticmethod
    def _verified(
        bundle: RagArtifactBundleRecord,
        slot: RagArtifactSlotRecord,
        source: _OfficialSource,
        role: ArtifactRole,
        binding: ArtifactBinding,
    ) -> VerifiedArtifact:
        if slot.published_size is None or slot.published_sha256 is None:
            raise ArtifactTrackingError("artifact_slot_state_conflict")
        return VerifiedArtifact(
            bundle_id=bundle.id,
            slot_id=slot.id,
            job_id=source.job_id,
            projection_id=source.projection_id,
            role=role,
            binding=binding,
            canonical_key=slot.canonical_key,
            size=slot.published_size,
            sha256=slot.published_sha256,
        )
