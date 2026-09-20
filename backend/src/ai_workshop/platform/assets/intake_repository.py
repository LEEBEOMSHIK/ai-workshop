"""Independent HTTP reservations and transaction-bound final source attachment."""

from dataclasses import replace
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.platform.assets.intake_contracts import UploadIntakeClaim
from ai_workshop.platform.assets.intake_models import UploadIntakeRecord
from ai_workshop.platform.assets.models import DocumentRecord
from ai_workshop.platform.assets.provenance_contracts import (
    ResourceIdentity,
    SourceIdentity,
    SourceRelation,
)
from ai_workshop.platform.assets.provenance_repository import ProvenanceRepository
from ai_workshop.platform.assets.temporary_contracts import TemporaryBinding
from ai_workshop.platform.assets.upload_contracts import UploadClaim, UploadOwnershipError
from ai_workshop.platform.assets.upload_models import OriginalResourceRecord, UploadAttemptRecord
from ai_workshop.platform.assets.upload_repository import UploadJournal
from ai_workshop.platform.workspaces.permissions import require_workspace_write

PARTICIPANT = "platform_http_uploads"


def record_claim(row: UploadIntakeRecord) -> UploadIntakeClaim:
    claim = UploadIntakeClaim(
        row.id,
        SourceIdentity(row.workspace_id, row.document_id, row.asset_version_id),
        row.user_id,
        row.new_document,
        TemporaryBinding(row.store_id, row.binding_id),
        row.generation,
        row.revision,
        row.state,
        row.original_attempt_id,
        row.attached,
    )
    if row.existing_document_id != (None if claim.new_document else claim.source.document_id):
        raise UploadOwnershipError("identity_mismatch")
    actual = (row.actual_document_id, row.actual_version_id, row.attached_original_id)
    expected = (
        (claim.source.document_id, claim.source.asset_version_id, claim.original_attempt_id)
        if claim.attached
        else (None, None, None)
    )
    if actual != expected:
        raise UploadOwnershipError("attachment_mismatch")
    return claim


def relation(claim: UploadIntakeClaim) -> SourceRelation:
    return SourceRelation(
        claim.source,
        ResourceIdentity(PARTICIPANT, "intake", claim.id, claim.revision),
        "source_copy",
    )


def _matching_original(intake: UploadIntakeClaim, original: UploadClaim) -> None:
    if (intake.source, intake.user_id, intake.new_document, intake.generation) != (
        original.source,
        original.user_id,
        original.new_document,
        original.generation,
    ) or (
        intake.original_attempt_id is not None and intake.original_attempt_id != original.attempt_id
    ):
        raise UploadOwnershipError("identity_mismatch")


