"""Private attachment authorization and transaction-bound upload association."""

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from ai_workshop.config import Settings
from ai_workshop.labs.rag.conversations.attachment_lifecycle import reconcile_deleted_attachments
from ai_workshop.labs.rag.conversations.attachment_models import ConversationAttachmentRecord
from ai_workshop.labs.rag.conversations.models import AttachmentDraftRecord, ConversationRecord
from ai_workshop.labs.rag.documents.models import RagIndexBuildRecord, RagProjectionRecord
from ai_workshop.labs.rag.domains.repository import (
    SqlAlchemyDomainConfigurationProvider,
    SqlAlchemyDomainRepository,
)
from ai_workshop.labs.rag.domains.service import DomainLibraryContext, DomainService
from ai_workshop.platform.assets.intake_contracts import UploadIntakeClaim
from ai_workshop.platform.assets.intake_models import UploadIntakeRecord
from ai_workshop.platform.assets.intake_repository import UploadIntakeJournal
from ai_workshop.platform.assets.library import get_library_service
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.schemas import DocumentResponse
from ai_workshop.platform.assets.upload_contracts import UploadClaim
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_write_allowed
from ai_workshop.shared.errors import AppError


class WorkspaceIdentity(Protocol):
    id: UUID
    created_by: UUID
    expires_at: datetime | None

    @property
    def kind(self) -> str: ...


def attachment_readiness(projection_status: str, build: RagIndexBuildRecord | None) -> str:
    if projection_status in {"failed", "partial_ready"}:
        return "failed"
    if (
        projection_status == "ready"
        and build is not None
        and build.status == "ready"
        and build.is_active
    ):
        return "ready"
    return "processing"


def eligible_attachment_workspace(
    workspace: WorkspaceIdentity,
    actor_id: UUID,
) -> bool:
    return (
        workspace.created_by == actor_id
        and workspace.kind in {"personal", "temporary"}
        and (
            workspace.kind != "temporary"
            or workspace.expires_at is not None
            and workspace.expires_at > datetime.now(UTC)
        )
    )


class AttachmentBinding(Protocol):
    owner_id: UUID
    conversation_id: UUID | None
    workspace_id: UUID
    planned_document_id: UUID | None
    planned_version_id: UUID | None
    state: str


def require_upload_binding(
    record: AttachmentBinding,
    actor_id: UUID,
    conversation_id: UUID,
    source: SourceIdentity,
    *,
    live: bool,
    draft_id: UUID | None = None,
) -> None:
    if (
        not live
        or record.owner_id != actor_id
        or (
            record.conversation_id != conversation_id
            if draft_id is None
            else getattr(record, "draft_id", None) != draft_id
        )
        or getattr(record, "excluded_at", None) is not None
        or record.workspace_id != source.workspace_id
        or record.planned_document_id != source.document_id
        or record.planned_version_id != source.asset_version_id
        or record.state != "uploading"
    ):
        raise AppError("conversation_attachment_changed", "The attachment is no longer valid.", 409)


class AttachmentWorkspaceResponse(BaseModel):
    id: UUID
    name: str
    kind: str


class AttachmentOptionsResponse(BaseModel):
    workspaces: list[AttachmentWorkspaceResponse]
    reason_code: str | None = None


class ConversationAttachmentResponse(BaseModel):
    id: UUID
    document: DocumentResponse | None
    status: str
    error_code: str | None = None
    excluded_at: datetime | None = None


