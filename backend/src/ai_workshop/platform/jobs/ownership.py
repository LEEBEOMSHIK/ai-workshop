"""Platform-owned source identity and current revision relation for durable jobs."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.platform.assets.provenance_contracts import (
    ResourceIdentity,
    SourceIdentity,
    SourceRelation,
)
from ai_workshop.platform.assets.provenance_models import AssetSourceRelationRecord
from ai_workshop.platform.assets.provenance_repository import (
    ProvenanceConflictError,
    ProvenanceRepository,
)
from ai_workshop.platform.jobs.domain import Job
from ai_workshop.platform.jobs.models import JobRecord, JobSourceRecord

PARTICIPANT = "platform_jobs"
_CODES = {
    "job_identity_mismatch",
    "job_revision_conflict",
    "job_source_mismatch",
    "job_relation_mismatch",
}


class JobOwnershipError(ValueError):
    def __init__(self, code: str) -> None:
        if code not in _CODES:
            raise ValueError("unsupported job ownership error")
        self.code = code
        super().__init__(code)


def validate_identity(record: JobRecord, job: Job) -> None:
    if (
        record.id,
        record.user_id,
        record.workspace_id,
        record.asset_version_id,
        record.type,
        record.idempotency_key,
    ) != (
        job.id,
        job.user_id,
        job.workspace_id,
        job.asset_version_id,
        job.type,
        job.idempotency_key,
    ):
        raise JobOwnershipError("job_identity_mismatch")


def relation(owner: JobSourceRecord, revision: int) -> SourceRelation:
    return SourceRelation(
        SourceIdentity(owner.workspace_id, owner.document_id, owner.asset_version_id),
        ResourceIdentity(PARTICIPANT, "job", owner.job_id, revision),
        "derived_artifact",
    )


async def advance_ownership(session: AsyncSession, record: JobRecord) -> int | None:
    """Caller holds fresh job lock. Never acquire source locks from this update path."""
    owner = await session.scalar(
        select(JobSourceRecord)
        .where(JobSourceRecord.job_id == record.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record.revision is None:
        existing = await session.scalar(
            select(AssetSourceRelationRecord.id).where(
                AssetSourceRelationRecord.participant == PARTICIPANT,
                AssetSourceRelationRecord.resource_id == record.id,
            )
        )
        if owner is not None or existing is not None:
            raise JobOwnershipError("job_relation_mismatch")
        return None
    if owner is None or (owner.workspace_id, owner.asset_version_id) != (
        record.workspace_id,
        record.asset_version_id,
    ):
        raise JobOwnershipError("job_source_mismatch")
    # The generic helper filters by kind; check the whole participant/resource identity
    # first so a second unexpected kind cannot silently survive a metadata update.
    current = list(
        await session.scalars(
            select(AssetSourceRelationRecord)
            .where(
                AssetSourceRelationRecord.participant == PARTICIPANT,
                AssetSourceRelationRecord.resource_id == record.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if len(current) != 1 or current[0].kind != "job":
        raise JobOwnershipError("job_relation_mismatch")
    revision = record.revision + 1
    try:
        await ProvenanceRepository(session).replace_current(
            relation(owner, record.revision), relation(owner, revision)
        )
    except ProvenanceConflictError:
        raise JobOwnershipError("job_relation_mismatch") from None
    return revision
