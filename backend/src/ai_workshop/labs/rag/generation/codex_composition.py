"""Request-lifetime SQL adapters; construction and metadata lookup never launch Codex."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_workshop.config import Settings
from ai_workshop.labs.rag.configurations.repository import SqlAlchemyRagConfigurationRepository
from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment, ProviderKind
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.shared.errors import AppError
from ai_workshop.shared.request_context import correlation_id_context

from .codex_approval_models import EvidenceApprovalEventRecord, EvidenceApprovalStateRecord
from .codex_approval_repository import SqlAlchemyCodexAuthorizationSource
from .codex_authorization import (
    CodexAuthorizationError,
    CodexAuthorizationErrorCode,
    EvidenceClassification,
)
from .codex_execution import CodexRequestExecutor
from .codex_request import CodexRequestContext
from .codex_runner_registry import CodexRunnerRegistry
from .codex_runtime import CodexExecRuntime, CodexPassiveReadiness
from .codex_slot_repository import SqlAlchemyCodexExecutionSlots
from .codex_stream import CodexStreamRunner
from .codex_verification import CodexVerificationService
from .codex_verification_repository import (
    SqlAlchemyCodexVerificationLookup,
    SqlAlchemyCodexVerificationRepository,
)
from .codex_workspace import CodexWorkspaceExecutor
from .domain import GenerationProfile


def codex_registry(settings: Settings) -> CodexRunnerRegistry:
    repository_root = Path(__file__).resolve().parents[6]
    return CodexRunnerRegistry(
        settings.codex_runner_refs,
        environment=settings.environment,
        protected_roots=(
            repository_root,
            settings.object_store_root.resolve(),
            settings.model_cache_root.resolve(),
        ),
    )


@dataclass(frozen=True, slots=True)
class EvidenceApprovalHistory:
    action: str
    generation: int
    actor_id: UUID | None
    occurred_at: datetime
    classification: str


@dataclass(frozen=True, slots=True)
class CodexEvidenceMetadata:
    revision_id: UUID
    document_id: UUID
    workspace_id: UUID
    document_name: str
    revision_number: int
    content_sha256: str
    approval_classification: str | None
    approved_at: datetime | None
    revoked: bool
    approval_generation: int
    provider: str
    approval_history: tuple[EvidenceApprovalHistory, ...]


class CodexEvidenceAdministration:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        source: SqlAlchemyCodexAuthorizationSource,
        environment: str,
    ) -> None:
        self._sessions, self._source, self._environment = sessions, source, environment

    async def _authorize(self, session: AsyncSession, actor_id: UUID, workspace_id: UUID) -> None:
        actor = await session.get(UserRecord, actor_id)
        if (
            self._environment not in {"local", "test"}
            or actor is None
            or not actor.is_active
            or actor.role != UserRole.OWNER
        ):
            raise AppError(
                "codex_actor_forbidden", "Codex administration requires a development owner.", 403
            )
        allowed = await SqlAlchemyRagConfigurationRepository(session).authorized_workspace_ids(
            actor_id, (workspace_id,)
        )
        if allowed != (workspace_id,):
            raise AppError("not_found", "The requested resource was not found.", 404)

    async def list_evidence(
        self, *, actor_id: UUID, workspace_id: UUID
    ) -> tuple[CodexEvidenceMetadata, ...]:
        try:
            async with self._sessions() as session, session.begin():
                # Establish one snapshot before authorization or metadata SQL so a
                # concurrent transition cannot split current state from its history.
                await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                await self._authorize(session, actor_id, workspace_id)
                rows = (
                    await session.execute(
                        select(
                            AssetVersionRecord.id,
                            AssetVersionRecord.document_id,
                            DocumentRecord.name,
                            AssetVersionRecord.number,
                            AssetVersionRecord.sha256,
                            EvidenceApprovalStateRecord.classification,
                            EvidenceApprovalStateRecord.content_sha256,
                            EvidenceApprovalStateRecord.approved_at,
                            EvidenceApprovalStateRecord.revoked_at,
                            EvidenceApprovalStateRecord.generation,
                        )
                        .join(DocumentRecord, AssetVersionRecord.document_id == DocumentRecord.id)
                        .outerjoin(
                            EvidenceApprovalStateRecord,
                            and_(
                                EvidenceApprovalStateRecord.revision_id == AssetVersionRecord.id,
                                EvidenceApprovalStateRecord.provider
                                == ProviderKind.DEVELOPMENT_CODEX_EXEC.value,
                            ),
                        )
                        .where(DocumentRecord.workspace_id == workspace_id)
                        .order_by(
                            DocumentRecord.name,
                            AssetVersionRecord.number.desc(),
                            AssetVersionRecord.id,
                        )
                        .limit(1001)
                    )
                ).all()
                if len(rows) > 1000:
                    raise AppError(
                        "codex_evidence_limit", "Narrow the workspace evidence scope.", 422
                    )
                history: dict[UUID, list[EvidenceApprovalHistory]] = {}
                if rows:
                    events = await session.scalars(
                        select(EvidenceApprovalEventRecord)
                        .where(
                            EvidenceApprovalEventRecord.revision_id.in_([row.id for row in rows]),
                            EvidenceApprovalEventRecord.provider
                            == ProviderKind.DEVELOPMENT_CODEX_EXEC.value,
                        )
                        .order_by(EvidenceApprovalEventRecord.generation)
                    )
                    for event in events:
                        history.setdefault(event.revision_id, []).append(
                            EvidenceApprovalHistory(
                                event.action,
                                event.generation,
                                event.actor_id,
                                event.occurred_at,
                                event.classification,
                            )
                        )
                return tuple(
                    CodexEvidenceMetadata(
                        row.id,
                        row.document_id,
                        workspace_id,
                        row.name,
                        row.number,
                        row.sha256,
                        row.classification
                        if row.revoked_at is None and row.content_sha256 == row.sha256
                        else None,
                        row.approved_at,
                        row.revoked_at is not None,
                        row.generation or 0,
                        ProviderKind.DEVELOPMENT_CODEX_EXEC.value,
                        tuple(history.get(row.id, ())),
                    )
                    for row in rows
                )
        except AppError:
            raise
        except Exception:
            pass
        raise AppError("codex_evidence_unavailable", "Codex evidence metadata is unavailable.", 503)

    async def approve(
        self,
        *,
        actor_id: UUID,
        revision_id: UUID,
        content_sha256: str,
        classification: EvidenceClassification,
        expected_generation: int,
        request_id: UUID,
    ) -> None:
        try:
            await self._authorize_revision(actor_id, revision_id)
            await self._source.approve_evidence(
                actor_id=actor_id,
                revision_id=revision_id,
                content_sha256=content_sha256,
                classification=classification,
                expected_generation=expected_generation,
                request_id=request_id,
            )
            return
        except AppError:
            raise
        except CodexAuthorizationError as error:
            if error.code is CodexAuthorizationErrorCode.EVIDENCE_APPROVAL_CONFLICT:
                raise AppError(
                    "codex_evidence_approval_conflict", "Refresh the current approval state.", 409
                ) from None
        raise AppError(
            "codex_evidence_approval_denied", "The revision approval could not be saved.", 409
        )

    async def revoke(
        self,
        *,
        actor_id: UUID,
        revision_id: UUID,
        expected_generation: int,
        request_id: UUID,
    ) -> None:
        try:
            await self._authorize_revision(actor_id, revision_id)
            await self._source.revoke_evidence(
                actor_id=actor_id,
                revision_id=revision_id,
                expected_generation=expected_generation,
                request_id=request_id,
            )
            return
        except AppError:
            raise
        except CodexAuthorizationError as error:
            if error.code is CodexAuthorizationErrorCode.EVIDENCE_APPROVAL_CONFLICT:
                raise AppError(
                    "codex_evidence_approval_conflict", "Refresh the current approval state.", 409
                ) from None
        raise AppError(
            "codex_evidence_approval_denied", "The revision approval could not be revoked.", 409
        )

    async def _authorize_revision(self, actor_id: UUID, revision_id: UUID) -> None:
        try:
            async with self._sessions() as session, session.begin():
                workspace_id = await session.scalar(
                    select(DocumentRecord.workspace_id)
                    .join(AssetVersionRecord, AssetVersionRecord.document_id == DocumentRecord.id)
                    .where(AssetVersionRecord.id == revision_id)
                )
                if workspace_id is None:
                    raise AppError("not_found", "The requested resource was not found.", 404)
                await self._authorize(session, actor_id, workspace_id)
                return
        except AppError:
            raise
        except Exception:
            pass
        raise AppError("codex_evidence_unavailable", "Codex evidence metadata is unavailable.", 503)


@dataclass(frozen=True, slots=True)
class CodexRequestRuntimeFactory:
    executor: CodexRequestExecutor
    readiness: CodexPassiveReadiness

    def create(
        self, *, context: CodexRequestContext, profile: GenerationProfile
    ) -> CodexExecRuntime:
        return CodexExecRuntime(context, profile, self.executor, self.readiness)


@dataclass(frozen=True, slots=True)
class CodexServices:
    verification: CodexVerificationService
    evidence: CodexEvidenceAdministration
    runtime_factory: CodexRequestRuntimeFactory


@asynccontextmanager
async def codex_services(settings: Settings) -> AsyncIterator[CodexServices]:
    # Middleware normalizes this public ID. Never use it as execution authority.
    raw_correlation = correlation_id_context.get()
    try:
        correlation_id = UUID(raw_correlation)
    except (ValueError, TypeError, AttributeError):
        correlation_id = None
    registry = codex_registry(settings)
    engines = []
    try:
        # Separate pools keep durable consumption/slot/audit commits outside snapshot locks.
        for _ in range(4):
            engines.append(create_engine(settings))
        snapshot, consumption, slots, audit = engines
        sessions = create_session_factory(snapshot)
        environment = (
            DeploymentEnvironment.DEVELOPMENT
            if settings.environment in {"local", "test"}
            else DeploymentEnvironment.PRODUCTION
        )
        source = SqlAlchemyCodexAuthorizationSource(
            sessions,
            consumption_engine=consumption,
            environment=environment,
            clock=lambda: datetime.now(UTC),
            registry=registry,
        )
        proofs = SqlAlchemyCodexVerificationRepository(audit)
        executor = CodexRequestExecutor(
            registry=registry,
            source=source,
            slots=SqlAlchemyCodexExecutionSlots(slots),
            workspace=CodexWorkspaceExecutor(registry=registry, stream_runner=CodexStreamRunner()),
            clock=lambda: datetime.now(UTC),
            audit=proofs,
            correlation_id=correlation_id,
        )
        verification = CodexVerificationService(
            lookup=SqlAlchemyCodexVerificationLookup(sessions, environment=settings.environment),
            proofs=proofs,
            registry=registry,
            executor=executor,
            environment=settings.environment,
        )
        yield CodexServices(
            verification,
            CodexEvidenceAdministration(sessions, source=source, environment=settings.environment),
            CodexRequestRuntimeFactory(executor, verification),
        )
    finally:
        for engine in reversed(engines):
            await engine.dispose()
