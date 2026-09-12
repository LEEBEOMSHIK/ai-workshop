"""Transactional document review workflow, independent from model execution grants."""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.config import Settings
from ai_workshop.labs.rag.policies.repository import SqlAlchemyDataPolicyRepository
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed
from ai_workshop.platform.workspaces.repository import workspace_is_active
from ai_workshop.shared.errors import AppError

from .codex_approval_models import EvidenceApprovalStateRecord
from .codex_authorization import CodexAuthorizationError
from .evidence_approval_lifecycle import mutate_evidence_approval
from .evidence_approval_request_access import (
    actor_access,
    not_found,
    require_current_expiry,
    revision_access,
)
from .evidence_approval_request_cursor import RequestCursor
from .evidence_approval_request_models import (
    EvidenceApprovalRequestReceiptRecord as Receipt,
)
from .evidence_approval_request_models import EvidenceApprovalRequestRecord as Record
from .evidence_approval_request_schemas import (
    EvidenceApprovalContext,
    EvidenceApprovalRequestAdminPage,
    EvidenceApprovalRequestAdminResponse,
    EvidenceApprovalRequestCreate,
    EvidenceApprovalRequestDecision,
    EvidenceApprovalRequestPage,
    EvidenceApprovalRequestResponse,
    SupportedEvidenceProvider,
)


def conflict() -> AppError:
    return AppError("evidence_request_conflict", "Refresh the document and request state.", 409)


