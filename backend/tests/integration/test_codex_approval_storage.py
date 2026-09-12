"""Synthetic-only PostgreSQL proofs, always using the guarded disposable DB helper."""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ai_workshop.labs.rag.configurations.domain import (
    BM25_RETRIEVAL_PROFILE_ID,
    E5_INDEXING_PROFILE_ID,
    AnswerPolicyVersion,
    SavedRagConfiguration,
)
from ai_workshop.labs.rag.configurations.repository import SqlAlchemyRagConfigurationRepository
from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.deployments.repository import SqlAlchemyDeploymentRepository
from ai_workshop.labs.rag.generation.codex_approval_codec import canonical_intent, encode_intent
from ai_workshop.labs.rag.generation.codex_approval_models import (
    CodexCallApprovalRecord,
    CodexCallConsumptionRecord,
    CodexEvidenceApprovalRecord,
    EvidenceApprovalEventRecord,
)
from ai_workshop.labs.rag.generation.codex_approval_repository import (
    SqlAlchemyCodexAuthorizationSource,
)
from ai_workshop.labs.rag.generation.codex_authorization import (
    CodexAuthorizationError,
    CodexCallIntent,
    CodexCallOperation,
    CodexCallStage,
    CodexExecutionGate,
    CodexExecutionPayload,
    EvidenceClassification,
    EvidenceRevision,
    WorkspacePolicyBinding,
)
from ai_workshop.labs.rag.generation.codex_authorization import (
    CodexAuthorizationErrorCode as Code,
)
from ai_workshop.labs.rag.generation.codex_prompt import build_codex_prompt
from ai_workshop.labs.rag.generation.codex_request import CodexRequestContext
from ai_workshop.labs.rag.generation.codex_runner_registry import (
    CodexRunnerRegistry,
    ResolvedCodexRunner,
)
from ai_workshop.labs.rag.generation.domain import GenerationRequest, generation_disclosure
from ai_workshop.labs.rag.generation.profile import resolve_generation_profile
from ai_workshop.labs.rag.models.models import (
    ModelDefinitionRecord,
    ProfileDeploymentBindingRecord,
    ProfileRecord,
)
from ai_workshop.labs.rag.policies.domain import (
    InstallationDataPolicyVersion,
    OutboundMode,
    WorkspaceDataPolicyVersion,
    WorkspaceOutboundMode,
)
from ai_workshop.labs.rag.policies.repository import (
    ApprovedWorkspacePolicySnapshot,
    ExternalConfigurationApproval,
    SqlAlchemyDataPolicyRepository,
)
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord, WorkspaceRecord
from alembic import command
from tests.integration.labs.rag.configurations.test_search_configuration_resolver import (
    _seed_actor_workspace,
)
from tests.integration.publishing_support import (
    IsolatedPublishingDatabase,
    isolated_publishing_database,
)
from tests.unit.labs.rag.generation.test_codex_command import _runner

pytestmark = pytest.mark.integration


class SyntheticRegistry(CodexRunnerRegistry):
    """Explicit fake registry: isolates current-settings binding from real CLI files."""

    def __init__(self) -> None:
        self.fingerprint = "c" * 64

    def resolve(self, reference: str) -> ResolvedCodexRunner:
        assert reference == "codex-synthetic-runner"
        return replace(
            _runner(Path("C:/synthetic-codex-fixture")),
            reference=reference,
            configuration_sha256=self.fingerprint,
        )


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Iterator[IsolatedPublishingDatabase]:
    with isolated_publishing_database(monkeypatch) as isolated:
        command.upgrade(isolated.config, "head")
        yield isolated


@dataclass
class Fixture:
    snapshot_engine: AsyncEngine
    consume_engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    source: SqlAlchemyCodexAuthorizationSource
    intent: CodexCallIntent
    payload: CodexExecutionPayload

    async def close(self) -> None:
        await self.snapshot_engine.dispose()
        await self.consume_engine.dispose()


