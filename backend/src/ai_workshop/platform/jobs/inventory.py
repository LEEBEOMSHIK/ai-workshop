"""Read-only Jobs metadata inventory; terminal status is not writer termination."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import ResourceIdentity
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.purge_inventory_contracts import ParticipantInventory
from ai_workshop.platform.assets.repository import SqlAlchemyAssetRepository
from ai_workshop.platform.jobs.models import JobRecord, JobSourceRecord
from ai_workshop.platform.jobs.ownership import PARTICIPANT
from ai_workshop.shared.errors import AppError
from ai_workshop.shared.models import Base


@dataclass(frozen=True)
class JobInventory:
    resources: tuple[ResourceIdentity, ...]
    blockers: tuple[str, ...]
    complete: bool

    @property
    def participant(self) -> ParticipantInventory:
        return ParticipantInventory(PARTICIPANT, 1, self.resources, True, True, self.complete)


@dataclass(frozen=True)
class _Snapshot:
    workspace_id: UUID
    document_id: UUID
    documents: tuple[DocumentRecord, ...]
    versions: tuple[AssetVersionRecord, ...]
    jobs: tuple[JobRecord, ...]
    owners: tuple[JobSourceRecord, ...]
    relations: tuple[AssetSourceRelationRecord, ...]

    def fingerprint(self) -> tuple[tuple[tuple[object, ...], ...], ...]:
        groups: tuple[tuple[Base, ...], ...] = (
            self.documents,
            self.versions,
            self.jobs,
            self.owners,
            self.relations,
        )
        return tuple(
            tuple(tuple(getattr(row, col.key) for col in row.__table__.columns) for row in rows)
            for rows in groups
        )


class JobMetadataInventory:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _snapshot(
        self, workspace_id: UUID, document_id: UUID, user_id: UUID | None = None
    ) -> _Snapshot:
        async with self.sessions() as session:
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            await session.execute(text("SET TRANSACTION READ ONLY"))
            documents = tuple(
                await session.scalars(
                    select(DocumentRecord).where(
                        DocumentRecord.workspace_id == workspace_id,
                        DocumentRecord.id == document_id,
                    )
                )
            )
            if user_id is not None and (
                not documents
                or not await SqlAlchemyAssetRepository(session).has_workspace_access(
                    user_id, workspace_id
                )
            ):
                raise AppError("not_found", "The requested resource was not found.", 404)
            versions = tuple(
                await session.scalars(
                    select(AssetVersionRecord)
                    .where(AssetVersionRecord.document_id == document_id)
                    .order_by(AssetVersionRecord.id)
                )
            )
            version_ids = [row.id for row in versions]
            owned_ids = select(JobSourceRecord.job_id).where(
                JobSourceRecord.workspace_id == workspace_id,
                JobSourceRecord.document_id == document_id,
            )
            relation_ids = select(AssetSourceRelationRecord.resource_id).where(
                AssetSourceRelationRecord.participant == PARTICIPANT,
                AssetSourceRelationRecord.workspace_id == workspace_id,
                AssetSourceRelationRecord.document_id == document_id,
            )
            jobs = tuple(
                await session.scalars(
                    select(JobRecord)
                    .where(
                        or_(
                            JobRecord.asset_version_id.in_(version_ids),
                            JobRecord.id.in_(owned_ids),
                            JobRecord.id.in_(relation_ids),
                        )
                    )
                    .order_by(JobRecord.id)
                )
            )
            job_ids = [row.id for row in jobs]
            owners = tuple(
                await session.scalars(
                    select(JobSourceRecord)
                    .where(
                        or_(
                            JobSourceRecord.job_id.in_(job_ids),
                            (JobSourceRecord.workspace_id == workspace_id)
                            & (JobSourceRecord.document_id == document_id),
                            JobSourceRecord.job_id.in_(relation_ids),
                        )
                    )
                    .order_by(JobSourceRecord.job_id)
                )
            )
            ids = sorted(set(job_ids + [row.job_id for row in owners]))
            relations = tuple(
                await session.scalars(
                    select(AssetSourceRelationRecord)
                    .where(
                        AssetSourceRelationRecord.participant == PARTICIPANT,
                        or_(
                            AssetSourceRelationRecord.resource_id.in_(ids),
                            (AssetSourceRelationRecord.workspace_id == workspace_id)
                            & (AssetSourceRelationRecord.document_id == document_id),
                        ),
                    )
                    .order_by(AssetSourceRelationRecord.id)
                )
            )
            return _Snapshot(
                workspace_id, document_id, documents, versions, jobs, owners, relations
            )

    @staticmethod
    def _reconcile(snapshot: _Snapshot) -> set[str]:
        blockers: set[str] = set()
        if not snapshot.documents:
            blockers.add("source_unavailable")
        owners = {row.job_id: row for row in snapshot.owners}
        versions = {row.id: row for row in snapshot.versions}
        jobs = {row.id: row for row in snapshot.jobs}
        expected = set()
        covered_versions = set()
        if snapshot.jobs or snapshot.owners or snapshot.relations:
            blockers.add("writer_unconfirmed")
        for job in snapshot.jobs:
            owner = owners.get(job.id)
            if job.revision is None:
                blockers.add("legacy_untracked")
                if owner is not None:
                    blockers.add("ownership_mismatch")
                continue
            if type(job.revision) is not int or job.revision < 1:
                blockers.add("invalid_revision")
                continue
            covered_versions.add(job.asset_version_id)
            source = (snapshot.workspace_id, snapshot.document_id, job.asset_version_id)
            if (
                owner is None
                or (owner.workspace_id, owner.document_id, owner.asset_version_id) != source
                or job.workspace_id != snapshot.workspace_id
                or job.asset_version_id not in versions
            ):
                blockers.add("ownership_mismatch")
            expected.add((*source, "job", job.id, job.revision, "derived_artifact"))
        if set(owners) - set(jobs):
            blockers.add("ownership_mismatch")
        if set(versions) - covered_versions:
            blockers.add("legacy_untracked")
        actual = {
            (
                row.workspace_id,
                row.document_id,
                row.asset_version_id,
                row.kind,
                row.resource_id,
                row.resource_revision,
                row.relation_kind,
            )
            for row in snapshot.relations
        }
        if actual != expected or len(actual) != len(snapshot.relations):
            blockers.add("relation_mismatch")
        return blockers

    async def collect(
        self, workspace_id: UUID, document_id: UUID, *, user_id: UUID | None = None
    ) -> JobInventory:
        """Trusted participant entry; pass user_id at an authenticated public boundary."""
        before = await self._snapshot(workspace_id, document_id, user_id)
        blockers = self._reconcile(before)
        after = await self._snapshot(workspace_id, document_id, user_id)
        if before.fingerprint() != after.fingerprint():
            blockers.add("inventory_changed")
        resources = tuple(
            ResourceIdentity(PARTICIPANT, "job", row.id, row.revision)
            for row in before.jobs
            if type(row.revision) is int and row.revision > 0
        )
        return JobInventory(resources, tuple(sorted(blockers)), not blockers)
