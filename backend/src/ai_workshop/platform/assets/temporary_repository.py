"""Independent committed reservation and atomic provenance state transitions."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import (
    ResourceIdentity,
    SourceIdentity,
    SourceRelation,
)
from ai_workshop.platform.assets.provenance_repository import ProvenanceRepository
from ai_workshop.platform.assets.temporary_contracts import (
    TEMPORARY_STATES,
    TemporaryBinding,
    TemporaryClaim,
    TemporaryContext,
    TemporaryOwnershipError,
    next_temporary_state,
)
from ai_workshop.platform.assets.temporary_models import TemporaryWorkspaceRecord
from ai_workshop.platform.jobs.models import JobRecord

PARTICIPANT = "platform_temporary"


def record_claim(row: TemporaryWorkspaceRecord) -> TemporaryClaim:
    return TemporaryClaim(
        row.id,
        TemporaryContext(
            SourceIdentity(row.workspace_id, row.document_id, row.asset_version_id), row.job_id
        ),
        row.purpose,
        TemporaryBinding(row.store_id, row.binding_id),
        row.generation,
        row.coverage,
    )


def relation(claim: TemporaryClaim, revision: int) -> SourceRelation:
    return SourceRelation(
        claim.context.source,
        ResourceIdentity(PARTICIPANT, "workspace", claim.id, revision),
        "source_copy",
    )


class TemporaryJournal:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def reserve(
        self, context: TemporaryContext, purpose: str, binding: TemporaryBinding, *, coverage: str
    ) -> TemporaryClaim:
        # Validate untrusted shape before opening a transaction.
        candidate = TemporaryClaim(uuid4(), context, purpose, binding, 1, coverage)
        source = context.source
        async with self.sessions.begin() as session:
            # Existing workers acquire these rows in this same order.
            if context.job_id is not None:
                job = await session.get(JobRecord, context.job_id, with_for_update=True)
                if (
                    job is None
                    or job.workspace_id != source.workspace_id
                    or job.asset_version_id != source.asset_version_id
                ):
                    raise TemporaryOwnershipError("job_mismatch")
            version = await session.get(
                AssetVersionRecord, source.asset_version_id, with_for_update=True
            )
            if version is None or version.document_id != source.document_id:
                raise TemporaryOwnershipError("source_mismatch")
            document = await session.get(DocumentRecord, source.document_id, with_for_update=True)
            if document is None or document.workspace_id != source.workspace_id:
                raise TemporaryOwnershipError("source_mismatch")
            if document.lifecycle != "active":
                raise TemporaryOwnershipError("writes_blocked")
            claim = TemporaryClaim(
                candidate.id, context, purpose, binding, document.lifecycle_generation, coverage
            )
            session.add(
                TemporaryWorkspaceRecord(
                    id=claim.id,
                    workspace_id=source.workspace_id,
                    document_id=source.document_id,
                    asset_version_id=source.asset_version_id,
                    job_id=context.job_id,
                    purpose=purpose,
                    store_id=binding.store_id,
                    binding_id=binding.binding_id,
                    generation=claim.generation,
                    coverage=coverage,
                    state="open",
                    revision=1,
                )
            )
            await session.flush()
            await ProvenanceRepository(session).register(relation(claim, 1))
        return claim

    async def transition(self, claim: TemporaryClaim, *, expected_state: str) -> None:
        next_state, revision = next_temporary_state(expected_state)
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(TemporaryWorkspaceRecord)
                .where(TemporaryWorkspaceRecord.id == claim.id)
                .with_for_update()
            )
            if row is None or record_claim(row) != claim:
                raise TemporaryOwnershipError("invalid_claim")
            if row.state != expected_state or row.revision != TEMPORARY_STATES[expected_state]:
                raise TemporaryOwnershipError("state_conflict")
            await ProvenanceRepository(session).replace_current(
                relation(claim, revision - 1), relation(claim, revision)
            )
            row.state, row.revision = next_state, revision
            await session.flush()