async def _seed(
    database_url: str,
    *,
    issue: bool = True,
    two_spaces: bool = False,
    wire: bool = False,
    approve: bool = True,
    legacy_membership: bool = False,
) -> Fixture:
    snapshot_engine = create_async_engine(database_url, pool_size=1, max_overflow=0, pool_timeout=3)
    consume_engine = create_async_engine(database_url, pool_size=1, max_overflow=0, pool_timeout=3)
    sessions = async_sessionmaker(snapshot_engine, expire_on_commit=False)
    source = SqlAlchemyCodexAuthorizationSource(
        sessions,
        consumption_engine=consume_engine,
        environment=DeploymentEnvironment.DEVELOPMENT,
        lock_timeout_ms=2000,
        registry=SyntheticRegistry(),
    )
    async with sessions() as session, session.begin():
        actor, workspace, revision = await _seed_actor_workspace(
            session,
            label="codex-synthetic",
            with_active_asset=True,
            legacy_membership=legacy_membership,
        )
        assert revision is not None
        workspace_ids = [workspace]
        if two_spaces:
            second = WorkspaceRecord(
                id=uuid4(), name="Synthetic second", kind="team", created_by=actor
            )
            session.add(second)
            await session.flush()
            session.add(
                WorkspaceMembershipRecord(workspace_id=second.id, user_id=actor, role="owner")
            )
            workspace_ids.append(second.id)
            await session.flush()
        model_id, profile_id = uuid4(), uuid4()
        session.add(
            ModelDefinitionRecord(
                id=model_id, kind="llm", name="Synthetic approval model", version=1, config={}
            )
        )
        await session.flush()
        deployment = ModelDeploymentVersion.create(
            deployment_id=uuid4(),
            version=1,
            display_name="Synthetic Codex runner",
            description="Synthetic fixture only",
            model_definition_id=model_id,
            provider=ProviderKind.DEVELOPMENT_CODEX_EXEC,
            location=ExecutionLocation.EXTERNAL,
            allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
            provider_model_id="synthetic-model",
            endpoint_ref=None,
            runner_ref="codex-synthetic-runner",
            secret_ref=None,
            capabilities=(
                DeploymentCapability.STRUCTURED_OUTPUT,
                DeploymentCapability.CONTEXTUALIZATION,
            ),
            external_transfer=True,
            transmitted_data_categories=("question", "history", "evidence"),
            data_processing_notice_ref="synthetic-notice",
            timeout_seconds=10,
            max_retries=0,
            retry_backoff_seconds=0,
            healthcheck_enabled=False,
            development_only=True,
            created_by=actor,
        )
        await SqlAlchemyDeploymentRepository(session).add_version(deployment)
        session.add(
            ProfileRecord(
                id=profile_id,
                kind="generation",
                name="Synthetic Codex profile",
                version=1,
                config={
                    "prompt_ref": "rag-codex-answer-v3" if wire else "rag-codex-answer-v2",
                    "context_prompt_ref": "rag-codex-contextualize-v1",
                    "citation_mode": "required",
                    "context_policy": {"max_history_turns": 2, "max_history_tokens": 128},
                    "generation": {
                        "timeout_seconds": 10,
                        "max_output_tokens": 128,
                        "temperature": 0,
                        "response_schema_version": 2,
                    },
                },
                evaluation_state="pending",
                is_default=False,
            )
        )
        await session.flush()
        session.add(
            ProfileDeploymentBindingRecord(
                profile_id=profile_id, deployment_version_id=deployment.id
            )
        )
        await session.flush()
        configs = SqlAlchemyRagConfigurationRepository(session)
        config_id, version = await configs.get_or_create_identity(
            actor, "Synthetic approval configuration"
        )
        configuration = SavedRagConfiguration.create(
            configuration_id=config_id,
            configuration_version_id=uuid4(),
            owner_id=actor,
            name="Synthetic approval configuration",
            version=version,
            indexing_profile_id=E5_INDEXING_PROFILE_ID,
            retrieval_profile_id=BM25_RETRIEVAL_PROFILE_ID,
            retrieval_indexing_profile_id=E5_INDEXING_PROFILE_ID,
            generation_profile_id=profile_id,
            answer_policy_version=AnswerPolicyVersion.create(
                configuration_id=config_id,
                version=version,
                mode="generative",
                min_semantic_score=0.5,
                min_keyword_coverage=0.5,
                require_complete_provenance=True,
                conflict_mode="separate_sources",
            ),
            workspace_ids=tuple(sorted(workspace_ids)),
        )
        await configs.add(configuration)
        policies = SqlAlchemyDataPolicyRepository(session)
        policy_id = await policies.installation_policy_id(for_update=True)
        installation = InstallationDataPolicyVersion.create(
            policy_id=policy_id,
            version=await policies.next_installation_version(policy_id),
            mode=OutboundMode.APPROVED_PROVIDERS,
            approved_providers=(ProviderKind.DEVELOPMENT_CODEX_EXEC,),
            changed_by=actor,
        )
        await policies.add_installation_version(installation)
        workspace_policies = []
        for workspace_id in sorted(workspace_ids):
            workspace_policy = WorkspaceDataPolicyVersion.create(
                policy_id=uuid4(),
                workspace_id=workspace_id,
                version=1,
                mode=WorkspaceOutboundMode.INHERIT,
                approved_providers=(),
                changed_by=actor,
            )
            await policies.add_workspace_version(workspace_policy)
            workspace_policies.append(workspace_policy)
        await policies.add_external_approval(
            ExternalConfigurationApproval(
                id=uuid4(),
                configuration_version_id=configuration.version_id,
                deployment_version_id=deployment.id,
                installation_policy_version_id=installation.id,
                approved_by=actor,
                disclosure_version=generation_disclosure(deployment).version,
                workspace_policies=tuple(
                    ApprovedWorkspacePolicySnapshot(item.workspace_id, item.id)
                    for item in workspace_policies
                ),
                created_at=datetime.now(UTC),
            )
        )
        profile = await configs.find_profile(profile_id)
        model = await configs.get_model_definition(model_id)
        assert profile is not None and model is not None
        resolved = resolve_generation_profile(profile, deployment, model)
        envelope = build_codex_prompt(
            GenerationRequest(
                question="synthetic question",
                resolved_query="synthetic question",
                history=(),
                evidence=(),
                profile=resolved,
                correlation_id="synthetic",
            )
        )
        payload = CodexExecutionPayload(
            envelope.stdin_json.encode(),
            envelope.developer_instructions.encode(),
            envelope.output_schema_json.encode(),
        )
        intent = canonical_intent(
            CodexCallIntent(
                actor_id=actor,
                request_id=uuid4(),
                approval_id=uuid4(),
                operation=CodexCallOperation.SEARCH,
                stage=CodexCallStage.GENERATE,
                configuration_version_id=configuration.version_id,
                deployment_version_id=deployment.id,
                generation_profile_id=profile_id,
                runner_ref="codex-synthetic-runner",
                runner_configuration_sha256="c" * 64,
                provider_model_id="synthetic-model",
                developer_instructions_sha256=sha256(payload.developer_instructions).hexdigest(),
                output_schema_sha256=sha256(payload.output_schema).hexdigest(),
                workspace_ids=tuple(workspace_ids),
                workspace_policy_bindings=tuple(
                    WorkspacePolicyBinding(item.workspace_id, item.id)
                    for item in workspace_policies
                ),
                installation_policy_version_id=installation.id,
                generation_disclosure_version=generation_disclosure(deployment).version,
                evidence_revisions=(EvidenceRevision(revision, "a" * 64, 1),),
            )
        )
    fixture = Fixture(snapshot_engine, consume_engine, sessions, source, intent, payload)
    if approve:
        await source.approve_evidence(
            actor_id=actor,
            revision_id=revision,
            content_sha256="a" * 64,
            classification=EvidenceClassification.SYNTHETIC,
            expected_generation=0,
            request_id=uuid4(),
        )
    if issue:
        await _issue(fixture)
    return fixture