async def receipt_lock(session: AsyncSession, actor_id: UUID, request_id: UUID) -> None:
    key = int.from_bytes(
        sha256(f"evidence-request:{actor_id}:{request_id}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def approval_context(
    session: AsyncSession, revision_id: UUID, provider: SupportedEvidenceProvider
) -> EvidenceApprovalContext:
    state = await session.get(EvidenceApprovalStateRecord, (revision_id, provider))
    return EvidenceApprovalContext(
        revision_id=revision_id,
        provider=provider,
        approval_generation=state.generation if state else 0,
        approval_status=(
            "approved"
            if state and state.status == "approved"
            else "revoked"
            if state
            else "unapproved"
        ),
    )


class EvidenceApprovalRequests:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.sessions, self.settings = sessions, settings
        self.cursor = RequestCursor(settings)

    async def create(
        self, *, actor_id: UUID, body: EvidenceApprovalRequestCreate
    ) -> EvidenceApprovalRequestResponse:
        # Validate even internal callers that used model_copy/model_construct.
        body = EvidenceApprovalRequestCreate.model_validate(body.model_dump())
        digest = sha256(body.model_dump_json(exclude={"request_id"}).encode()).hexdigest()
        async with self.sessions.begin() as session:
            await SqlAlchemyDataPolicyRepository(session).lock_external_execution_policy()
            await actor_access(
                session, actor_id, admin=False, environment=self.settings.environment, lock=True
            )
            asset, document = await revision_access(
                session, body.revision_id, (actor_id,), lock=True
            )
            if asset.status != "ready":
                raise conflict()
            await receipt_lock(session, actor_id, body.request_id)
            await require_current_expiry(session, document.workspace_id)
            receipt = await session.get(Receipt, (actor_id, body.request_id))
            if receipt:
                if receipt.request_digest != digest:
                    raise conflict()
                prior = await session.get(Record, receipt.approval_request_id)
                return EvidenceApprovalRequestResponse.model_validate(prior)
            context = await approval_context(session, body.revision_id, body.provider)
            if context.approval_generation != body.expected_approval_generation:
                raise conflict()
            if context.approval_status == "approved":
                raise conflict()
            row = await session.scalar(
                select(Record).where(
                    Record.requester_id == actor_id,
                    Record.revision_id == body.revision_id,
                    Record.provider == body.provider,
                    Record.status == "pending",
                )
            )
            if row is None:
                row = Record(
                    id=uuid4(),
                    requester_id=actor_id,
                    revision_id=body.revision_id,
                    provider=body.provider,
                    status="pending",
                    state_revision=0,
                    created_at=datetime.now(UTC),
                )
                session.add(row)
                await session.flush()
            session.add(
                Receipt(
                    actor_id=actor_id,
                    request_id=body.request_id,
                    request_digest=digest,
                    approval_request_id=row.id,
                )
            )
            await session.flush()
            return EvidenceApprovalRequestResponse.model_validate(row)

    async def decide(
        self, *, actor_id: UUID, id: UUID, body: EvidenceApprovalRequestDecision
    ) -> EvidenceApprovalRequestResponse:
        body = EvidenceApprovalRequestDecision.model_validate(body.model_dump())
        digest = sha256(
            (str(id) + body.model_dump_json(exclude={"request_id"})).encode()
        ).hexdigest()
        async with self.sessions.begin() as session:
            await SqlAlchemyDataPolicyRepository(session).lock_external_execution_policy()
            # Metadata lookup is private; authorize and lock actors before any disclosure.
            target = await session.get(Record, id)
            if target is None:
                raise not_found()
            for selected in sorted({actor_id, target.requester_id}):
                await actor_access(
                    session,
                    selected,
                    admin=selected == actor_id,
                    environment=self.settings.environment,
                    lock=True,
                )
            asset, document = await revision_access(
                session, target.revision_id, (actor_id, target.requester_id), lock=True
            )
            await receipt_lock(session, actor_id, body.request_id)
            await require_current_expiry(session, document.workspace_id)
            prior = await session.scalar(
                select(Record)
                .where(
                    Record.resolved_by == actor_id, Record.decision_request_id == body.request_id
                )
                .execution_options(populate_existing=True)
            )
            if prior:
                if prior.id != id or prior.decision_digest != digest:
                    raise conflict()
                return EvidenceApprovalRequestResponse.model_validate(prior)
            # Refresh the initial metadata row after the asset serialized concurrent writers.
            row = await session.scalar(
                select(Record)
                .where(Record.id == id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise not_found()
            if row.status != "pending" or row.state_revision != body.expected_state_revision:
                raise conflict()
            provider: SupportedEvidenceProvider = "development_codex_exec"
            if row.provider != provider:
                raise conflict()
            context = await approval_context(session, row.revision_id, provider)
            if context.approval_generation != body.expected_approval_generation:
                raise conflict()
            occurred_at = datetime.now(UTC)
            if body.decision == "approve":
                if asset.status != "ready" or asset.sha256 != body.content_sha256:
                    raise conflict()
                if context.approval_status == "approved":
                    # Another reviewed request or owner action may have already granted
                    # this classification. Link the exact current grant without issuing
                    # a redundant generation; the asset lock keeps it stable until commit.
                    state = await session.get(
                        EvidenceApprovalStateRecord, (row.revision_id, provider)
                    )
                    if (
                        state is None
                        or state.classification != body.classification
                        or state.content_sha256 != body.content_sha256
                    ):
                        raise conflict()
                else:
                    try:
                        await mutate_evidence_approval(
                            session,
                            actor_id=actor_id,
                            revision_id=row.revision_id,
                            provider=provider,
                            action="approve",
                            content_sha256=body.content_sha256,
                            classification=body.classification,
                            expected_generation=body.expected_approval_generation,
                            request_id=body.request_id,
                            occurred_at=occurred_at,
                        )
                    except CodexAuthorizationError:
                        raise conflict() from None
            await require_current_expiry(session, document.workspace_id)
            row.status = "approved" if body.decision == "approve" else "rejected"
            row.state_revision = 1
            row.resolved_at = occurred_at
            row.resolved_by = actor_id
            row.decision_request_id = body.request_id
            row.decision_digest = digest
            await session.flush()
            return EvidenceApprovalRequestResponse.model_validate(row)

    async def list(
        self,
        *,
        actor_id: UUID,
        admin: bool = False,
        revision_id: UUID | None = None,
        provider: SupportedEvidenceProvider = "development_codex_exec",
        cursor: str | None = None,
        limit: int | None = None,
    ) -> EvidenceApprovalRequestPage | EvidenceApprovalRequestAdminPage:
        page_size = self.settings.library_page_size if limit is None else limit
        if type(page_size) is not int or not 1 <= page_size <= self.settings.library_max_page_size:
            raise AppError("evidence_request_invalid_limit", "Invalid request page size.", 422)
        if provider != "development_codex_exec":
            raise AppError("evidence_request_invalid_provider", "Unsupported review provider.", 422)
        scope = [str(actor_id), "admin" if admin else "self", str(revision_id), provider]
        position = self.cursor.decode(cursor, scope)
        async with self.sessions.begin() as session:
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            await actor_access(
                session, actor_id, admin=admin, environment=self.settings.environment
            )
            context = None
            if revision_id is not None:
                await revision_access(session, revision_id, (actor_id,))
                context = await approval_context(session, revision_id, provider)
            query = (
                select(
                    Record,
                    AssetVersionRecord,
                    DocumentRecord,
                    WorkspaceRecord,
                    UserRecord.display_name,
                )
                .join(AssetVersionRecord, AssetVersionRecord.id == Record.revision_id)
                .join(DocumentRecord, DocumentRecord.id == AssetVersionRecord.document_id)
                .join(WorkspaceRecord, WorkspaceRecord.id == DocumentRecord.workspace_id)
                .join(
                    WorkspaceMembershipRecord,
                    and_(
                        WorkspaceMembershipRecord.workspace_id == WorkspaceRecord.id,
                        WorkspaceMembershipRecord.user_id == actor_id,
                    ),
                )
                .join(UserRecord, UserRecord.id == Record.requester_id)
                .where(
                    workspace_is_active(),
                    workspace_read_allowed(actor_id),
                    or_(WorkspaceRecord.kind != "personal", WorkspaceRecord.created_by == actor_id),
                    Record.provider == provider,
                )
            )
            if not admin:
                query = query.where(Record.requester_id == actor_id)
            if revision_id is not None:
                query = query.where(Record.revision_id == revision_id)
            if position:
                query = query.where(tuple_(Record.created_at, Record.id) > position)
            rows = (
                await session.execute(
                    query.order_by(Record.created_at, Record.id).limit(page_size + 1)
                )
            ).all()
            visible = rows[:page_size]
            next_cursor = None
            if len(rows) > page_size:
                last = visible[-1][0]
                next_cursor = self.cursor.encode(scope, last.created_at, last.id)
            if admin:
                return EvidenceApprovalRequestAdminPage(
                    items=[
                        EvidenceApprovalRequestAdminResponse(
                            **EvidenceApprovalRequestResponse.model_validate(row).model_dump(),
                            document_id=document.id,
                            workspace_id=workspace.id,
                            document_name=document.name,
                            workspace_name=workspace.name,
                            revision_number=asset.number,
                            requester_display_name=display_name,
                        )
                        for row, asset, document, workspace, display_name in visible
                    ],
                    next_cursor=next_cursor,
                )
            return EvidenceApprovalRequestPage(
                items=[EvidenceApprovalRequestResponse.model_validate(row[0]) for row in visible],
                next_cursor=next_cursor,
                context=context,
            )
