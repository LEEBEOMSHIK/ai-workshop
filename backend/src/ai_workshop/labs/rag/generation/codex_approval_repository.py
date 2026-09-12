"""Internal PostgreSQL authorization adapter; no runtime or API activation.

Snapshot and consumption use distinct engine pools. The snapshot owns policy,
actor, scope and revision locks through the callback, while a parent-free ledger
insert commits independently even when that callback fails or is cancelled.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import wraps
from hashlib import sha256
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ai_workshop.labs.rag.configurations.repository import SqlAlchemyRagConfigurationRepository
from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment, ProviderKind
from ai_workshop.labs.rag.generation.codex_approval_codec import (
    canonical_intent,
    decode_intent,
    encode_intent,
    valid_sha256,
)
from ai_workshop.labs.rag.generation.codex_approval_models import (
    CodexCallApprovalRecord,
    CodexCallConsumptionRecord,
    EvidenceApprovalStateRecord,
)
from ai_workshop.labs.rag.generation.codex_authorization import (
    CodexAuthorizationError,
    CodexCallIntent,
    CodexCallOperation,
    CodexCallStage,
    CodexCurrentAuthorization,
    CodexExecutionPayload,
    EvidenceApproval,
    EvidenceClassification,
    EvidenceRevision,
    WorkspacePolicyBinding,
)
from ai_workshop.labs.rag.generation.codex_authorization import (
    CodexAuthorizationErrorCode as Code,
)
from ai_workshop.labs.rag.generation.codex_prompt import build_codex_prompt
from ai_workshop.labs.rag.generation.codex_request import CodexRequestContext
from ai_workshop.labs.rag.generation.codex_runner_registry import CodexRunnerRegistry
from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    GenerationRequest,
    generation_disclosure,
)
from ai_workshop.labs.rag.generation.profile import resolve_generation_profile
from ai_workshop.labs.rag.policies.domain import (
    PolicyDecision,
    exact_external_approval_is_current,
    resolve_external_transfer_policy,
)
from ai_workshop.labs.rag.policies.repository import SqlAlchemyDataPolicyRepository
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.domain import WorkspaceKind
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from ai_workshop.platform.workspaces.permissions import workspace_read_allowed

from .evidence_approval_lifecycle import mutate_evidence_approval


def _deny(code: Code) -> NoReturn:
    raise CodexAuthorizationError(code)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _safe_mutation_errors[**P, T](
    operation: Callable[P, Awaitable[T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    """Sanitize after contextlib exits (it can restore the thrown SQL error context)."""

    @wraps(operation)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        error_code: Code | None = None
        result: T | None = None
        try:
            result = await operation(*args, **kwargs)
        except CodexAuthorizationError as error:
            error_code = error.code
        except Exception:
            error_code = Code.SOURCE_UNAVAILABLE
        if error_code is not None:
            raise CodexAuthorizationError(error_code)
        return cast(T, result)

    return wrapped


@dataclass(slots=True)
class _ReservationContext:
    intent: CodexCallIntent
    task: asyncio.Task[object] | None
    active: bool = True


class SqlAlchemyCodexAuthorizationSource:
    """Trusted internal issue/revoke operations and the existing gate source port.

    ``environment`` must come from server settings, never request parameters.
    Factories are fixed at construction and must bind distinct pools for the same
    database. Each context opens a new session, so no stale identity map is reused.
    """

    def __init__(
        self,
        snapshot_sessions: async_sessionmaker[AsyncSession],
        *,
        consumption_engine: AsyncEngine,
        environment: DeploymentEnvironment,
        clock: Callable[[], datetime] = _utc_now,
        lock_timeout_ms: int = 5000,
        registry: CodexRunnerRegistry | None = None,
    ) -> None:
        snapshot_engine = snapshot_sessions.kw.get("bind")
        if (
            not isinstance(snapshot_engine, AsyncEngine)
            or snapshot_engine is consumption_engine
            or snapshot_engine.pool is consumption_engine.pool
            or snapshot_engine.url != consumption_engine.url
        ):
            raise ValueError("codex_approval_requires_distinct_pools_same_database")
        if type(lock_timeout_ms) is not int or not 1 <= lock_timeout_ms <= 60000:
            raise ValueError("codex_approval_invalid_lock_timeout")
        if not isinstance(environment, DeploymentEnvironment):
            raise ValueError("codex_approval_invalid_environment")
        self._sessions = snapshot_sessions
        self._consumption_sessions = async_sessionmaker(consumption_engine, expire_on_commit=False)
        self._environment = environment
        self._clock = clock
        self._lock_timeout_ms = lock_timeout_ms
        self._registry = registry
        self._active: ContextVar[_ReservationContext | None] = ContextVar(
            "codex_approval_context", default=None
        )

    async def _timeout(self, session: AsyncSession) -> None:
        await session.execute(
            text("SELECT set_config('lock_timeout', :timeout, true)"),
            {"timeout": f"{self._lock_timeout_ms}ms"},
        )

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        error_code: Code | None = None
        try:
            async with self._sessions() as session, session.begin():
                # A caller may supply RR or AUTOCOMMIT engines. Override before
                # any SQL so policy reads are current and row locks survive statements.
                await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
                await self._timeout(session)
                yield session
        except CodexAuthorizationError as error:
            error_code = error.code
        except Exception:
            error_code = Code.SOURCE_UNAVAILABLE
        # Map to a safe code here; public mutations and the gate sanitize again
        # after contextlib exits, since __aexit__ can restore the original context.
        if error_code is not None:
            raise CodexAuthorizationError(error_code)

    @asynccontextmanager
    async def locked_snapshot(
        self, intent: CodexCallIntent
    ) -> AsyncIterator[CodexCurrentAuthorization | None]:
        async with self._transaction() as session:
            record = await session.get(CodexCallApprovalRecord, intent.approval_id)
            if record is None:
                yield None
                return
            stored = _read_binding(record)
            if stored != intent:
                _deny(Code.INTENT_MISMATCH)
            snapshot = await self._current(session, stored, record=record, lock_call=True)
            context = _ReservationContext(stored, asyncio.current_task())
            token = self._active.set(context)
            try:
                yield snapshot
            finally:
                context.active = False
                self._active.reset(token)

    async def consume(self, approval_id: UUID, request_id: UUID, stage: CodexCallStage) -> bool:
        context = self._active.get()
        if (
            context is None
            or not context.active
            or context.task is not asyncio.current_task()
            or (approval_id, request_id, stage)
            != (context.intent.approval_id, context.intent.request_id, context.intent.stage)
        ):
            _deny(Code.INVALID_INTENT)
        try:
            async with self._consumption_sessions() as session, session.begin():
                await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
                await self._timeout(session)
                result = await session.scalar(
                    insert(CodexCallConsumptionRecord)
                    .values(
                        approval_id=approval_id,
                        request_id=request_id,
                        stage=stage.value,
                        consumed_at=self._clock(),
                    )
                    .on_conflict_do_nothing(index_elements=["approval_id"])
                    .returning(CodexCallConsumptionRecord.approval_id)
                )
            return result is not None
        except Exception:
            pass
        raise CodexAuthorizationError(Code.SOURCE_UNAVAILABLE)

    @_safe_mutation_errors
    async def issue_request(
        self,
        context: CodexRequestContext,
        *,
        stage: CodexCallStage,
        payload: CodexExecutionPayload,
        evidence_revision_ids: tuple[UUID, ...],
        ttl: timedelta,
    ) -> CodexCallIntent:
        """Issue body-free consent binding from current trusted state, never caller hashes."""
        if (
            type(context) is not CodexRequestContext
            or type(stage) is not CodexCallStage
            or type(payload) is not CodexExecutionPayload
            or type(evidence_revision_ids) is not tuple
            or len(evidence_revision_ids) > 1024
            or any(type(value) is not UUID for value in evidence_revision_ids)
            or len(set(evidence_revision_ids)) != len(evidence_revision_ids)
            or type(ttl) is not timedelta
            or not timedelta(0) < ttl <= timedelta(hours=1)
            or any(
                type(part) is not bytes or len(part) > 4 * 1024 * 1024
                for part in (payload.stdin, payload.developer_instructions, payload.output_schema)
            )
        ):
            _deny(Code.INVALID_INTENT)
        try:
            context = replace(context)  # Revalidate even forged/frozen DTOs at the boundary.
        except ValueError:
            _deny(Code.INVALID_INTENT)
        async with self._transaction() as session:
            current, _, _, _ = await self._derive(
                session,
                context,
                stage=stage,
                approval_id=uuid4(),
                revisions=evidence_revision_ids,
            )
            if (
                sha256(payload.developer_instructions).hexdigest()
                != current.developer_instructions_sha256
                or sha256(payload.output_schema).hexdigest() != current.output_schema_sha256
            ):
                _deny(Code.PAYLOAD_MISMATCH)
        # Independent rederivation in issue_call closes the gap between transactions.
        return await self.issue_call(
            current,
            approved_payload_sha256=payload.digest(),
            input_classification=context.input_classification,
            consented=context.consented,
            ttl=ttl,
        )

    @_safe_mutation_errors
    async def issue_call(
        self,
        intent: CodexCallIntent,
        *,
        approved_payload_sha256: str,
        input_classification: EvidenceClassification,
        consented: bool,
        ttl: timedelta,
    ) -> CodexCallIntent:
        """Register an exact server-built intent and explicit whole-input attestation."""
        if (
            not valid_sha256(approved_payload_sha256)
            or input_classification
            not in (EvidenceClassification.PUBLIC, EvidenceClassification.SYNTHETIC)
            or not isinstance(input_classification, EvidenceClassification)
            or type(consented) is not bool
            or not consented
            or not isinstance(ttl, timedelta)
            or not timedelta(0) < ttl <= timedelta(hours=1)
        ):
            _deny(Code.INVALID_INTENT)
        try:
            bound = canonical_intent(intent)
        except ValueError:
            _deny(Code.INVALID_INTENT)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            _deny(Code.APPROVAL_EXPIRED)
        record = CodexCallApprovalRecord(
            id=bound.approval_id,
            actor_id=bound.actor_id,
            approved_by=bound.actor_id,
            request_id=bound.request_id,
            operation=bound.operation.value,
            stage=bound.stage.value,
            configuration_version_id=bound.configuration_version_id,
            deployment_version_id=bound.deployment_version_id,
            generation_profile_id=bound.generation_profile_id,
            binding=encode_intent(bound),
            approved_payload_sha256=approved_payload_sha256,
            input_classification=input_classification.value,
            consented=consented,
            issued_at=now,
            expires_at=now + ttl,
            revoked_at=None,
        )
        async with self._transaction() as session:
            snapshot = await self._current(session, bound, record=record, lock_call=False)
            if snapshot.current_intent != bound:
                _deny(Code.INTENT_MISMATCH)
            if not snapshot.policy.allowed:
                _deny(Code.POLICY_DENIED)
            session.add(record)
            await session.flush()
        return bound

    @_safe_mutation_errors
    async def approve_evidence(
        self,
        *,
        actor_id: UUID,
        revision_id: UUID,
        content_sha256: str,
        classification: EvidenceClassification,
        expected_generation: int,
        request_id: UUID,
    ) -> None:
        """Explicit owner classification, generation CAS and immutable request receipt."""
        if (
            not valid_sha256(content_sha256)
            or not isinstance(classification, EvidenceClassification)
            or classification
            not in (EvidenceClassification.PUBLIC, EvidenceClassification.SYNTHETIC)
        ):
            _deny(Code.EVIDENCE_NOT_APPROVED)
        async with self._transaction() as session:
            await SqlAlchemyDataPolicyRepository(session).lock_external_execution_policy()
            await self._owner(session, actor_id)
            # Read only IDs before acquiring locks in the global space→asset→document order.
            workspace_id = await session.scalar(
                select(DocumentRecord.workspace_id)
                .join(AssetVersionRecord, AssetVersionRecord.document_id == DocumentRecord.id)
                .where(AssetVersionRecord.id == revision_id)
            )
            if workspace_id is None:
                _deny(Code.EVIDENCE_NOT_APPROVED)
            await self._workspaces(session, actor_id, (workspace_id,))
            await self._revisions(
                session,
                (EvidenceRevision(revision_id, content_sha256, expected_generation),),
                (workspace_id,),
                require_active=False,
                require_approval=False,
                mutation=True,
            )
            await mutate_evidence_approval(
                session,
                actor_id=actor_id,
                revision_id=revision_id,
                provider=ProviderKind.DEVELOPMENT_CODEX_EXEC.value,
                action="approve",
                content_sha256=content_sha256,
                classification=classification.value,
                expected_generation=expected_generation,
                request_id=request_id,
                occurred_at=self._clock(),
            )

    @_safe_mutation_errors
    async def revoke_call(self, *, actor_id: UUID, approval_id: UUID) -> None:
        async with self._transaction() as session:
            await SqlAlchemyDataPolicyRepository(session).lock_external_execution_policy()
            await self._owner(session, actor_id)
            record = await session.scalar(
                select(CodexCallApprovalRecord)
                .where(CodexCallApprovalRecord.id == approval_id)
                .with_for_update()
            )
            if record is None:
                _deny(Code.INVALID_INTENT)
            if record.revoked_at is None:
                record.revoked_at = self._clock()

    @_safe_mutation_errors
    async def revoke_evidence(
        self,
        *,
        actor_id: UUID,
        revision_id: UUID,
        expected_generation: int,
        request_id: UUID,
    ) -> None:
        async with self._transaction() as session:
            await SqlAlchemyDataPolicyRepository(session).lock_external_execution_policy()
            await self._owner(session, actor_id)
            workspace_id = await session.scalar(
                select(DocumentRecord.workspace_id)
                .join(AssetVersionRecord, AssetVersionRecord.document_id == DocumentRecord.id)
                .where(AssetVersionRecord.id == revision_id)
            )
            if workspace_id is None:
                _deny(Code.EVIDENCE_NOT_APPROVED)
            await self._workspaces(session, actor_id, (workspace_id,))
            await self._revisions(
                session,
                (revision_id,),
                (workspace_id,),
                require_active=False,
                require_approval=False,
                mutation=True,
                require_ready=False,
            )
            await mutate_evidence_approval(
                session,
                actor_id=actor_id,
                revision_id=revision_id,
                provider=ProviderKind.DEVELOPMENT_CODEX_EXEC.value,
                action="revoke",
                content_sha256=None,
                classification=None,
                expected_generation=expected_generation,
                request_id=request_id,
                occurred_at=self._clock(),
            )

    async def _owner(self, session: AsyncSession, actor_id: UUID) -> None:
        actor = (
            await session.execute(
                select(UserRecord.id, UserRecord.role, UserRecord.is_active)
                .where(UserRecord.id == actor_id)
                .with_for_update(read=True)
            )
        ).one_or_none()
        if actor is None or actor.role != UserRole.OWNER or not actor.is_active:
            _deny(Code.ACTOR_NOT_AUTHORIZED)

    async def _workspaces(
        self,
        session: AsyncSession,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        *,
        selected_ids: tuple[UUID, ...] | None = None,
    ) -> dict[UUID, datetime]:
        expiries: dict[UUID, datetime] = {}
        for workspace_id in sorted(workspace_ids):
            workspace = await session.scalar(
                select(WorkspaceRecord)
                .where(WorkspaceRecord.id == workspace_id)
                .with_for_update(read=True)
            )
            if workspace is None:
                _deny(Code.SCOPE_MISMATCH)
            if selected_ids is not None and workspace_id not in selected_ids:
                continue
            allowed = await session.scalar(
                select(WorkspaceRecord.id).where(
                    WorkspaceRecord.id == workspace_id, workspace_read_allowed(actor_id)
                )
            )
            if allowed is None:
                _deny(Code.SCOPE_MISMATCH)
            membership = await session.scalar(
                select(WorkspaceMembershipRecord.id)
                .where(
                    WorkspaceMembershipRecord.workspace_id == workspace_id,
                    WorkspaceMembershipRecord.user_id == actor_id,
                )
                .with_for_update(read=True)
            )
            if (
                workspace is None
                or membership is None
                or (workspace.kind == WorkspaceKind.PERSONAL and workspace.created_by != actor_id)
                or (
                    workspace.kind == WorkspaceKind.TEMPORARY
                    and (workspace.expires_at is None or workspace.expires_at <= self._clock())
                )
            ):
                _deny(Code.SCOPE_MISMATCH)
            if workspace.kind == WorkspaceKind.TEMPORARY and workspace.expires_at is not None:
                expiries[workspace_id] = workspace.expires_at
        return expiries

    async def _current(
        self,
        session: AsyncSession,
        stored: CodexCallIntent,
        *,
        record: CodexCallApprovalRecord,
        lock_call: bool,
    ) -> CodexCurrentAuthorization:
        context = CodexRequestContext(
            actor_id=stored.actor_id,
            request_id=stored.request_id,
            operation=stored.operation,
            configuration_version_id=stored.configuration_version_id,
            workspace_ids=stored.workspace_ids,
            input_classification=EvidenceClassification(record.input_classification),
            consented=True,
            disclosure_version=stored.generation_disclosure_version,
        )
        current, policy, evidence, expiries = await self._derive(
            session,
            context,
            stage=stored.stage,
            approval_id=stored.approval_id,
            revisions=stored.evidence_revisions,
            locked_intent=stored if lock_call else None,
        )
        if current != stored:
            _deny(Code.INTENT_MISMATCH)
        return CodexCurrentAuthorization(
            actor_id=stored.actor_id,
            actor_role=UserRole.OWNER,
            actor_active=True,
            environment=self._environment,
            current_intent=current,
            approved_by=record.approved_by,
            issued_at=record.issued_at,
            expires_at=min([record.expires_at] + list(expiries.values())),
            revoked=record.revoked_at is not None,
            consented=record.consented,
            policy=policy,
            allowed_workspace_ids=stored.workspace_ids,
            evidence_approvals=evidence,
            approved_payload_sha256=record.approved_payload_sha256,
        )

    async def _derive(
        self,
        session: AsyncSession,
        context: CodexRequestContext,
        *,
        stage: CodexCallStage,
        approval_id: UUID,
        revisions: tuple[EvidenceRevision, ...] | tuple[UUID, ...],
        locked_intent: CodexCallIntent | None = None,
    ) -> tuple[CodexCallIntent, PolicyDecision, tuple[EvidenceApproval, ...], dict[UUID, datetime]]:
        policies = SqlAlchemyDataPolicyRepository(session)
        await policies.lock_external_execution_policy()
        await self._owner(session, context.actor_id)
        if self._environment is not DeploymentEnvironment.DEVELOPMENT:
            _deny(Code.ENVIRONMENT_NOT_ALLOWED)
        configurations = SqlAlchemyRagConfigurationRepository(session)
        configuration = await configurations.find_version_visible(
            context.configuration_version_id, context.actor_id
        )
        if configuration is None or configuration.generation_profile_id is None:
            _deny(Code.INTENT_MISMATCH)
        # Exact external approvals cover every configured space, even a selected subset.
        configured_ids = tuple(sorted(configuration.workspace_ids))
        if not set(context.workspace_ids).issubset(configured_ids):
            _deny(Code.SCOPE_MISMATCH)
        expiries = await self._workspaces(
            session, context.actor_id, configured_ids, selected_ids=context.workspace_ids
        )
        if locked_intent is not None:
            locked = await session.scalar(
                select(CodexCallApprovalRecord)
                .where(CodexCallApprovalRecord.id == approval_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if locked is None or _read_binding(locked) != locked_intent:
                _deny(Code.INTENT_MISMATCH)
        generation = await configurations.find_profile(configuration.generation_profile_id)
        if generation is None or generation.deployment_version_id is None:
            _deny(Code.INTENT_MISMATCH)
        deployment = await configurations.get_deployment_version(generation.deployment_version_id)
        if deployment is None or deployment.provider is not ProviderKind.DEVELOPMENT_CODEX_EXEC:
            _deny(Code.INTENT_MISMATCH)
        if (
            not deployment.development_only
            or self._environment not in deployment.allowed_environments
            or deployment.runner_ref is None
        ):
            _deny(Code.ENVIRONMENT_NOT_ALLOWED)
        if self._registry is None:
            _deny(Code.SOURCE_UNAVAILABLE)
        runner = self._registry.resolve(deployment.runner_ref)
        if not valid_sha256(runner.configuration_sha256):
            _deny(Code.SOURCE_UNAVAILABLE)
        model = await configurations.get_model_definition(deployment.model_definition_id)
        if model is None:
            _deny(Code.INTENT_MISMATCH)
        profile = resolve_generation_profile(generation, deployment, model)
        request: ContextualizationRequest | GenerationRequest
        if stage is CodexCallStage.CONTEXTUALIZE:
            request = ContextualizationRequest(question="", history=(), profile=profile)
        else:
            request = GenerationRequest(
                question="",
                resolved_query="",
                history=(),
                evidence=(),
                profile=profile,
                correlation_id="",
            )
        envelope = build_codex_prompt(request)
        disclosure = generation_disclosure(deployment)
        if disclosure.version != context.disclosure_version:
            _deny(Code.INTENT_MISMATCH)
        installation = await policies.latest_installation_policy()
        workspace_policies = await policies.latest_workspace_policies(configured_ids)
        if {item.workspace_id for item in workspace_policies} != set(configured_ids):
            _deny(Code.POLICY_DENIED)
        policy = resolve_external_transfer_policy(
            provider=deployment.provider, installation=installation, workspaces=workspace_policies
        )
        approval = await policies.get_external_approval_for_configuration(configuration.version_id)
        if (
            not policy.allowed
            or approval is None
            or not exact_external_approval_is_current(
                approval_configuration_version_id=approval.configuration_version_id,
                approval_deployment_version_id=approval.deployment_version_id,
                approval_installation_policy_version_id=approval.installation_policy_version_id,
                approval_disclosure_version=approval.disclosure_version,
                approval_workspace_policy_snapshots=tuple(
                    (item.workspace_id, item.policy_version_id)
                    for item in approval.workspace_policies
                ),
                configuration_version_id=configuration.version_id,
                deployment_version_id=deployment.id,
                workspace_ids=configured_ids,
                policy=policy,
                disclosure_version=disclosure.version,
            )
        ):
            _deny(Code.POLICY_DENIED)
        selected_policies = tuple(
            item for item in workspace_policies if item.workspace_id in context.workspace_ids
        )
        selected_policy = replace(
            policy,
            workspace_policy_version_ids=tuple(item.id for item in selected_policies),
            workspace_policy_snapshots=tuple(
                (item.workspace_id, item.id) for item in selected_policies
            ),
        )
        evidence = await self._revisions(
            session,
            revisions,
            context.workspace_ids,
            require_active=context.operation is not CodexCallOperation.EVALUATION,
            require_approval=True,
        )
        current = canonical_intent(
            CodexCallIntent(
                actor_id=context.actor_id,
                request_id=context.request_id,
                approval_id=approval_id,
                operation=context.operation,
                stage=stage,
                configuration_version_id=configuration.version_id,
                deployment_version_id=deployment.id,
                generation_profile_id=profile.profile_id,
                runner_ref=deployment.runner_ref,
                provider_model_id=deployment.provider_model_id,
                developer_instructions_sha256=sha256(
                    envelope.developer_instructions.encode()
                ).hexdigest(),
                output_schema_sha256=sha256(envelope.output_schema_json.encode()).hexdigest(),
                workspace_ids=context.workspace_ids,
                workspace_policy_bindings=tuple(
                    WorkspacePolicyBinding(item.workspace_id, item.id) for item in selected_policies
                ),
                installation_policy_version_id=installation.id,
                generation_disclosure_version=disclosure.version,
                evidence_revisions=tuple(
                    EvidenceRevision(
                        item.revision_id, item.content_sha256, item.approval_generation
                    )
                    for item in evidence
                ),
                runner_configuration_sha256=runner.configuration_sha256,
            )
        )
        return current, selected_policy, evidence, expiries

    async def _revisions(
        self,
        session: AsyncSession,
        revisions: tuple[EvidenceRevision | UUID, ...],
        workspace_ids: tuple[UUID, ...],
        *,
        require_active: bool,
        require_approval: bool,
        mutation: bool = False,
        require_ready: bool = True,
    ) -> tuple[EvidenceApproval, ...]:
        assets = []
        for revision in sorted(
            revisions, key=lambda item: item if isinstance(item, UUID) else item.revision_id
        ):
            revision_id = revision if isinstance(revision, UUID) else revision.revision_id
            asset = (
                await session.execute(
                    select(
                        AssetVersionRecord.id,
                        AssetVersionRecord.document_id,
                        AssetVersionRecord.sha256,
                        AssetVersionRecord.status,
                    )
                    .where(AssetVersionRecord.id == revision_id)
                    .with_for_update(read=not mutation)
                )
            ).one_or_none()
            if (
                asset is None
                or (require_ready and asset.status != VersionStatus.READY)
                or (
                    isinstance(revision, EvidenceRevision)
                    and asset.sha256 != revision.content_sha256
                )
            ):
                _deny(Code.EVIDENCE_NOT_APPROVED)
            assets.append(asset)
        documents = {}
        for document_id in sorted({asset.document_id for asset in assets}):
            document = (
                await session.execute(
                    select(
                        DocumentRecord.id,
                        DocumentRecord.workspace_id,
                        DocumentRecord.active_version_id,
                    )
                    .where(DocumentRecord.id == document_id)
                    .with_for_update(read=True)
                )
            ).one_or_none()
            if document is None or document.workspace_id not in workspace_ids:
                _deny(Code.EVIDENCE_NOT_APPROVED)
            documents[document_id] = document
        result = []
        for asset in assets:
            if require_active and documents[asset.document_id].active_version_id != asset.id:
                _deny(Code.EVIDENCE_NOT_APPROVED)
            if not require_approval:
                continue
            approved = await session.scalar(
                select(EvidenceApprovalStateRecord)
                .where(
                    EvidenceApprovalStateRecord.revision_id == asset.id,
                    EvidenceApprovalStateRecord.provider
                    == ProviderKind.DEVELOPMENT_CODEX_EXEC.value,
                )
                .with_for_update(read=True)
            )
            if (
                approved is None
                or approved.status != "approved"
                or approved.content_sha256 != asset.sha256
                or approved.classification not in ("public", "synthetic")
            ):
                _deny(Code.EVIDENCE_NOT_APPROVED)
            result.append(
                EvidenceApproval(
                    asset.id,
                    asset.sha256,
                    EvidenceClassification(approved.classification),
                    approved.generation,
                )
            )
        return tuple(result)


def _read_binding(record: CodexCallApprovalRecord) -> CodexCallIntent:
    try:
        bound = decode_intent(record.binding)
    except ValueError:
        _deny(Code.INVALID_INTENT)
    if (
        record.id != bound.approval_id
        or record.actor_id != bound.actor_id
        or record.approved_by != bound.actor_id
        or record.request_id != bound.request_id
        or record.configuration_version_id != bound.configuration_version_id
        or record.deployment_version_id != bound.deployment_version_id
        or record.generation_profile_id != bound.generation_profile_id
        or record.operation != bound.operation.value
        or record.stage != bound.stage.value
        or record.input_classification not in ("public", "synthetic")
        or not valid_sha256(record.approved_payload_sha256)
    ):
        _deny(Code.INTENT_MISMATCH)
    return bound