async def test_reapproval_keeps_revision_history_and_never_revives_old_call(database):
    from ai_workshop.labs.rag.generation.codex_approval_models import (
        EvidenceApprovalEventRecord,
        EvidenceApprovalStateRecord,
    )

    fixture = await _seed(database.database_url)
    actor_id = fixture.intent.actor_id
    revision_id = fixture.intent.evidence_revisions[0].revision_id
    revoke_request, approve_request = uuid4(), uuid4()
    try:
        await fixture.source.revoke_evidence(
            actor_id=actor_id,
            revision_id=revision_id,
            expected_generation=1,
            request_id=revoke_request,
        )
        async with fixture.sessions() as session:
            initial_request = await session.scalar(
                select(EvidenceApprovalEventRecord.request_id).where(
                    EvidenceApprovalEventRecord.revision_id == revision_id,
                    EvidenceApprovalEventRecord.generation == 1,
                )
            )
        # The original approval's late replay must not undo the later revocation.
        await fixture.source.approve_evidence(
            actor_id=actor_id,
            revision_id=revision_id,
            content_sha256="a" * 64,
            classification=EvidenceClassification.SYNTHETIC,
            expected_generation=0,
            request_id=initial_request,
        )
        async with fixture.sessions() as session:
            state = await session.scalar(select(EvidenceApprovalStateRecord))
            assert state.generation == 2 and state.status == "revoked"
        await fixture.source.approve_evidence(
            actor_id=actor_id,
            revision_id=revision_id,
            content_sha256="a" * 64,
            classification=EvidenceClassification.PUBLIC,
            expected_generation=2,
            request_id=approve_request,
        )
        # Exact late replay returns success without reapplying the historical revoke.
        await fixture.source.revoke_evidence(
            actor_id=actor_id,
            revision_id=revision_id,
            expected_generation=1,
            request_id=revoke_request,
        )
        with pytest.raises(CodexAuthorizationError):
            await _gate(fixture.source).run(fixture.intent, fixture.payload, _ok)
        for expected, request_id, classification in (
            (1, uuid4(), EvidenceClassification.PUBLIC),
            (2, approve_request, EvidenceClassification.SYNTHETIC),
        ):
            with pytest.raises(CodexAuthorizationError) as error:
                await fixture.source.approve_evidence(
                    actor_id=actor_id,
                    revision_id=revision_id,
                    content_sha256="a" * 64,
                    classification=classification,
                    expected_generation=expected,
                    request_id=request_id,
                )
            assert error.value.code is Code.EVIDENCE_APPROVAL_CONFLICT
        async with fixture.sessions() as session:
            state = await session.scalar(select(EvidenceApprovalStateRecord))
            assert state.generation == 3 and state.status == "approved"
            events = (
                await session.scalars(
                    select(EvidenceApprovalEventRecord).order_by(
                        EvidenceApprovalEventRecord.generation
                    )
                )
            ).all()
            assert [(item.action, item.generation) for item in events] == [
                ("approve", 1),
                ("revoke", 2),
                ("approve", 3),
            ]
            asset = await session.get(AssetVersionRecord, revision_id)
            assert asset.sha256 == "a" * 64
            assert await session.scalar(select(func.count()).select_from(AssetVersionRecord)) == 1
    finally:
        await fixture.close()


@pytest.mark.parametrize("same_request", [False, True])
async def test_concurrent_first_approval_serializes_absent_state(database, same_request):
    from ai_workshop.labs.rag.generation.codex_approval_models import EvidenceApprovalStateRecord

    fixture = await _seed(database.database_url, issue=False, approve=False)
    second_engine = create_async_engine(database.database_url)
    second = SqlAlchemyCodexAuthorizationSource(
        async_sessionmaker(second_engine, expire_on_commit=False),
        consumption_engine=fixture.consume_engine,
        environment=DeploymentEnvironment.DEVELOPMENT,
    )
    first_id, second_id = uuid4(), uuid4()
    try:

        async def approve(source, request_id):
            await source.approve_evidence(
                actor_id=fixture.intent.actor_id,
                revision_id=fixture.intent.evidence_revisions[0].revision_id,
                content_sha256="a" * 64,
                classification=EvidenceClassification.SYNTHETIC,
                expected_generation=0,
                request_id=request_id,
            )

        outcomes = await asyncio.gather(
            approve(fixture.source, first_id),
            approve(second, first_id if same_request else second_id),
            return_exceptions=True,
        )
        assert sum(item is None for item in outcomes) == (2 if same_request else 1)
        for item in outcomes:
            if item is not None:
                assert isinstance(item, CodexAuthorizationError)
                assert item.code is Code.EVIDENCE_APPROVAL_CONFLICT
        async with fixture.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(EvidenceApprovalEventRecord))
                == 1
            )
            assert (await session.scalar(select(EvidenceApprovalStateRecord))).generation == 1
    finally:
        await second_engine.dispose()
        await fixture.close()


@pytest.mark.parametrize("action", ["approve", "revoke"])
async def test_evidence_mutations_recheck_current_document_membership(database, action):
    fixture = await _seed(database.database_url)
    try:
        async with fixture.sessions() as session, session.begin():
            await session.execute(
                delete(WorkspaceMembershipRecord).where(
                    WorkspaceMembershipRecord.user_id == fixture.intent.actor_id
                )
            )
        arguments = dict(
            actor_id=fixture.intent.actor_id,
            revision_id=fixture.intent.evidence_revisions[0].revision_id,
            expected_generation=1,
            request_id=uuid4(),
        )
        with pytest.raises(CodexAuthorizationError) as error:
            if action == "approve":
                await fixture.source.approve_evidence(
                    **arguments,
                    content_sha256="a" * 64,
                    classification=EvidenceClassification.PUBLIC,
                )
            else:
                await fixture.source.revoke_evidence(**arguments)
        assert error.value.code is Code.SCOPE_MISMATCH
        async with fixture.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(EvidenceApprovalEventRecord))
                == 1
            )
    finally:
        await fixture.close()


