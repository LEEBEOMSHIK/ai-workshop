from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import insert, select, update
from sqlalchemy.exc import DBAPIError

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.configurations.models import (
    AnswerPolicyVersionRecord,
    RagConfigurationRecord,
    RagConfigurationVersionRecord,
    RagConfigurationWorkspaceSubscriptionRecord,
)
from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.deployments.repository import (
    SecretReference,
    SqlAlchemyDeploymentRepository,
)
from ai_workshop.labs.rag.generation.audit import (
    GenerationExecutionAudit,
    SqlAlchemyGenerationAuditRepository,
    WorkspacePolicyAuditSnapshot,
)
from ai_workshop.labs.rag.generation.audit_models import GenerationExecutionAuditRecord
from ai_workshop.labs.rag.models.models import (
    ModelDefinitionRecord,
    ProfileDeploymentBindingRecord,
    ProfileRecord,
)
from ai_workshop.labs.rag.policies.domain import (
    WorkspaceDataPolicyVersion,
    WorkspaceOutboundMode,
)
from ai_workshop.labs.rag.policies.models import InstallationDataPolicyVersionRecord
from ai_workshop.labs.rag.policies.repository import (
    ApprovedWorkspacePolicySnapshot,
    ExternalConfigurationApproval,
    SqlAlchemyDataPolicyRepository,
)
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.shared.db import create_engine, create_session_factory
from alembic import command

pytestmark = pytest.mark.integration
BACKEND_ROOT = Path(__file__).resolve().parents[5]


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "0016_rag_llm_deployments")