class UploadIntakeJournal:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def reserve(
        self,
        *,
        user_id: UUID,
        workspace_id: UUID | None,
        document_id: UUID | None,
        binding: TemporaryBinding,
    ) -> UploadIntakeClaim:
        if type(user_id) is not UUID or type(binding) is not TemporaryBinding:
            raise UploadOwnershipError("invalid_claim")
        if workspace_id is not None and type(workspace_id) is not UUID:
            raise UploadOwnershipError("invalid_claim")
        if document_id is not None and type(document_id) is not UUID:
            raise UploadOwnershipError("invalid_claim")
        if workspace_id is None and document_id is None:
            raise UploadOwnershipError("invalid_claim")
        async with self.sessions.begin() as session:
            if document_id is not None:
                # Discover the workspace without locking the document ahead of workspace.
                actual_workspace = await session.scalar(
                    select(DocumentRecord.workspace_id).where(DocumentRecord.id == document_id)
                )
                if actual_workspace is None or (
                    workspace_id is not None and workspace_id != actual_workspace
                ):
                    raise UploadOwnershipError("source_unavailable")
                workspace_id = actual_workspace
            assert workspace_id is not None
            await require_workspace_write(session, user_id, workspace_id, lock=True)
            generation = None
            if document_id is not None:
                document = await session.scalar(
                    select(DocumentRecord)
                    .where(DocumentRecord.id == document_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if (
                    document is None
                    or document.workspace_id != workspace_id
                    or document.lifecycle != "active"
                ):
                    raise UploadOwnershipError("source_unavailable")
                generation = document.lifecycle_generation
            claim = UploadIntakeClaim(
                uuid4(),
                SourceIdentity(workspace_id, document_id or uuid4(), uuid4()),
                user_id,
                document_id is None,
                binding,
                generation,
            )
            session.add(
                UploadIntakeRecord(
                    id=claim.id,
                    workspace_id=workspace_id,
                    document_id=claim.source.document_id,
                    asset_version_id=claim.source.asset_version_id,
                    user_id=user_id,
                    new_document=claim.new_document,
                    generation=generation,
                    existing_document_id=document_id,
                    original_attempt_id=None,
                    actual_document_id=None,
                    actual_version_id=None,
                    attached_original_id=None,
                    attached=False,
                    store_id=binding.store_id,
                    binding_id=binding.binding_id,
                    state="open",
                    revision=1,
                    error_code=None,
                )
            )
            await session.flush()
        return claim

    async def _intake(self, session: AsyncSession, claim: UploadIntakeClaim) -> UploadIntakeRecord:
        row = await session.scalar(
            select(UploadIntakeRecord)
            .where(UploadIntakeRecord.id == claim.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or record_claim(row) != claim:
            raise UploadOwnershipError("identity_mismatch")
        return row

    async def reserve_original(
        self, intake: UploadIntakeClaim, original: UploadClaim
    ) -> UploadIntakeClaim:
        _matching_original(intake, original)
        if intake.state != "open" or intake.original_attempt_id is not None:
            raise UploadOwnershipError("invalid_state")
        async with self.sessions.begin() as session:
            await UploadJournal(self.sessions)._source(session, original)
            row = await self._intake(session, intake)
            session.add(
                UploadAttemptRecord(
                    id=original.attempt_id,
                    workspace_id=original.source.workspace_id,
                    document_id=original.source.document_id,
                    asset_version_id=original.source.asset_version_id,
                    user_id=original.user_id,
                    folder_id=original.folder_id,
                    new_document=original.new_document,
                    store_id=original.binding.store_id,
                    binding_id=original.binding.binding_id,
                    suffix=original.suffix,
                    generation=original.generation,
                    canonical_key=original.canonical_key,
                    temporary_key=original.temporary_key,
                    state="open",
                    revision=1,
                    size=None,
                    sha256=None,
                )
            )
            await session.flush()
            row.original_attempt_id, row.revision = original.attempt_id, intake.revision + 1
            await session.flush()
            linked = record_claim(row)
        return linked

    async def prepare_attachment(
        self, session: AsyncSession, intake: UploadIntakeClaim, original: UploadClaim
    ) -> None:
        _matching_original(intake, original)
        if (
            intake.state != "open"
            or intake.attached
            or intake.original_attempt_id != original.attempt_id
        ):
            raise UploadOwnershipError("invalid_state")
        await UploadJournal(self.sessions)._source(session, original)
        await self._intake(session, intake)
        session.info["http_intake_attachment"] = (
            intake,
            original,
            session.sync_session.get_transaction(),
            session.sync_session.get_nested_transaction(),
        )

    async def attach(
        self, session: AsyncSession, intake: UploadIntakeClaim, original: UploadClaim
    ) -> UploadIntakeClaim:
        capability = session.info.pop("http_intake_attachment", None)
        current = session.sync_session.get_transaction()
        if current is None or capability != (
            intake,
            original,
            current,
            session.sync_session.get_nested_transaction(),
        ):
            raise UploadOwnershipError("attachment_mismatch")
        row = await self._intake(session, intake)
        await UploadJournal(self.sessions)._attempt(session, original, "attached", 3)
        resource = await session.get(OriginalResourceRecord, original.attempt_id)
        if resource is None or (
            resource.workspace_id,
            resource.document_id,
            resource.asset_version_id,
        ) != (
            intake.source.workspace_id,
            intake.source.document_id,
            intake.source.asset_version_id,
        ):
            raise UploadOwnershipError("attachment_mismatch")
        row.attached, row.revision = True, intake.revision + 1
        row.actual_document_id, row.actual_version_id = (
            intake.source.document_id,
            intake.source.asset_version_id,
        )
        row.attached_original_id = original.attempt_id
        attached = record_claim(row)
        await ProvenanceRepository(session).register(relation(attached))
        await session.flush()
        return attached

    async def transition(
        self, intake: UploadIntakeClaim, *, expected_state: str
    ) -> UploadIntakeClaim:
        next_states = {"open": "closed", "closed": "cleaning", "cleaning": "cleaned"}
        if expected_state not in next_states or intake.state != expected_state:
            raise UploadOwnershipError("invalid_state")
        changed = replace(intake, state=next_states[expected_state], revision=intake.revision + 1)
        async with self.sessions.begin() as session:
            row = await self._intake(session, intake)
            if intake.attached:
                await ProvenanceRepository(session).replace_current(
                    relation(intake), relation(changed)
                )
            row.state, row.revision = changed.state, changed.revision
            await session.flush()
        return changed