@pytest.mark.parametrize("revoked", [False, True])
async def test_migration_preserves_legacy_evidence_and_blocks_old_writers(monkeypatch, revoked):
    from ai_workshop.labs.rag.generation.codex_approval_models import EvidenceApprovalStateRecord

    with isolated_publishing_database(monkeypatch) as database:
        await asyncio.to_thread(command.upgrade, database.config, "0030_technology_permissions")
        fixture = await _seed(
            database.database_url, issue=False, approve=False, legacy_membership=True
        )
        intent = fixture.intent
        approved_at = datetime(2026, 9, 1, tzinfo=UTC)
        revoked_at = datetime(2026, 9, 2, tzinfo=UTC) if revoked else None
        old_binding = encode_intent(intent)
        old_binding["version"] = 2
        for evidence in old_binding["evidence_revisions"]:
            evidence.pop("approval_generation")
        try:
            async with fixture.sessions() as session, session.begin():
                session.add(
                    CodexEvidenceApprovalRecord(
                        revision_id=intent.evidence_revisions[0].revision_id,
                        content_sha256="a" * 64,
                        classification="synthetic",
                        approved_by=intent.actor_id,
                        approved_at=approved_at,
                        revoked_at=revoked_at,
                    )
                )
                session.add(
                    CodexCallApprovalRecord(
                        id=intent.approval_id,
                        actor_id=intent.actor_id,
                        approved_by=intent.actor_id,
                        request_id=intent.request_id,
                        configuration_version_id=intent.configuration_version_id,
                        deployment_version_id=intent.deployment_version_id,
                        generation_profile_id=intent.generation_profile_id,
                        operation=intent.operation.value,
                        stage=intent.stage.value,
                        binding=old_binding,
                        approved_payload_sha256=fixture.payload.digest(),
                        input_classification="synthetic",
                        issued_at=datetime.now(UTC),
                        expires_at=datetime.now(UTC) + timedelta(minutes=5),
                        consented=True,
                    )
                )
            await asyncio.to_thread(command.upgrade, database.config, "0031_evidence_reapproval")
            async with fixture.sessions() as session:
                legacy = await session.get(
                    CodexEvidenceApprovalRecord, intent.evidence_revisions[0].revision_id
                )
                assert legacy.approved_at == approved_at and legacy.revoked_at == revoked_at
                assert legacy.approved_by == intent.actor_id
                state = await session.scalar(select(EvidenceApprovalStateRecord))
                assert state.generation == (2 if revoked else 1)
                assert state.status == ("revoked" if revoked else "approved")
                history = (
                    await session.scalars(
                        select(EvidenceApprovalEventRecord).order_by(
                            EvidenceApprovalEventRecord.generation
                        )
                    )
                ).all()
                assert (
                    history[0].actor_id == intent.actor_id and history[0].occurred_at == approved_at
                )
                assert len(history) == (2 if revoked else 1)
                if revoked:
                    assert history[1].actor_id is None and history[1].occurred_at == revoked_at
                old_call = await session.get(CodexCallApprovalRecord, intent.approval_id)
                assert old_call.revoked_at is not None and old_call.binding == old_binding
            # Historical migration assertions above remain on 0031; current service
            # behavior below requires the current membership schema as well.
            await asyncio.to_thread(command.upgrade, database.config, "head")
            with pytest.raises(CodexAuthorizationError):
                await _gate(fixture.source).run(intent, fixture.payload, _ok)
            fixture.intent = replace(intent, approval_id=uuid4(), request_id=uuid4())
            if revoked:
                with pytest.raises(CodexAuthorizationError):
                    await _issue(fixture)
                await fixture.source.approve_evidence(
                    actor_id=intent.actor_id,
                    revision_id=intent.evidence_revisions[0].revision_id,
                    content_sha256="a" * 64,
                    classification=EvidenceClassification.PUBLIC,
                    expected_generation=2,
                    request_id=uuid4(),
                )
                fixture.intent = replace(
                    fixture.intent,
                    evidence_revisions=(
                        replace(intent.evidence_revisions[0], approval_generation=3),
                    ),
                )
            await _issue(fixture)
            assert (
                await _gate(fixture.source).run(fixture.intent, fixture.payload, _ok)
                == "synthetic answer"
            )
            for statement in (
                update(CodexEvidenceApprovalRecord).values(revoked_at=datetime.now(UTC)),
                delete(CodexEvidenceApprovalRecord),
                update(EvidenceApprovalEventRecord).values(classification="public"),
                delete(EvidenceApprovalEventRecord),
            ):
                async with fixture.sessions() as session, session.begin():
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.execute(statement)
            async with fixture.sessions() as session, session.begin():
                with pytest.raises(DBAPIError, match="evidence_approval_history_immutable"):
                    async with session.begin_nested():
                        session.add(
                            CodexEvidenceApprovalRecord(
                                revision_id=uuid4(),
                                content_sha256="b" * 64,
                                classification="public",
                                approved_by=intent.actor_id,
                                approved_at=approved_at,
                            )
                        )
                        await session.flush()
            async with fixture.sessions() as session, session.begin():
                with pytest.raises(DBAPIError, match="ck_codex_call_v3"):
                    async with session.begin_nested():
                        # Old applications cannot issue generation-free calls after cutover.
                        record = await session.get(
                            CodexCallApprovalRecord, fixture.intent.approval_id
                        )
                        values = {
                            column.name: getattr(record, column.name)
                            for column in record.__table__.columns
                        }
                        values.update(id=uuid4(), binding=old_binding)
                        session.add(CodexCallApprovalRecord(**values))
                        await session.flush()
            with pytest.raises(
                Exception, match="evidence_reapproval_downgrade_requires_empty_tables"
            ):
                await asyncio.to_thread(
                    command.downgrade, database.config, "0030_technology_permissions"
                )
        finally:
            await fixture.close()