@pytest.mark.asyncio
async def test_generation_audit_round_trip_contains_ids_and_metadata_only() -> None:
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    owner_id = uuid4()
    workspace_id = uuid4()
    model_id = uuid4()
    deployment_id = uuid4()
    deployment_version_id = uuid4()
    indexing_profile_id = uuid4()
    retrieval_profile_id = uuid4()
    generation_profile_id = uuid4()
    configuration_id = uuid4()
    answer_policy_id = uuid4()
    configuration_version_id = uuid4()
    now = datetime.now(UTC)
    try:
        async with sessions() as session:
            transaction = await session.begin()
            try:
                await session.execute(
                    insert(UserRecord).values(
                        id=owner_id,
                        display_name="Audit owner",
                        email=f"{owner_id}@example.test",
                        normalized_email=f"{owner_id}@example.test",
                        password_hash="fixture-hash",
                        role="owner",
                        is_active=True,
                    )
                )
                await session.execute(
                    insert(WorkspaceRecord).values(
                        id=workspace_id,
                        name=f"Audit workspace {workspace_id}",
                        kind="personal",
                        created_by=owner_id,
                        expires_at=None,
                    )
                )
                await session.execute(
                    insert(ModelDefinitionRecord).values(
                        id=model_id,
                        kind="llm",
                        name=f"Audit model {model_id}",
                        version=1,
                        config={},
                    )
                )
                profiles = (
                    ProfileRecord(
                        id=indexing_profile_id,
                        kind="indexing",
                        name=f"Audit indexing {indexing_profile_id}",
                        version=1,
                        config={},
                        evaluation_state="draft",
                        is_default=False,
                    ),
                    ProfileRecord(
                        id=retrieval_profile_id,
                        kind="retrieval",
                        name=f"Audit retrieval {retrieval_profile_id}",
                        version=1,
                        config={"reranker": {"enabled": False}},
                        evaluation_state="draft",
                        is_default=False,
                    ),
                    ProfileRecord(
                        id=generation_profile_id,
                        kind="generation",
                        name=f"Audit generation {generation_profile_id}",
                        version=1,
                        config={
                            "prompt_ref": "answer-v1",
                            "context_prompt_ref": "contextualize-v1",
                            "citation_mode": "required",
                            "context_policy": {"max_prior_turns": 2},
                            "generation": {"max_output_tokens": 256},
                        },
                        evaluation_state="draft",
                        is_default=False,
                    ),
                )
                session.add_all(profiles)
                await session.flush()
                deployment = ModelDeploymentVersion(
                    id=deployment_version_id,
                    deployment_id=deployment_id,
                    version=1,
                    display_name="Audit external deployment",
                    description="Synthetic metadata only",
                    model_definition_id=model_id,
                    provider=ProviderKind.OPENAI_RESPONSES,
                    location=ExecutionLocation.EXTERNAL,
                    allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
                    provider_model_id="synthetic/exact-model",
                    endpoint_ref="openai-responses",
                    secret_ref="openai-primary",
                    capabilities=frozenset({DeploymentCapability.STRUCTURED_OUTPUT}),
                    external_transfer=True,
                    transmitted_data_categories=("question", "evidence"),
                    data_processing_notice_ref="notice-v1",
                    timeout_seconds=10,
                    max_retries=0,
                    retry_backoff_seconds=0,
                    healthcheck_enabled=True,
                    development_only=False,
                    created_by=owner_id,
                    created_at=now,
                )
                deployment_repository = SqlAlchemyDeploymentRepository(session)
                await deployment_repository.register_secret_reference(
                    SecretReference(
                        reference_name="openai-primary",
                        created_by=owner_id,
                        created_at=now,
                    )
                )
                await deployment_repository.add_version(deployment)
                session.add(
                    ProfileDeploymentBindingRecord(
                        profile_id=generation_profile_id,
                        deployment_version_id=deployment_version_id,
                    )
                )
                await session.flush()
                session.add(
                    RagConfigurationRecord(
                        id=configuration_id,
                        owner_id=owner_id,
                        name=f"Audit configuration {configuration_id}",
                        is_system=False,
                    )
                )
                await session.flush()
                session.add(
                    AnswerPolicyVersionRecord(
                        id=answer_policy_id,
                        configuration_id=configuration_id,
                        version=1,
                        mode="generative",
                        min_semantic_score=0,
                        min_keyword_coverage=0,
                        require_complete_provenance=True,
                        conflict_mode="separate_sources",
                    )
                )
                await session.flush()
                session.add(
                    RagConfigurationVersionRecord(
                        id=configuration_version_id,
                        configuration_id=configuration_id,
                        version=1,
                        indexing_profile_id=indexing_profile_id,
                        retrieval_profile_id=retrieval_profile_id,
                        generation_profile_id=generation_profile_id,
                        answer_policy_version_id=answer_policy_id,
                        evaluation_state="draft",
                        is_default=False,
                    )
                )
                await session.flush()
                session.add(
                    RagConfigurationWorkspaceSubscriptionRecord(
                        id=uuid4(),
                        configuration_version_id=configuration_version_id,
                        workspace_id=workspace_id,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await session.flush()
                installation_policy_version_id = await session.scalar(
                    select(InstallationDataPolicyVersionRecord.id).order_by(
                        InstallationDataPolicyVersionRecord.version.desc()
                    )
                )
                assert installation_policy_version_id is not None
                workspace_policy = WorkspaceDataPolicyVersion(
                    id=uuid4(),
                    policy_id=uuid4(),
                    workspace_id=workspace_id,
                    version=1,
                    mode=WorkspaceOutboundMode.DENY,
                    approved_providers=frozenset(),
                    changed_by=owner_id,
                    created_at=now,
                )
                policy_repository = SqlAlchemyDataPolicyRepository(session)
                await policy_repository.add_workspace_version(workspace_policy)
                approval = ExternalConfigurationApproval(
                    id=uuid4(),
                    configuration_version_id=configuration_version_id,
                    deployment_version_id=deployment_version_id,
                    installation_policy_version_id=installation_policy_version_id,
                    approved_by=owner_id,
                    disclosure_version="external-generation-v1",
                    workspace_policies=(
                        ApprovedWorkspacePolicySnapshot(
                            workspace_id=workspace_id,
                            policy_version_id=workspace_policy.id,
                        ),
                    ),
                    created_at=now,
                )
                invalid_approvals = (
                    replace(
                        approval,
                        id=uuid4(),
                        deployment_version_id=uuid4(),
                    ),
                    replace(
                        approval,
                        id=uuid4(),
                        installation_policy_version_id=uuid4(),
                    ),
                    replace(approval, id=uuid4(), workspace_policies=()),
                    replace(
                        approval,
                        id=uuid4(),
                        workspace_policies=(
                            *approval.workspace_policies,
                            ApprovedWorkspacePolicySnapshot(
                                workspace_id=uuid4(),
                                policy_version_id=uuid4(),
                            ),
                        ),
                    ),
                    replace(
                        approval,
                        id=uuid4(),
                        workspace_policies=(
                            ApprovedWorkspacePolicySnapshot(
                                workspace_id=workspace_id,
                                policy_version_id=uuid4(),
                            ),
                        ),
                    ),
                )
                for invalid_approval in invalid_approvals:
                    with pytest.raises(ValueError, match="approval"):
                        await policy_repository.add_external_approval(invalid_approval)
                await policy_repository.add_external_approval(approval)
                assert (
                    await policy_repository.get_external_approval_for_configuration(
                        configuration_version_id
                    )
                    == approval
                )
                evidence_ids = (uuid4(), uuid4())
                audit = GenerationExecutionAudit(
                    id=uuid4(),
                    actor_id=owner_id,
                    configuration_version_id=configuration_version_id,
                    generation_profile_id=generation_profile_id,
                    deployment_version_id=deployment_version_id,
                    installation_policy_version_id=installation_policy_version_id,
                    workspace_policies=(
                        WorkspacePolicyAuditSnapshot(
                            workspace_id=workspace_id,
                            policy_version_id=workspace_policy.id,
                        ),
                    ),
                    provider=ProviderKind.OPENAI_RESPONSES,
                    provider_model_id="synthetic/exact-model",
                    location=ExecutionLocation.EXTERNAL,
                    external_transfer=True,
                    policy_allowed=True,
                    policy_reason_code=None,
                    prompt_ref="answer-v1",
                    prompt_version=1,
                    evidence_ids=evidence_ids,
                    input_tokens=100,
                    output_tokens=20,
                    latency_ms=12,
                    provider_reported_input_tokens=None,
                    provider_reported_output_tokens=None,
                    cost_basis_version=None,
                    estimated_cost_microunits=None,
                    status="succeeded",
                    safe_error_code=None,
                    correlation_id=uuid4(),
                    created_at=now,
                )
                repository = SqlAlchemyGenerationAuditRepository(session)

                await repository.add(audit)
                loaded = await repository.get(audit.id)

                assert loaded == audit
                assert loaded is not None
                assert loaded.evidence_ids == evidence_ids
                for forbidden in (
                    "question",
                    "history",
                    "prompt_text",
                    "evidence_text",
                    "document_text",
                    "secret",
                    "secret_ref",
                ):
                    assert not hasattr(loaded, forbidden)
                with pytest.raises(DBAPIError, match="immutable"):
                    async with session.begin_nested():
                        await session.execute(
                            update(GenerationExecutionAuditRecord)
                            .where(GenerationExecutionAuditRecord.id == audit.id)
                            .values(status="failed")
                        )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