class ConversationAttachmentService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.sessions, self.settings = sessions, settings

    async def authorize(
        self,
        session: AsyncSession,
        slug: str,
        conversation_id: UUID,
        actor_id: UUID,
        *,
        lock: bool = False,
    ) -> DomainLibraryContext:
        domains = DomainService(
            SqlAlchemyDomainRepository(session),
            SqlAlchemyDomainConfigurationProvider(session, self.settings, actor_id=actor_id),
        )
        context = await domains.resolve_library(slug=slug, actor_id=actor_id)
        query = select(ConversationRecord).where(
            ConversationRecord.id == conversation_id,
            ConversationRecord.owner_id == actor_id,
            ConversationRecord.domain_id == context.domain.id,
            ConversationRecord.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update()
        record = await session.scalar(query)
        if record is None:
            raise AppError("not_found", "The conversation was not found.", 404)
        if lock and record.legacy_state != "active":
            raise AppError(
                "legacy_draft_required", "Restore the previous unsent attachment draft.", 409
            )
        return context

    def parent_predicate(self, id: UUID) -> ColumnElement[bool]:
        legacy = select(AttachmentDraftRecord.id).where(
            AttachmentDraftRecord.legacy_conversation_id == id
        )
        bound = select(AttachmentDraftRecord.bound_conversation_id).where(
            AttachmentDraftRecord.legacy_conversation_id == id
        )
        return or_(
            ConversationAttachmentRecord.conversation_id == id,
            ConversationAttachmentRecord.draft_id.in_(legacy),
            ConversationAttachmentRecord.conversation_id.in_(bound),
        )

    async def _spaces(
        self,
        session: AsyncSession,
        context: DomainLibraryContext,
        actor_id: UUID,
    ) -> list[WorkspaceRecord]:
        # Storage permission is independent of the domain's generation subscriptions.
        # Callers still authorize domain access and conversation ownership first.
        rows = await session.scalars(
            select(WorkspaceRecord).where(
                WorkspaceRecord.created_by == actor_id,
                WorkspaceRecord.kind.in_(("personal", "temporary")),
                workspace_write_allowed(actor_id),
            )
        )
        return [row for row in rows if eligible_attachment_workspace(row, actor_id)]

    async def options(
        self, slug: str, conversation_id: UUID, actor_id: UUID
    ) -> AttachmentOptionsResponse:
        async with self.sessions() as session:
            context = await self.authorize(session, slug, conversation_id, actor_id)
            rows = await self._spaces(session, context, actor_id)
            return AttachmentOptionsResponse(
                workspaces=[
                    AttachmentWorkspaceResponse(id=row.id, name=row.name, kind=row.kind)
                    for row in rows
                ],
                reason_code=None if rows else "no_private_attachment_workspace",
            )

    async def reserve(
        self,
        slug: str,
        conversation_id: UUID,
        actor_id: UUID,
        workspace_id: UUID,
    ) -> UUID:
        async with self.sessions.begin() as session:
            context = await self.authorize(session, slug, conversation_id, actor_id, lock=True)
            if workspace_id not in {
                row.id for row in await self._spaces(session, context, actor_id)
            }:
                raise AppError(
                    "attachment_workspace_forbidden", "Select an allowed private space.", 403
                )
            record = ConversationAttachmentRecord(
                id=uuid4(),
                conversation_id=conversation_id,
                owner_id=actor_id,
                workspace_id=workspace_id,
                state="uploading",
                created_at=datetime.now(UTC),
            )
            session.add(record)
            return record.id

    async def fail(self, attachment_id: UUID) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(
                ConversationAttachmentRecord, attachment_id, with_for_update=True
            )
            if row is not None and row.state == "uploading":
                row.state, row.error_code = "failed", "attachment_upload_interrupted"

    async def confirm_upload_termination(self, attachment_id: UUID) -> None:
        """Called only after the owning upload coroutine has returned or joined cleanup."""
        async with self.sessions.begin() as session:
            identity = (
                await session.execute(
                    select(
                        ConversationAttachmentRecord.conversation_id,
                        ConversationAttachmentRecord.draft_id,
                        ConversationAttachmentRecord.intake_id,
                    ).where(ConversationAttachmentRecord.id == attachment_id)
                )
            ).one_or_none()
            if identity is None:
                return
            conversation_id, draft_id, intake_id = identity
            # Intake -> RAG parent -> attachment; a joined coroutine plus cleaned
            # intake certifies transport termination, even for a failed upload.
            intake = (
                await session.get(UploadIntakeRecord, intake_id, with_for_update=True)
                if intake_id
                else None
            )
            conversation = (
                await session.get(ConversationRecord, conversation_id, with_for_update=True)
                if conversation_id
                else None
            )
            draft = (
                await session.get(AttachmentDraftRecord, draft_id, with_for_update=True)
                if draft_id
                else None
            )
            row = await session.get(
                ConversationAttachmentRecord, attachment_id, with_for_update=True
            )
            if row is None:
                return
            if row.intake_id is None or (
                intake is not None and intake.state == "cleaned" and intake.error_code is None
            ):
                row.upload_terminated_at = datetime.now(UTC)
                await session.flush()
            if conversation is not None:
                await reconcile_deleted_attachments(session, conversation)
            if draft is not None and draft.state in {"abandoned", "expired"}:
                from ai_workshop.labs.rag.conversations.attachment_lifecycle import (
                    reconcile_draft_attachments,
                )

                await reconcile_draft_attachments(session, draft)

    async def list(
        self,
        slug: str,
        conversation_id: UUID,
        user: User,
    ) -> list[ConversationAttachmentResponse]:
        async with self.sessions() as session:
            context = await self.authorize(session, slug, conversation_id, user.id)
            eligible = {row.id for row in await self._spaces(session, context, user.id)}
            # Resolve the current exact indexing configuration through its normal repository.
            from ai_workshop.labs.rag.configurations.repository import (
                SqlAlchemyRagConfigurationRepository,
            )

            config = await SqlAlchemyRagConfigurationRepository(session).find_server_bound_version(
                context.connection.configuration_version_id
            )
            rows = await session.scalars(
                select(ConversationAttachmentRecord)
                .where(
                    self.parent_predicate(conversation_id),
                    ConversationAttachmentRecord.owner_id == user.id,
                )
                .order_by(ConversationAttachmentRecord.created_at)
            )
            result = []
            for row in rows:
                if row.workspace_id not in eligible:
                    result.append(
                        ConversationAttachmentResponse(
                            id=row.id,
                            excluded_at=row.excluded_at,
                            document=None,
                            status="failed",
                            error_code="attachment_access_changed",
                        )
                    )
                    continue
                if row.document_id is None:
                    interrupted = row.state == "failed" or row.created_at < datetime.now(
                        UTC
                    ) - timedelta(minutes=30)
                    result.append(
                        ConversationAttachmentResponse(
                            id=row.id,
                            excluded_at=row.excluded_at,
                            document=None,
                            status="failed" if interrupted else "uploading",
                            error_code="attachment_upload_interrupted" if interrupted else None,
                        )
                    )
                    continue
                try:
                    document = await get_library_service(session, self.settings).document(
                        user=user, workspace_id=row.workspace_id, document_id=row.document_id
                    )
                except AppError:
                    result.append(
                        ConversationAttachmentResponse(
                            id=row.id,
                            excluded_at=row.excluded_at,
                            document=None,
                            status="failed",
                            error_code="attachment_access_changed",
                        )
                    )
                    continue
                status = "processing"
                if document.versions[-1].status == "failed":
                    status = "failed"
                elif (
                    config is None
                    or row.workspace_id not in config.workspace_ids
                    or row.workspace_id not in context.allowed_workspace_ids
                ):
                    # A durable private upload must not be mislabeled as searchable
                    # or remain "processing" forever when there is no subscription.
                    status = "stored"
                elif config is not None:
                    projection = await session.scalar(
                        select(RagProjectionRecord).where(
                            RagProjectionRecord.asset_version_id == document.active_version_id,
                            RagProjectionRecord.indexing_profile_id == config.indexing_profile_id,
                            RagProjectionRecord.document_processing_profile_id
                            == config.document_processing_profile_id,
                        )
                    )
                    if projection is not None:
                        build = await session.scalar(
                            select(RagIndexBuildRecord).where(
                                RagIndexBuildRecord.projection_id == projection.id,
                                RagIndexBuildRecord.indexing_profile_id
                                == config.indexing_profile_id,
                                RagIndexBuildRecord.document_processing_profile_id
                                == config.document_processing_profile_id,
                            )
                        )
                        status = attachment_readiness(projection.status, build)
                result.append(
                    ConversationAttachmentResponse(
                        id=row.id,
                        excluded_at=row.excluded_at,
                        document=DocumentResponse.from_domain(document),
                        status=status,
                        error_code=(
                            "attachment_processing_failed"
                            if status == "failed"
                            else "attachment_outside_generation_scope"
                            if status == "stored"
                            else None
                        ),
                    )
                )
            return result


class ConversationUploadJournal(UploadIntakeJournal):
    def __init__(
        self,
        service: ConversationAttachmentService,
        *,
        slug: str,
        conversation_id: UUID,
        actor_id: UUID,
        attachment_id: UUID,
        draft_id: UUID | None = None,
    ) -> None:
        super().__init__(service.sessions)
        self.draft_id = draft_id
        self.service, self.slug = service, slug
        self.conversation_id, self.actor_id, self.attachment_id = (
            conversation_id,
            actor_id,
            attachment_id,
        )

    async def reserved(self, session: AsyncSession, claim: UploadIntakeClaim) -> None:
        context = await self.service.authorize(
            session, self.slug, self.conversation_id, self.actor_id, lock=True
        )
        if claim.source.workspace_id not in {
            space.id for space in await self.service._spaces(session, context, self.actor_id)
        }:
            raise AppError(
                "attachment_workspace_forbidden", "The attachment storage permission changed.", 403
            )
        row = await session.get(
            ConversationAttachmentRecord, self.attachment_id, with_for_update=True
        )
        if (
            row is None
            or row.state != "uploading"
            or row.owner_id != self.actor_id
            or row.workspace_id != claim.source.workspace_id
            or row.excluded_at is not None
        ):
            raise AppError(
                "conversation_attachment_changed", "The attachment reservation changed.", 409
            )
        if (
            row.conversation_id != self.conversation_id
            if self.draft_id is None
            else row.draft_id != self.draft_id
        ):
            raise AppError("conversation_attachment_changed", "The attachment parent changed.", 409)
        row.intake_id, row.planned_document_id = claim.id, claim.source.document_id
        row.planned_version_id = claim.source.asset_version_id

    async def prepare_attachment(
        self, session: AsyncSession, claim: UploadIntakeClaim, original: UploadClaim
    ) -> None:
        await super().prepare_attachment(session, claim, original)
        context = await self.service.authorize(
            session, self.slug, self.conversation_id, self.actor_id, lock=True
        )
        if original.source.workspace_id not in {
            row.id for row in await self.service._spaces(session, context, self.actor_id)
        }:
            raise AppError("attachment_workspace_forbidden", "The attachment scope changed.", 403)
        row = await session.get(
            ConversationAttachmentRecord, self.attachment_id, with_for_update=True
        )
        assert row is not None
        require_upload_binding(
            row,
            self.actor_id,
            self.conversation_id,
            original.source,
            live=True,
            draft_id=self.draft_id,
        )

    async def attach(
        self, session: AsyncSession, claim: UploadIntakeClaim, original: UploadClaim
    ) -> UploadIntakeClaim:
        attached = await super().attach(session, claim, original)
        row = await session.get(
            ConversationAttachmentRecord, self.attachment_id, with_for_update=True
        )
        assert row is not None
        require_upload_binding(
            row,
            self.actor_id,
            self.conversation_id,
            original.source,
            live=True,
            draft_id=self.draft_id,
        )
        row.document_id, row.asset_version_id = (
            original.source.document_id,
            original.source.asset_version_id,
        )
        row.state = "attached"
        await session.flush()
        return attached