async def _issue(fixture: Fixture) -> None:
    await fixture.source.issue_call(
        fixture.intent,
        approved_payload_sha256=fixture.payload.digest(),
        input_classification=EvidenceClassification.SYNTHETIC,
        consented=True,
        ttl=timedelta(minutes=5),
    )


async def _ok(payload: CodexExecutionPayload) -> str:
    return "synthetic answer"


def _request_context(fixture: Fixture) -> CodexRequestContext:
    return CodexRequestContext(
        actor_id=fixture.intent.actor_id,
        request_id=fixture.intent.request_id,
        operation=fixture.intent.operation,
        configuration_version_id=fixture.intent.configuration_version_id,
        workspace_ids=fixture.intent.workspace_ids,
        input_classification=EvidenceClassification.SYNTHETIC,
        consented=True,
        disclosure_version=fixture.intent.generation_disclosure_version,
    )


async def test_issue_request_derives_current_binding(database: IsolatedPublishingDatabase) -> None:
    fixture = await _seed(database.database_url, issue=False)
    try:
        issued = await fixture.source.issue_request(
            _request_context(fixture),
            stage=CodexCallStage.GENERATE,
            payload=fixture.payload,
            evidence_revision_ids=tuple(r.revision_id for r in fixture.intent.evidence_revisions),
            ttl=timedelta(minutes=5),
        )
        assert issued == replace(fixture.intent, approval_id=issued.approval_id)
        assert issued.approval_id != fixture.intent.approval_id
        assert await _gate(fixture.source).run(issued, fixture.payload, _ok) == "synthetic answer"
    finally:
        await fixture.close()


@pytest.mark.parametrize("field", ["developer_instructions", "output_schema"])
async def test_issue_request_rejects_untrusted_payload_envelope(
    database: IsolatedPublishingDatabase,
    field: str,
) -> None:
    fixture = await _seed(database.database_url, issue=False)
    try:
        with pytest.raises(CodexAuthorizationError) as error:
            await fixture.source.issue_request(
                _request_context(fixture),
                stage=CodexCallStage.GENERATE,
                payload=replace(fixture.payload, **{field: b"untrusted synthetic bytes"}),
                evidence_revision_ids=(),
                ttl=timedelta(minutes=5),
            )
        assert error.value.code is Code.PAYLOAD_MISMATCH
        async with fixture.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(CodexCallApprovalRecord)) == 0
            )
    finally:
        await fixture.close()


async def test_changed_registry_prevents_old_issue_and_gate(
    database: IsolatedPublishingDatabase,
) -> None:
    fixture = await _seed(database.database_url)
    registry = SyntheticRegistry()
    registry.fingerprint = "d" * 64
    fixture.source = SqlAlchemyCodexAuthorizationSource(
        fixture.sessions,
        consumption_engine=fixture.consume_engine,
        environment=DeploymentEnvironment.DEVELOPMENT,
        registry=registry,
    )
    try:
        await _assert_denied(fixture, Code.INTENT_MISMATCH)
        with pytest.raises(CodexAuthorizationError) as error:
            await _issue(fixture)
        assert error.value.code is Code.INTENT_MISMATCH
    finally:
        await fixture.close()


async def test_issue_request_rejects_mixed_unknown_revision(
    database: IsolatedPublishingDatabase,
) -> None:
    fixture = await _seed(database.database_url, issue=False)
    try:
        with pytest.raises(CodexAuthorizationError) as error:
            await fixture.source.issue_request(
                _request_context(fixture),
                stage=CodexCallStage.GENERATE,
                payload=fixture.payload,
                evidence_revision_ids=(fixture.intent.evidence_revisions[0].revision_id, uuid4()),
                ttl=timedelta(minutes=5),
            )
        assert error.value.code is Code.EVIDENCE_NOT_APPROVED
    finally:
        await fixture.close()


async def test_issue_request_revalidates_forged_consent_and_classification(
    database: IsolatedPublishingDatabase,
) -> None:
    fixture = await _seed(database.database_url, issue=False)
    try:
        for field, value in (
            ("consented", False),
            ("input_classification", EvidenceClassification.PRIVATE),
        ):
            context = _request_context(fixture)
            object.__setattr__(context, field, value)
            with pytest.raises(CodexAuthorizationError) as error:
                await fixture.source.issue_request(
                    context,
                    stage=CodexCallStage.GENERATE,
                    payload=fixture.payload,
                    evidence_revision_ids=(),
                    ttl=timedelta(minutes=5),
                )
            assert error.value.code is Code.INVALID_INTENT
            assert error.value.__context__ is None and error.value.__cause__ is None
        async with fixture.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(CodexCallApprovalRecord)) == 0
            )
    finally:
        await fixture.close()


async def test_missing_registry_fails_closed_for_issue_and_gate(
    database: IsolatedPublishingDatabase,
) -> None:
    fixture = await _seed(database.database_url)
    fixture.source = SqlAlchemyCodexAuthorizationSource(
        fixture.sessions,
        consumption_engine=fixture.consume_engine,
        environment=DeploymentEnvironment.DEVELOPMENT,
    )
    try:
        await _assert_denied(fixture, Code.SOURCE_UNAVAILABLE)
        with pytest.raises(CodexAuthorizationError) as error:
            await fixture.source.issue_request(
                _request_context(fixture),
                stage=CodexCallStage.GENERATE,
                payload=fixture.payload,
                evidence_revision_ids=(),
                ttl=timedelta(minutes=5),
            )
        assert error.value.code is Code.SOURCE_UNAVAILABLE
    finally:
        await fixture.close()


def _gate(source: SqlAlchemyCodexAuthorizationSource) -> CodexExecutionGate:
    return CodexExecutionGate(source=source, clock=lambda: datetime.now(UTC))


async def _assert_denied(fixture: Fixture, code: Code | None = None) -> None:
    called = False

    async def callback(payload: CodexExecutionPayload) -> None:
        nonlocal called
        called = True

    with pytest.raises(CodexAuthorizationError) as error:
        await _gate(fixture.source).run(fixture.intent, fixture.payload, callback)
    assert not called
    if code is not None:
        assert error.value.code is code
    async with fixture.sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(CodexCallConsumptionRecord)) == 0
        )


async def test_real_gate_success_and_restart_replay(database: IsolatedPublishingDatabase) -> None:
    fixture = await _seed(database.database_url)
    try:
        assert (
            await asyncio.wait_for(
                _gate(fixture.source).run(fixture.intent, fixture.payload, _ok), 5
            )
            == "synthetic answer"
        )
        restarted = SqlAlchemyCodexAuthorizationSource(
            fixture.sessions,
            consumption_engine=fixture.consume_engine,
            environment=DeploymentEnvironment.DEVELOPMENT,
            registry=SyntheticRegistry(),
        )
        with pytest.raises(CodexAuthorizationError) as error:
            await _gate(restarted).run(fixture.intent, fixture.payload, _ok)
        assert error.value.code is Code.APPROVAL_ALREADY_CONSUMED
        async with fixture.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(CodexCallConsumptionRecord))
                == 1
            )
    finally:
        await fixture.close()


@pytest.mark.parametrize("isolation_level", ["REPEATABLE READ", "AUTOCOMMIT"])
async def test_source_forces_real_read_committed_transactions_before_sql(
    database: IsolatedPublishingDatabase,
    isolation_level: str,
) -> None:
    # Seed with ordinary transactions; custom engine defaults apply only to execution.
    fixture = await _seed(database.database_url)
    snapshot_engine = create_async_engine(database.database_url, isolation_level=isolation_level)
    consumption_engine = create_async_engine(database.database_url, isolation_level=isolation_level)
    observed: dict[str, list[tuple[str, bool]]] = {"snapshot": [], "consume": []}

    def record_snapshot(connection: Connection, *args: object) -> None:
        observed["snapshot"].append(
            (connection.get_isolation_level(), connection.connection.driver_connection.autocommit)
        )

    def record_consumption(connection: Connection, *args: object) -> None:
        observed["consume"].append(
            (connection.get_isolation_level(), connection.connection.driver_connection.autocommit)
        )

    event.listen(snapshot_engine.sync_engine, "before_cursor_execute", record_snapshot)
    event.listen(consumption_engine.sync_engine, "before_cursor_execute", record_consumption)
    source = SqlAlchemyCodexAuthorizationSource(
        async_sessionmaker(snapshot_engine),
        consumption_engine=consumption_engine,
        environment=DeploymentEnvironment.DEVELOPMENT,
        registry=SyntheticRegistry(),
    )
    try:
        assert (
            await asyncio.wait_for(_gate(source).run(fixture.intent, fixture.payload, _ok), 5)
            == "synthetic answer"
        )
        # Check actual driver autocommit too: SHOW isolation alone cannot detect autocommit.
        assert observed["snapshot"] and observed["consume"]
        assert set(observed["snapshot"]) == {("READ COMMITTED", False)}
        assert set(observed["consume"]) == {("READ COMMITTED", False)}
    finally:
        await snapshot_engine.dispose()
        await consumption_engine.dispose()
        await fixture.close()


@pytest.mark.parametrize("failure", ["exception", "cancel"])
async def test_callback_failure_or_cancel_cannot_rollback_consumption(
    database: IsolatedPublishingDatabase, failure: str
) -> None:
    fixture = await _seed(database.database_url)

    async def callback(payload: CodexExecutionPayload) -> None:
        if failure == "cancel":
            raise asyncio.CancelledError
        raise RuntimeError("synthetic private callback body")

    try:
        with pytest.raises((CodexAuthorizationError, asyncio.CancelledError)):
            await _gate(fixture.source).run(fixture.intent, fixture.payload, callback)
        async with fixture.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(CodexCallConsumptionRecord))
                == 1
            )
        with pytest.raises(CodexAuthorizationError) as error:
            await _gate(fixture.source).run(fixture.intent, fixture.payload, _ok)
        assert error.value.code is Code.APPROVAL_ALREADY_CONSUMED
    finally:
        await fixture.close()


async def test_concurrent_sources_only_one_callback_and_revocation_waits(
    database: IsolatedPublishingDatabase,
) -> None:
    fixture = await _seed(database.database_url)
    other_engine = create_async_engine(database.database_url, pool_size=2, pool_timeout=3)
    other = SqlAlchemyCodexAuthorizationSource(
        async_sessionmaker(other_engine),
        consumption_engine=fixture.consume_engine,
        environment=DeploymentEnvironment.DEVELOPMENT,
        lock_timeout_ms=2000,
        registry=SyntheticRegistry(),
    )
    entered, release, revoking = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0

    async def callback(payload: CodexExecutionPayload) -> str:
        nonlocal calls
        calls += 1
        entered.set()
        await asyncio.wait_for(release.wait(), 3)
        return "done"

    async def revoke() -> None:
        revoking.set()
        await other.revoke_call(
            actor_id=fixture.intent.actor_id, approval_id=fixture.intent.approval_id
        )

    first = asyncio.create_task(
        _gate(fixture.source).run(fixture.intent, fixture.payload, callback)
    )
    tasks = [first]
    try:
        await asyncio.wait_for(entered.wait(), 3)
        second = asyncio.create_task(_gate(other).run(fixture.intent, fixture.payload, callback))
        revocation = asyncio.create_task(revoke())
        tasks.extend((second, revocation))
        await asyncio.wait_for(revoking.wait(), 1)
        await asyncio.sleep(0.05)
        assert not second.done() and not revocation.done()
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
        assert results[0] == "done" and results[2] is None
        assert isinstance(results[1], CodexAuthorizationError)
        assert results[1].code in (Code.APPROVAL_ALREADY_CONSUMED, Code.APPROVAL_REVOKED)
        assert calls == 1
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await other_engine.dispose()
        await fixture.close()


@pytest.mark.parametrize(
    "change",
    [
        "member",
        "inactive",
        "membership",
        "personal_owner",
        "revision_inactive",
        "revision_hash",
        "evidence_revoke",
        "call_revoke",
        "model",
        "prompt",
        "missing",
        "expiry",
        "policy",
    ],
)
async def test_current_state_changes_deny_before_consumption(
    database: IsolatedPublishingDatabase, change: str
) -> None:
    fixture = await _seed(database.database_url)
    try:
        intent = fixture.intent
        if change == "call_revoke":
            await fixture.source.revoke_call(
                actor_id=intent.actor_id, approval_id=intent.approval_id
            )
        elif change == "evidence_revoke":
            await fixture.source.revoke_evidence(
                actor_id=intent.actor_id,
                revision_id=intent.evidence_revisions[0].revision_id,
                expected_generation=1,
                request_id=uuid4(),
            )
        elif change in ("model", "prompt", "missing"):
            fixture.intent = replace(
                intent,
                **{
                    "model": {"provider_model_id": "different-model"},
                    "prompt": {"developer_instructions_sha256": "b" * 64},
                    "missing": {"approval_id": uuid4()},
                }[change],
            )
        elif change == "expiry":
            fixture.source._clock = lambda: datetime.now(UTC) + timedelta(days=1)
            expired_gate = CodexExecutionGate(source=fixture.source, clock=fixture.source._clock)
            with pytest.raises(CodexAuthorizationError) as error:
                await expired_gate.run(intent, fixture.payload, _ok)
            assert error.value.code is Code.APPROVAL_EXPIRED
            return
        else:
            async with fixture.sessions() as session, session.begin():
                if change in ("member", "inactive"):
                    await session.execute(
                        update(UserRecord)
                        .where(UserRecord.id == intent.actor_id)
                        .values(
                            **({"role": "member"} if change == "member" else {"is_active": False})
                        )
                    )
                elif change == "membership":
                    await session.execute(
                        delete(WorkspaceMembershipRecord).where(
                            WorkspaceMembershipRecord.user_id == intent.actor_id
                        )
                    )
                elif change == "personal_owner":
                    other, _, _ = await _seed_actor_workspace(
                        session, label="other", with_active_asset=False
                    )
                    await session.execute(
                        update(WorkspaceRecord)
                        .where(WorkspaceRecord.id == intent.workspace_ids[0])
                        .values(created_by=other)
                    )
                elif change == "revision_inactive":
                    await session.execute(update(DocumentRecord).values(active_version_id=None))
                elif change == "revision_hash":
                    await session.execute(
                        update(AssetVersionRecord)
                        .where(AssetVersionRecord.id == intent.evidence_revisions[0].revision_id)
                        .values(sha256="b" * 64)
                    )
                elif change == "policy":
                    policies = SqlAlchemyDataPolicyRepository(session)
                    policy_id = await policies.installation_policy_id(for_update=True)
                    await policies.add_installation_version(
                        InstallationDataPolicyVersion.create(
                            policy_id=policy_id,
                            version=await policies.next_installation_version(policy_id),
                            mode=OutboundMode.DENY,
                            approved_providers=(),
                            changed_by=intent.actor_id,
                        )
                    )
        await _assert_denied(fixture)
    finally:
        await fixture.close()


async def test_selected_subset_still_checks_configured_scope_policy_and_temporary_expiry(
    database: IsolatedPublishingDatabase,
) -> None:
    fixture = await _seed(database.database_url, issue=False, two_spaces=True)
    try:
        async with fixture.sessions() as session:
            revision = await session.get(
                AssetVersionRecord, fixture.intent.evidence_revisions[0].revision_id
            )
            assert revision is not None
            document = await session.get(DocumentRecord, revision.document_id)
            assert document is not None
            selected = document.workspace_id
        fixture.intent = replace(
            fixture.intent,
            workspace_ids=(selected,),
            workspace_policy_bindings=tuple(
                item
                for item in fixture.intent.workspace_policy_bindings
                if item.workspace_id == selected
            ),
        )
        async with fixture.sessions() as session, session.begin():
            await session.execute(
                delete(WorkspaceMembershipRecord).where(
                    WorkspaceMembershipRecord.workspace_id != selected,
                    WorkspaceMembershipRecord.user_id == fixture.intent.actor_id,
                )
            )
        expires = datetime.now(UTC) + timedelta(seconds=30)
        async with fixture.sessions() as session, session.begin():
            await session.execute(
                update(WorkspaceRecord)
                .where(WorkspaceRecord.id == selected)
                .values(kind="temporary", expires_at=expires)
            )
        await _issue(fixture)
        async with fixture.source.locked_snapshot(fixture.intent) as snapshot:
            assert snapshot is not None and snapshot.expires_at == expires
            assert snapshot.allowed_workspace_ids == (selected,)
        async with fixture.sessions() as session, session.begin():
            policies = SqlAlchemyDataPolicyRepository(session)
            await policies.installation_policy_id(for_update=True)
            other = next(
                item.workspace_id
                for item in (
                    await policies.latest_workspace_policies(
                        tuple((await session.scalars(select(WorkspaceRecord.id))).all())
                    )
                )
                if item.workspace_id != selected
            )
            policy_id = await policies.workspace_policy_id(other)
            assert policy_id is not None
            await policies.add_workspace_version(
                WorkspaceDataPolicyVersion.create(
                    policy_id=policy_id,
                    workspace_id=other,
                    version=2,
                    mode=WorkspaceOutboundMode.DENY,
                    approved_providers=(),
                    changed_by=fixture.intent.actor_id,
                )
            )
        await _assert_denied(fixture, Code.POLICY_DENIED)
    finally:
        await fixture.close()


async def test_evaluation_allows_explicit_historical_ready_revision_only(
    database: IsolatedPublishingDatabase,
) -> None:
    fixture = await _seed(database.database_url, issue=False)
    try:
        async with fixture.sessions() as session, session.begin():
            await session.execute(update(DocumentRecord).values(active_version_id=None))
        with pytest.raises(CodexAuthorizationError):
            await _issue(fixture)
        fixture.intent = replace(fixture.intent, operation=CodexCallOperation.EVALUATION)
        await _issue(fixture)
        assert (
            await _gate(fixture.source).run(fixture.intent, fixture.payload, _ok)
            == "synthetic answer"
        )
    finally:
        await fixture.close()


async def test_immutable_rows_and_terminal_revocation(database: IsolatedPublishingDatabase) -> None:
    fixture = await _seed(database.database_url)
    try:
        await _gate(fixture.source).run(fixture.intent, fixture.payload, _ok)
        await fixture.source.revoke_call(
            actor_id=fixture.intent.actor_id, approval_id=fixture.intent.approval_id
        )
        await fixture.source.revoke_evidence(
            actor_id=fixture.intent.actor_id,
            revision_id=fixture.intent.evidence_revisions[0].revision_id,
            expected_generation=1,
            request_id=uuid4(),
        )
        with pytest.raises(CodexAuthorizationError) as registration_error:
            await fixture.source.approve_evidence(
                actor_id=fixture.intent.actor_id,
                revision_id=fixture.intent.evidence_revisions[0].revision_id,
                content_sha256="a" * 64,
                classification=EvidenceClassification.PUBLIC,
                expected_generation=1,
                request_id=uuid4(),
            )
        assert registration_error.value.code is Code.EVIDENCE_APPROVAL_CONFLICT
        assert registration_error.value.__context__ is None
        assert registration_error.value.__cause__ is None
        for statement in (
            update(CodexCallApprovalRecord).values(
                binding={"question": "synthetic forbidden body"}
            ),
            update(CodexCallApprovalRecord).values(revoked_at=None),
            delete(CodexCallApprovalRecord),
            update(EvidenceApprovalEventRecord).values(classification="public"),
            delete(EvidenceApprovalEventRecord),
            update(CodexCallConsumptionRecord).values(request_id=uuid4()),
            delete(CodexCallConsumptionRecord),
        ):
            async with fixture.sessions() as session, session.begin():
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(statement)
        async with fixture.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(CodexCallConsumptionRecord))
                == 1
            )
    finally:
        await fixture.close()


@pytest.mark.parametrize(
    "malformation",
    ["unknown", "duplicate_header", "private", "stale_model", "stale_prompt", "stale_policy"],
)
async def test_untrusted_stored_binding_denied(
    database: IsolatedPublishingDatabase, malformation: str
) -> None:
    fixture = await _seed(database.database_url, issue=False)
    try:
        if malformation == "stale_model":
            fixture.intent = replace(fixture.intent, provider_model_id="stale-synthetic-model")
        elif malformation == "stale_prompt":
            fixture.intent = replace(fixture.intent, developer_instructions_sha256="b" * 64)
        elif malformation == "stale_policy":
            fixture.intent = replace(fixture.intent, installation_policy_version_id=uuid4())
        intent = fixture.intent
        binding = encode_intent(intent)
        if malformation == "unknown":
            binding["question"] = "synthetic forbidden body"
        async with fixture.sessions() as session, session.begin():
            record = CodexCallApprovalRecord(
                id=intent.approval_id,
                actor_id=intent.actor_id,
                approved_by=intent.actor_id,
                request_id=uuid4() if malformation == "duplicate_header" else intent.request_id,
                configuration_version_id=intent.configuration_version_id,
                deployment_version_id=intent.deployment_version_id,
                generation_profile_id=intent.generation_profile_id,
                operation=intent.operation.value,
                stage=intent.stage.value,
                binding=binding,
                approved_payload_sha256=fixture.payload.digest(),
                input_classification="private" if malformation == "private" else "synthetic",
                issued_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
                consented=True,
            )
            if malformation == "private":
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        session.add(record)
                        await session.flush()
                return
            session.add(record)
        await _assert_denied(fixture)
    finally:
        await fixture.close()


def test_migration_preserves_old_rows_empty_down_and_nonempty_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, "0026_codex_runner_reference")
        url = database.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url, connect_timeout=5) as connection:
            before = connection.execute("SELECT id FROM rag_profiles ORDER BY id").fetchall()
        command.upgrade(database.config, "0027_codex_call_approvals")
        command.downgrade(database.config, "0026_codex_runner_reference")
        command.upgrade(database.config, "0027_codex_call_approvals")
        with psycopg.connect(url, connect_timeout=5) as connection:
            assert (
                connection.execute("SELECT id FROM rag_profiles ORDER BY id").fetchall() == before
            )
            connection.execute(
                "INSERT INTO rag_codex_call_consumptions "
                "(approval_id, request_id, stage, consumed_at) VALUES (%s,%s,'generate',now())",
                (uuid4(), uuid4()),
            )
        with pytest.raises(Exception, match="codex_approval_downgrade_requires_empty_tables"):
            command.downgrade(database.config, "0026_codex_runner_reference")
        with psycopg.connect(url, connect_timeout=5) as connection:
            assert connection.execute(
                "SELECT count(*) FROM rag_codex_call_consumptions"
            ).fetchone() == (1,)
            assert (
                connection.execute("SELECT id FROM rag_profiles ORDER BY id").fetchall() == before
            )
